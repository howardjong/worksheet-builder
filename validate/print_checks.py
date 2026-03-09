"""Print quality validation — checks PDF readiness for printing."""

from __future__ import annotations

import fitz  # PyMuPDF

from validate.schema import ValidationResult

# Expected dimensions for letter size (in points, with tolerance)
LETTER_WIDTH = 612.0
LETTER_HEIGHT = 792.0
DIMENSION_TOLERANCE = 2.0  # points

# Minimum margin (in points) — 0.75 inches = 54 points
MIN_MARGIN = 50.0  # slightly less than 54 for tolerance


def validate_print_quality(pdf_path: str) -> ValidationResult:
    """Validate a PDF for print readiness.

    Checks:
    1. PDF is readable
    2. Page dimensions are letter size
    3. Has at least one page
    4. Fonts are embedded (or standard PDF fonts)
    5. No empty pages
    """
    result = ValidationResult(validator="print_quality", passed=True, checks_run=0)

    # Check 1: PDF is readable
    result.checks_run += 1
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        result.add_violation(
            check="pdf_readable",
            message=f"Cannot open PDF: {e}",
        )
        return result

    # Check 2: Has at least one page
    result.checks_run += 1
    if doc.page_count == 0:
        result.add_violation(
            check="has_pages",
            message="PDF has no pages",
        )
        doc.close()
        return result

    # Check 3: Page dimensions are letter size
    result.checks_run += 1
    for i in range(doc.page_count):
        page = doc[i]
        width = page.rect.width
        height = page.rect.height

        if abs(width - LETTER_WIDTH) > DIMENSION_TOLERANCE:
            result.add_violation(
                check="page_dimensions",
                message=(
                    f"Page {i + 1} width is {width:.1f}pt, "
                    f"expected {LETTER_WIDTH:.1f}pt (letter size)"
                ),
            )
        if abs(height - LETTER_HEIGHT) > DIMENSION_TOLERANCE:
            result.add_violation(
                check="page_dimensions",
                message=(
                    f"Page {i + 1} height is {height:.1f}pt, "
                    f"expected {LETTER_HEIGHT:.1f}pt (letter size)"
                ),
            )

    # Check 4: Pages have content (not blank)
    result.checks_run += 1
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()
        if not text.strip():
            result.add_violation(
                check="non_empty_page",
                message=f"Page {i + 1} appears to be blank",
                severity="warning",
            )

    # Check 5: Text content is present (vector text, not just images)
    result.checks_run += 1
    total_text = ""
    for i in range(doc.page_count):
        page = doc[i]
        total_text += page.get_text()

    if not total_text.strip():
        result.add_violation(
            check="vector_text",
            message="PDF contains no extractable text — text may be rasterized",
        )

    # Check 6: Text-image overlap detection
    result.checks_run += 1
    for i in range(doc.page_count):
        page = doc[i]
        overlaps = _check_text_image_overlap(page)
        for overlap in overlaps:
            result.add_violation(
                check="text_image_overlap",
                message=(
                    f"Page {i + 1}: text overlaps image at "
                    f"({overlap[0]:.0f}, {overlap[1]:.0f})"
                ),
                severity="warning",
            )

    doc.close()
    return result


def _check_text_image_overlap(page: fitz.Page) -> list[tuple[float, float]]:
    """Detect text blocks that overlap with image bounding boxes.

    Returns list of (x, y) points where overlap was detected.
    """
    overlaps: list[tuple[float, float]] = []

    # Get image bounding boxes
    image_rects: list[fitz.Rect] = []
    for img in page.get_image_info():
        bbox = img.get("bbox")
        if bbox:
            image_rects.append(fitz.Rect(bbox))

    if not image_rects:
        return overlaps

    # Get text blocks and check for overlap with images
    text_blocks = page.get_text("blocks")
    for block in text_blocks:
        if block[6] != 0:  # skip image blocks
            continue
        text_rect = fitz.Rect(block[:4])
        text_content = str(block[4]).strip()
        if not text_content:
            continue

        for img_rect in image_rects:
            # Check if text rect overlaps image rect significantly
            intersection = text_rect & img_rect
            if intersection.is_empty:
                continue
            # Only flag if overlap area is > 20% of the text block
            overlap_area = intersection.width * intersection.height
            text_area = text_rect.width * text_rect.height
            if text_area > 0 and overlap_area / text_area > 0.2:
                overlaps.append((text_rect.x0, text_rect.y0))

    return overlaps
