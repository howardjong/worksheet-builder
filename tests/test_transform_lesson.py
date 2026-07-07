"""Tests for the --lesson entry point: lesson-mode transform + CLI arg validation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import corpus.ufli.lookup as lookup_module
import transform as transform_module
from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from corpus.ufli.lookup import reset_lookup_cache
from transform import RunArtifacts, run_lesson_pipeline_collect_artifacts, transform
from validate.ai_review import ReviewResult
from validate.schema import ValidationResult


@pytest.fixture(autouse=True)
def _force_fixture_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", tmp_path / "no_corpus")
    reset_lookup_cache()
    yield
    reset_lookup_cache()


def test_lesson_mode_skips_capture_and_hashes_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        captured.append({"skill_model": skill_model, **kwargs})
        return RunArtifacts(
            source_image_path=str(kwargs["source_image_path"]),
            source_image_hash=str(kwargs["source_image_hash"]),
            extracted_text=str(kwargs["extracted_text"]),
            template_type=str(kwargs["template_type"]),
            ocr_engine=str(kwargs["ocr_engine"]),
            region_count=int(kwargs["region_count"]),
            skill_domain=skill_model.domain,
            skill_name=skill_model.specific_skill,
            grade_level=skill_model.grade_level,
            theme_id="roblox_obby",
            worksheet_mode="multi",
            adapted_summaries=[],
            pdf_paths=[str(Path(kwargs["output"]) / "lesson_x.pdf")],
            validation_results={"all_validators_passed": True},
        )

    # Capture/OCR stages must never run in lesson mode.
    for name in ("preprocess_page", "store_master", "extract_with_vision", "extract_skill"):
        monkeypatch.setattr(
            f"transform.{name}", lambda *a, **k: pytest.fail("capture/OCR ran in lesson mode")
        )
    monkeypatch.setattr(transform_module, "_run_from_skill_model", fake_run_from_skill_model)

    for _ in range(2):
        run_lesson_pipeline_collect_artifacts(
            74,
            "profiles/does-not-need-to-exist.yaml",
            "roblox_obby",
            str(tmp_path / "out"),
            str(tmp_path / "art"),
            index_results=False,
        )

    expected_hash = hashlib.sha256(b"ufli_lesson:74").hexdigest()[:16]
    assert len(captured) == 2
    assert captured[0]["source_image_hash"] == expected_hash
    assert captured[1]["source_image_hash"] == expected_hash  # stable across runs
    assert captured[0]["ocr_engine"] == "none"
    assert captured[0]["region_count"] == 0
    assert captured[0]["extracted_text"] == ""

    model = captured[0]["skill_model"]
    assert model.lesson_number == 74
    assert model.template_type == "ufli_word_work"
    assert model.specific_skill == "vowel_teams"


def test_lesson_mode_defaults_planner_v2_and_restores_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lesson mode defaults planner-v2 AND its LLM_ADAPT prerequisite, call-scoped.

    Both must be defaulted together: WORKSHEET_PLANNER_V2 alone routes the
    engine to plan_lesson_llm, which is a no-op without WORKSHEET_LLM_ADAPT —
    silently reproducing the deterministic 10-worksheet overflow.
    """
    monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_SLOT_CONTRACT", raising=False)
    seen: list[tuple[str | None, str | None, str | None]] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        seen.append(
            (
                os.environ.get("WORKSHEET_PLANNER_V2"),
                os.environ.get("WORKSHEET_LLM_ADAPT"),
                os.environ.get("WORKSHEET_OBJECTIVE_COVERAGE"),
            )
        )
        return RunArtifacts(
            source_image_path=str(kwargs["source_image_path"]),
            source_image_hash=str(kwargs["source_image_hash"]),
            extracted_text=str(kwargs["extracted_text"]),
            template_type=str(kwargs["template_type"]),
            ocr_engine=str(kwargs["ocr_engine"]),
            region_count=int(kwargs["region_count"]),
            skill_domain=skill_model.domain,
            skill_name=skill_model.specific_skill,
            grade_level=skill_model.grade_level,
            theme_id="roblox_obby",
            worksheet_mode="multi",
            adapted_summaries=[],
            pdf_paths=[],
            validation_results={"all_validators_passed": True},
        )

    monkeypatch.setattr(transform_module, "_run_from_skill_model", fake_run_from_skill_model)

    run_lesson_pipeline_collect_artifacts(
        74,
        "profiles/does-not-need-to-exist.yaml",
        "roblox_obby",
        str(tmp_path / "out"),
        str(tmp_path / "art"),
        index_results=False,
    )

    assert seen == [("1", "1", "1")]  # all defaulted on for the duration of the call
    assert "WORKSHEET_PLANNER_V2" not in os.environ  # restored afterward
    assert "WORKSHEET_LLM_ADAPT" not in os.environ  # restored afterward
    assert "WORKSHEET_OBJECTIVE_COVERAGE" not in os.environ  # restored afterward


