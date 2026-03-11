"""Vertex AI Gemini client for RAG embedding operations only."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-exp-03-07")
GENERATIVE_MODEL = os.environ.get("GEMINI_GENERATIVE_MODEL", "gemini-2.5-flash")


def rag_available() -> bool:
    """Check if Vertex AI is configured for RAG operations."""
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


@lru_cache(maxsize=1)
def get_rag_client() -> Any:
    """Return a singleton Gemini client using Vertex AI backend."""
    from google import genai

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        raise OSError(
            "GOOGLE_CLOUD_PROJECT must be set for Vertex AI RAG backend. "
            "Run: gcloud auth application-default login && "
            "export GOOGLE_CLOUD_PROJECT=your-project-id"
        )

    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
    )

    try:
        client.models.get(model=EMBEDDING_MODEL)
        logger.info(
            "RAG client initialized: model=%s project=%s location=%s",
            EMBEDDING_MODEL,
            project,
            location,
        )
    except Exception as exc:  # pragma: no cover - defensive startup warning
        logger.warning(
            "Embedding model '%s' may not be available: %s. "
            "Set GEMINI_EMBEDDING_MODEL to override.",
            EMBEDDING_MODEL,
            exc,
        )

    return client
