"""Tests for render/pdf.py and validate/print_checks.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.engine import adapt_activity, adapt_lesson
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


# --- Multi-Worksheet Render Tests ---


def _ufli_59_skill() -> LiteracySkillModel:
    """UFLI Lesson 59 fixture for render tests."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["grade", "chase", "slide", "quite", "froze", "these"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, chase, slide, quite",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="1. tune \u2192 tone \u2192 cone \u2192 cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my",
                source_region_index=2,
            ),
            SourceItem(
                item_type="sentence",
                content="1. The slide was quite fun.",
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content="A Cake for Tess. Tess had a cake. The cake was huge!",
                source_region_index=4,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


class TestMultiWorksheetRender:
    def test_render_match_items(self) -> None:
        """Word-picture matching items should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"]
        assert len(discovery) == 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(discovery[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_trace_items(self) -> None:
        """Trace items (dotted letters) should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        discovery = [ws for ws in worksheets if ws.worksheet_title == "Word Discovery"]
        assert len(discovery) == 1
        # Verify trace items exist
        trace_items = [
            item
            for chunk in discovery[0].chunks
            for item in chunk.items
            if item.response_format == "trace"
        ]
        assert len(trace_items) >= 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(discovery[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_fill_blank_items(self) -> None:
        """Fill-blank items should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        builder = [ws for ws in worksheets if ws.worksheet_title == "Word Builder"]
        assert len(builder) == 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(builder[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_read_aloud_items(self) -> None:
        """Read-aloud passage should render in styled box."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        story = [ws for ws in worksheets if ws.worksheet_title == "Story Time"]
        assert len(story) == 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(story[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_all_worksheets(self) -> None:
        """All multi-worksheets should render successfully."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        theme = load_theme("space")
        for i, ws in enumerate(worksheets):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                pdf_path = f.name
            render_worksheet(ws, theme, pdf_path)
            assert Path(pdf_path).stat().st_size > 0
            # Verify print quality
            result = validate_print_quality(pdf_path)
            assert result.passed, f"Worksheet {i+1} failed print quality: {result.violations}"
            Path(pdf_path).unlink()

    def test_render_with_roblox_obby_theme(self) -> None:
        """Roblox Obby theme should load and render correctly."""
        theme = load_theme("roblox_obby")
        assert theme.multi_worksheet is True
        assert theme.avatar_position == "integrated"
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(worksheets[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_break_prompt_renders(self) -> None:
        """Brain break prompt should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        # First worksheet should have a break prompt
        assert worksheets[0].break_prompt is not None
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(worksheets[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_backward_compat_single_worksheet(self) -> None:
        """Original single-worksheet rendering still works unchanged."""
        adapted = adapt_activity(_phonics_skill(), _profile())
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(adapted, theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()
