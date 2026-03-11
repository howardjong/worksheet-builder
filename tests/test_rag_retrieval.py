"""Tests for hybrid retrieval behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from rag.embeddings import EmbeddingResult
from rag.retrieval import retrieve_context
from rag.store import (
    ADAPTATIONS,
    EXEMPLARS,
    SKILLS,
    WORKSHEETS,
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


def test_retrieve_empty_store_returns_empty_context(
    tmp_path: Path,
    fake_embed: None,
) -> None:
    del fake_embed
    context = retrieve_context(
        skill_description="phonics: cvce",
        extracted_text="grade chase slide",
        db_path=str(tmp_path / "vector_store"),
    )
    assert context.similar_skills == []
    assert context.prior_adaptations == []
    assert context.similar_worksheets == []
    assert context.curated_exemplars == []


def test_retrieve_by_skill_finds_match(
    tmp_path: Path,
    fake_embed: None,
) -> None:
    del fake_embed
    store = get_store(str(tmp_path / "vector_store"))
    skill_col = get_or_create_collection(store, SKILLS)
    add_document(
        skill_col,
        doc_id="skill_a",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "s1", "grade_level": "1"},
        document="phonics: cvce",
    )

    context = retrieve_context(
        skill_description="phonics: cvce",
        db_path=str(tmp_path / "vector_store"),
    )
    assert len(context.similar_skills) == 1
    assert context.similar_skills[0].doc_id == "skill_a"


def test_retrieve_deduplicates_by_source_hash(
    tmp_path: Path,
    fake_embed: None,
) -> None:
    del fake_embed
    store = get_store(str(tmp_path / "vector_store"))
    adapt_col = get_or_create_collection(store, ADAPTATIONS)

    add_document(
        adapt_col,
        doc_id="a1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "same", "grade_level": "1"},
    )
    add_document(
        adapt_col,
        doc_id="a2",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "same", "grade_level": "1"},
    )
    add_document(
        adapt_col,
        doc_id="a3",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "different", "grade_level": "1"},
    )

    context = retrieve_context(
        skill_description="phonics: cvce",
        n_results=2,
        db_path=str(tmp_path / "vector_store"),
    )
    hashes = [result.metadata.get("source_hash") for result in context.prior_adaptations]
    assert len(hashes) == 2
    assert len(set(hashes)) == 2


def test_exemplars_only_include_validated_and_grade_filter(
    tmp_path: Path,
    fake_embed: None,
) -> None:
    del fake_embed
    store = get_store(str(tmp_path / "vector_store"))
    exemplar_col = get_or_create_collection(store, EXEMPLARS)

    add_document(
        exemplar_col,
        doc_id="e1",
        embedding=[1.0, 0.0, 0.0],
        metadata={
            "source_hash": "s1",
            "all_validators_passed": True,
            "grade_level": "1",
        },
    )
    add_document(
        exemplar_col,
        doc_id="e2",
        embedding=[1.0, 0.0, 0.0],
        metadata={
            "source_hash": "s2",
            "all_validators_passed": True,
            "grade_level": "2",
        },
    )

    context = retrieve_context(
        skill_description="phonics: cvce",
        grade_level="1",
        db_path=str(tmp_path / "vector_store"),
    )
    assert len(context.curated_exemplars) == 1
    assert context.curated_exemplars[0].doc_id == "e1"


def test_hybrid_stages_populate_skill_and_content_results(
    tmp_path: Path,
    fake_embed: None,
) -> None:
    del fake_embed
    store = get_store(str(tmp_path / "vector_store"))

    skill_col = get_or_create_collection(store, SKILLS)
    add_document(
        skill_col,
        doc_id="skill_1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "s_skill"},
    )

    worksheet_col = get_or_create_collection(store, WORKSHEETS)
    add_document(
        worksheet_col,
        doc_id="ws_1",
        embedding=[1.0, 0.0, 0.0],
        metadata={"source_hash": "s_ws"},
    )

    context = retrieve_context(
        skill_description="phonics: cvce",
        extracted_text="grade chase slide",
        db_path=str(tmp_path / "vector_store"),
    )
    assert len(context.similar_skills) == 1
    assert len(context.similar_worksheets) == 1
