"""Live composition contracts, with entirely synthetic artwork and no network."""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any

import fitz
import pytest
from PIL import Image

from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
from companion.schema import LearnerProfile
from render.concurrency import ordered_parallel_map
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import SceneGate, generate_scene, judge_scene
from render.strategies import RenderContext, resolve_render_strategy
from theme.engine import load_theme
from validate.print_checks import validate_print_quality


def context(directory: Path, grade: str = "2", count: int = 12) -> RenderContext:
    worksheet = AdaptedActivityModel(
        source_hash="synthetic",
        skill_model_hash="synthetic",
        learner_profile_hash="synthetic",
        grade_level=grade,
        domain="phonics",
        specific_skill="cvc",
        theme_id="space",
        worksheet_title="Word practice",
        scaffolding=ScaffoldConfig(),
        decoration_zones=[],
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal=f"Write {count} words",
                instructions=[
                    Step(number=1, text="Read each word."),
                    Step(number=2, text="Write each word on the line."),
                ],
                items=[
                    ActivityItem(item_id=index, content=f"cat {index}", response_format="write")
                    for index in range(1, count + 1)
                ],
                response_format="write",
                time_estimate="About 3 minutes",
            )
        ],
        feedback=FeedbackPanel(goal_statement="I can read and write words"),
        break_prompt="Stand up and stretch.",
    )
    theme = load_theme("space")
    return RenderContext(
        design_spec=compile_worksheet_design_spec(
            worksheet,
            theme,
            LearnerProfile(name="Test Learner", grade_level=grade),
            render_mode="hybrid_shell",
        ),
        adapted=worksheet,
        theme=theme,
        output_path=directory / "worksheet.pdf",
        artifacts_dir=directory,
    )


def synthetic_image() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 576), "#DBEAFE").save(buffer, format="PNG")
    return buffer.getvalue()


def approved_gate() -> SceneGate:
    return SceneGate(
        identity_ok=True,
        supports_task=True,
        no_text=True,
        no_answers=True,
        bounds=(0.02, 0.02, 0.98, 0.98),
    )


def mock_images(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-surrogate")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "first,second,third")

    def generate(*args: Any, **kwargs: Any) -> bytes:
        calls.append(str(kwargs["model"]))
        assert kwargs["aspect_ratio"] == "16:9"
        assert "never a worksheet" in str(args[0])
        return synthetic_image()

    monkeypatch.setattr("ai.openrouter.generate_image", generate)
    monkeypatch.setattr("render.live_scene.judge_scene", lambda *args: approved_gate())
    return calls


def test_independent_work_overlaps_but_remains_bounded_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_IMAGE_CONCURRENCY", "2")
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    peak = 0

    def work(number: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=3)
        with lock:
            active -= 1
        return number * 10

    assert ordered_parallel_map(work, [1, 2, 3, 4]) == [10, 20, 30, 40]
    assert peak == 2


def test_scene_quality_failure_advances_with_a_total_candidate_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = mock_images(monkeypatch)
    monkeypatch.setattr(
        "render.live_scene.judge_scene",
        lambda *args: approved_gate().model_copy(update={"no_text": False}),
    )
    assert generate_scene(context(tmp_path)) is None
    assert calls == ["first", "second"]
    assert json.loads((tmp_path / "learning_scene.json").read_text())["status"] == "fallback"


def test_approved_cache_is_bound_to_actual_art_bytes_and_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = mock_images(monkeypatch)
    first = context(tmp_path)
    assert generate_scene(first)
    assert generate_scene(first)
    assert calls == ["first"]
    (tmp_path / "learning_scene.png").write_bytes(b"corrupt")
    assert generate_scene(first)
    monkeypatch.setenv("WORKSHEET_OPENROUTER_SCENE_JUDGE_MODELS", "new-judge")
    assert generate_scene(first)
    assert calls == ["first", "first", "first"]


def test_unavailable_scene_is_explicit_and_can_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_ALLOW_PDF_FALLBACK", "0")
    with pytest.raises(RuntimeError, match="Learning scene unavailable"):
        generate_scene(context(tmp_path))
    report = json.loads((tmp_path / "learning_scene.json").read_text())
    assert report["status"] == "fallback" and report["attempts"] == []


@pytest.mark.parametrize("grade", ["K", "1", "2", "3"])
def test_composed_pdf_has_real_text_art_and_no_caregiver_only_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    grade: str,
) -> None:
    mock_images(monkeypatch)
    current = context(tmp_path, grade)
    result = resolve_render_strategy("hybrid_shell").render(current)
    assert result.artwork_approved is True
    assert result.effective_activity == current.adapted
    assert validate_print_quality(str(current.output_path)).passed
    with fitz.open(current.output_path) as pdf:
        assert len(pdf) >= 2  # deliberately exercise pagination
        for page in pdf:
            text = page.get_text()
            assert "cat " in text and "Test Learner" in text
            assert len(page.get_images()) == 1
            for span in (
                span
                for block in page.get_text("dict")["blocks"]
                if "lines" in block
                for line in block["lines"]
                for span in line["spans"]
            ):
                assert span["size"] >= 10  # no invisible expected-text layer
        assert "Right: ___ of 12" in pdf[-1].get_text()


