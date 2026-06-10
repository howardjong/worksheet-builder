"""Tests for RAG context selection used by the transform pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from extract.schema import PIPELINE_VERSION, SourceRegion, SourceWorksheetModel
from rag.retrieval import RAGContext, RetrievalResult
from skill.schema import LiteracySkillModel, SourceItem
from transform import (
    RunArtifacts,
    _select_rag_adaptation_context,
    _select_rag_curriculum_context,
    run_pipeline_collect_artifacts,
)


def _result(doc_id: str, score: float, metadata: dict[str, object]) -> RetrievalResult:
    return RetrievalResult(doc_id=doc_id, score=score, metadata=metadata, document="")


def _source_model() -> SourceWorksheetModel:
    return SourceWorksheetModel(
        source_image_hash="hash123",
        pipeline_version=PIPELINE_VERSION,
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="word_list",
                content="grade chase",
                bbox=(0, 0, 10, 10),
                confidence=0.9,
                metadata={},
            )
        ],
        raw_text="grade chase slide",
        ocr_engine="gemini_vision",
        low_confidence_flags=[],
    )


def _skill_model() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["grade", "chase"],
        response_types=["circle", "trace"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade chase",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.9,
        template_type="ufli_word_work",
    )


def _patch_minimal_live_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    source = _source_model()
    skill = _skill_model()
    captured: dict[str, Any] = {}

    monkeypatch.setattr("transform.preprocess_page", lambda _src, _dst: None)
    monkeypatch.setattr(
        "transform.store_master",
        lambda _path, _masters_dir: SimpleNamespace(image_hash="hash123"),
    )
    monkeypatch.setattr("transform.extract_with_vision", lambda _path, _hash: source)
    monkeypatch.setattr("transform.extract_skill", lambda _source: skill)
    monkeypatch.setattr("transform.load_profile", lambda _path: SimpleNamespace(name="Ian"))
    monkeypatch.setattr(
        "transform.load_theme",
        lambda _theme: SimpleNamespace(multi_worksheet=False),
    )

    def fake_single_pipeline(**kwargs: Any) -> RunArtifacts:
        captured.update(kwargs)
        return RunArtifacts(
            source_image_path=str(kwargs["source_image_path"]),
            source_image_hash=str(kwargs["source_image_hash"]),
            extracted_text=str(kwargs["extracted_text"]),
            template_type=str(kwargs["template_type"]),
            ocr_engine=str(kwargs["ocr_engine"]),
            region_count=int(kwargs["region_count"]),
            skill_domain=skill.domain,
            skill_name=skill.specific_skill,
            grade_level=skill.grade_level,
            theme_id=str(kwargs["theme_id"]),
            worksheet_mode="single",
            adapted_summaries=[],
            pdf_paths=[str(Path(kwargs["output"]) / "worksheet.pdf")],
            validation_results={"all_validators_passed": True},
            profile_name="Ian",
        )

    monkeypatch.setattr("transform._run_single_worksheet_pipeline", fake_single_pipeline)
    return captured


def test_live_pipeline_rag_retrieval_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_minimal_live_pipeline(monkeypatch)
    retrieval_calls: list[dict[str, object]] = []
    monkeypatch.delenv("WORKSHEET_USE_RAG", raising=False)
    monkeypatch.setattr("transform.rag_available", lambda: True)

    def fake_retrieve_context(**kwargs: object) -> RAGContext:
        retrieval_calls.append(kwargs)
        return RAGContext()

    monkeypatch.setattr("rag.retrieval.retrieve_context", fake_retrieve_context)

    run_pipeline_collect_artifacts(
        input_path="input.jpg",
        profile_path="profiles/ian.yaml",
        theme_id="roblox_obby",
        output_dir=str(tmp_path / "output"),
        artifacts_dir=str(tmp_path / "artifacts"),
        index_results=False,
    )

    assert retrieval_calls == []
    assert captured["rag_prior_adaptations"] is None
    assert captured["rag_curriculum_references"] is None
    rag_debug = json.loads((tmp_path / "artifacts" / "rag_context.json").read_text())
    assert rag_debug["enabled"] is False
    assert "WORKSHEET_USE_RAG not set" in rag_debug["reason"]


def test_live_pipeline_rag_indexing_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_minimal_live_pipeline(monkeypatch)
    index_calls: list[dict[str, object]] = []
    monkeypatch.delenv("WORKSHEET_USE_RAG", raising=False)
    monkeypatch.setattr("transform.rag_available", lambda: True)

    def fake_index_run(**kwargs: object) -> None:
        index_calls.append(kwargs)

    monkeypatch.setattr("rag.indexer.index_run", fake_index_run)

    run_pipeline_collect_artifacts(
        input_path="input.jpg",
        profile_path="profiles/ian.yaml",
        theme_id="roblox_obby",
        output_dir=str(tmp_path / "output"),
        artifacts_dir=str(tmp_path / "artifacts"),
        index_results=True,
    )

    assert index_calls == []


def test_live_pipeline_rag_opt_in_allows_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_minimal_live_pipeline(monkeypatch)
    retrieval_calls: list[dict[str, object]] = []
    monkeypatch.setenv("WORKSHEET_USE_RAG", "1")
    monkeypatch.setattr("transform.rag_available", lambda: True)

    def fake_retrieve_context(**kwargs: object) -> RAGContext:
        retrieval_calls.append(kwargs)
        return RAGContext(
            curated_exemplars=[
                _result("exemplar_best", 0.93, {"source_hash": "best"}),
            ],
            curriculum_references=[
                RetrievalResult(
                    doc_id="curriculum_ufli_59",
                    score=0.97,
                    metadata={"lesson_id": "59"},
                    document="grade slide quite",
                )
            ],
        )

    monkeypatch.setattr("rag.retrieval.retrieve_context", fake_retrieve_context)

    run_pipeline_collect_artifacts(
        input_path="input.jpg",
        profile_path="profiles/ian.yaml",
        theme_id="roblox_obby",
        output_dir=str(tmp_path / "output"),
        artifacts_dir=str(tmp_path / "artifacts"),
        index_results=False,
    )

    assert len(retrieval_calls) == 1
    assert captured["rag_prior_adaptations"] is not None
    assert captured["rag_curriculum_references"] is not None
    rag_debug = json.loads((tmp_path / "artifacts" / "rag_context.json").read_text())
    assert rag_debug["enabled"] is True
    assert rag_debug["selected_source"] == "curated_exemplars"


def test_live_pipeline_rag_opt_in_allows_indexing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_minimal_live_pipeline(monkeypatch)
    index_calls: list[dict[str, object]] = []
    monkeypatch.setenv("WORKSHEET_USE_RAG", "1")
    monkeypatch.setattr("transform.rag_available", lambda: True)
    monkeypatch.setattr("rag.retrieval.retrieve_context", lambda **_kwargs: RAGContext())

    def fake_index_run(**kwargs: object) -> None:
        index_calls.append(kwargs)

    monkeypatch.setattr("rag.indexer.index_run", fake_index_run)

    run_pipeline_collect_artifacts(
        input_path="input.jpg",
        profile_path="profiles/ian.yaml",
        theme_id="roblox_obby",
        output_dir=str(tmp_path / "output"),
        artifacts_dir=str(tmp_path / "artifacts"),
        index_results=True,
    )

    assert len(index_calls) == 1
    assert index_calls[0]["source_image_hash"] == "hash123"


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
