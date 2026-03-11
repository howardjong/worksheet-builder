"""ChromaDB vector store for worksheet embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import chromadb

DEFAULT_DB_PATH = "vector_store"

WORKSHEETS = "worksheets"
SKILLS = "skills"
ADAPTATIONS = "adaptations"
EXEMPLARS = "exemplars"


def get_store(db_path: str = DEFAULT_DB_PATH) -> Any:
    """Get a persistent ChromaDB client."""
    Path(db_path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=db_path)


def get_or_create_collection(store: Any, name: str) -> Any:
    """Get or create a collection with cosine similarity."""
    return store.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def add_document(
    collection: Any,
    doc_id: str,
    embedding: list[float],
    metadata: dict[str, Any],
    document: str = "",
) -> None:
    """Add or update a document in a collection."""
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[document],
    )


def query_similar(
    collection: Any,
    query_embedding: list[float],
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query for similar documents with optional metadata filtering."""
    count = int(collection.count())
    if count == 0:
        return {
            "ids": [[]],
            "distances": [[]],
            "metadatas": [[]],
            "documents": [[]],
        }

    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": min(n_results, count),
    }
    if where:
        kwargs["where"] = where

    return cast(dict[str, Any], collection.query(**kwargs))
