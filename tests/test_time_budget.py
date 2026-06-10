"""Tests for cross-worksheet time budget validation."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

import transform as transform_module
from adapt.engine import adapt_lesson
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from theme.schema import ThemeConfig
from transform import _run_multi_worksheet_pipeline
from validate.adhd_compliance import validate_lesson_time_budget
from validate.schema import ValidationResult


def _ufli_59_skill() -> LiteracySkillModel:
    """Synthetic UFLI Lesson 59 skill model with varied content types."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=[
            "Read words with CVCe pattern",
            "Apply CVCe pattern in connected text",
        ],
        target_words=["grade", "chase", "slide", "quite", "froze", "these"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, chase, slide, quite, froze, these",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content=("1. tune → tone → cone → cane " "2. tame → time → dime → dome"),
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my, one, once",
                source_region_index=2,
            ),
            SourceItem(
                item_type="sentence",
                content=(
                    "1. The grade on the slide was quite nice. " "2. These froze by the chase."
                ),
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content=(
                    "A Cake for Tess. Tess had a cake. " "The cake was huge! She made it with love."
                ),
                source_region_index=4,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _grade_1_profile() -> LearnerProfile:
    return LearnerProfile(
        name="Test G1",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle"],
        ),
    )


class TestLessonTimeBudget:
    def test_normal_lesson_passes(self) -> None:
        """Normal lessons should pass time budget validation."""
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        result = validate_lesson_time_budget(worksheets)
        assert result.passed is True
        # Should have no violations with check "total_time_budget"
        total_time_violations = [v for v in result.violations if v.check == "total_time_budget"]
        assert len(total_time_violations) == 0

    def test_warns_when_over_20_minutes(self) -> None:
        """Lessons exceeding 20 minutes should generate a warning."""
        # Generate real worksheets then inflate time estimates
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())

        # Manually inflate time estimates to exceed 20 minutes
        for ws in worksheets:
            for chunk in ws.chunks:
                chunk.time_estimate = "About 10 minutes"

        result = validate_lesson_time_budget(worksheets)

        # Should still pass (warnings don't fail validation)
        assert result.passed is True

        # Should have a warning violation with check "total_time_budget"
        total_time_violations = [v for v in result.violations if v.check == "total_time_budget"]
        assert len(total_time_violations) >= 1
        assert total_time_violations[0].severity == "warning"

    def test_empty_worksheets_passes(self) -> None:
        """Empty worksheet list should pass with 0 violations."""
        result = validate_lesson_time_budget([])
        assert result.passed is True
        assert len(result.violations) == 0

    def test_individual_worksheet_time_limit(self) -> None:
        """Individual worksheets exceeding 8 minutes should generate a warning."""
        # Create a single worksheet with inflated time
        ws = AdaptedActivityModel(
            source_hash="test123",
            skill_model_hash="skill456",
            learner_profile_hash="profile789",
            grade_level="1",
            domain="phonics",
            specific_skill="test_skill",
            chunks=[
                ActivityChunk(
                    chunk_id=1,
                    micro_goal="Test goal",
                    instructions=[Step(number=1, text="Test instruction")],
                    items=[
                        ActivityItem(
                            item_id=1,
                            content="test",
                            response_format="write",
                        )
                    ],
                    response_format="write",
                    time_estimate="About 10 minutes",
                )
            ],
            scaffolding=ScaffoldConfig(),
            theme_id="default",
            decoration_zones=[],
            worksheet_number=1,
            worksheet_count=1,
        )

        result = validate_lesson_time_budget([ws])

        # Should pass but with a warning
        assert result.passed is True
        worksheet_time_violations = [
            v for v in result.violations if v.check == "worksheet_time_limit"
        ]
        assert len(worksheet_time_violations) >= 1
        assert worksheet_time_violations[0].severity == "warning"

    def test_multi_pipeline_includes_lesson_time_budget_result(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        worksheets = adapt_lesson(_ufli_59_skill(), _grade_1_profile())
        for ws in worksheets:
            for chunk in ws.chunks:
                chunk.time_estimate = "About 10 minutes"

        output = tmp_path / "output"
        artifacts = tmp_path / "artifacts"
        output.mkdir()
        artifacts.mkdir()
        (artifacts / "judge_verdict.json").write_text(
            json.dumps({"approved": True, "overall_score": 1.0})
        )

        def fake_adapt_lesson(*args: object, **kwargs: object) -> list[AdaptedActivityModel]:
            return worksheets

        def fake_render_worksheet(*args: object, **kwargs: object) -> None:
            return None

        def fake_apply_theme(*args: object, **kwargs: object) -> None:
            return None

        def fake_merge_lesson_package(*args: object, **kwargs: object) -> list[str]:
            return [str(output / "lesson.pdf")]

        def fake_validate_print_quality(*args: object, **kwargs: object) -> ValidationResult:
            return ValidationResult(validator="print_quality", passed=True, checks_run=1)

        monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
        monkeypatch.setattr(transform_module, "render_worksheet", fake_render_worksheet)
        monkeypatch.setattr(transform_module, "apply_theme", fake_apply_theme)
        monkeypatch.setattr(transform_module, "_merge_lesson_package", fake_merge_lesson_package)
        monkeypatch.setattr(transform_module, "validate_print_quality", fake_validate_print_quality)

        run_artifacts = _run_multi_worksheet_pipeline(
            skill_model=_ufli_59_skill(),
            profile=_grade_1_profile(),
            theme=ThemeConfig(name="Test", multi_worksheet=True),
            theme_id="test_theme",
            source_image_path="source.png",
            source_image_hash="source_hash",
            extracted_text="source text",
            template_type="ufli_word_work",
            ocr_engine="test",
            region_count=3,
            output=output,
            artifacts=artifacts,
            rag_prior_adaptations=None,
            rag_curriculum_references=None,
        )

        assert run_artifacts.validation_results["lesson_time_budget_passed"] is True
        time_budget_json = artifacts / "validation_lesson_time_budget.json"
        assert time_budget_json.exists()
        validation = json.loads(time_budget_json.read_text())
        assert validation["lesson_time_budget"]["violations"]