def test_lesson_mode_respects_explicit_planner_v2_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit overrides win: PLANNER_V2=0 (legacy opt-in) and LLM_ADAPT=0 (all-LLM off)."""
    monkeypatch.setenv("WORKSHEET_PLANNER_V2", "0")
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    seen: list[tuple[str | None, str | None]] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        seen.append(
            (os.environ.get("WORKSHEET_PLANNER_V2"), os.environ.get("WORKSHEET_LLM_ADAPT"))
        )
        return RunArtifacts(
            source_image_path=str(kwargs["source_image_path"]),
            source_image_hash=str(kwargs["source_image_hash"]),
            extracted_text=str(kwargs["extracted_text"]),
            template_type=str(kwargs["template_type"]),
            ocr_engine=str(kwargs["ocr_engine"]),
            region_count=int(kwargs["region_count"]),
            skill_domain=skill_model.domain,
            skill_name=skill_model.specific_skill,
            grade_level=skill_model.grade_level,
            theme_id="roblox_obby",
            worksheet_mode="multi",
            adapted_summaries=[],
            pdf_paths=[],
            validation_results={"all_validators_passed": True},
        )

    monkeypatch.setattr(transform_module, "_run_from_skill_model", fake_run_from_skill_model)

    run_lesson_pipeline_collect_artifacts(
        74,
        "profiles/does-not-need-to-exist.yaml",
        "roblox_obby",
        str(tmp_path / "out"),
        str(tmp_path / "art"),
        index_results=False,
    )

    assert seen == [("0", "0")]  # explicit overrides are never clobbered
    assert os.environ["WORKSHEET_PLANNER_V2"] == "0"  # left exactly as the caller set it
    assert os.environ["WORKSHEET_LLM_ADAPT"] == "0"


def test_lesson_mode_skips_objective_default_when_slot_contract_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit slot-contract opt-in suppresses the objective-coverage default.

    The two coverage systems are mutually exclusive (plan_lesson_llm raises when
    both are set), so lesson mode must never stack its objective default on top
    of a user's slot-contract choice.
    """
    monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)
    monkeypatch.setenv("WORKSHEET_PLANNER_SLOT_CONTRACT", "1")
    seen: list[str | None] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        seen.append(os.environ.get("WORKSHEET_OBJECTIVE_COVERAGE"))
        return RunArtifacts(
            source_image_path=str(kwargs["source_image_path"]),
            source_image_hash=str(kwargs["source_image_hash"]),
            extracted_text=str(kwargs["extracted_text"]),
            template_type=str(kwargs["template_type"]),
            ocr_engine=str(kwargs["ocr_engine"]),
            region_count=int(kwargs["region_count"]),
            skill_domain=skill_model.domain,
            skill_name=skill_model.specific_skill,
            grade_level=skill_model.grade_level,
            theme_id="roblox_obby",
            worksheet_mode="multi",
            adapted_summaries=[],
            pdf_paths=[],
            validation_results={"all_validators_passed": True},
        )

    monkeypatch.setattr(transform_module, "_run_from_skill_model", fake_run_from_skill_model)

    run_lesson_pipeline_collect_artifacts(
        74,
        "profiles/does-not-need-to-exist.yaml",
        "roblox_obby",
        str(tmp_path / "out"),
        str(tmp_path / "art"),
        index_results=False,
    )

    assert seen == [None]  # objective default suppressed, slot contract untouched
    assert os.environ["WORKSHEET_PLANNER_SLOT_CONTRACT"] == "1"
    assert "WORKSHEET_OBJECTIVE_COVERAGE" not in os.environ