def test_artwork_fallback_does_not_claim_visual_approval(tmp_path: Path) -> None:
    result = resolve_render_strategy("hybrid_shell").render(context(tmp_path, count=2))
    assert result.pdf_path and result.artwork_approved is False


def test_scene_gate_refuses_string_booleans_and_missing_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_complete(*args: Any, **kwargs: Any) -> None:
        validate = kwargs["validate"]
        assert not validate(
            {
                "identity_ok": "true",
                "supports_task": True,
                "no_text": True,
                "no_answers": True,
                "bounds": [0, 0, 1, 1],
            }
        )
        assert not validate({"identity_ok": True})
        assert validate(approved_gate().model_dump(mode="json"))
        assert kwargs["json_schema"]
        return None

    monkeypatch.setattr("ai.openrouter.complete_json", fake_complete)
    assert judge_scene(synthetic_image(), None, context(Path("unused")).design_spec) is None


def test_novel_photo_reaches_a_merged_pdf_without_any_live_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import transform
    from adapt.llm_judge import JudgeVerdict
    from extract.schema import SourceRegion, SourceWorksheetModel

    # The photo is new, not a committed lesson. Only model outputs are canned;
    # capture, extraction mapping, adaptation, rendering and validators are real.
    photo = tmp_path / "new-photo.png"
    image = Image.new("RGB", (1000, 1300), "white")
    image.save(photo)
    profile = tmp_path / "profile.yaml"
    profile.write_text("name: New Learner\ngrade_level: '1'\n")
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    monkeypatch.delenv("WORKSHEET_OBJECTIVE_COVERAGE", raising=False)
    monkeypatch.delenv("WORKSHEET_MAX_WORKSHEETS", raising=False)
    source = SourceWorksheetModel(
        source_image_hash="new-photo",
        pipeline_version="test",
        template_type="ufli_word_work",
        regions=[
            SourceRegion(type=kind, content=text, bbox=(0, 0, 100, 100), confidence=1, metadata={})
            for kind, text in [("concept_label", "CVC"), ("sample_words", "cat bag map jam")]
        ],
        raw_text="CVC\ncat bag map jam",
        ocr_engine="canned-vision",
        low_confidence_flags=[],
    )
    seen: list[str] = []

    def extract(path: str, image_hash: str) -> SourceWorksheetModel:
        seen.append(path)
        return source.model_copy(update={"source_image_hash": image_hash})

    monkeypatch.setattr(transform, "extract_with_vision", extract)
    monkeypatch.setattr(
        "adapt.llm_judge.judge_adaptation",
        lambda *args: JudgeVerdict(
            approved=True,
            overall_score=0.95,
            concept_alignment=0.95,
            content_coverage=1,
            lesson_flow=0.95,
            adhd_compliance=0.95,
            feedback=[],
            rationale="Canned offline verdict",
        ),
    )
    mock_images(monkeypatch)
    result = transform.run_pipeline_collect_artifacts(
        str(photo),
        str(profile),
        "space",
        str(tmp_path / "out"),
        str(tmp_path / "art"),
        index_results=False,
        render_mode="hybrid_shell",
    )
    assert seen == [str(photo)]
    assert result.validation_results["all_validators_passed"], result.validation_results
    assert result.validation_results["approval_matches_delivery"]
    recorded = json.loads((tmp_path / "art/run_summary.json").read_text())
    assert recorded["validation_results"]["all_validators_passed"]
    assert len(result.pdf_paths) == 1
    with fitz.open(result.pdf_paths[0]) as pdf:
        text = " ".join(page.get_text() for page in pdf)
        assert all(word in text for word in ["cat", "bag", "map", "jam"])
        assert all(page.get_images() for page in pdf)
    timing = json.loads((tmp_path / "art/timing_summary.json").read_text())
    assert timing["completed"] and timing["inference_http_attempts"] == 0
    assert not timing["cost_is_complete"]  # mocked inference is not a live cost measurement


