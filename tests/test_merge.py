"""Tests for render/merge.py — PDF merging and page number stamping."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from render.merge import merge_worksheet_package


def _make_pdf(path: str, text: str = "Hello", pages: int = 1) -> str:
    """Create a simple PDF with the given number of pages."""
    c = Canvas(path, pagesize=letter)
    for i in range(pages):
        c.drawString(72, 720, f"{text} - page {i + 1}")
        if i < pages - 1:
            c.showPage()
    c.save()
    return path


class TestMerge:
    def test_merge_combines_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1", pages=2)
            ws2 = _make_pdf(str(Path(tmpdir) / "ws2.pdf"), "WS2", pages=1)
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package([ws1, ws2], out, cleanup=False)

            doc = fitz.open(out)
            assert doc.page_count == 3  # 2 + 1, no cover
            doc.close()

    def test_merged_package_has_no_footer_page_stamp(self) -> None:
        # D10: fixed-coordinate "Page X of Y" stamp collided with full-bleed
        # page art (print-check true positive at (517,760)). Page identity
        # already lives in the page header via the prompt
        # ("This is worksheet N of M"), so the stamp is redundant. Inverted
        # from test_merge_stamps_page_numbers, which asserted the stamp
        # existed (spec 2026-07-13 D10).
        with tempfile.TemporaryDirectory() as tmpdir:
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1", pages=1)
            ws2 = _make_pdf(str(Path(tmpdir) / "ws2.pdf"), "WS2", pages=1)
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package([ws1, ws2], out, cleanup=False)

            doc = fitz.open(out)
            for page in doc:
                text = page.get_text()
                assert "Page 1 of" not in text
                assert "Page 2 of" not in text
            doc.close()

    def test_merge_cleanup_deletes_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1")
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package([ws1], out, cleanup=True)

            assert Path(out).exists()
            assert not Path(ws1).exists()

    def test_merge_no_cleanup_preserves_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1")
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package([ws1], out, cleanup=False)

            assert Path(out).exists()
            assert Path(ws1).exists()
