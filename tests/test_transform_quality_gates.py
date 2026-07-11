"""Tests for transform quality-gate aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

import transform as transform_module
from adapt.llm_judge import ObjectiveJudgeCellScore, ObjectiveJudgeVerdict, SevereDefect
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem
from theme.schema import ThemeConfig
from transform import (
    UnapprovedPackageError,
    _aggregate_validation_results,
    _run_multi_worksheet_pipeline,
)
from validate.ai_review import ReviewResult
from validate.schema import ValidationResult, ValidationViolation


def test_aggregate_validation_results_blocks_on_content_coverage_failure() -> None:
    result = _aggregate_validation_results(
        [
            {
                "skill_parity_passed": True,
                "age_band_passed": True,
                "adhd_compliance_passed": True,
                "print_quality_passed": True,
                "content_coverage_passed": False,
                "all_validators_passed": True,
            }
        ]
    )

    assert result["content_coverage_passed"] is False
    assert result["all_validators_passed"] is False


def test_multi_worksheet_package_content_coverage_uses_combined_content(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    skill = _ufli_split_word_work_skill()
    worksheets = [
        _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
        _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
    ]
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

    def fake_review_adapted_worksheet(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [
            ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
        ]

    monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)
    monkeypatch.setattr(transform_module, "apply_theme", fake_apply_theme)
    monkeypatch.setattr(transform_module, "_merge_lesson_package", fake_merge_lesson_package)
    monkeypatch.setattr(transform_module, "validate_print_quality", fake_validate_print_quality)
    monkeypatch.setattr(transform_module, "review_adapted_worksheet", fake_review_adapted_worksheet)

    run_artifacts = _run_multi_worksheet_pipeline(
        skill_model=skill,
        profile=LearnerProfile(name="Test", grade_level="1"),
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

    assert run_artifacts.validation_results["content_coverage_passed"] is True
    assert run_artifacts.validation_results["all_validators_passed"] is True


def test_multi_worksheet_package_content_coverage_accepts_production_answers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet_with_items(
                1,
                [
                    ActivityItem(item_id=1, content="grade", response_format="write"),
                    ActivityItem(
                        item_id=2,
                        content='Start with "tune." Change u to o. Write the new word.',
                        response_format="write",
                        metadata={"display": "chain_step"},
                        answer="tone",
                    ),
                    ActivityItem(
                        item_id=3,
                        content='Start with "tone." Change t to c. Write the new word.',
                        response_format="write",
                        metadata={"display": "chain_step"},
                        answer="cone",
                    ),
                ],
            ),
            _adapted_worksheet_with_items(
                2,
                [
                    ActivityItem(
                        item_id=1,
                        content='Start with "cone." Change o to a. Write the new word.',
                        response_format="write",
                        metadata={"display": "chain_step"},
                        answer="cane",
                    ),
                    ActivityItem(
                        item_id=2,
                        content="The ________ is quite tall.",
                        response_format="fill_blank",
                        answer="slide",
                    ),
                ],
            ),
        ],
    )

    assert run_artifacts.validation_results["content_coverage_passed"] is True
    assert run_artifacts.validation_results["all_validators_passed"] is True


def test_multi_worksheet_package_content_coverage_blocks_true_missing_content(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone"]),
        ],
    )

    assert run_artifacts.validation_results["content_coverage_passed"] is False
    assert run_artifacts.validation_results["all_validators_passed"] is False


def test_multi_worksheet_ai_review_failure_blocks_package(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def failing_review(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [
            ReviewResult(
                passed=False,
                issues=[{"criterion": "completeness", "description": "Truncated item"}],
                suggestions=[],
            )
        ]

    monkeypatch.setattr(transform_module, "review_adapted_worksheet", failing_review)

    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        stub_ai_review=False,
    )

    assert run_artifacts.validation_results["ai_review_passed"] is False
    assert run_artifacts.validation_results["all_validators_passed"] is False
    review_artifact = tmp_path / "artifacts" / "ai_review_1.json"
    assert json.loads(review_artifact.read_text())[0]["passed"] is False


def test_multi_worksheet_ai_review_success_allows_package(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def passing_review(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [ReviewResult(passed=True, issues=[], suggestions=[])]

    monkeypatch.setattr(transform_module, "review_adapted_worksheet", passing_review)

    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        stub_ai_review=False,
    )

    assert run_artifacts.validation_results["ai_review_passed"] is True
    assert run_artifacts.validation_results["all_validators_passed"] is True


def test_multi_worksheet_no_api_review_artifact_marks_skip(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        stub_ai_review=False,
    )

    assert run_artifacts.validation_results["ai_review_passed"] is True
    review_artifact = tmp_path / "artifacts" / "ai_review_1.json"
    review_data = json.loads(review_artifact.read_text())
    assert review_data[0]["skipped_no_api_key"] is True


def test_rejected_pedagogical_judge_blocks_package(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        judge_verdict={
            "approved": False,
            "overall_score": 0.35,
            "rationale": "Missing source content",
        },
    )

    assert run_artifacts.validation_results["pedagogical_judge_passed"] is False
    assert run_artifacts.validation_results["all_validators_passed"] is False


def test_missing_pedagogical_judge_does_not_block_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        write_judge_verdict=False,
    )

    assert "pedagogical_judge_passed" not in run_artifacts.validation_results
    assert run_artifacts.validation_results["all_validators_passed"] is True


def test_merged_lesson_print_failure_blocks_package(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    final_print_result = ValidationResult(
        validator="print_quality",
        passed=False,
        checks_run=1,
        violations=[
            ValidationViolation(
                check="page_dimensions",
                severity="error",
                message="Merged lesson page is not letter sized",
            )
        ],
    )

    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        final_print_result=final_print_result,
    )

    assert run_artifacts.validation_results["print_quality_passed"] is False
    assert run_artifacts.validation_results["all_validators_passed"] is False
    validation = json.loads(
        (tmp_path / "artifacts" / "validation_final_print_quality.json").read_text()
    )
    assert validation["print_quality"]["passed"] is False
    assert validation["print_quality"]["violations"][0]["check"] == "page_dimensions"


def test_merged_lesson_print_success_keeps_package_valid(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    validation_calls: list[str] = []

    run_artifacts = _run_pipeline_with_worksheets(
        tmp_path,
        monkeypatch,
        [
            _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
            _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
        ],
        final_print_result=ValidationResult(
            validator="print_quality",
            passed=True,
            checks_run=1,
        ),
        validation_calls=validation_calls,
    )

    assert any(Path(call).name == "lesson.pdf" for call in validation_calls)
    assert run_artifacts.validation_results["print_quality_passed"] is True
    assert run_artifacts.validation_results["all_validators_passed"] is True
    validation = json.loads(
        (tmp_path / "artifacts" / "validation_final_print_quality.json").read_text()
    )
    assert validation["print_quality"]["passed"] is True


def _ufli_split_word_work_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read and spell CVCe words"],
        target_words=["grade", "slide", "quite"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, slide, quite",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="tune -> tone -> cone -> cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sentence",
                content="The slide is quite tall.",
                source_region_index=2,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _adapted_worksheet(worksheet_number: int, contents: list[str]) -> AdaptedActivityModel:
    return _adapted_worksheet_with_items(
        worksheet_number,
        [
            ActivityItem(item_id=i + 1, content=text, response_format="write")
            for i, text in enumerate(contents)
        ],
    )


def _adapted_worksheet_with_items(
    worksheet_number: int,
    items: list[ActivityItem],
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice source content",
                instructions=[Step(number=1, text="Read each item.")],
                worked_example=None,
                items=items,
                response_format="write",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="test_theme",
        decoration_zones=[],
        worksheet_number=worksheet_number,
        worksheet_count=2,
        feedback=FeedbackPanel(goal_statement="I practiced the source words."),
    )


def _run_pipeline_with_worksheets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    worksheets: list[AdaptedActivityModel],
    judge_verdict: dict[str, object] | None = None,
    write_judge_verdict: bool = True,
    stub_ai_review: bool = True,
    final_print_result: ValidationResult | None = None,
    validation_calls: list[str] | None = None,
) -> transform_module.RunArtifacts:
    output = tmp_path / "output"
    artifacts = tmp_path / "artifacts"
    output.mkdir()
    artifacts.mkdir()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if write_judge_verdict:
        if judge_verdict is None:
            judge_verdict = {"approved": True, "overall_score": 1.0}
        (artifacts / "judge_verdict.json").write_text(json.dumps(judge_verdict))

    def fake_adapt_lesson(*args: object, **kwargs: object) -> list[AdaptedActivityModel]:
        return worksheets

    def fake_render_worksheet(*args: object, **kwargs: object) -> None:
        return None

    def fake_apply_theme(*args: object, **kwargs: object) -> None:
        return None

    def fake_merge_lesson_package(*args: object, **kwargs: object) -> list[str]:
        return [str(output / "lesson.pdf")]

    def fake_validate_print_quality(*args: object, **kwargs: object) -> ValidationResult:
        pdf_path = str(args[0])
        if validation_calls is not None:
            validation_calls.append(pdf_path)
        if final_print_result is not None and Path(pdf_path).name == "lesson.pdf":
            return final_print_result
        return ValidationResult(validator="print_quality", passed=True, checks_run=1)

    def fake_review_adapted_worksheet(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [
            ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
        ]

    monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)
    monkeypatch.setattr(transform_module, "apply_theme", fake_apply_theme)
    monkeypatch.setattr(transform_module, "_merge_lesson_package", fake_merge_lesson_package)
    monkeypatch.setattr(transform_module, "validate_print_quality", fake_validate_print_quality)
    if stub_ai_review:
        monkeypatch.setattr(
            transform_module,
            "review_adapted_worksheet",
            fake_review_adapted_worksheet,
        )

    return _run_multi_worksheet_pipeline(
        skill_model=_ufli_split_word_work_skill(),
        profile=LearnerProfile(name="Test", grade_level="1"),
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


# =========================================================================== #
# P3b — advisory objective judge + fail-before-render policy.
#
# Objective mode (WORKSHEET_OBJECTIVE_COVERAGE=1), fallback package (no
# judge_verdict.json on disk — the planner didn't already judge it). Stubs
# judge_package_objective at the transform import site (its own behavior is
# covered in tests/test_llm_judge.py) and asserts the P3b policy matrix:
# not-approved + flag unset aborts BEFORE any render artifacts exist; the
# flag overrides; a None verdict (judge unavailable) ships with a warning.
# =========================================================================== #


def _objective_verdict(
    *,
    approved: bool,
    defects: bool = False,
    recommendation: str | None = None,
) -> ObjectiveJudgeVerdict:
    cell = ObjectiveJudgeCellScore(
        objective_id="obj_decode",
        quality=0.30 if not approved else 0.85,
        severe_defects=(
            [SevereDefect(defect_type="generic_activity_not_exercising_objective", evidence="e1")]
            if defects
            else []
        ),
        evidence_item_ids=["e1"],
        rationale="stub",
    )
    if recommendation is None:
        recommendation = "approve" if approved else "reject"
    return ObjectiveJudgeVerdict(
        objective_scores=[cell],
        objective_sufficiency=0.85 if approved else 0.30,
        skill_form_fidelity=0.85 if approved else 0.30,
        structured_literacy_alignment=0.85 if approved else 0.30,
        adhd_cognitive_load_fit=0.85 if approved else 0.30,
        lesson_flow_and_usability=0.85 if approved else 0.30,
        overall_score=0.85 if approved else 0.30,
        approval_recommendation=recommendation,  # type: ignore[arg-type]
        feedback=["all good"] if approved else ["cell obj_decode is weak busywork"],
    )


def _run_objective_pipeline_with_stubbed_judge(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    judge_return: ObjectiveJudgeVerdict | None,
) -> tuple[Path, Path, transform_module.RunArtifacts]:
    """Run the multi-worksheet pipeline in objective mode, fallback (unjudged) package.

    Returns (output_dir, artifacts_dir, run_artifacts) so callers can assert
    on-disk state (or lack of it) even when the pipeline raises.
    """
    worksheets = [
        _adapted_worksheet(1, ["grade", "slide", "tune tone"]),
        _adapted_worksheet(2, ["quite", "cone cane", "The slide is quite tall."]),
    ]
    output = tmp_path / "output"
    artifacts = tmp_path / "artifacts"
    output.mkdir()
    artifacts.mkdir()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    # No judge_verdict.json written — this is the fallback (unjudged) package
    # path, exactly what triggers the advisory judge in Stage 5c.

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

    def fake_review_adapted_worksheet(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        return adapted, [
            ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
        ]

    def fake_judge_package_objective(
        *args: object, **kwargs: object
    ) -> ObjectiveJudgeVerdict | None:
        return judge_return

    monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)
    monkeypatch.setattr(transform_module, "apply_theme", fake_apply_theme)
    monkeypatch.setattr(transform_module, "_merge_lesson_package", fake_merge_lesson_package)
    monkeypatch.setattr(transform_module, "validate_print_quality", fake_validate_print_quality)
    monkeypatch.setattr(transform_module, "review_adapted_worksheet", fake_review_adapted_worksheet)
    monkeypatch.setattr("adapt.llm_judge.judge_package_objective", fake_judge_package_objective)

    run_artifacts = _run_multi_worksheet_pipeline(
        skill_model=_ufli_split_word_work_skill(),
        profile=LearnerProfile(name="Test", grade_level="1"),
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
    return output, artifacts, run_artifacts


def test_objective_advisory_not_approved_aborts_before_render(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Not-approved + WORKSHEET_SHIP_UNAPPROVED unset -> abort, no render artifacts."""
    monkeypatch.delenv("WORKSHEET_SHIP_UNAPPROVED", raising=False)

    with pytest.raises(UnapprovedPackageError):
        _run_objective_pipeline_with_stubbed_judge(
            tmp_path,
            monkeypatch,
            judge_return=_objective_verdict(approved=False, defects=True),
        )

    output = tmp_path / "output"
    artifacts = tmp_path / "artifacts"
    assert list(output.glob("*.pdf")) == []
    assert not (artifacts / "adapted_model_1.json").exists()
    # The verdict artifact itself is allowed to remain (debuggability).
    assert (artifacts / "judge_verdict.json").exists()


