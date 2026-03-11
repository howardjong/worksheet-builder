"""Multimodal embedding service using Gemini Embedding 2 via Vertex AI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from rag.client import EMBEDDING_MODEL, get_rag_client

DEFAULT_DIMENSIONS = 768

TaskType = Literal[
    "RETRIEVAL_DOCUMENT",
    "RETRIEVAL_QUERY",
    "SEMANTIC_SIMILARITY",
]


class EmbeddingResult(BaseModel):
    """Result of an embedding operation."""

    values: list[float]
    model: str = EMBEDDING_MODEL
    dimensions: int = DEFAULT_DIMENSIONS
    task_type: str = "RETRIEVAL_DOCUMENT"
    content_type: str = "text"


def _types_module() -> Any:
    from google.genai import types

    return types


def _parse_values(response: Any) -> list[float]:
    embeddings = getattr(response, "embeddings", None)
    if not embeddings:
        raise ValueError("Embedding response did not include embeddings")

    first = embeddings[0]
    values = getattr(first, "values", None)
    if not values:
        raise ValueError("Embedding response did not include vector values")

    return [float(v) for v in values]


def _embed(contents: Any, task_type: TaskType, dimensions: int) -> list[float]:
    types = _types_module()
    client = get_rag_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=contents,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    return _parse_values(response)


def _image_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".webp"}:
        return "image/webp"
    return "image/jpeg"


def embed_text(
    text: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed a text string."""
    values = _embed(text, task_type=task_type, dimensions=dimensions)
    return EmbeddingResult(
        values=values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="text",
    )


def embed_image(
    image_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed an image file."""
    types = _types_module()
    image_bytes = Path(image_path).read_bytes()
    mime = _image_mime(image_path)
    values = _embed(
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime)],
        task_type=task_type,
        dimensions=dimensions,
    )
    return EmbeddingResult(
        values=values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="image",
    )


def embed_pdf(
    pdf_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed a PDF file."""
    types = _types_module()
    pdf_bytes = Path(pdf_path).read_bytes()
    values = _embed(
        contents=[types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
        task_type=task_type,
        dimensions=dimensions,
    )
    return EmbeddingResult(
        values=values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="pdf",
    )


def embed_multimodal(
    text: str,
    image_path: str,
    task_type: TaskType = "RETRIEVAL_DOCUMENT",
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbeddingResult:
    """Embed text and image together as a single fused embedding."""
    types = _types_module()
    image_bytes = Path(image_path).read_bytes()
    mime = _image_mime(image_path)
    text_part = types.Part.from_text(text=text)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime)
    values = _embed(
        contents=[types.Content(parts=[text_part, image_part])],
        task_type=task_type,
        dimensions=dimensions,
    )
    return EmbeddingResult(
        values=values,
        dimensions=dimensions,
        task_type=task_type,
        content_type="multimodal",
    )
