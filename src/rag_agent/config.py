"""Runtime configuration for the RAG agent.

All values are read from environment variables (or a local `.env` file). The
same settings object is used by the ADK agent, the FastAPI server, and tests.
"""

from __future__ import annotations

import functools

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- GCP / Vertex ---
    google_cloud_project: str = ""
    google_cloud_location: str = "europe-west1"
    # ADK reads this to route models through Vertex AI instead of the public API.
    google_genai_use_vertexai: str = "TRUE"

    # --- Agent ---
    agent_model: str = "gemini-2.5-flash"
    environment: str = "dev"

    # --- API auth ---
    # Shared secret expected in the `X-API-Key` request header. Injected on
    # Cloud Run from Secret Manager. When empty, auth is disabled (local dev).
    api_key: str = ""

    @field_validator("api_key", mode="before")
    @classmethod
    def strip_api_key(cls, v: str) -> str:
        return v.strip() if v else v

    # --- Vertex AI RAG Engine corpus ---
    # Full resource name takes precedence; otherwise we resolve by display name.
    # e.g. projects/123/locations/us-central1/ragCorpora/456
    rag_corpus: str = ""
    rag_corpus_display_name: str = "rag-agent-corpus"
    similarity_top_k: int = 10
    vector_distance_threshold: float = 0.5

    # --- PostgreSQL Database ---
    # Connection URL for ADK session persistence (required).
    # Local development: postgresql+asyncpg://user:password@localhost:5432/database
    # Cloud Run with Cloud SQL Connector: postgresql+asyncpg+cloudsql://user:password@PROJECT_ID%3AREGION%3AINSTANCE/database
    # Note: colons in the connection name must be URL-encoded as %3A
    database_url: str

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "DATABASE_URL is required. Set it in .env or as an environment variable. "
                "Local: postgresql+asyncpg://user:password@localhost:5432/database. "
                "Cloud Run: postgresql+asyncpg+cloudsql://user:password@PROJECT_ID%3AREGION%3AINSTANCE/database"
            )
        return v.strip()

    def rag_corpus_resource_name(self) -> str:
        """Return the fully-qualified RAG corpus resource name.

        Prefers the explicit `RAG_CORPUS` env var (set at deploy time so cold
        starts don't pay a lookup). Falls back to resolving by display name.
        """
        if self.rag_corpus:
            return self.rag_corpus

        import vertexai
        from vertexai.preview import rag

        vertexai.init(project=self.google_cloud_project, location=self.google_cloud_location)
        for corpus in rag.list_corpora():
            if corpus.display_name == self.rag_corpus_display_name:
                return corpus.name
        raise RuntimeError(
            f"No Vertex AI RAG corpus with display name "
            f"{self.rag_corpus_display_name!r} found in "
            f"{self.google_cloud_project}/{self.google_cloud_location}. "
            "Run scripts/manage_corpus.py to create it."
        )


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
