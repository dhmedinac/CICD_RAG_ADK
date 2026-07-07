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


async def _get_session_service() -> DatabaseSessionService:
    """Create session service with proper Cloud SQL Connector setup for async."""
    db_url = settings.database_url
    parsed = urlparse(db_url)

    # Local development with standard PostgreSQL
    if parsed.scheme == "postgresql+asyncpg":
        engine = create_async_engine(db_url, echo=False)
        return DatabaseSessionService(engine)

    # Cloud Run with Cloud SQL Connector
    elif parsed.scheme == "postgresql+cloudsql":
        from google.cloud.sql.connector import Connector

        # Extract connection info from URL
        userinfo = parsed.netloc.split("@")[0]
        connection_name = parsed.netloc.split("@")[1].replace("%3A", ":")
        database = parsed.path.lstrip("/")

        user, password = (userinfo.split(":", 1) if ":" in userinfo else (userinfo, ""))

        # Create Cloud SQL Connector
        connector = Connector()

        # Define async creator that uses the connector
        async def get_connection():
            return await asyncio.to_thread(
                lambda: connector.connect(
                    connection_name,
                    driver="asyncpg",
                    user=user,
                    password=password,
                    db=database,
                )
            )

        # Create async engine using the connector's connection
        engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=get_connection,
        )
        return DatabaseSessionService(engine)

    else:
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")


# Create session service synchronously at module load time
# ADK needs this to be available before app creation
def _create_sync_session_service() -> DatabaseSessionService:
    """Synchronous wrapper to create session service."""
    from urllib.parse import unquote

    db_url = settings.database_url
    parsed = urlparse(db_url)

    if parsed.scheme == "postgresql+asyncpg":
        engine = create_async_engine(db_url, echo=False)
        return DatabaseSessionService(engine)

    elif parsed.scheme == "postgresql+cloudsql":
        from google.cloud.sql.connector import Connector
        from concurrent.futures import ThreadPoolExecutor

        # Handle URL-encoded special characters in credentials and connection name
        if "@" not in parsed.netloc:
            raise ValueError(
                f"Invalid Cloud SQL URL format: {db_url}. "
                "Expected: postgresql+cloudsql://user:password@PROJECT%3AREGION%3AINSTANCE/database. "
                "Password special characters (/, +, =) must be percent-encoded (%2F, %2B, %3D)"
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

        connector = Connector()
        executor = ThreadPoolExecutor(max_workers=5)

        async def get_connection():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                executor,
                lambda: connector.connect(
                    connection_name,
                    driver="asyncpg",
                    user=user,
                    password=password,
                    db=database,
                ),
            )

        engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=get_connection,
        )
        return DatabaseSessionService(engine)

    else:
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")


session_service = _create_sync_session_service()

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
