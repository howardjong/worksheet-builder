"""Model adapter interface — pluggable AI assist behind a provider protocol.

AI is optional. The pipeline works fully without any API keys.
When AI is enabled, all outputs are schema-validated before entering the pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from extract.schema import SourceRegion, SourceWorksheetModel

logger = logging.getLogger(__name__)


# --- Schema contracts for AI outputs ---


class RegionTag(BaseModel):
    """AI-suggested semantic tag for a worksheet region."""

    region_index: int
    suggested_type: str
    confidence: float
    rationale: str = ""


class SkillInference(BaseModel):
    """AI-inferred skill from a worksheet."""

    domain: str
    specific_skill: str
    grade_level: str
    confidence: float
    rationale: str = ""


class OCRCorrection(BaseModel):
    """AI-suggested correction for a low-confidence OCR region."""

    region_index: int
    original_text: str
    corrected_text: str
    confidence: float


class AdaptationSuggestion(BaseModel):
    """AI-suggested activity adaptation."""

    suggestion_type: str  # "response_format" | "chunking" | "scaffold"
    description: str
    confidence: float


class AIResult(BaseModel):
    """Container for AI assist results — all Optional."""

    region_tags: list[RegionTag] = Field(default_factory=list)
    skill_inference: SkillInference | None = None
    ocr_corrections: list[OCRCorrection] = Field(default_factory=list)
    adaptation_suggestions: list[AdaptationSuggestion] = Field(default_factory=list)
    provider: str = "none"
    enabled: bool = False


# --- Provider Protocol ---


@runtime_checkable
class ModelAdapter(Protocol):
    """Protocol for AI assist providers. All methods are optional-use."""

    def tag_regions(self, image_path: str, source: SourceWorksheetModel) -> list[RegionTag]: ...

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None: ...

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]: ...

    def suggest_adaptations(self, source: SourceWorksheetModel) -> list[AdaptationSuggestion]: ...


# --- No-op adapter (always available, deterministic baseline) ---


class NoOpAdapter:
    """Default adapter when AI is disabled. Returns empty results."""

    def tag_regions(self, image_path: str, source: SourceWorksheetModel) -> list[RegionTag]:
        return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        return None

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]:
        return []

    def suggest_adaptations(self, source: SourceWorksheetModel) -> list[AdaptationSuggestion]:
        return []


class OpenRouterAdapter:
    """Schema-validated AI assist through the shared OpenRouter model chain."""

    def __init__(self, model: str | None = None) -> None:
        from ai import openrouter

        self.model = model or next(iter(openrouter.models("text")), "none")
        self._model_ids = [model] if model else None

    def _call(self, prompt: str, max_tokens: int = 512) -> str:
        from ai import openrouter

        result = openrouter.complete(
            prompt,
            max_tokens=max_tokens,
            model_ids=self._model_ids,
            accept=lambda text: isinstance(openrouter.json_value(text), (dict, list)),
        )
        return json.dumps(openrouter.json_value(result.text)) if result else ""

    def generate_image(self, prompt: str, output_path: str, size: str = "1024x1024") -> str | None:
        from pathlib import Path

        from ai import openrouter

        result = openrouter.generate_with_fallbacks(prompt, aspect_ratio="1:1")
        if result:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(result)
            return output_path
        return None

    def tag_regions(self, image_path: str, source: SourceWorksheetModel) -> list[RegionTag]:
        try:
            prompt = _build_tag_prompt(source)
            text = self._call(prompt, max_tokens=1024)
            data = json.loads(text)
            return [RegionTag.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"OpenRouter tag_regions failed: {e}")
            return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        try:
            prompt = _build_skill_prompt(source)
            text = self._call(prompt, max_tokens=256)
            data = json.loads(text)
            return SkillInference.model_validate(data)
        except Exception as e:
            logger.warning(f"OpenRouter infer_skill failed: {e}")
            return None

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]:
        try:
            prompt = _build_ocr_prompt(regions)
            if prompt is None:
                return []
            text = self._call(prompt)
            data = json.loads(text)
            return [OCRCorrection.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"OpenRouter review_ocr failed: {e}")
            return []

    def suggest_adaptations(self, source: SourceWorksheetModel) -> list[AdaptationSuggestion]:
        try:
            prompt = _build_adaptation_prompt(source)
            text = self._call(prompt)
            data = json.loads(text)
            return [AdaptationSuggestion.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"OpenRouter suggest_adaptations failed: {e}")
            return []


# Legacy import names retain the protocol, but cannot create direct provider clients.
ClaudeAdapter = OpenRouterAdapter
OpenAIAdapter = OpenRouterAdapter
GeminiAdapter = OpenRouterAdapter


# --- Shared prompt builders ---


def _build_tag_prompt(source: SourceWorksheetModel) -> str:
    prompt = (
        "You are analyzing a K-3 literacy worksheet. "
        f"Template type: {source.template_type}. "
        f"There are {len(source.regions)} text regions extracted by OCR.\n\n"
        "For each region, suggest a semantic type from: "
        "title, concept_label, sample_words, word_chain, chain_script, "
        "sight_word_list, practice_sentences, story_title, decodable_passage, "
        "instruction, question, word_list.\n\nRegions:\n"
    )
    for i, r in enumerate(source.regions):
        prompt += f'{i}. [{r.type}] "{r.content[:80]}"\n'
    prompt += (
        "\nRespond with ONLY a JSON array: "
        '[{"region_index": 0, "suggested_type": "...", '
        '"confidence": 0.9, "rationale": "..."}]'
    )
    return prompt


def _build_skill_prompt(source: SourceWorksheetModel) -> str:
    return (
        "You are analyzing a K-3 literacy worksheet.\n"
        f"Template: {source.template_type}\n"
        f"Text content:\n{source.raw_text[:500]}\n\n"
        "Infer the primary literacy skill being taught. "
        "Respond with ONLY JSON: "
        '{"domain": "phonics|fluency|...", "specific_skill": "...", '
        '"grade_level": "K|1|2|3", "confidence": 0.9, "rationale": "..."}'
    )


def _build_ocr_prompt(regions: list[SourceRegion]) -> str | None:
    low_conf = [(i, r) for i, r in enumerate(regions) if r.confidence < 0.7]
    if not low_conf:
        return None
    prompt = (
        "Review these low-confidence OCR extractions from a K-3 worksheet. "
        "Suggest corrections where the text looks wrong.\n\n"
    )
    for i, r in low_conf:
        prompt += f'{i}. "{r.content}" (conf: {r.confidence:.2f})\n'
    prompt += (
        "\nRespond with ONLY a JSON array: "
        '[{"region_index": 0, "original_text": "...", '
        '"corrected_text": "...", "confidence": 0.9}]'
    )
    return prompt


def _build_adaptation_prompt(source: SourceWorksheetModel) -> str:
    return (
        "You are an ADHD learning specialist reviewing a K-3 worksheet.\n"
        f"Template: {source.template_type}\n"
        f"Content preview:\n{source.raw_text[:300]}\n\n"
        "Suggest ADHD-friendly adaptations. Keep suggestions specific "
        "and actionable. Respond with ONLY a JSON array: "
        '[{"suggestion_type": "response_format|chunking|scaffold", '
        '"description": "...", "confidence": 0.9}]'
    )


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            if line.strip() == "```" and in_block:
                break
            if in_block:
                json_lines.append(line)
        return "\n".join(json_lines)
    return text


# --- Adapter factory ---


_PROVIDERS: dict[str, type] = {
    "claude": ClaudeAdapter,
    "openai": OpenAIAdapter,
    "gemini": GeminiAdapter,
    "none": NoOpAdapter,
}


def get_adapter(provider: str = "auto", **kwargs: str) -> ModelAdapter:
    """Select OpenRouter or the deterministic baseline; vendor names are aliases."""
    from ai import openrouter

    if provider == "none" or (provider == "auto" and not openrouter.available()):
        return NoOpAdapter()
    if provider in {"auto", "openrouter", "openai", "gemini", "claude"}:
        return OpenRouterAdapter(**kwargs)
    logger.warning("Unknown AI provider '%s', using NoOp", provider)
    return NoOpAdapter()


def run_ai_assist(
    adapter: ModelAdapter,
    source: SourceWorksheetModel,
    image_path: str | None = None,
) -> AIResult:
    """Run all AI assist operations and return validated results.

    All outputs are schema-validated. Failures are logged and skipped.
    """
    is_noop = isinstance(adapter, NoOpAdapter)

    result = AIResult(
        provider=type(adapter).__name__,
        enabled=not is_noop,
    )

    if is_noop:
        return result

    # Tag regions (requires image)
    if image_path:
        result.region_tags = adapter.tag_regions(image_path, source)

    # Infer skill
    result.skill_inference = adapter.infer_skill(source)

    # Review low-confidence OCR
    result.ocr_corrections = adapter.review_ocr(source.regions)

    # Suggest adaptations
    result.adaptation_suggestions = adapter.suggest_adaptations(source)

    logger.info(
        f"AI assist ({result.provider}): "
        f"{len(result.region_tags)} tags, "
        f"{'skill inferred' if result.skill_inference else 'no skill'}, "
        f"{len(result.ocr_corrections)} OCR corrections, "
        f"{len(result.adaptation_suggestions)} suggestions"
    )

    return result


def generate_image(prompt: str, output_path: str) -> str | None:
    """Generate an image through the shared OpenRouter model fallback chain."""
    return OpenRouterAdapter().generate_image(prompt, output_path)
