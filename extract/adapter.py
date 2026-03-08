"""Model adapter interface — pluggable AI assist behind a provider protocol.

AI is optional. The pipeline works fully without any API keys.
When AI is enabled, all outputs are schema-validated before entering the pipeline.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

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

    def tag_regions(
        self, image_path: str, source: SourceWorksheetModel
    ) -> list[RegionTag]: ...

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None: ...

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]: ...

    def suggest_adaptations(
        self, source: SourceWorksheetModel
    ) -> list[AdaptationSuggestion]: ...


# --- No-op adapter (always available, deterministic baseline) ---


class NoOpAdapter:
    """Default adapter when AI is disabled. Returns empty results."""

    def tag_regions(
        self, image_path: str, source: SourceWorksheetModel
    ) -> list[RegionTag]:
        return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        return None

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]:
        return []

    def suggest_adaptations(
        self, source: SourceWorksheetModel
    ) -> list[AdaptationSuggestion]:
        return []


# --- Claude adapter ---


class ClaudeAdapter:
    """AI assist via Anthropic Claude API."""

    def __init__(
        self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _call(self, prompt: str, max_tokens: int = 512) -> str:
        """Make an API call and return the text response."""
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return str(response.content[0].text)

    def tag_regions(
        self, image_path: str, source: SourceWorksheetModel
    ) -> list[RegionTag]:
        try:
            text = self._call(_build_tag_prompt(source), max_tokens=1024)
            data = json.loads(text)
            return [RegionTag.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"Claude tag_regions failed: {e}")
            return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        try:
            text = self._call(_build_skill_prompt(source), max_tokens=256)
            data = json.loads(text)
            return SkillInference.model_validate(data)
        except Exception as e:
            logger.warning(f"Claude infer_skill failed: {e}")
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
            logger.warning(f"Claude review_ocr failed: {e}")
            return []

    def suggest_adaptations(
        self, source: SourceWorksheetModel
    ) -> list[AdaptationSuggestion]:
        try:
            text = self._call(_build_adaptation_prompt(source))
            data = json.loads(text)
            return [AdaptationSuggestion.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"Claude suggest_adaptations failed: {e}")
            return []


# --- OpenAI adapter ---


class OpenAIAdapter:
    """AI assist via OpenAI API (GPT-5.4 primary)."""

    def __init__(
        self, api_key: str | None = None, model: str = "gpt-5.4"
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def _call(self, prompt: str, max_tokens: int = 512) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return str(response.choices[0].message.content or "")

    def tag_regions(
        self, image_path: str, source: SourceWorksheetModel
    ) -> list[RegionTag]:
        try:
            prompt = _build_tag_prompt(source)
            text = self._call(prompt, max_tokens=1024)
            data = json.loads(text)
            return [RegionTag.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"OpenAI tag_regions failed: {e}")
            return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        try:
            prompt = _build_skill_prompt(source)
            text = self._call(prompt, max_tokens=256)
            data = json.loads(text)
            return SkillInference.model_validate(data)
        except Exception as e:
            logger.warning(f"OpenAI infer_skill failed: {e}")
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
            logger.warning(f"OpenAI review_ocr failed: {e}")
            return []

    def suggest_adaptations(
        self, source: SourceWorksheetModel
    ) -> list[AdaptationSuggestion]:
        try:
            prompt = _build_adaptation_prompt(source)
            text = self._call(prompt)
            data = json.loads(text)
            return [AdaptationSuggestion.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"OpenAI suggest_adaptations failed: {e}")
            return []

    IMAGE_MODEL = "gpt-image-1.5"

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        size: str = "1024x1024",
    ) -> str | None:
        """Generate an image using OpenAI gpt-image-1.5.

        Fallback image generator when Gemini is unavailable.
        Returns the output path on success, None on failure.
        """
        try:
            import base64
            from pathlib import Path

            client = self._get_client()
            response = client.images.generate(
                model=self.IMAGE_MODEL,
                prompt=prompt,
                n=1,
                size=size,
                response_format="b64_json",
            )

            b64_data = response.data[0].b64_json
            if not b64_data:
                logger.warning("OpenAI image generation returned no data")
                return None

            image_bytes = base64.b64decode(b64_data)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            logger.info(f"Generated image (OpenAI): {output_path}")
            return output_path

        except Exception as e:
            logger.warning(f"OpenAI image generation failed: {e}")
            return None


# --- Gemini adapter ---


class GeminiAdapter:
    """AI assist via Google Gemini API.

    Uses gemini-3.1-flash-lite-preview for text tasks and
    gemini-3.1-flash-image-preview for image generation.
    """

    IMAGE_MODEL = "gemini-3.1-flash-image-preview"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3.1-flash-lite-preview",
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self._client: Any = None
        self._image_client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._client = genai.GenerativeModel(self.model)
        return self._client

    def _get_image_client(self) -> Any:
        if self._image_client is None:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._image_client = genai.GenerativeModel(self.IMAGE_MODEL)
        return self._image_client

    def _call(self, prompt: str) -> str:
        client = self._get_client()
        response = client.generate_content(prompt)
        return str(response.text)

    def generate_image(
        self,
        prompt: str,
        output_path: str,
    ) -> str | None:
        """Generate an image using gemini-3.1-flash-image-preview.

        Used for custom avatar items and theme assets.
        Returns the output path on success, None on failure.
        """
        try:
            from pathlib import Path

            client = self._get_image_client()
            response = client.generate_content(prompt)

            # Extract image data from response
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    image_data = part.inline_data.data
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(image_data)
                    logger.info(f"Generated image: {output_path}")
                    return output_path

            # If response is text-only, no image was generated
            logger.warning("Gemini image generation returned text, not image")
            return None

        except Exception as e:
            logger.warning(f"Gemini image generation failed: {e}")
            return None

    def tag_regions(
        self, image_path: str, source: SourceWorksheetModel
    ) -> list[RegionTag]:
        try:
            prompt = _build_tag_prompt(source)
            text = self._call(prompt)
            data = json.loads(_extract_json(text))
            return [RegionTag.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"Gemini tag_regions failed: {e}")
            return []

    def infer_skill(self, source: SourceWorksheetModel) -> SkillInference | None:
        try:
            prompt = _build_skill_prompt(source)
            text = self._call(prompt)
            data = json.loads(_extract_json(text))
            return SkillInference.model_validate(data)
        except Exception as e:
            logger.warning(f"Gemini infer_skill failed: {e}")
            return None

    def review_ocr(self, regions: list[SourceRegion]) -> list[OCRCorrection]:
        try:
            prompt = _build_ocr_prompt(regions)
            if prompt is None:
                return []
            text = self._call(prompt)
            data = json.loads(_extract_json(text))
            return [OCRCorrection.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"Gemini review_ocr failed: {e}")
            return []

    def suggest_adaptations(
        self, source: SourceWorksheetModel
    ) -> list[AdaptationSuggestion]:
        try:
            prompt = _build_adaptation_prompt(source)
            text = self._call(prompt)
            data = json.loads(_extract_json(text))
            return [AdaptationSuggestion.model_validate(item) for item in data]
        except Exception as e:
            logger.warning(f"Gemini suggest_adaptations failed: {e}")
            return []


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
        prompt += f"{i}. [{r.type}] \"{r.content[:80]}\"\n"
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
        prompt += f"{i}. \"{r.content}\" (conf: {r.confidence:.2f})\n"
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
    """Get an AI adapter by provider name.

    "auto" — tries providers in order: OpenAI, Gemini, Claude, NoOp.
    "openai" — requires OPENAI_API_KEY (primary, GPT-5.4).
    "gemini" — requires GEMINI_API_KEY (text + image generation).
    "claude" — requires ANTHROPIC_API_KEY.
    "none" — deterministic baseline, no AI.
    """
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        elif os.environ.get("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            provider = "claude"
        else:
            provider = "none"

    adapter_cls = _PROVIDERS.get(provider)
    if adapter_cls is None:
        logger.warning(f"Unknown AI provider '{provider}', using NoOp")
        return NoOpAdapter()

    instance: Any = adapter_cls(**kwargs)
    return instance  # type: ignore[no-any-return]


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
    """Generate an image, trying Gemini first, falling back to OpenAI.

    Returns the output path on success, None if both fail or no keys available.
    """
    # Try Gemini first
    if os.environ.get("GEMINI_API_KEY"):
        gemini = GeminiAdapter()
        result = gemini.generate_image(prompt, output_path)
        if result:
            return result
        logger.info("Gemini image generation failed, trying OpenAI fallback")

    # Fall back to OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        openai_adapter = OpenAIAdapter()
        result = openai_adapter.generate_image(prompt, output_path)
        if result:
            return result

    logger.warning("No image generation provider available")
    return None
