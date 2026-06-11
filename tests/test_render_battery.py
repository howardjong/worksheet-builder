"""Tests for the render battery scorecard builder (no pipeline runs)."""

from __future__ import annotations


def test_scorecard_table_includes_rows_and_verdicts() -> None:
    from render_battery import BatteryRow, build_scorecard

    rows = [
        BatteryRow(
            input_name="IMG_0004.JPG",
            classic_all_pass=True,
            image_all_pass=True,
            image_fell_back=False,
            image_pdf_paths=["out/b/worksheet_1.pdf"],
            classic_pdf_paths=["out/a/worksheet_1.pdf"],
        ),
        BatteryRow(
            input_name="IMG_0007.JPG",
            classic_all_pass=True,
            image_all_pass=False,
            image_fell_back=True,
            image_pdf_paths=[],
            classic_pdf_paths=["out/a/worksheet_2.pdf"],
        ),
    ]

    scorecard = build_scorecard(rows)

    assert "IMG_0004.JPG" in scorecard
    assert "IMG_0007.JPG" in scorecard
    assert "| input | classic all-pass | image_gen all-pass | fell back |" in scorecard
    assert "image_gen fallbacks: 1/2" in scorecard
    assert "out/a/worksheet_1.pdf" in scorecard
    assert "out/b/worksheet_1.pdf" in scorecard
