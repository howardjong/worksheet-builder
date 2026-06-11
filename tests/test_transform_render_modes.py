"""Tests for transform render-mode orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import transform as transform_module
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from theme.schema import ThemeConfig
from validate.ai_review import ReviewResult


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="vowel teams",
        learning_objectives=["Read vowel team words"],
        target_words=["rain", "play"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="rain, play", source_region_index=0)
        ],
        extraction_confidence=0.95,
        template_type="generic",
    )


def _adapted() -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source_hash",
        skill_model_hash="skill_hash",
        learner_profile_hash="profile_hash",
        grade_level="1",
        domain="phonics",
        specific_skill="vowel teams",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Read vowel team words",
                instructions=[Step(number=1, text="Read each word.")],
                items=[
                    ActivityItem(item_id=1, content="rain", response_format="write"),
                    ActivityItem(item_id=2, content="play", response_format="write"),
                ],
                response_format="write",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="geometry_dash",
        decoration_zones=[],
        worksheet_title="Vowel Team Adventure",
    )


def _stub_common(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_review(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [ReviewResult(passed=True, issues=[], suggestions=[])]

    monkeypatch.setattr(transform_module, "adapt_activity", lambda *a, **k: _adapted())
    monkeypatch.setattr(transform_module, "review_adapted_worksheet", fake_review)
    monkeypatch.setattr(transform_module, "apply_theme", lambda *a, **k: None)
    monkeypatch.setattr(
        transform_module,
        "_validate_and_report",
        lambda *a, **k: {
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
            "all_validators_passed": True,
        },
    )


def test_single_pipeline_defaults_to_pdf_classic_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_common(monkeypatch)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    rendered_paths: list[str] = []

    def fake_render_worksheet(*args: object, **kwargs: object) -> str:
        rendered_paths.append(str(args[2]))
        Path(str(args[2])).write_text("pdf placeholder")
        return str(args[2])

    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)

    run_artifacts = transform_module._run_single_worksheet_pipeline(
        skill_model=_skill(),
        profile=LearnerProfile(name="Ian", grade_level="1"),
        theme=ThemeConfig(name="Geometry Dash Calm"),
        theme_id="geometry_dash",
        source_image_path="source.png",
        source_image_hash="source_hash",
        extracted_text="rain play",
        template_type="generic",
        ocr_engine="test",
        region_count=1,
        output=tmp_path,
        artifacts=artifacts,
        rag_prior_adaptations=None,
        rag_curriculum_references=None,
    )

    assert run_artifacts.render_mode == "pdf_classic"
    assert run_artifacts.renderer_id == "pdf_classic"
    assert run_artifacts.renderer_experimental is False
    assert run_artifacts.pdf_paths == rendered_paths
    assert run_artifacts.validation_results["renderer_produces_pdf"] is True
    manifest = json.loads((artifacts / "renderer_manifest.json").read_text())
    assert manifest["renderer_id"] == "pdf_classic"
    assert manifest["render_mode"] == "pdf_classic"
    assert manifest["produces_pdf"] is True


def test_single_pipeline_image_prompt_writes_artifacts_without_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_common(monkeypatch)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    run_artifacts = transform_module._run_single_worksheet_pipeline(
        skill_model=_skill(),
        profile=LearnerProfile(name="Ian", grade_level="1"),
        theme=ThemeConfig(name="Geometry Dash Calm"),
        theme_id="geometry_dash",
        source_image_path="source.png",
        source_image_hash="source_hash",
        extracted_text="rain play",
        template_type="generic",
        ocr_engine="test",
        region_count=1,
        output=tmp_path,
        artifacts=artifacts,
        rag_prior_adaptations=None,
        rag_curriculum_references=None,
        render_mode="image_prompt",
    )

    assert run_artifacts.render_mode == "image_prompt"
    assert run_artifacts.renderer_id == "image_prompt"
    assert run_artifacts.renderer_experimental is True
    assert run_artifacts.pdf_paths == []
    assert run_artifacts.validation_results["renderer_produces_pdf"] is False
    assert run_artifacts.validation_results["all_validators_passed"] is False
    assert (tmp_path / "artifacts" / "worksheet_image_prompt.md").exists()
    assert (tmp_path / "artifacts" / "renderer_manifest.json").exists()
