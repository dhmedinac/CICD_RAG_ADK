"""Firestore client for RAG agent session and data persistence."""

from __future__ import annotations

import functools
from datetime import datetime

from google.cloud import firestore

from rag_agent.config import settings


@functools.lru_cache
def get_firestore_client() -> firestore.AsyncClient:
    """Get or create a Firestore client for async operations.

    Uses the GCP project from settings. Client is cached and reused.
    """
    return firestore.AsyncClient(project=settings.google_cloud_project)


async def save_session(session_id: str, user_id: str, state: dict) -> None:
    """Save session state to Firestore with metadata.

    Args:
        session_id: Unique session identifier
        user_id: User associated with this session
        state: Agent state/context to persist (e.g., conversation history, tool results)
    """
    client = get_firestore_client()
    data = {
        "user_id": user_id,
        "state": state,
        "updated_at": datetime.utcnow(),
        "environment": settings.environment,
    }
    await client.collection("sessions").document(session_id).set(data, merge=True)


async def get_session(session_id: str) -> dict | None:
    """Retrieve complete session data from Firestore.

    Args:
        session_id: Session identifier to load

    Returns:
        Session dict with user_id, state, and metadata, or None if not found
    """
    client = get_firestore_client()
    doc = await client.collection("sessions").document(session_id).get()
    return doc.to_dict() if doc.exists else None


async def delete_session(session_id: str) -> None:
    """Delete a session from Firestore."""
    client = get_firestore_client()
    await client.collection("sessions").document(session_id).delete()


async def list_user_sessions(user_id: str) -> list[dict]:
    """List all sessions for a user.

    Args:
        user_id: User identifier

    Returns:
        List of session documents with metadata
    """
    client = get_firestore_client()
    docs = await client.collection("sessions").where("user_id", "==", user_id).stream()
    return [{"id": doc.id, **doc.to_dict()} async for doc in docs]