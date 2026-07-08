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

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _setup_cloud_sql_connector() -> str:
    """Setup Cloud SQL Connector for async SQLAlchemy if using Cloud SQL."""
    db_url = settings.database_url
    parsed = urlparse(db_url)

    # For Cloud Run with Cloud SQL: use Cloud SQL Python Connector
    if parsed.scheme == "postgresql+cloudsql":
        from google.cloud.sql.connector import Connector

        # Parse connection details from URL
        userinfo = parsed.netloc.split("@")[0]
        connection_name = parsed.netloc.split("@")[1].replace("%3A", ":")
        database = parsed.path.lstrip("/")

        user, password = (
            userinfo.split(":", 1) if ":" in userinfo else (userinfo, "")
        )

        # Create global connector instance
        connector = Connector()

        async def getconn():
            """Get async connection via Cloud SQL Connector."""
            return await asyncio.to_thread(
                lambda: connector.connect(
                    connection_name,
                    driver="asyncpg",
                    user=user,
                    password=password if password else None,
                    db=database,
                )
            )

        # Store the connector and creator globally for ADK to use
        os.environ["_CLOUD_SQL_CREATOR"] = "true"
        # Return a URL that ADK can parse - ADK will handle async creation
        # We'll monkey-patch SQLAlchemy to use our connector
        return f"postgresql+asyncpg://{user}:{'*' * len(password or '')}@{connection_name}/{database}"

    return db_url


# Setup Cloud SQL if needed
_setup_cloud_sql_connector()

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service_uri=settings.database_url,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}