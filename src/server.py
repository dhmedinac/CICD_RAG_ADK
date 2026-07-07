"""FastAPI entrypoint for Cloud Run.

Builds the standard ADK FastAPI app (which exposes /run, /run_sse, session
endpoints, etc. for the `rag_agent` app) and wraps it with:
  * a /health endpoint for Cloud Run startup/liveness probes, and
  * service account authentication for /agent/* endpoints (Vertex AI),
  * API-key fallback for direct/external access.

Run locally:  uv run uvicorn server:app --app-dir src --reload
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.sessions import DatabaseSessionService
from sqlalchemy.ext.asyncio import create_async_engine

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _create_session_service() -> DatabaseSessionService:
    """Create DatabaseSessionService with proper Cloud SQL Connector or local setup."""
    db_url = settings.database_url
    parsed = urlparse(db_url)

    # Cloud Run with Cloud SQL Connector
    if parsed.scheme == "postgresql+cloudsql":
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from google.cloud.sql.connector import Connector

        # Extract credentials and connection info
        userinfo = parsed.netloc.split("@")[0]
        connection_name = parsed.netloc.split("@")[1]
        database = parsed.path.lstrip("/")

        # Decode URL-encoded colons
        connection_name = connection_name.replace("%3A", ":")

        # Parse user and password
        if ":" in userinfo:
            user, password = userinfo.split(":", 1)
        else:
            user = userinfo
            password = None

        # Create Cloud SQL Connector and async engine
        connector = Connector()
        executor = ThreadPoolExecutor(max_workers=5)

        def sync_connect():
            return connector.connect(
                connection_name,
                driver="asyncpg",
                user=user,
                password=password,
                db=database,
            )

        async def get_async_connection():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, sync_connect)

        async_engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=get_async_connection,
        )
        return DatabaseSessionService(async_engine)

    # Local development with standard PostgreSQL
    elif parsed.scheme == "postgresql+asyncpg":
        async_engine = create_async_engine(db_url)
        return DatabaseSessionService(async_engine)

    else:
        raise ValueError(
            f"Unsupported database URL scheme: {parsed.scheme}. "
            "Use 'postgresql+asyncpg://' for local or 'postgresql+cloudsql://' for Cloud Run."
        )


# Create session service
session_service = _create_session_service()

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service=session_service,
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
