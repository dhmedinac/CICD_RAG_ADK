"""FastAPI entrypoint for Cloud Run.

Builds the standard ADK FastAPI app (which exposes /run, /run_sse, session
endpoints, etc. for the `rag_agent` app) and wraps it with:
  * a /health endpoint for Cloud Run startup/liveness probes, and
  * an API-key gate that protects every endpoint except health/docs.

Run locally:  uv run uvicorn server:app --app-dir src --reload
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Endpoints that must remain reachable without an API key.
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=False,
)


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """Reject requests without a valid X-API-Key header (when one is configured)."""
    received_key = request.headers.get("x-api-key")
    if not settings.api_key or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    if request.headers.get("x-api-key") != settings.api_key:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})

    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
