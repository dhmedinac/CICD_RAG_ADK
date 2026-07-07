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


def _create_session_service_for_url(db_url: str) -> DatabaseSessionService:
    """Create DatabaseSessionService with proper async engine for Cloud SQL or local."""
    from urllib.parse import unquote
    from concurrent.futures import ThreadPoolExecutor

    parsed = urlparse(db_url)

    # Local development
    if parsed.scheme == "postgresql+asyncpg":
        engine = create_async_engine(db_url)
        return DatabaseSessionService(engine)

    # Cloud Run with Cloud SQL Connector
    if parsed.scheme == "postgresql+cloudsql":
        from google.cloud.sql.connector import Connector

        if "@" not in parsed.netloc:
            raise ValueError(
                f"Invalid Cloud SQL URL format: {db_url}. "
                "Expected: postgresql+cloudsql://user:password@PROJECT%3AREGION%3AINSTANCE/database"
            )

        userinfo, connection_part = parsed.netloc.split("@", 1)
        connection_name = unquote(connection_part.replace("%3A", ":"))
        database = parsed.path.lstrip("/")

        if ":" in userinfo:
            user, password = userinfo.split(":", 1)
            user = unquote(user)
            password = unquote(password)
        else:
            user = unquote(userinfo)
            password = ""

        # Create Cloud SQL Connector
        connector = Connector()
        executor = ThreadPoolExecutor(max_workers=10)

        async def get_connection():
            """Create async connection via Cloud SQL Connector."""
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                executor,
                lambda: connector.connect(
                    connection_name,
                    driver="asyncpg",
                    user=user,
                    password=password if password else None,
                    db=database,
                ),
            )

        # Create async engine with Cloud SQL Connector
        engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=get_connection,
            pool_pre_ping=True,
        )
        return DatabaseSessionService(engine)

    raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")


# Create session service
_session_service = _create_session_service_for_url(settings.database_url)

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service=_session_service,
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
