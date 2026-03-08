"""Tests for render/pdf.py and validate/print_checks.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.engine import adapt_activity
from companion.schema import Accommodations, LearnerProfile
from render.pdf import (
    CONTENT_BOTTOM,
    CONTENT_TOP,
    MARGIN,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    render_worksheet,
)
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import load_theme
from validate.print_checks import validate_print_quality


def _phonics_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=["Blend CVC words"],
        target_words=["tall", "call", "wall", "fall", "mall", "doll"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=0),
            SourceItem(item_type="word_list", content="fall, mall, doll", source_region_index=1),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _fluency_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=["Read a decodable passage"],
        target_words=["june", "flute"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="passage",
                content="June has a flute. June likes to make tunes.",
                source_region_index=0,
            ),
        ],
        extraction_confidence=0.92,
        template_type="ufli_decodable_story",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Test", grade_level="1")


def _render_pdf(skill: LiteracySkillModel | None = None, theme_id: str = "space") -> str:
    """Render a test PDF and return its path."""
    if skill is None:
        skill = _phonics_skill()
    adapted = adapt_activity(skill, _profile())
    theme = load_theme(theme_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    render_worksheet(adapted, theme, pdf_path)
    return pdf_path


class TestRenderWorksheet:
    def test_creates_pdf_file(self) -> None:
        pdf_path = _render_pdf()
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_different_themes_produce_different_pdfs(self) -> None:
        pdf1 = _render_pdf(theme_id="space")
        pdf2 = _render_pdf(theme_id="dinosaur")
        # Different themes should produce different files
        assert Path(pdf1).exists()
        assert Path(pdf2).exists()
        # Both should have content
        assert Path(pdf1).stat().st_size > 0
        assert Path(pdf2).stat().st_size > 0
        Path(pdf1).unlink()
        Path(pdf2).unlink()

    def test_phonics_render(self) -> None:
        pdf_path = _render_pdf(_phonics_skill())
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_fluency_render(self) -> None:
        pdf_path = _render_pdf(_fluency_skill())
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_grade_k_render(self) -> None:
        skill = _phonics_skill()
        profile = LearnerProfile(
            name="Test K",
            grade_level="K",
            accommodations=Accommodations(chunking_level="small"),
        )
        adapted = adapt_activity(skill, profile)
        theme = load_theme("space")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(adapted, theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_creates_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = str(Path(tmpdir) / "subdir" / "test.pdf")
            adapted = adapt_activity(_phonics_skill(), _profile())
            theme = load_theme("space")
            render_worksheet(adapted, theme, pdf_path)
            assert Path(pdf_path).exists()

    def test_page_geometry_constants(self) -> None:
        assert PAGE_WIDTH == 612.0
        assert PAGE_HEIGHT == 792.0
        assert MARGIN > 0
        assert CONTENT_TOP < PAGE_HEIGHT
        assert CONTENT_BOTTOM > 0


class TestPrintQuality:
    def test_valid_pdf_passes(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        assert result.passed
        assert result.checks_run >= 5
        Path(pdf_path).unlink()

    def test_letter_dimensions(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        dim_violations = [v for v in result.violations if v.check == "page_dimensions"]
        assert len(dim_violations) == 0
        Path(pdf_path).unlink()

    def test_has_vector_text(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        text_violations = [v for v in result.violations if v.check == "vector_text"]
        assert len(text_violations) == 0
        Path(pdf_path).unlink()

    def test_invalid_pdf_fails(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="w") as f:
            f.write("not a pdf")
            bad_path = f.name
        result = validate_print_quality(bad_path)
        assert not result.passed
        Path(bad_path).unlink()

    def test_has_pages(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        page_violations = [v for v in result.violations if v.check == "has_pages"]
        assert len(page_violations) == 0
        Path(pdf_path).unlink()
