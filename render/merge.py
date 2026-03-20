"""PDF merge utility — combines cover + worksheets into a single lesson package."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Footer positioning: matches render/pdf.py constants
_MARGIN = 54  # 0.75 * inch
_PAGE_WIDTH = 612  # letter width
_FOOTER_Y = _MARGIN / 2


def merge_worksheet_package(
    cover_path: str,
    worksheet_paths: list[str],
    output_path: str,
    *,
    cleanup: bool = True,
) -> str:
    """Merge cover + worksheet PDFs into a single lesson package.

    Stamps "Page X of Y" on every content page (skips cover).
    If cleanup=True, deletes the individual input PDFs after merge.
    Returns the output path.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    merged = fitz.open()

    # Insert cover page
    cover_doc = fitz.open(cover_path)
    merged.insert_pdf(cover_doc)
    cover_doc.close()

    # Insert each worksheet
    for ws_path in worksheet_paths:
        ws_doc = fitz.open(ws_path)
        merged.insert_pdf(ws_doc)
        ws_doc.close()

    # Stamp page numbers on content pages (skip cover = page 0)
    total_content_pages = merged.page_count - 1
    for page_idx in range(1, merged.page_count):
        page = merged.load_page(page_idx)
        content_page_num = page_idx  # page 1 = "Page 1 of N"
        stamp_text = f"Page {content_page_num} of {total_content_pages}"
        # Right-aligned in bottom-right footer area (fitz y is top-down)
        rect = fitz.Rect(
            _PAGE_WIDTH / 2,  # left bound (generous)
            page.rect.height - _FOOTER_Y - 4,  # top
            _PAGE_WIDTH - _MARGIN,  # right bound
            page.rect.height - _FOOTER_Y + 10,  # bottom
        )
        page.insert_textbox(
            rect,
            stamp_text,
            fontname="helv",
            fontsize=8,
            color=(0.78, 0.8, 0.82),  # matches chunk_border gray
            align=fitz.TEXT_ALIGN_RIGHT,
        )

    merged.save(output_path)
    merged.close()

    if cleanup:
        for p in [cover_path, *worksheet_paths]:
            try:
                Path(p).unlink()
            except OSError:
                pass

    logger.info(
        "Merged lesson package: %s (cover + %s worksheets, %s pages)",
        output_path,
        len(worksheet_paths),
        total_content_pages + 1,
    )
    return output_path
