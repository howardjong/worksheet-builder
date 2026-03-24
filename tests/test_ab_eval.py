"""Tests for eval extraction hardening and A/B reporting in ab_eval.py."""

from __future__ import annotations

import pytest

from ab_eval import _build_pair_summary, _extract_source_model, _select_negative_control_context
from extract.schema import PIPELINE_VERSION, OCRResult, SourceRegion, SourceWorksheetModel
from rag.retrieval import RAGContext, RetrievalResult


def _source_model() -> SourceWorksheetModel:
    return SourceWorksheetModel(
        source_image_hash="hash123",
        pipeline_version=PIPELINE_VERSION,
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="sample_words",
                content="grade chase",
                bbox=(0, 0, 10, 10),
                confidence=0.9,
                metadata={},
            )
        ],
        raw_text="grade chase",
        ocr_engine="gemini_vision",
        low_confidence_flags=[],
    )


def test_extract_source_model_vision_only_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ab_eval.extract_with_vision", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="Gemini vision extraction is unavailable"):
        _extract_source_model("unused.png", "hash123", extract_mode="vision_only")


def test_extract_source_model_auto_falls_back_to_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ocr_result = OCRResult(blocks=[], engine="paddleocr", raw_text="grade chase")
    expected = _source_model()

    monkeypatch.setattr("ab_eval.extract_with_vision", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "ab_eval.extract_text_with_fallback",
        lambda image_path: ocr_result if image_path == "unused.png" else None,
    )
    monkeypatch.setattr(
        "ab_eval.map_to_source_model",
        lambda result, source_hash: expected
        if result is ocr_result and source_hash == "hash123"
        else None,
    )

    result = _extract_source_model("unused.png", "hash123", extract_mode="auto")

    assert result == expected


def test_extract_source_model_tesseract_uses_requested_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ocr_result = OCRResult(blocks=[], engine="tesseract", raw_text="grade chase")
    expected = _source_model()

    monkeypatch.setattr(
        "ab_eval.extract_text",
        lambda image_path, engine: ocr_result
        if image_path == "unused.png" and engine == "tesseract"
        else None,
    )
    monkeypatch.setattr(
        "ab_eval.map_to_source_model",
        lambda result, source_hash: expected
        if result is ocr_result and source_hash == "hash123"
        else None,
    )

    result = _extract_source_model("unused.png", "hash123", extract_mode="tesseract")

    assert result == expected


def test_select_negative_control_context_prefers_similar_skills() -> None:
    context = RAGContext(
        similar_skills=[
            RetrievalResult(
                doc_id="skill_1",
                score=0.42,
                metadata={"source_hash": "skill-hash"},
                document="",
            )
        ],
        curated_exemplars=[
            RetrievalResult(
                doc_id="ex_1",
                score=0.95,
                metadata={"source_hash": "exemplar-hash"},
                document="",
            )
        ],
    )

    selected, debug = _select_negative_control_context(context)

    assert selected is not None
    assert debug["selected_source"] == "negative_control_similar_skills"
    assert debug["selected_count"] == 1
    assert selected[0]["_rag_doc_id"] == "skill_1"


def test_build_pair_summary_includes_curriculum_and_control_deltas() -> None:
    result_a = {
        "validation": {
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        "all_validators_passed": True,
        "response_format_count": 4,
        "curriculum_supported_items": 0,
        "curriculum_support_rate": 0.0,
    }
    result_b = {
        "validation": {
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        "all_validators_passed": True,
        "response_format_count": 4,
        "curriculum_supported_items": 2,
        "curriculum_support_rate": 0.5,
    }
    result_c = {
        "validation": {
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        "all_validators_passed": True,
        "response_format_count": 4,
        "curriculum_supported_items": 1,
        "curriculum_support_rate": 0.25,
    }

    summary = _build_pair_summary("IMG_0004.JPG", result_a, result_b, result_c)

    assert summary["delta"]["curriculum_supported_items"] == 2
    assert summary["delta"]["curriculum_support_rate"] == 0.5
    assert summary["control_delta"] is not None
    assert summary["control_delta"]["curriculum_supported_items"] == 1
    assert int(summary["control_delta"]["score"]) > 0
