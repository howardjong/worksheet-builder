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
            cover = _make_pdf(str(Path(tmpdir) / "cover.pdf"), "Cover")
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1", pages=2)
            ws2 = _make_pdf(str(Path(tmpdir) / "ws2.pdf"), "WS2", pages=1)
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package(cover, [ws1, ws2], out, cleanup=False)

            doc = fitz.open(out)
            assert doc.page_count == 4  # 1 cover + 2 + 1
            doc.close()

    def test_merge_stamps_page_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cover = _make_pdf(str(Path(tmpdir) / "cover.pdf"), "Cover")
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1", pages=2)
            ws2 = _make_pdf(str(Path(tmpdir) / "ws2.pdf"), "WS2", pages=1)
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package(cover, [ws1, ws2], out, cleanup=False)

            doc = fitz.open(out)
            # Cover (page 0) should NOT have page numbers
            cover_text = doc.load_page(0).get_text()
            assert "Page 1 of" not in cover_text

            # Content pages should have "Page X of 3"
            total = doc.page_count - 1  # 3 content pages
            for page_idx in range(1, doc.page_count):
                text = doc.load_page(page_idx).get_text()
                expected = f"Page {page_idx} of {total}"
                assert expected in text, (
                    f"Page {page_idx} missing stamp '{expected}', got: {text!r}"
                )
            doc.close()

    def test_merge_cleanup_deletes_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cover = _make_pdf(str(Path(tmpdir) / "cover.pdf"), "Cover")
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1")
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package(cover, [ws1], out, cleanup=True)

            assert Path(out).exists()
            assert not Path(cover).exists()
            assert not Path(ws1).exists()

    def test_merge_no_cleanup_preserves_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cover = _make_pdf(str(Path(tmpdir) / "cover.pdf"), "Cover")
            ws1 = _make_pdf(str(Path(tmpdir) / "ws1.pdf"), "WS1")
            out = str(Path(tmpdir) / "merged.pdf")

            merge_worksheet_package(cover, [ws1], out, cleanup=False)

            assert Path(out).exists()
            assert Path(cover).exists()
            assert Path(ws1).exists()
