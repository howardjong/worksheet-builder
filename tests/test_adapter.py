"""Tests for extract/adapter.py — AI assist interface and schema contracts."""

from __future__ import annotations

from extract.adapter import (
    AdaptationSuggestion,
    AIResult,
    ClaudeAdapter,
    GeminiAdapter,
    NoOpAdapter,
    OCRCorrection,
    OpenAIAdapter,
    RegionTag,
    SkillInference,
    get_adapter,
    run_ai_assist,
)
from extract.schema import SourceRegion, SourceWorksheetModel


def _source_model() -> SourceWorksheetModel:
    return SourceWorksheetModel(
        source_image_hash="test123",
        pipeline_version="0.1.0",
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="title", content="Lesson 43",
                bbox=(0, 0, 100, 50), confidence=0.98, metadata={},
            ),
            SourceRegion(
                type="concept_label", content="New Concept: -all",
                bbox=(0, 60, 100, 100), confidence=0.95, metadata={},
            ),
            SourceRegion(
                type="sample_words", content="tall call wall",
                bbox=(0, 110, 100, 140), confidence=0.5, metadata={},
            ),
        ],
        raw_text="Lesson 43\nNew Concept: -all\ntall call wall",
        ocr_engine="paddleocr",
        low_confidence_flags=[2],
    )


# --- Schema Contract Tests ---


class TestSchemaContracts:
    def test_region_tag_validates(self) -> None:
        tag = RegionTag(
            region_index=0, suggested_type="title",
            confidence=0.95, rationale="First line",
        )
        assert tag.region_index == 0
        json_str = tag.model_dump_json()
        restored = RegionTag.model_validate_json(json_str)
        assert restored.suggested_type == "title"

    def test_skill_inference_validates(self) -> None:
        inf = SkillInference(
            domain="phonics", specific_skill="cvc_blending",
            grade_level="1", confidence=0.9,
        )
        assert inf.domain == "phonics"

    def test_ocr_correction_validates(self) -> None:
        corr = OCRCorrection(
            region_index=2, original_text="ta11",
            corrected_text="tall", confidence=0.85,
        )
        assert corr.corrected_text == "tall"

    def test_adaptation_suggestion_validates(self) -> None:
        sug = AdaptationSuggestion(
            suggestion_type="chunking",
            description="Split into 3-item chunks for Grade 1",
            confidence=0.8,
        )
        assert sug.suggestion_type == "chunking"

    def test_ai_result_round_trip(self) -> None:
        result = AIResult(
            provider="test",
            enabled=True,
            region_tags=[
                RegionTag(region_index=0, suggested_type="title", confidence=0.9),
            ],
            skill_inference=SkillInference(
                domain="phonics", specific_skill="cvc",
                grade_level="1", confidence=0.85,
            ),
        )
        json_str = result.model_dump_json()
        restored = AIResult.model_validate_json(json_str)
        assert len(restored.region_tags) == 1
        assert restored.skill_inference is not None


# --- NoOp Adapter Tests ---


class TestNoOpAdapter:
    def test_tag_regions_returns_empty(self) -> None:
        adapter = NoOpAdapter()
        result = adapter.tag_regions("fake.png", _source_model())
        assert result == []

    def test_infer_skill_returns_none(self) -> None:
        adapter = NoOpAdapter()
        result = adapter.infer_skill(_source_model())
        assert result is None

    def test_review_ocr_returns_empty(self) -> None:
        adapter = NoOpAdapter()
        result = adapter.review_ocr(_source_model().regions)
        assert result == []

    def test_suggest_adaptations_returns_empty(self) -> None:
        adapter = NoOpAdapter()
        result = adapter.suggest_adaptations(_source_model())
        assert result == []

    def test_implements_protocol(self) -> None:
        from extract.adapter import ModelAdapter

        adapter = NoOpAdapter()
        assert isinstance(adapter, ModelAdapter)


# --- Adapter Factory Tests ---


class TestGetAdapter:
    def test_none_returns_noop(self) -> None:
        adapter = get_adapter("none")
        assert isinstance(adapter, NoOpAdapter)

    def test_unknown_returns_noop(self) -> None:
        adapter = get_adapter("unknown_provider")
        assert isinstance(adapter, NoOpAdapter)

    def test_auto_without_key_returns_noop(self) -> None:
        import os
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            adapter = get_adapter("auto")
            assert isinstance(adapter, NoOpAdapter)
        finally:
            if old:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_claude_adapter_created(self) -> None:
        adapter = get_adapter("claude", api_key="test-key")
        assert isinstance(adapter, ClaudeAdapter)

    def test_openai_adapter_created(self) -> None:
        adapter = get_adapter("openai", api_key="test-key")
        assert isinstance(adapter, OpenAIAdapter)

    def test_gemini_adapter_created(self) -> None:
        adapter = get_adapter("gemini", api_key="test-key")
        assert isinstance(adapter, GeminiAdapter)

    def test_claude_implements_protocol(self) -> None:
        from extract.adapter import ModelAdapter

        adapter = ClaudeAdapter(api_key="test")
        assert isinstance(adapter, ModelAdapter)

    def test_openai_implements_protocol(self) -> None:
        from extract.adapter import ModelAdapter

        adapter = OpenAIAdapter(api_key="test")
        assert isinstance(adapter, ModelAdapter)

    def test_gemini_implements_protocol(self) -> None:
        from extract.adapter import ModelAdapter

        adapter = GeminiAdapter(api_key="test")
        assert isinstance(adapter, ModelAdapter)

    def test_auto_with_gemini_key(self) -> None:
        import os

        old_a = os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["GEMINI_API_KEY"] = "test-key"
        try:
            adapter = get_adapter("auto")
            assert isinstance(adapter, GeminiAdapter)
        finally:
            del os.environ["GEMINI_API_KEY"]
            if old_a:
                os.environ["ANTHROPIC_API_KEY"] = old_a

    def test_auto_with_openai_key(self) -> None:
        import os

        old_a = os.environ.pop("ANTHROPIC_API_KEY", None)
        old_g = os.environ.pop("GEMINI_API_KEY", None)
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            adapter = get_adapter("auto")
            assert isinstance(adapter, OpenAIAdapter)
        finally:
            del os.environ["OPENAI_API_KEY"]
            if old_a:
                os.environ["ANTHROPIC_API_KEY"] = old_a
            if old_g:
                os.environ["GEMINI_API_KEY"] = old_g


# --- AI Assist Runner Tests ---


class TestRunAiAssist:
    def test_noop_returns_disabled(self) -> None:
        adapter = NoOpAdapter()
        result = run_ai_assist(adapter, _source_model())
        assert not result.enabled
        assert result.provider == "NoOpAdapter"
        assert len(result.region_tags) == 0
        assert result.skill_inference is None

    def test_result_is_valid_model(self) -> None:
        adapter = NoOpAdapter()
        result = run_ai_assist(adapter, _source_model())
        json_str = result.model_dump_json()
        restored = AIResult.model_validate_json(json_str)
        assert not restored.enabled
