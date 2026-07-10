"""PDF merge utility — combines worksheets into a single lesson package."""

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
    worksheet_paths: list[str],
    output_path: str,
    *,
    cleanup: bool = True,
) -> str:
    """Merge worksheet PDFs into a single lesson package (no cover page —
    owner decision 2026-07-10). Stamps "Page X of Y" on every page.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    merged = fitz.open()
    for ws_path in worksheet_paths:
        ws_doc = fitz.open(ws_path)
        merged.insert_pdf(ws_doc)
        ws_doc.close()

    total_pages = merged.page_count
    for page_idx in range(total_pages):
        page = merged.load_page(page_idx)
        stamp_text = f"Page {page_idx + 1} of {total_pages}"
        rect = fitz.Rect(
            _PAGE_WIDTH / 2,
            page.rect.height - _FOOTER_Y - 4,
            _PAGE_WIDTH - _MARGIN,
            page.rect.height - _FOOTER_Y + 10,
        )
        page.insert_textbox(
            rect,
            stamp_text,
            fontname="helv",
            fontsize=8,
            color=(0.78, 0.8, 0.82),
            align=fitz.TEXT_ALIGN_RIGHT,
        )

    merged.save(output_path)
    merged.close()
    if cleanup:
        for p in worksheet_paths:
            try:
                Path(p).unlink()
            except OSError:
                pass
    logger.info(
        "Merged lesson package: %s (%s worksheets, %s pages)",
        output_path,
        len(worksheet_paths),
        total_pages,
    )
    return output_path
