"""Rule-based heuristics for UFLI template detection and region classification."""

from __future__ import annotations

import re

from extract.schema import (
    PIPELINE_VERSION,
    OCRBlock,
    OCRResult,
    SourceRegion,
    SourceWorksheetModel,
    flag_low_confidence,
)

# Keywords that identify UFLI Word Work template sections
_WORD_WORK_KEYWORDS = {
    "concept_label": ["new concept", "sample words"],
    "word_chain": ["word work chains", "word chains"],
    "chain_script": ["sample word work chain script", "word work chain script", "chain script"],
    "sight_word_list": ["new irregular words", "irregular words"],
    "practice_sentences": ["sentences"],
}

# Combined keyword list for template detection
_ALL_WORD_WORK_KEYWORDS = [
    "new concept",
    "word work chains",
    "chain script",
    "irregular words",
    "home practice",
]

_LESSON_PATTERN = re.compile(r"lesson\s+\d+", re.IGNORECASE)


def detect_ufli_template(ocr_result: OCRResult) -> str:
    """Classify a UFLI page as one of two known templates.

    Returns "ufli_word_work", "ufli_decodable_story", or "unknown".
    """
    raw_lower = ocr_result.raw_text.lower()

    # Word Work: multiple structured section keywords present
    keyword_hits = sum(1 for kw in _ALL_WORD_WORK_KEYWORDS if kw in raw_lower)
    if keyword_hits >= 2:
        return "ufli_word_work"

    # Decodable Story: lesson reference + large text block but no section keywords
    has_lesson = bool(_LESSON_PATTERN.search(raw_lower))
    has_story_indicators = _has_story_structure(ocr_result)

    if has_story_indicators and keyword_hits <= 1:
        return "ufli_decodable_story"

    # Also detect story pages without explicit lesson number
    # (story pages sometimes lack headers)
    if has_story_indicators and not has_lesson and keyword_hits == 0:
        return "ufli_decodable_story"

    return "unknown"


def _has_story_structure(ocr_result: OCRResult) -> bool:
    """Check if OCR result looks like a decodable story page.

    Story pages have: a large continuous text block (many words in one or
    few blocks), typically with a short title above it.
    """
    if not ocr_result.blocks:
        return False

    # Find blocks with substantial text (likely passage text)
    long_blocks = [b for b in ocr_result.blocks if len(b.text.split()) >= 8]

    # Story pages typically have at least one large passage block
    if len(long_blocks) >= 1:
        total_words = sum(len(b.text.split()) for b in long_blocks)
        if total_words >= 20:
            return True

    return False


def map_to_source_model(
    ocr_result: OCRResult,
    source_image_hash: str,
    layout_family: str = "ufli",
) -> SourceWorksheetModel:
    """Rule-based mapping from OCR output to SourceWorksheetModel.

    Dispatches to template-specific heuristics based on detected template type.
    """
    template_type = detect_ufli_template(ocr_result)

    if template_type == "ufli_word_work":
        regions = _classify_word_work_regions(ocr_result)
    elif template_type == "ufli_decodable_story":
        regions = _classify_decodable_story_regions(ocr_result)
    else:
        regions = _classify_generic_regions(ocr_result)

    low_flags = flag_low_confidence(regions)

    return SourceWorksheetModel(
        source_image_hash=source_image_hash,
        pipeline_version=PIPELINE_VERSION,
        template_type=template_type,
        regions=regions,
        raw_text=ocr_result.raw_text,
        ocr_engine=ocr_result.engine,
        low_confidence_flags=low_flags,
    )


def _classify_word_work_regions(ocr_result: OCRResult) -> list[SourceRegion]:
    """Classify OCR blocks into UFLI Word Work region types."""
    regions: list[SourceRegion] = []

    # Track which blocks have been assigned to a section
    assigned: set[int] = set()

    # First pass: identify section headers and their content
    for i, block in enumerate(ocr_result.blocks):
        text_lower = block.text.lower().strip()

        # Title / lesson header
        if _LESSON_PATTERN.search(text_lower) or "home practice" in text_lower:
            regions.append(_make_region("title", block))
            assigned.add(i)
            continue

        # Check for section headers
        matched_section = _match_section_header(text_lower)
        if matched_section:
            regions.append(_make_region(matched_section, block))
            assigned.add(i)
            continue

    # Second pass: assign remaining blocks based on vertical position and context
    for i, block in enumerate(ocr_result.blocks):
        if i in assigned:
            continue

        text = block.text.strip()
        if not text:
            continue

        region_type = _infer_word_work_content_type(block, regions)
        regions.append(_make_region(region_type, block))

    return regions


