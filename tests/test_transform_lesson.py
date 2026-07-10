"""Tests for the --lesson entry point: lesson-mode transform + CLI arg validation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import corpus.ufli.lookup as lookup_module
import transform as transform_module
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
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
    monkeypatch.delenv("WORKSHEET_MAX_WORKSHEETS", raising=False)
    seen: list[tuple[str | None, str | None, str | None, str | None]] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        seen.append(
            (
                os.environ.get("WORKSHEET_PLANNER_V2"),
                os.environ.get("WORKSHEET_LLM_ADAPT"),
                os.environ.get("WORKSHEET_OBJECTIVE_COVERAGE"),
                os.environ.get("WORKSHEET_MAX_WORKSHEETS"),
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

    assert seen == [("1", "1", "1", "auto")]  # all defaulted on for the duration of the call
    assert "WORKSHEET_PLANNER_V2" not in os.environ  # restored afterward
    assert "WORKSHEET_LLM_ADAPT" not in os.environ  # restored afterward
    assert "WORKSHEET_OBJECTIVE_COVERAGE" not in os.environ  # restored afterward
    assert "WORKSHEET_MAX_WORKSHEETS" not in os.environ  # restored afterward


def test_lesson_mode_respects_explicit_planner_v2_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit overrides win: PLANNER_V2=0 (legacy opt-in) and LLM_ADAPT=0 (all-LLM off)."""
    monkeypatch.setenv("WORKSHEET_PLANNER_V2", "0")
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    seen: list[tuple[str | None, str | None]] = []

    def fake_run_from_skill_model(skill_model: Any, **kwargs: Any) -> RunArtifacts:
        seen.append((os.environ.get("WORKSHEET_PLANNER_V2"), os.environ.get("WORKSHEET_LLM_ADAPT")))
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
        feedback=FeedbackPanel(goal_statement="I practiced ay words."),
    )


def _stub_lesson_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_adapt_lesson: Callable[..., list[AdaptedActivityModel]],
) -> Path:
    """Stub every expensive lesson-pipeline stage; returns the profile path.

    The adapt stage is the only stage tests vary (verdict-writing planner vs
    silent deterministic fallback), so it's the one injectable piece.
    """
    monkeypatch.setenv("WORKSHEET_SKIP_ASSET_GEN", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("name: Ian\ngrade_level: '2'\n", encoding="utf-8")

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
    return profile_path


def test_lesson_mode_produces_stable_lesson_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merged output is a stable, hash-derived lesson_<hash>.pdf across runs."""
    worksheets = [
        _worksheet(1, ["day", "play", "stay"]),
        _worksheet(2, ["say", "way", "tray"]),
        _worksheet(3, ["clay", "gray"]),
    ]

    def fake_adapt_lesson(*a: Any, **k: Any) -> list[AdaptedActivityModel]:
        # Write the approving verdict the way the real planner does — DURING
        # the adapt stage. Seeding it before the run would be cleared as a
        # stale prior-run artifact.
        artifacts_dir = k.get("artifacts_dir")
        if artifacts_dir:
            verdict = json.dumps({"approved": True, "overall_score": 1.0})
            (Path(str(artifacts_dir)) / "judge_verdict.json").write_text(verdict)
        return worksheets

    profile_path = _stub_lesson_pipeline(tmp_path, monkeypatch, fake_adapt_lesson)

    def run() -> RunArtifacts:
        art = tmp_path / "art"
        art.mkdir(exist_ok=True)
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


def test_lesson_pdf_has_no_cover_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The merged lesson PDF has no cover — session 60 dropped it entirely.

    page_count must equal the worksheet count (previously worksheets + 1
    cover), and page 1 must open on a worksheet (section banner), not the
    old "What's Inside" cover text.

    Unlike other lesson-pipeline tests, this one needs the real merge to run
    over real per-worksheet PDFs, so it stubs render_worksheet to write an
    actual one-page PDF (banner text stands in for the section banner)
    instead of using _stub_lesson_pipeline's no-op, and leaves
    _merge_lesson_package unstubbed.
    """
    import fitz
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas

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
        artifacts_dir = k.get("artifacts_dir")
        if artifacts_dir:
            verdict = json.dumps({"approved": True, "overall_score": 1.0})
            (Path(str(artifacts_dir)) / "judge_verdict.json").write_text(verdict)
        return worksheets

    def fake_review(
        adapted: AdaptedActivityModel,
    ) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
        review = ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
        return adapted, [review]

    def fake_print(*a: Any, **k: Any) -> ValidationResult:
        return ValidationResult(validator="print_quality", passed=True, checks_run=1)

    def fake_render_worksheet(
        adapted: AdaptedActivityModel, theme: Any, output_path: str, *a: Any, **k: Any
    ) -> str:
        c = Canvas(output_path, pagesize=letter)
        c.drawString(72, 720, f"Worksheet {adapted.worksheet_number} banner")
        c.save()
        return output_path

    monkeypatch.setattr(transform_module, "adapt_lesson", fake_adapt_lesson)
    monkeypatch.setattr(transform_module, "apply_theme", lambda *a, **k: None)
    monkeypatch.setattr(transform_module, "review_adapted_worksheet", fake_review)
    monkeypatch.setattr(transform_module, "validate_print_quality", fake_print)
    monkeypatch.setattr(transform_module, "_should_generate_chunk_assets", lambda _mode: False)
    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)

    art = tmp_path / "art"
    art.mkdir(exist_ok=True)

    result = run_lesson_pipeline_collect_artifacts(
        74,
        str(profile_path),
        "roblox_obby",
        str(tmp_path / "out"),
        str(art),
        index_results=False,
        render_mode="pdf_classic",
    )

    doc = fitz.open(result.pdf_paths[0])
    try:
        assert doc.page_count == len(worksheets)
        first_page_text = doc.load_page(0).get_text()
        assert "What's Inside" not in first_page_text
    finally:
        doc.close()


