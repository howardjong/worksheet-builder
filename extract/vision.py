"""Vision-based worksheet extraction using Gemini as fallback for poor OCR results."""

from __future__ import annotations

import json
import logging
import os

from extract.schema import (
    PIPELINE_VERSION,
    OCRResult,
    SourceRegion,
    SourceWorksheetModel,
)

logger = logging.getLogger(__name__)

# Thresholds for OCR quality — if exceeded, fall back to vision
MAX_FRAGMENTS_PER_PAGE = 80  # too many tiny blocks = fragmented OCR
MIN_AVG_CONFIDENCE = 0.5  # average confidence too low


def ocr_quality_is_poor(ocr_result: OCRResult, source: SourceWorksheetModel) -> bool:
    """Check if OCR results are too fragmented or low-quality to use."""
    if not ocr_result.blocks:
        return True

    # Too many tiny fragments
    if len(ocr_result.blocks) > MAX_FRAGMENTS_PER_PAGE:
        logger.info(
            f"OCR quality check: {len(ocr_result.blocks)} blocks "
            f"exceeds threshold {MAX_FRAGMENTS_PER_PAGE}"
        )
        return True

    # Average confidence too low
    avg_conf = sum(b.confidence for b in ocr_result.blocks) / len(ocr_result.blocks)
    if avg_conf < MIN_AVG_CONFIDENCE:
        logger.info(f"OCR quality check: avg confidence {avg_conf:.2f} below {MIN_AVG_CONFIDENCE}")
        return True

    return False


def extract_with_vision(
    image_path: str,
    source_image_hash: str,
) -> SourceWorksheetModel | None:
    """Extract worksheet content using Gemini vision as a fallback.

    Sends the image directly to Gemini and asks it to identify the template,
    regions, and content. Returns a SourceWorksheetModel or None if unavailable.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.info("No GEMINI_API_KEY — vision fallback unavailable")
        return None

    try:
        from pathlib import Path

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Read image
        image_bytes = Path(image_path).read_bytes()

        prompt = _build_vision_prompt()

        from typing import Any

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        text_part = types.Part.from_text(text=prompt)
        contents: Any = [image_part, text_part]

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=contents,
        )

        text = str(response.text)
        text = _extract_json_text(text)
        data = json.loads(text)

        template_type = data.get("template_type", "unknown")
        raw_regions = data.get("regions", [])

        regions: list[SourceRegion] = []
        all_text_parts: list[str] = []

        for i, r in enumerate(raw_regions):
            content = str(r.get("content", ""))
            region_type = str(r.get("type", "word_list"))
            if not content.strip():
                continue

            regions.append(
                SourceRegion(
                    type=region_type,
                    content=content,
                    bbox=(0.0, float(i * 50), 500.0, float(i * 50 + 40)),
                    confidence=0.85,
                    metadata={"source": "gemini_vision"},
                )
            )
            all_text_parts.append(content)

        if not regions:
            logger.warning("Gemini vision returned no regions")
            return None

        logger.info(
            f"Gemini vision: template={template_type}, "
            f"{len(regions)} regions extracted"
        )

        return SourceWorksheetModel(
            source_image_hash=source_image_hash,
            pipeline_version=PIPELINE_VERSION,
            template_type=template_type,
            regions=regions,
            raw_text="\n".join(all_text_parts),
            ocr_engine="gemini_vision",
            low_confidence_flags=[],
        )

    except Exception as e:
        logger.warning(f"Gemini vision extraction failed: {e}")
        return None


def _build_vision_prompt() -> str:
    """Build the prompt for Gemini vision-based worksheet extraction."""
    region_types = (
        "concept_label, sample_words, word_chain, chain_script, "
        "sight_word_list, practice_sentences, story_title, "
        "decodable_passage, title"
    )
    return (
        "You are analyzing a photo of a K-3 literacy worksheet "
        "(UFLI Foundations).\n\n"
        "Identify the template type and extract all text regions. "
        "The image may show TWO pages side by side:\n"
        "- LEFT: Word Work (New Concept, Sample Words, "
        "Word Chains, Chain Script, Irregular Words, Sentences)\n"
        "- RIGHT: Decodable Story (title, illustration, passage)\n\n"
        "If BOTH pages are visible, treat LEFT as ufli_word_work.\n\n"
        "IMPORTANT RULES for structuring regions:\n"
        "- Each WORD CHAIN must be its own region. "
        "If there are 2 chains, create 2 separate word_chain regions.\n"
        "- Each PRACTICE SENTENCE must be its own region. "
        "If there are 3 sentences, create 3 separate "
        "practice_sentences regions.\n"
        "- Do NOT combine multiple chains or sentences "
        "into a single region.\n"
        "- chain_script is the TEACHER instructions "
        "(e.g., 'Make the word tune. Change /t/ to /k/.'). "
        "Keep it as ONE region.\n\n"
        "Respond with ONLY this JSON (no markdown fences):\n"
        "{\n"
        '  "template_type": "ufli_word_work" or "ufli_decodable_story",\n'
        '  "regions": [\n'
        "    {\n"
        f'      "type": one of [{region_types}],\n'
        '      "content": "the actual text"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Extract TEXT CONTENT accurately. Include arrows for chains "
        "(e.g., tune -> tone -> cone -> cane). "
        "List sample words comma-separated. "
        "Include full sentence and passage text."
    )


def _extract_json_text(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines: list[str] = []
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