def test_final_review_iteration_never_publishes_an_unreviewed_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from validate.ai_review import ReviewResult, review_adapted_worksheet

    original = context(tmp_path, count=1).adapted
    assert isinstance(original, AdaptedActivityModel)
    monkeypatch.setattr(
        "validate.ai_review._run_review",
        lambda *args: ReviewResult(
            passed=False,
            issues=[{"criterion": "content", "description": "bad word"}],
            suggestions=[{"chunk_id": "1", "item_id": "1", "fix": "changed"}],
        ),
    )

    def forbidden(*args: object) -> None:
        pytest.fail("last failed review must not apply an edit without another review")

    monkeypatch.setattr("validate.ai_review._apply_suggestions", forbidden)
    delivered, reviews = review_adapted_worksheet(original, max_iterations=1)
    assert delivered == original and not reviews[-1].passed


def test_parallel_inference_telemetry_preserves_stages_without_private_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from ai import openrouter
    from ai.telemetry import stage, traced_pipeline

    monkeypatch.setenv("OPENROUTER_API_KEY", "private-test-secret")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}], "usage": {"cost": 0.01}},
            )
        ),
        trust_env=False,
    )
    monkeypatch.setattr(client, "post", lambda url, **kwargs: client.request("POST", url, **kwargs))
    monkeypatch.setattr(openrouter, "_client", client)

    @traced_pipeline
    def run(artifacts_dir: str) -> None:
        def call(index: int) -> None:
            with stage(f"scene_{index}"):
                assert openrouter.complete("private-learner-name")

        ordered_parallel_map(call, [1, 2, 3])

    try:
        run(str(tmp_path))
    finally:
        client.close()
    lines = (tmp_path / "inference_calls.jsonl").read_text()
    assert "private" not in lines
    records = [json.loads(line) for line in lines.splitlines()]
    assert {record["stage"] for record in records} == {"scene_1", "scene_2", "scene_3"}
    summary = json.loads((tmp_path / "timing_summary.json").read_text())
    assert summary["reported_cost_usd"] == pytest.approx(0.03) and summary["cost_is_complete"]


def test_content_defect_stops_before_any_artwork_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import transform
    from adapt.llm_judge import JudgeVerdict
    from skill.schema import LiteracySkillModel, SourceItem

    current = context(tmp_path, count=1)
    assert isinstance(current.adapted, AdaptedActivityModel)
    worksheet = current.adapted
    worksheet.chunks[0].items[0] = ActivityItem(
        item_id=1,
        content="Choose cat",
        response_format="circle",
        options=["cat", "dog"],
        answer="fish",
    )
    skill = LiteracySkillModel(
        grade_level="2",
        domain="phonics",
        specific_skill="cvc",
        learning_objectives=["Read CVC words"],
        target_words=["cat"],
        response_types=["circle"],
        source_items=[SourceItem(item_type="word_list", content="cat", source_region_index=0)],
        extraction_confidence=1,
        template_type="unknown",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setattr(transform, "adapt_lesson", lambda *args, **kwargs: [worksheet])
    monkeypatch.setattr(
        "adapt.llm_judge.judge_adaptation",
        lambda *args: JudgeVerdict(
            approved=True,
            overall_score=0.95,
            concept_alignment=0.95,
            content_coverage=1,
            lesson_flow=0.95,
            adhd_compliance=0.95,
            feedback=[],
            rationale="Canned erroneous approval",
        ),
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("content defect spent artwork budget")

    monkeypatch.setattr("render.live_scene.generate_scene", forbidden)
    with pytest.raises(transform.UnapprovedPackageError, match="Deterministic content"):
        transform._run_multi_worksheet_pipeline(
            skill_model=skill,
            profile=LearnerProfile(name="Test", grade_level="2"),
            theme=current.theme,
            theme_id="space",
            source_image_path="new.png",
            source_image_hash="new",
            extracted_text="cat",
            template_type="unknown",
            ocr_engine="test",
            region_count=1,
            output=tmp_path,
            artifacts=tmp_path,
            rag_prior_adaptations=None,
            rag_curriculum_references=None,
            render_mode="hybrid_shell",
        )
    report = json.loads((tmp_path / "validation_before_artwork.json").read_text())
    assert not report["passed"] and not report["blocking_gates"]["passed"]
