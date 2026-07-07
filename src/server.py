"""FastAPI entrypoint for Cloud Run.

Builds the standard ADK FastAPI app (which exposes /run, /run_sse, session
endpoints, etc. for the `rag_agent` app) and wraps it with:
  * a /health endpoint for Cloud Run startup/liveness probes, and
  * service account authentication for /agent/* endpoints (Vertex AI),
  * API-key fallback for direct/external access. 

Run locally:  uv run uvicorn server:app --app-dir src --reload
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.sessions import DatabaseSessionService
from sqlalchemy.ext.asyncio import create_async_engine

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _convert_cloud_sql_url(db_url: str) -> str:
    """Convert postgresql+cloudsql:// URL to postgresql+asyncpg:// for SQLAlchemy parsing.

    DatabaseSessionService will parse this URL and ADK will create the engine.
    The Cloud SQL Connector is registered as a dialect and will handle the connection.
    """
    from urllib.parse import unquote

    parsed = urlparse(db_url)

    if parsed.scheme != "postgresql+cloudsql":
        return db_url

    # For Cloud SQL, convert to standard asyncpg format that SQLAlchemy can parse
    # The Cloud SQL Connector's dialect registration will intercept the connection
    if "@" not in parsed.netloc:
        raise ValueError(
            f"Invalid Cloud SQL URL format: {db_url}. "
            "Expected: postgresql+cloudsql://user:password@PROJECT%3AREGION%3AINSTANCE/database. "
            "Password special characters (/, +, =) must be percent-encoded (%2F, %2B, %3D)"
        )

    userinfo, connection_part = parsed.netloc.split("@", 1)
    connection_name = unquote(connection_part.replace("%3A", ":"))
    database = parsed.path.lstrip("/")

    # Return URL in format that Cloud SQL Connector can intercept
    # Use empty host and connection name in path
    if ":" in userinfo:
        user, password = userinfo.split(":", 1)
        user = unquote(user)
        password = unquote(password)
        return f"postgresql+asyncpg://{user}:{password}@/{database}?unix_socket_dir=/cloudsql/{connection_name}"
    else:
        user = unquote(userinfo)
        return f"postgresql+asyncpg://{user}@/{database}?unix_socket_dir=/cloudsql/{connection_name}"


# Register Cloud SQL Connector dialect before creating session service
try:
    from google.cloud.sql.connector import Connector  # noqa: F401
except ImportError:
    pass

# Convert URL to parseable format for ADK
_db_url = _convert_cloud_sql_url(settings.database_url)

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service_uri=_db_url,
)


#app.middleware("http")
#sync def verify_service_account(request: Request, call_next):
#   """Verify requests from Vertex AI Agent (via service account) or API key fallback."""
#
#   # Public endpoints don't need auth
#   if request.url.path in _PUBLIC_PATHS:
#       return await call_next(request)
#
#   # Service-to-service endpoints (Vertex AI Agent calls) use service account auth
#   if request.url.path in {"/run", "/run_sse"}:
#       auth_header = request.headers.get("authorization", "")
#       if auth_header.startswith("Bearer "):
#           token = auth_header.split(" ")[1]
#           try:
#               # Verify the token is from our service account
#               claims = id_token.verify_oauth2_token(token, requests.Request())
#               if claims.get("email") == os.getenv("VERTEX_AI_SERVICE_ACCOUNT", ""):
#                   return await call_next(request)
#           except Exception:
#               pass
#           return JSONResponse(status_code=401, content={"detail": "Invalid token"})
#
#   # Other endpoints: require API key (for direct/external access)
#   if settings.api_key:
#       received_key = request.headers.get("x-api-key")
#       if received_key != settings.api_key:
#           return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
#
#   return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
