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

from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service_uri=settings.database_url,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