def test_objective_advisory_not_approved_ships_when_flag_set(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Not-approved + WORKSHEET_SHIP_UNAPPROVED=1 -> render proceeds with a warning."""
    monkeypatch.setenv("WORKSHEET_SHIP_UNAPPROVED", "1")

    output, artifacts, run_artifacts = _run_objective_pipeline_with_stubbed_judge(
        tmp_path,
        monkeypatch,
        judge_return=_objective_verdict(approved=False, defects=True),
    )

    # Render loop ran: PDF paths collected + per-worksheet artifacts on disk.
    assert run_artifacts.pdf_paths == [str(output / "lesson.pdf")]
    assert (artifacts / "adapted_model_1.json").exists()
    assert (artifacts / "adapted_model_2.json").exists()
    verdict = json.loads((artifacts / "judge_verdict.json").read_text())
    assert verdict["approved"] is False


def test_objective_advisory_judge_none_ships_with_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """judge_package_objective returning None -> ship + 'unavailable' warning."""
    monkeypatch.delenv("WORKSHEET_SHIP_UNAPPROVED", raising=False)

    with caplog.at_level("WARNING"):
        output, artifacts, run_artifacts = _run_objective_pipeline_with_stubbed_judge(
            tmp_path,
            monkeypatch,
            judge_return=None,
        )

    # Render loop ran: PDF paths collected + per-worksheet artifacts on disk.
    assert run_artifacts.pdf_paths == [str(output / "lesson.pdf")]
    assert (artifacts / "adapted_model_1.json").exists()
    verdict = json.loads((artifacts / "judge_verdict.json").read_text())
    assert verdict.get("unavailable") is True
    assert any("unavailable" in record.message for record in caplog.records)


def test_objective_advisory_abstain_ships_with_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Abstain -> render + loud warning; only an affirmative reject trips the abort.

    Abstain is the judge-level analogue of the deterministic validator's
    needs_verification ("cannot confidently verify"), which counts as
    pass-with-note — it must not fire the cost circuit-breaker.
    """
    monkeypatch.delenv("WORKSHEET_SHIP_UNAPPROVED", raising=False)

    with caplog.at_level("WARNING"):
        output, artifacts, run_artifacts = _run_objective_pipeline_with_stubbed_judge(
            tmp_path,
            monkeypatch,
            judge_return=_objective_verdict(approved=False, recommendation="abstain"),
        )

    # Render loop ran: PDF paths collected + per-worksheet artifacts on disk.
    assert run_artifacts.pdf_paths == [str(output / "lesson.pdf")]
    assert (artifacts / "adapted_model_1.json").exists()
    assert any("abstain" in record.message.lower() for record in caplog.records)
    # Abstain is pass-with-note: it must not mark package validation failed.
    assert run_artifacts.validation_results.get("pedagogical_judge_passed") is not False
