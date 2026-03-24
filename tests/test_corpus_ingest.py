"""Tests for UFLI curriculum ingestion into ChromaDB."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from corpus.ufli.ingest import _derive_grade, ingest_curriculum
from rag.embeddings import EmbeddingResult
from rag.store import CURRICULUM, get_or_create_collection, get_store


def _fake_embedding(content_type: str = "text") -> EmbeddingResult:
    return EmbeddingResult(
        values=[1.0, 0.0, 0.0],
        dimensions=3,
        task_type="RETRIEVAL_DOCUMENT",
        content_type=content_type,
    )


def _write_normalized(tmp_path: Path, records: list[dict[str, object]]) -> None:
    normalized = tmp_path / "normalized.jsonl"
    with normalized.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_ingest_creates_curriculum_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingestion creates documents in the curriculum collection."""
    monkeypatch.setattr(
        "corpus.ufli.ingest.embed_text",
        lambda *_a, **_k: _fake_embedding(),
    )

    _write_normalized(
        tmp_path,
        [
            {
                "lesson_id": "58",
                "lesson_group": "35-64",
                "concept": "CVCe (a_e)",
                "slide_text": "Introduce CVCe pattern with a_e words.",
                "slide_count": 10,
                "decodable_text": "The cake was on the plate.",
                "home_practice_text": "Read these words: grade, chase.",
                "additional_text": "",
            }
        ],
    )

    count = ingest_curriculum(data_dir=str(tmp_path), db_path=str(tmp_path / "vs"))
    assert count == 1

    store = get_store(str(tmp_path / "vs"))
    col = get_or_create_collection(store, CURRICULUM)
    assert col.count() == 1

    result = col.get(ids=["curriculum_ufli_58"], include=["metadatas", "documents"])
    meta = result["metadatas"][0]
    assert meta["concept"] == "CVCe (a_e)"
    assert meta["grade_level"] == "1"
    assert meta["has_decodable"] is True
    assert meta["has_home_practice"] is True
    assert meta["has_additional"] is False


def test_ingest_multiple_lessons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple lessons are indexed with correct IDs."""
    monkeypatch.setattr(
        "corpus.ufli.ingest.embed_text",
        lambda *_a, **_k: _fake_embedding(),
    )

    _write_normalized(
        tmp_path,
        [
            {
                "lesson_id": "A",
                "lesson_group": "a-j",
                "concept": "Letter A",
                "slide_text": "This is the letter A.",
                "slide_count": 5,
                "decodable_text": "",
                "home_practice_text": "",
                "additional_text": "",
            },
            {
                "lesson_id": "100",
                "lesson_group": "95-128",
                "concept": "r-controlled vowels",
                "slide_text": "Words with ar, or, er.",
                "slide_count": 20,
                "decodable_text": "The car went far.",
                "home_practice_text": "",
                "additional_text": "",
            },
        ],
    )

    count = ingest_curriculum(data_dir=str(tmp_path), db_path=str(tmp_path / "vs"))
    assert count == 2

    store = get_store(str(tmp_path / "vs"))
    col = get_or_create_collection(store, CURRICULUM)
    assert col.count() == 2


def test_ingest_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running ingestion upserts, not duplicates."""
    monkeypatch.setattr(
        "corpus.ufli.ingest.embed_text",
        lambda *_a, **_k: _fake_embedding(),
    )

    _write_normalized(
        tmp_path,
        [
            {
                "lesson_id": "10",
                "lesson_group": "1-34",
                "concept": "short i",
                "slide_text": "Short i words.",
                "slide_count": 8,
                "decodable_text": "",
                "home_practice_text": "",
                "additional_text": "",
            },
        ],
    )

    ingest_curriculum(data_dir=str(tmp_path), db_path=str(tmp_path / "vs"))
    ingest_curriculum(data_dir=str(tmp_path), db_path=str(tmp_path / "vs"))

    store = get_store(str(tmp_path / "vs"))
    col = get_or_create_collection(store, CURRICULUM)
    assert col.count() == 1


def test_derive_grade() -> None:
    """Grade derivation matches UFLI scope and sequence."""
    assert _derive_grade("A") == "K"
    assert _derive_grade("J") == "K"
    assert _derive_grade("1") == "K"
    assert _derive_grade("34") == "K"
    assert _derive_grade("35") == "1"
    assert _derive_grade("64") == "1"
    assert _derive_grade("65") == "1"
    assert _derive_grade("94") == "1"
    assert _derive_grade("95") == "2"
    assert _derive_grade("128") == "2"
