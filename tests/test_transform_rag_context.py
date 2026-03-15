"""Tests for RAG context selection used by the transform pipeline."""

from __future__ import annotations

from rag.retrieval import RAGContext, RetrievalResult
from transform import _select_rag_adaptation_context, _select_rag_curriculum_context


def _result(doc_id: str, score: float, metadata: dict[str, object]) -> RetrievalResult:
    return RetrievalResult(doc_id=doc_id, score=score, metadata=metadata, document="")


def test_select_context_prefers_curated_exemplars() -> None:
    context = RAGContext(
        prior_adaptations=[
            _result("adapt_old", 0.61, {"source_hash": "old"}),
        ],
        curated_exemplars=[
            _result(
                "exemplar_best",
                0.93,
                {
                    "source_hash": "best",
                    "response_formats": "match,trace,circle",
                    "distractor_words": "cat,dog",
                },
            ),
        ],
    )

    selected, debug = _select_rag_adaptation_context(context)

    assert selected is not None
    assert len(selected) == 1
    assert selected[0]["source_hash"] == "best"
    assert selected[0]["_rag_doc_id"] == "exemplar_best"
    assert debug["selected_source"] == "curated_exemplars"
    assert debug["selected_count"] == 1


def test_select_context_falls_back_to_prior_adaptations() -> None:
    context = RAGContext(
        prior_adaptations=[
            _result(
                "adapt_1",
                0.88,
                {"source_hash": "seed_1", "response_formats": "fill_blank,write"},
            ),
            _result(
                "adapt_2",
                0.77,
                {"source_hash": "seed_2", "response_formats": "match,circle"},
            ),
        ],
        curated_exemplars=[],
    )

    selected, debug = _select_rag_adaptation_context(context)

    assert selected is not None
    assert len(selected) == 2
    assert debug["selected_source"] == "prior_adaptations"
    assert debug["selected_count"] == 2
    assert debug["selected_doc_ids"] == ["adapt_1", "adapt_2"]


def test_select_context_returns_none_when_no_hits() -> None:
    context = RAGContext()
    selected, debug = _select_rag_adaptation_context(context)
    assert selected is None
    assert debug["selected_source"] == "none"
    assert debug["selected_count"] == 0


def test_select_curriculum_context_preserves_documents() -> None:
    context = RAGContext(
        curriculum_references=[
            RetrievalResult(
                doc_id="curriculum_ufli_59",
                score=0.97,
                metadata={"lesson_id": "59", "concept": "VCe Review 2"},
                document="grade slide quite froze these",
            )
        ]
    )

    selected = _select_rag_curriculum_context(context)

    assert selected is not None
    assert selected[0]["lesson_id"] == "59"
    assert selected[0]["_rag_doc_id"] == "curriculum_ufli_59"
    assert selected[0]["_rag_document"] == "grade slide quite froze these"
