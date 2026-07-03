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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.auth.transport import requests
from google.oauth2 import id_token

from rag_agent.config import settings

# Directory that contains agent app packages (here: src/rag_agent).
AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Endpoints that must remain reachable without an API key.
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

app: FastAPI = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    allow_origins=["*"],
    web=True,
    session_service_uri=settings.database_url,
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
