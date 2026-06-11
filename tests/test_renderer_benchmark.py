"""Tests for renderer promotion benchmark gates."""

from __future__ import annotations

from pathlib import Path

from render.design_spec import (
    AnswerZoneSpec,
    PageSpec,
    VisualBudget,
    WorksheetDesignSpec,
)
from render.strategies import RenderResult


def _spec() -> WorksheetDesignSpec:
    return WorksheetDesignSpec(
        render_mode="image_prompt",
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        theme_id="geometry_dash",
        theme_name="Geometry Dash Calm",
        learner_name="Ian",
        learner_grade_level="1",
        worksheet_title="Vowel Team Adventure",
        worksheet_number=1,
        worksheet_count=1,
        domain="phonics",
        specific_skill="vowel teams",
        page=PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        visual_budget=VisualBudget(
            style="calm",
            intensity="low",
            max_decorative_elements=2,
            max_colors=4,
        ),
        required_text=["Vowel Team Adventure", "rain", "play"],
        answer_zones=[],
    )


def test_benchmark_blocks_image_prompt_without_pdf(tmp_path: Path) -> None:
    from render.benchmark import evaluate_renderer_artifacts

    prompt_path = tmp_path / "worksheet_image_prompt.md"
    prompt_path.write_text("OFFLINE PROMPT ONLY\nVowel Team Adventure\nrain\nplay")
    result = RenderResult(
        renderer_id="image_prompt",
        pdf_path=None,
        artifact_paths=[str(prompt_path)],
        produces_pdf=False,
        experimental=True,
    )

    report = evaluate_renderer_artifacts(_spec(), result)

    assert report.passed is False
    assert report.gates["required_text_present"] is True
    assert report.gates["print_ready_output"] is False
    assert "Print-ready PDF was not produced" in report.blocking_issues


def test_benchmark_blocks_missing_required_text(tmp_path: Path) -> None:
    from render.benchmark import evaluate_renderer_artifacts

    prompt_path = tmp_path / "worksheet_image_prompt.md"
    prompt_path.write_text("OFFLINE PROMPT ONLY\nVowel Team Adventure\nrain")
    result = RenderResult(
        renderer_id="image_prompt",
        pdf_path=None,
        artifact_paths=[str(prompt_path)],
        produces_pdf=False,
        experimental=True,
    )

    report = evaluate_renderer_artifacts(_spec(), result)

    assert report.passed is False
    assert report.gates["required_text_present"] is False
    assert "Missing required text: play" in report.blocking_issues


def test_benchmark_blocks_missing_answer_zone_affordance(tmp_path: Path) -> None:
    from render.benchmark import evaluate_renderer_artifacts

    prompt_path = tmp_path / "worksheet_image_prompt.md"
    prompt_path.write_text("OFFLINE PROMPT ONLY\nVowel Team Adventure\nrain\nplay")
    result = RenderResult(
        renderer_id="image_prompt",
        pdf_path=None,
        artifact_paths=[str(prompt_path)],
        produces_pdf=False,
        experimental=True,
    )

    report = evaluate_renderer_artifacts(
        _spec().model_copy(
            update={
                "answer_zones": [
                    AnswerZoneSpec(
                        chunk_id=1,
                        item_id=2,
                        response_format="write",
                        prompt_text="play",
                        expected_answer="play",
                        x0=0.1,
                        y0=0.2,
                        x1=0.9,
                        y1=0.3,
                    )
                ]
            }
        ),
        result,
    )

    assert report.passed is False
    assert report.gates["required_text_present"] is True
    assert report.gates["answer_zones_present"] is False
    assert "Missing answer zone affordance for item 2" in report.blocking_issues


def test_benchmark_passes_pdf_renderer_with_required_text_contract(tmp_path: Path) -> None:
    from render.benchmark import evaluate_renderer_artifacts

    pdf_path = tmp_path / "worksheet.pdf"
    pdf_path.write_text("pdf placeholder")
    result = RenderResult(
        renderer_id="pdf_classic",
        pdf_path=str(pdf_path),
        artifact_paths=[str(pdf_path)],
        produces_pdf=True,
        experimental=False,
    )

    report = evaluate_renderer_artifacts(_spec(), result)

    assert report.passed is True
    assert report.gates["required_text_present"] is True
    assert report.gates["visual_budget_respected"] is True
    assert report.gates["print_ready_output"] is True
    assert report.blocking_issues == []