def test_stale_run_artifacts_cleared_before_adapt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A previous run's artifacts must not leak into this run.

    Observed live: a 3-day-old NOT-APPROVED judge_verdict.json (about a
    10-worksheet package) was read back and replayed against a fresh
    2-worksheet package — the judge never ran. Numbered debris
    (adapted_model_9.json etc.) from larger prior runs also lingered.
    """
    worksheets = [_worksheet(1, ["day", "play"]), _worksheet(2, ["say", "way"])]

    def fake_adapt_lesson(*a: Any, **k: Any) -> list[AdaptedActivityModel]:
        # Deterministic fallback path: the planner writes NO verdict this run.
        return worksheets

    profile_path = _stub_lesson_pipeline(tmp_path, monkeypatch, fake_adapt_lesson)

    art = tmp_path / "art"
    art.mkdir()
    stale_verdict = {
        "approved": False,
        "overall_score": 0.46,
        "rationale": "stale — references Worksheet 9",
        "planner_version": 2,
    }
    (art / "judge_verdict.json").write_text(json.dumps(stale_verdict))
    (art / "planner_attempts.json").write_text(json.dumps({"outcome": "objective_rejected_gate"}))
    (art / "adapted_model_9.json").write_text("{}")
    (art / "ai_review_9.json").write_text("{}")
    (art / "validation_9.json").write_text("{}")

    run_lesson_pipeline_collect_artifacts(
        74,
        str(profile_path),
        "roblox_obby",
        str(tmp_path / "out"),
        str(art),
        index_results=False,
        render_mode="pdf_classic",
    )

    # The stale verdict was NOT replayed: whatever exists now was written
    # by THIS run (advisory judge path — skipped without API keys).
    fresh = json.loads((art / "judge_verdict.json").read_text())
    assert fresh != stale_verdict
    assert fresh.get("overall_score") != 0.46
    # Prior-run debris is gone; this run's own numbered artifacts remain.
    assert not (art / "adapted_model_9.json").exists()
    assert not (art / "ai_review_9.json").exists()
    assert not (art / "validation_9.json").exists()
    assert not (art / "planner_attempts.json").exists()
    assert (art / "adapted_model_1.json").exists()


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