def _match_section_header(text_lower: str) -> str | None:
    """Match text against known UFLI Word Work section header keywords."""
    for region_type, keywords in _WORD_WORK_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return region_type
    return None


def _infer_word_work_content_type(
    block: OCRBlock, existing_regions: list[SourceRegion]  # noqa: F821
) -> str:
    """Infer the type of an unclassified block in a Word Work page."""

    text = block.text.strip()

    # Arrow chains suggest word_chain content
    if "→" in text or "->" in text:
        return "word_chain"

    # Numbered items with brackets suggest chain_script steps
    if re.match(r"^\d+\.", text) and ("[" in text or "spelling" in text.lower()):
        return "chain_script"

    # Numbered sentences
    if re.match(r"^\d+\.", text) and len(text.split()) >= 3:
        return "practice_sentences"

    # Short single words or comma-separated words → sample_words
    words = text.replace(",", " ").split()
    if all(len(w) <= 10 for w in words) and len(words) <= 6 and len(words) >= 1:
        if not any(c.isdigit() for c in text):
            return "sample_words"

    # Heart symbols or asterisks near short words → sight_word_list
    if "*" in text or "♥" in text or "❤" in text:
        return "sight_word_list"

    return "word_list"


def _classify_decodable_story_regions(ocr_result: OCRResult) -> list[SourceRegion]:
    """Classify OCR blocks into UFLI Decodable Story region types."""
    regions: list[SourceRegion] = []

    if not ocr_result.blocks:
        return regions

    # Sort blocks by vertical position
    sorted_blocks = sorted(ocr_result.blocks, key=lambda b: b.bbox[1])

    # Find the passage blocks (longest continuous text)
    passage_blocks: list[int] = []
    title_assigned = False

    for i, block in enumerate(sorted_blocks):
        text = block.text.strip()
        if not text:
            continue

        word_count = len(text.split())

        # First short block at the top is likely the title
        if not title_assigned and word_count <= 8 and i < 3:
            # Check if it looks like a title (capitalized, short)
            if any(c.isupper() for c in text):
                regions.append(_make_region("story_title", block))
                title_assigned = True
                continue

        # Long blocks are passage text
        if word_count >= 5:
            passage_blocks.append(i)
            regions.append(_make_region("decodable_passage", block))
        elif word_count <= 3 and not title_assigned:
            # Short block before passage could be title
            regions.append(_make_region("story_title", block))
            title_assigned = True
        else:
            regions.append(_make_region("decodable_passage", block))

    return regions


def _classify_generic_regions(ocr_result: OCRResult) -> list[SourceRegion]:
    """Generic fallback classification for unknown layouts."""
    regions: list[SourceRegion] = []

    if not ocr_result.blocks:
        return regions

    sorted_blocks = sorted(ocr_result.blocks, key=lambda b: b.bbox[1])

    # Simple heuristic: first block is title, rest are content
    page_height = max(b.bbox[3] for b in sorted_blocks) if sorted_blocks else 1.0

    for i, block in enumerate(sorted_blocks):
        text = block.text.strip()
        if not text:
            continue

        y_frac = block.bbox[1] / page_height if page_height > 0 else 0

        if y_frac < 0.15 and i < 3:
            region_type = "title"
        elif re.match(r"^\d+[\.\)]\s", text):
            region_type = "question"
        elif "_" * 3 in text:
            region_type = "answer_blank"
        else:
            region_type = "instruction" if len(text.split()) >= 5 else "word_list"

        regions.append(_make_region(region_type, block))

    return regions


def _make_region(region_type: str, block: OCRBlock) -> SourceRegion:  # noqa: F821
    """Create a SourceRegion from an OCR block."""

    return SourceRegion(
        type=region_type,
        content=block.text,
        bbox=block.bbox,
        confidence=block.confidence,
        metadata={},
    )
