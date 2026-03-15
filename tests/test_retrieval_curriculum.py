"""Tests for curriculum collection integration in retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from rag.embeddings import EmbeddingResult
from rag.retrieval import retrieve_context
from rag.store import (
    CURRICULUM,
    add_document,
    get_or_create_collection,
    get_store,
)


@pytest.fixture
def fake_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch embed_text so retrieval tests don't hit external APIs."""

    def _fake_embed_text(
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        dimensions: int = 768,
    ) -> EmbeddingResult:
        del text
        return EmbeddingResult(
            values=[1.0, 0.0, 0.0],
            dimensions=dimensions,
            task_type=task_type,
            content_type="text",
        )

    monkeypatch.setattr("rag.retrieval.embed_text", _fake_embed_text)


def test_retrieve_includes_curriculum_references(
    tmp_path: Path, fake_embed: None
) -> None:
    """Curriculum collection results appear in RAGContext."""
    db_path = str(tmp_path / "vector_store")
    store = get_store(db_path)
    cur_col = get_or_create_collection(store, CURRICULUM)
    add_document(
        cur_col,
        doc_id="curriculum_ufli_58",
        embedding=[1.0, 0.0, 0.0],
        metadata={"lesson_id": "58", "concept": "CVCe (a_e)", "grade_level": "1"},
        document="CVCe words: grade chase slide",
    )

    context = retrieve_context(
        skill_description="phonics: cvce",
        grade_level="1",
        db_path=db_path,
    )
    assert len(context.curriculum_references) == 1
    assert context.curriculum_references[0].doc_id == "curriculum_ufli_58"
    assert context.curriculum_references[0].metadata["concept"] == "CVCe (a_e)"


def test_retrieve_curriculum_grade_filter(
    tmp_path: Path, fake_embed: None
) -> None:
    """Curriculum retrieval respects grade_level filter."""
    db_path = str(tmp_path / "vector_store")
    store = get_store(db_path)
    cur_col = get_or_create_collection(store, CURRICULUM)

    add_document(
        cur_col,
        doc_id="curriculum_ufli_10",
        embedding=[1.0, 0.0, 0.0],
        metadata={"lesson_id": "10", "concept": "short i", "grade_level": "K"},
        document="Short i: sit, hit, bit",
    )
    add_document(
        cur_col,
        doc_id="curriculum_ufli_100",
        embedding=[1.0, 0.0, 0.0],
        metadata={"lesson_id": "100", "concept": "r-controlled", "grade_level": "2"},
        document="R-controlled: car, star, far",
    )

    context = retrieve_context(
        skill_description="phonics: short vowels",
        grade_level="K",
        db_path=db_path,
    )
    assert len(context.curriculum_references) == 1
    assert context.curriculum_references[0].metadata["grade_level"] == "K"


def test_retrieve_empty_curriculum(
    tmp_path: Path, fake_embed: None
) -> None:
    """Empty curriculum collection returns empty list, not error."""
    db_path = str(tmp_path / "vector_store")

    context = retrieve_context(
        skill_description="phonics: cvce",
        db_path=db_path,
    )
    assert context.curriculum_references == []
