"""PDF merge utility — combines worksheets into a single lesson package."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def merge_worksheet_package(
    worksheet_paths: list[str],
    output_path: str,
    *,
    cleanup: bool = True,
) -> str:
    """Merge worksheet PDFs into a single lesson package (no cover page —
    owner decision 2026-07-10).

    No footer page stamp: a prior "Page X of Y" stamp at a fixed
    bottom-right rect was removed (D10, spec 2026-07-13) — it collided
    with full-bleed page art (print-check true positive at (517,760)) and
    was redundant, since page identity already lives in the page header
    via the prompt ("This is worksheet N of M").
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    merged = fitz.open()
    for ws_path in worksheet_paths:
        ws_doc = fitz.open(ws_path)
        merged.insert_pdf(ws_doc)
        ws_doc.close()

    total_pages = merged.page_count
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
