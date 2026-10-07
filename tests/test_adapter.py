"""Tests for extract/adapter.py — AI assist interface and schema contracts."""

from __future__ import annotations

import pytest

from extract.adapter import (
    AdaptationSuggestion,
    AIResult,
    ClaudeAdapter,
    GeminiAdapter,
    ModelAdapter,
    NoOpAdapter,
    OCRCorrection,
    OpenAIAdapter,
    OpenRouterAdapter,
    RegionTag,
    SkillInference,
    generate_image,
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
                type="title",
                content="Lesson 43",
                bbox=(0, 0, 100, 50),
                confidence=0.98,
                metadata={},
            ),
            SourceRegion(
                type="concept_label",
                content="New Concept: -all",
                bbox=(0, 60, 100, 100),
                confidence=0.95,
                metadata={},
            ),
            SourceRegion(
                type="sample_words",
                content="tall call wall",
                bbox=(0, 110, 100, 140),
                confidence=0.5,
                metadata={},
            ),
        ],
        raw_text="Lesson 43\nNew Concept: -all\ntall call wall",
        ocr_engine="paddleocr",
        low_confidence_flags=[2],
    )


# --- Schema Contract Tests ---


class TestSchemaContracts:
    def test_ai_result_round_trip_preserves_all_nested_contracts(self) -> None:
        result = AIResult(
            provider="test",
            enabled=True,
            region_tags=[
                RegionTag(
                    region_index=0, suggested_type="title", confidence=0.9, rationale="First line"
                ),
            ],
            skill_inference=SkillInference(
                domain="phonics",
                specific_skill="cvc",
                grade_level="1",
                confidence=0.85,
            ),
            ocr_corrections=[
                OCRCorrection(
                    region_index=2, original_text="ta11", corrected_text="tall", confidence=0.85
                )
            ],
            adaptation_suggestions=[
                AdaptationSuggestion(
                    suggestion_type="chunking",
                    description="Split into 3-item chunks for Grade 1",
                    confidence=0.8,
                )
            ],
        )
        json_str = result.model_dump_json()
        restored = AIResult.model_validate_json(json_str)
        assert restored == result


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


# --- Adapter Factory Tests ---


class TestGetAdapter:
    @pytest.mark.parametrize("provider", ["none", "unknown_provider", "auto"])
    def test_disabled_or_unconfigured_returns_noop(
        self, provider: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert isinstance(get_adapter(provider), NoOpAdapter)

    def test_explicit_none_disables_configured_router(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert isinstance(get_adapter("none"), NoOpAdapter)

    @pytest.mark.parametrize("provider", ["auto", "openrouter", "openai", "gemini", "claude"])
    def test_supported_provider_names_create_router(
        self, provider: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert type(get_adapter(provider)) is OpenRouterAdapter


def test_legacy_adapter_imports_are_router_aliases() -> None:
    assert ClaudeAdapter is OpenAIAdapter is GeminiAdapter is OpenRouterAdapter


@pytest.mark.parametrize("adapter_type", [NoOpAdapter, OpenRouterAdapter])
def test_distinct_adapter_implementations_satisfy_protocol(
    adapter_type: type[NoOpAdapter] | type[OpenRouterAdapter],
) -> None:
    assert isinstance(adapter_type(), ModelAdapter)


def test_adapter_uses_configured_model_and_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_TEXT_MODELS", "model-a,model-b")
    assert OpenRouterAdapter().model == "model-a"
    adapter = get_adapter("openrouter", model="model-c")
    assert isinstance(adapter, OpenRouterAdapter)
    assert adapter.model == "model-c"


# --- AI Assist Runner Tests ---


def test_generate_image_without_router_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert generate_image("a robot", "/tmp/test.png") is None


class TestRunAiAssist:
    def test_noop_returns_disabled(self) -> None:
        adapter = NoOpAdapter()
        result = run_ai_assist(adapter, _source_model())
        assert not result.enabled
        assert result.provider == "NoOpAdapter"
        assert len(result.region_tags) == 0
        assert result.skill_inference is None
        assert result.ocr_corrections == []
        assert result.adaptation_suggestions == []