def _worksheet(number: int, contents: list[str]) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="2",
        domain="phonics",
        specific_skill="vowel_teams",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice the ay pattern",
                instructions=[Step(number=1, text="Read each word.")],
                worked_example=None,
                items=[
                    ActivityItem(item_id=i + 1, content=text, response_format="write")
                    for i, text in enumerate(contents)
                ],
                response_format="write",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="roblox_obby",
        decoration_zones=[],
        worksheet_number=number,
        worksheet_count=3,
        self_assessment=["I practiced ay words."],
    )


def test_lesson_mode_produces_stable_lesson_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merged output is a stable, hash-derived lesson_<hash>.pdf across runs."""
    monkeypatch.setenv("WORKSHEET_SKIP_ASSET_GEN", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("name: Ian\ngrade_level: '2'\n", encoding="utf-8")

    worksheets = [
        _worksheet(1, ["day", "play", "stay"]),
        _worksheet(2, ["say", "way", "tray"]),
        _worksheet(3, ["clay", "gray"]),
    ]

    def fake_adapt_lesson(*a: Any, **k: Any) -> list[AdaptedActivityModel]:
        return worksheets

    def fake_review(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        review = ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
        return adapted, [review]

    def fake_print(*a: Any, **k: Any) -> ValidationResult:
        return ValidationResult(validator="print_quality", passed=True, checks_run=1)

    def fake_merge(**kwargs: Any) -> list[str]:
        return [str(Path(kwargs["output"]) / f"lesson_{kwargs['content_hash']}.pdf")]

    monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
    monkeypatch.setattr(transform_module, "apply_theme", lambda *a, **k: None)
    monkeypatch.setattr(transform_module, "review_adapted_worksheet", fake_review)
    monkeypatch.setattr(transform_module, "validate_print_quality", fake_print)
    monkeypatch.setattr(transform_module, "_merge_lesson_package", fake_merge)
    monkeypatch.setattr(transform_module, "_should_generate_chunk_assets", lambda _mode: False)
    monkeypatch.setattr("render.strategies.render_worksheet", lambda *a, **k: None)

    def run() -> RunArtifacts:
        art = tmp_path / "art"
        art.mkdir(exist_ok=True)
        # Pre-seed an approving judge verdict so no LLM judge is attempted.
        verdict = json.dumps({"approved": True, "overall_score": 1.0})
        (art / "judge_verdict.json").write_text(verdict)
        return run_lesson_pipeline_collect_artifacts(
            74,
            str(profile_path),
            "roblox_obby",
            str(tmp_path / "out"),
            str(art),
            index_results=False,
            render_mode="pdf_classic",
        )

    first = run()
    second = run()

    source_hash = hashlib.sha256(b"ufli_lesson:74").hexdigest()[:16]
    content_hash = hashlib.sha256(f"{source_hash}:Ian:roblox_obby".encode()).hexdigest()[:12]
    assert first.pdf_paths == second.pdf_paths  # stable across runs
    assert first.pdf_paths[0].endswith(f"lesson_{content_hash}.pdf")


def test_cli_requires_exactly_one_entry_point(tmp_path: Path) -> None:
    runner = CliRunner()

    # Neither --input nor --lesson.
    result = runner.invoke(
        transform,
        ["--profile", "p.yaml", "--theme", "roblox_obby", "--output", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "exactly one of --input or --lesson" in result.output

    # Both provided.
    result = runner.invoke(
        transform,
        ["--input", "x.jpg", "--lesson", "74", "--profile", "p.yaml", "--output", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_cli_lesson_mode_invokes_lesson_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_lesson_pipeline(**kwargs: Any) -> str:
        calls.update(kwargs)
        return ""

    monkeypatch.setattr(transform_module, "run_lesson_pipeline", fake_run_lesson_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        transform,
        [
            "--lesson",
            "74",
            "--profile",
            "profiles/ian.yaml",
            "--theme",
            "roblox_obby",
            "--output",
            str(tmp_path),
            "--render-mode",
            "pdf_classic",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["lesson_number"] == 74
    assert calls["theme_id"] == "roblox_obby"
    assert calls["render_mode"] == "pdf_classic"
