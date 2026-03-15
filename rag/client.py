"""Gemini client setup for RAG embedding operations."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-exp-03-07"
EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
GENERATIVE_MODEL = os.environ.get("GEMINI_GENERATIVE_MODEL", "gemini-2.5-flash")
_FALLBACK_EMBEDDING_MODELS = ("gemini-embedding-2-preview", "text-embedding-005")


def _configured_api_key() -> str:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""


def get_embedding_models() -> list[str]:
    """Return embedding model candidates in priority order."""
    configured = os.environ.get("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    candidates = [configured, *_FALLBACK_EMBEDDING_MODELS]
    return list(dict.fromkeys(candidates))


def _resolve_backend() -> str:
    backend = os.environ.get("RAG_GEMINI_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "api_key", "vertex"}:
        raise ValueError(
            "RAG_GEMINI_BACKEND must be one of: auto, api_key, vertex"
        )

    api_key = _configured_api_key()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if backend == "api_key":
        if not api_key:
            raise OSError(
                "RAG_GEMINI_BACKEND=api_key requires GOOGLE_API_KEY or GEMINI_API_KEY"
            )
        return "api_key"

    if backend == "vertex":
        if not project:
            raise OSError(
                "RAG_GEMINI_BACKEND=vertex requires GOOGLE_CLOUD_PROJECT"
            )
        return "vertex"

    if api_key:
        return "api_key"
    if project:
        return "vertex"

    raise OSError(
        "RAG backend unavailable. Set GOOGLE_API_KEY / GEMINI_API_KEY for direct "
        "Gemini API access, or set GOOGLE_CLOUD_PROJECT for Vertex AI."
    )


def rag_available() -> bool:
    """Check if any supported Gemini backend is configured for RAG operations."""
    try:
        _resolve_backend()
    except (OSError, ValueError):
        return False
    return True


@lru_cache(maxsize=1)
def get_rag_client() -> Any:
    """Return a singleton Gemini client using the configured backend."""
    from google import genai

    backend = _resolve_backend()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    api_key = _configured_api_key()

    if backend == "api_key":
        client = genai.Client(api_key=api_key)
        logger.info(
            "RAG client initialized: backend=api_key model_candidates=%s",
            ",".join(get_embedding_models()),
        )
        return client

    if not project:
        raise OSError(
            "GOOGLE_CLOUD_PROJECT must be set for Vertex AI RAG backend. "
            "Run: gcloud auth application-default login && "
            "export GOOGLE_CLOUD_PROJECT=your-project-id"
        )

    client = genai.Client(vertexai=True, project=project, location=location)

    try:
        client.models.get(model=get_embedding_models()[0])
        logger.info(
            "RAG client initialized: backend=vertex model_candidates=%s project=%s location=%s",
            ",".join(get_embedding_models()),
            project,
            location,
        )
    except Exception as exc:  # pragma: no cover - defensive startup warning
        logger.warning(
            "Primary embedding model '%s' may not be available: %s. "
            "Fallbacks configured: %s",
            get_embedding_models()[0],
            exc,
            ",".join(get_embedding_models()[1:]) or "none",
        )

    return client
