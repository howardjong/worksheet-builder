"""Vision-based worksheet extraction using Gemini as fallback for poor OCR results."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

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

# Vision model: use gemini-3-flash-preview for reliable image reading
# (gemini-3.1-flash-lite-preview hallucinated content in testing)
_VISION_MODEL = "gemini-3-flash-preview"


def _configured_api_key() -> str:
    """Return the configured Gemini API key, supporting both env var names."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


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
    api_key = _configured_api_key()
    if not api_key:
        logger.info("No GEMINI_API_KEY or GOOGLE_API_KEY — vision fallback unavailable")
        return None

    try:
        from pathlib import Path

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Read image
        image_bytes = Path(image_path).read_bytes()

        prompt = _build_vision_prompt()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        text_part = types.Part.from_text(text=prompt)
        contents: Any = [image_part, text_part]

        response = client.models.generate_content(
            model=_VISION_MODEL,
            contents=contents,
        )

        text = _extract_response_text(response)
        if not text:
            logger.warning("Gemini vision returned empty response")
            return None
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

        # Structural validation: catch hallucinated template misclassification
        template_type = _validate_template_type(template_type, regions)

        # Corpus cross-validation: detect hallucinated content
        hallucination = _check_corpus_hallucination(regions)
        if hallucination:
            logger.warning(
                "Gemini vision: possible hallucination detected — %s. "
                "Lowering confidence on all regions.",
                hallucination,
            )
            regions = [
                SourceRegion(
                    type=r.type,
                    content=r.content,
                    bbox=r.bbox,
                    confidence=0.5,
                    metadata={**r.metadata, "hallucination_warning": hallucination},
                )
                for r in regions
            ]

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
        "FIRST decide the template type by looking at the page layout:\n"
        "- ufli_decodable_story: has a STORY TITLE, an illustration box, "
        "and a multi-sentence READING PASSAGE (paragraph text). "
        "The header usually says 'Lesson XX: [concept]'.\n"
        "- ufli_word_work: has a 'New Concept and Sample Words' section, "
        "WORD CHAINS (word -> word -> word), a CHAIN SCRIPT with teacher "
        "instructions, IRREGULAR WORDS list, and PRACTICE SENTENCES.\n\n"
        "If the page has a reading passage (multiple sentences forming "
        "a story/narrative), it is ufli_decodable_story — NOT word work.\n"
        "If BOTH pages are visible side by side, treat LEFT as ufli_word_work.\n\n"
        "CRITICAL: Extract ONLY what is actually visible in the image. "
        "Do NOT invent or hallucinate content that is not on the page. "
        "If the page says 'Lesson 72', do not change it to a different "
        "lesson number.\n\n"
        "IMPORTANT RULES for structuring regions:\n"
        "- The 'title' region should contain the lesson header "
        "(e.g., 'Lesson 72: Long VCC').\n"
        "- For decodable stories: use 'story_title' for the story name "
        "and 'decodable_passage' for the reading text.\n"
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
        "Extract TEXT CONTENT accurately — transcribe exactly what you see. "
        "Include arrows for chains (e.g., tune -> tone -> cone -> cane). "
        "List sample words comma-separated. "
        "Include full sentence and passage text."
    )


_LESSON_RE = re.compile(r"[Ll]esson\s+(\d+)", re.IGNORECASE)


def _check_corpus_hallucination(regions: list[SourceRegion]) -> str | None:
    """Cross-validate extracted lesson against corpus to detect hallucinations.

    If a lesson number is found in the extracted regions, look it up in the
    corpus and check whether the extracted concept/words match. A mismatch
    strongly suggests the vision model hallucinated the content.

    Returns a warning string if hallucination is detected, None otherwise.
    """
    lesson_number: int | None = None
    extracted_concept = ""
    extracted_words: set[str] = set()

    for r in regions:
        m = _LESSON_RE.search(r.content)
        if m and lesson_number is None:
            lesson_number = int(m.group(1))

        if r.type == "concept_label":
            extracted_concept = r.content.lower()

        if r.type == "sample_words":
            for word in re.findall(r"[a-zA-Z]+", r.content.lower()):
                if len(word) >= 2:
                    extracted_words.add(word)

    if lesson_number is None:
        return None

    try:
        from corpus.ufli.lookup import lookup_lesson
    except ImportError:
        return None

    result = lookup_lesson(lesson_number)
    if result is None:
        return None

    # Check concept match
    if result.concept:
        corpus_concept = result.concept.lower()
        # If concept text exists in both but they share no significant words,
        # that's a strong hallucination signal
        if extracted_concept:
            concept_words = set(re.findall(r"[a-z]{3,}", corpus_concept))
            extracted_concept_words = set(re.findall(r"[a-z]{3,}", extracted_concept))
            if concept_words and extracted_concept_words:
                overlap = concept_words & extracted_concept_words
                if not overlap:
                    return (
                        f"extracted concept '{extracted_concept}' "
                        f"does not match corpus lesson {lesson_number} "
                        f"concept '{corpus_concept}'"
                    )

    # Check word overlap against corpus content (home practice has word chains)
    corpus_text = " ".join([
        result.home_practice_text,
        result.additional_text,
        result.decodable_text,
    ]).lower()
    if corpus_text.strip() and extracted_words:
        corpus_words = set(
            w for w in re.findall(r"[a-z]{3,}", corpus_text)
        )
        if corpus_words:
            overlap = corpus_words & extracted_words
            if not overlap:
                return (
                    f"extracted words {sorted(extracted_words)[:5]} "
                    f"have no overlap with corpus lesson {lesson_number} "
                    f"content words {sorted(corpus_words)[:5]}"
                )

    return None


def _validate_template_type(
    template_type: str, regions: list[SourceRegion]
) -> str:
    """Validate and correct template_type based on structural signals in regions.

    If Gemini claims word_work but the regions contain a decodable_passage or
    story_title (and lack word_chain/chain_script), correct to decodable_story.
    Vice versa if it claims decodable_story but has word chains.
    """
    region_types = {r.type for r in regions}

    has_passage = "decodable_passage" in region_types or "story_title" in region_types
    has_word_work = bool(region_types & {"word_chain", "chain_script", "sample_words"})

    if template_type == "ufli_word_work" and has_passage and not has_word_work:
        logger.info(
            "Gemini vision: correcting template_type from ufli_word_work "
            "to ufli_decodable_story (passage detected, no word chains)"
        )
        return "ufli_decodable_story"

    if template_type == "ufli_decodable_story" and has_word_work and not has_passage:
        logger.info(
            "Gemini vision: correcting template_type from ufli_decodable_story "
            "to ufli_word_work (word chains detected, no passage)"
        )
        return "ufli_word_work"

    return template_type


def _extract_response_text(response: Any) -> str:
    """Extract text content from a Gemini response, handling thinking models.

    Thinking models (e.g., gemini-2.5-flash) may include thought parts
    alongside text parts. response.text can return empty if the response
    only has thought parts. This function extracts text from non-thought parts.
    """
    # Try response.text first (works for non-thinking models)
    try:
        text = str(response.text)
        if text.strip():
            return text
    except (ValueError, AttributeError):
        pass

    # Fall back to extracting from parts (handles thinking models)
    if response.candidates:
        for part in response.candidates[0].content.parts:
            if getattr(part, "thought", False):
                continue
            if part.text and part.text.strip():
                return str(part.text)

    return ""


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
