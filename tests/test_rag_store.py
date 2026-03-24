"""Tests for the ChromaDB store wrapper used by RAG."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from rag.store import (
    ADAPTATIONS,
    EXEMPLARS,
    SKILLS,
    WORKSHEETS,
    add_document,
    get_or_create_collection,
    get_store,
    query_similar,
)


def test_create_persistent_store(tmp_path: Path) -> None:
    db_path = tmp_path / "vector_store"
    store = get_store(str(db_path))
    assert db_path.exists()
    collection = get_or_create_collection(store, WORKSHEETS)
    assert collection.name == WORKSHEETS


def test_add_and_query_document(tmp_path: Path) -> None:
    store = get_store(str(tmp_path / "vector_store"))
    collection = get_or_create_collection(store, SKILLS)

    add_document(
        collection,
        doc_id="skill_1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"grade_level": "1", "source_hash": "abc"},
        document="phonics cvce",
    )

    result = query_similar(collection, query_embedding=[1.0, 0.0, 0.0], n_results=1)
    assert result["ids"][0] == ["skill_1"]


def test_upsert_overwrites_same_id(tmp_path: Path) -> None:
    store = get_store(str(tmp_path / "vector_store"))
    collection = get_or_create_collection(store, ADAPTATIONS)

    add_document(
        collection,
        doc_id="adapt_1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"version": 1, "source_hash": "s1"},
        document="first",
    )
    add_document(
        collection,
        doc_id="adapt_1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"version": 2, "source_hash": "s1"},
        document="second",
    )

    result = query_similar(collection, query_embedding=[1.0, 0.0, 0.0], n_results=1)
    assert result["metadatas"][0][0]["version"] == 2
    assert result["documents"][0][0] == "second"


def test_query_with_metadata_filter(tmp_path: Path) -> None:
    store = get_store(str(tmp_path / "vector_store"))
    collection = get_or_create_collection(store, EXEMPLARS)

    add_document(
        collection,
        doc_id="e1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"grade_level": "1", "all_validators_passed": True},
    )
    add_document(
        collection,
        doc_id="e2",
        embedding=[1.0, 0.0, 0.0],
        metadata={"grade_level": "2", "all_validators_passed": True},
    )

    result = query_similar(
        collection,
        query_embedding=[1.0, 0.0, 0.0],
        n_results=5,
        where={"grade_level": "1"},
    )
    assert result["ids"][0] == ["e1"]


def test_query_empty_collection_returns_empty(tmp_path: Path) -> None:
    store = get_store(str(tmp_path / "vector_store"))
    collection = get_or_create_collection(store, WORKSHEETS)

    result = query_similar(collection, query_embedding=[1.0, 0.0, 0.0], n_results=3)
    assert result["ids"][0] == []


def test_four_collections_created(tmp_path: Path) -> None:
    store = get_store(str(tmp_path / "vector_store"))
    names = {
        get_or_create_collection(store, WORKSHEETS).name,
        get_or_create_collection(store, SKILLS).name,
        get_or_create_collection(store, ADAPTATIONS).name,
        get_or_create_collection(store, EXEMPLARS).name,
    }
    assert names == {WORKSHEETS, SKILLS, ADAPTATIONS, EXEMPLARS}
