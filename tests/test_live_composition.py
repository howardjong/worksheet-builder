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
        action_ok=True,
        outfit_ok=True,
        child_safe=True,
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
    report = json.loads((tmp_path / "learning_scene.json").read_text())
    assert all(not attempt["selected"] for attempt in report["attempts"])
    assert all((tmp_path / attempt["image_path"]).is_file() for attempt in report["attempts"])
    assert report["action_contract"]["kind"] == "write"


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
    monkeypatch.setenv("WORKSHEET_SCENE_GATE_BACKEND", "vision")
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
    current = context(tmp_path, grade, count=24)
    result = resolve_render_strategy("hybrid_shell").render(current)
    assert result.artwork_approved is True
    assert result.effective_activity == current.adapted
    assert validate_print_quality(str(current.output_path)).passed
    with fitz.open(current.output_path) as pdf:
        assert len(pdf) >= 2  # deliberately exercise pagination
        for index, page in enumerate(pdf):
            text = page.get_text()
            assert "cat " in text and "Test Learner" in text
            assert len(page.get_images()) == (1 if index == 0 else 0)
            for span in (
                span
                for block in page.get_text("dict")["blocks"]
                if "lines" in block
                for line in block["lines"]
                for span in line["spans"]
            ):
                assert span["size"] >= 10  # no invisible expected-text layer
        assert "Right: ___ of 24" in pdf[-1].get_text()
    layout = json.loads((tmp_path / "layout_report.json").read_text())
    assert layout["physical_pages"] == len(layout["practice_pages"])
    assert layout["artwork_pages"] == [1] and layout["artwork_section"] == 1
    assert layout["child_body_font_pt"] >= layout["child_min_font_pt"]
    assert 150 < layout["artwork_effective_ppi"] < 300


def test_artwork_fallback_does_not_claim_visual_approval(tmp_path: Path) -> None:
    result = resolve_render_strategy("hybrid_shell").render(context(tmp_path, count=2))
    assert result.pdf_path and result.artwork_approved is False


@pytest.mark.parametrize("grade,format", [("1", "write"), ("2", "write"), ("2", "trace")])
def test_visible_numbers_restart_at_one_without_changing_approved_item_ids(
    tmp_path: Path, grade: str, format: str
) -> None:
    from adapt.approval import package_hash

    current = context(tmp_path, grade=grade, count=5)
    assert isinstance(current.adapted, AdaptedActivityModel)
    words = ["higher", "lower", "older", "newer", "taller"]
    chunk = current.adapted.chunks[0]
    chunk.response_format = format
    chunk.items = [
        ActivityItem(item_id=number + 1, content=word, response_format=format)
        for number, word in enumerate(words, 1)
    ]
    original = package_hash([current.adapted])
    resolve_render_strategy("hybrid_shell").render(current)
    assert package_hash([current.adapted]) == original
    with fitz.open(current.output_path) as pdf:
        text = " ".join(page.get_text() for page in pdf)
    for number, word in enumerate(words, 1):
        assert f"{number}. {word}" in text
    assert "6. taller" not in text
    report = json.loads((tmp_path / "layout_report.json").read_text())
    assert [row["item_id"] for row in report["display_numbering"]] == [2, 3, 4, 5, 6]
    assert [row["display_number"] for row in report["display_numbering"]] == [1, 2, 3, 4, 5]


def test_caregiver_scores_each_section_and_never_counts_a_passage_as_one_word(
    tmp_path: Path,
) -> None:
    current = context(tmp_path, count=7)
    assert isinstance(current.adapted, AdaptedActivityModel)
    written = current.adapted.chunks[0]
    read = written.model_copy(deep=True)
    read.chunk_id = 10  # semantic identifiers need not be sequential
    read.micro_goal = "Read 5 words"
    read.response_format = "read_aloud"
    read.instructions = [Step(number=1, text="Read each word aloud.")]
    read.items = [
        ActivityItem(item_id=i * 10, content=word, response_format="read_aloud")
        for i, word in enumerate(["cat", "dog", "bag", "map", "jam"], 1)
    ]
    passage = read.model_copy(deep=True)
    passage.micro_goal = "Read the story"
    passage.items = [
        ActivityItem(
            item_id=1,
            content="The taller cat sat near the smaller dog.",
            response_format="read_aloud",
        )
    ]
    current.adapted.chunks = [read, written, passage]
    resolve_render_strategy("hybrid_shell").render(current)
    with fitz.open(current.output_path) as pdf:
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    assert "Section 1: Read correctly: ___ of 5 words" in text
    assert "Section 2: Right: ___ of 7 tasks" in text
    assert "Section 3: Reading: smooth / choppy" in text
    assert "Section 3: Right:" not in text
    report = json.loads((tmp_path / "layout_report.json").read_text())
    assert report["caregiver_rows"] == [
        "Section 1: Read correctly: ___ of 5 words",
        "Section 2: Right: ___ of 7 tasks",
        "Section 3: Reading: smooth / choppy",
        "Help: none / some / lots",
    ]


@pytest.mark.parametrize(
    "failed",
    [
        None,
        "identity_ok",
        "supports_task",
        "action_ok",
        "outfit_ok",
        "child_safe",
        "no_text",
        "no_answers",
        "meaningful_area",
    ],
)
def test_luna_batches_all_scene_checks_and_fails_closed_on_uncertainty(
    monkeypatch: pytest.MonkeyPatch, failed: str | None
) -> None:
    calls: list[str] = []

    def decide(state: str, questions: dict[str, str], **kwargs: Any) -> dict[str, float]:
        calls.append(str(kwargs["model"]))
        assert "Required action:" in state and "Costume:" in state
        assert len(kwargs["images"]) == 2
        assert set(questions) == {
            "identity_ok",
            "supports_task",
            "action_ok",
            "outfit_ok",
            "child_safe",
            "no_text",
            "no_answers",
            "meaningful_area",
        }
        return {name: 0.94 if name == failed else 0.99 for name in questions}

    monkeypatch.setattr("ai.openrouter.decide_yes_no", decide)
    monkeypatch.setattr(
        "ai.openrouter.complete_json", lambda *a, **k: pytest.fail("legacy fallback")
    )
    current = context(Path("unused"))
    gate = judge_scene(synthetic_image(), synthetic_image(), current.design_spec)
    assert gate is not None and gate.approved is (failed is None)
    assert calls == ["openai/gpt-6-luna-decisions"]
    assert gate.probabilities
    assert judge_scene(synthetic_image(), None, current.design_spec) is None
    assert len(calls) == 1  # absent reference cannot spend or approve


def test_scene_gate_refuses_string_booleans_and_missing_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_SCENE_GATE_BACKEND", "vision")

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
        assert any(page.get_images() for page in pdf)
        assert any(not page.get_images() for page in pdf)  # no repeated continuation artwork
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


@pytest.mark.parametrize("failed_check", ["action_ok", "outfit_ok", "child_safe"])
def test_a_near_miss_scene_never_passes_a_mandatory_check(failed_check: str) -> None:
    assert not approved_gate().model_copy(update={failed_check: False}).approved


def test_action_contract_follows_the_task_and_is_shared_by_artist_and_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_SCENE_GATE_BACKEND", "vision")
    from render.live_scene import scene_action, scene_prompt

    current = context(tmp_path, count=2)
    from theme.schema import ThemeConfig

    assert isinstance(current.theme, ThemeConfig)
    current.design_spec.specific_skill = "suffix_er_est"
    action = scene_action(current.design_spec, current.theme)
    assert action.kind == "write"  # comparison lesson must still model this writing task
    prompt = scene_prompt(current.design_spec, current.theme, None)
    assert action.action in prompt and action.props in prompt
    assert current.design_spec.learner_name not in prompt

    def gate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert action.action in args[0] and action.costume in args[0]
        return approved_gate().model_dump()

    monkeypatch.setattr("ai.openrouter.complete_json", gate)
    verdict = judge_scene(synthetic_image(), synthetic_image(), current.design_spec, current.theme)
    assert verdict and verdict.approved


def test_uncertain_photo_stops_before_planning_or_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import transform
    from extract.schema import SourceRegion, SourceWorksheetModel

    photo = tmp_path / "photo.png"
    Image.new("RGB", (1000, 1300), "white").save(photo)
    source = SourceWorksheetModel(
        source_image_hash="test",
        pipeline_version="test",
        template_type="unknown",
        regions=[
            SourceRegion(
                type="word_list",
                content="[unreadable]",
                bbox=(0, 0, 1, 1),
                confidence=0.2,
                metadata={},
            )
        ],
        raw_text="[unreadable]",
        ocr_engine="test",
        low_confidence_flags=[],
    )
    monkeypatch.setattr(transform, "extract_with_vision", lambda *args: source)
    monkeypatch.setattr(
        transform,
        "_run_from_skill_model",
        lambda *args, **kwargs: pytest.fail("planned uncertain photo"),
    )
    with pytest.raises(transform.UnapprovedPackageError, match="Photo extraction"):
        transform.run_pipeline_collect_artifacts(
            str(photo),
            "unused-profile",
            "space",
            str(tmp_path / "out"),
            str(tmp_path / "art"),
            index_results=False,
            render_mode="hybrid_shell",
        )
    assert not json.loads((tmp_path / "art/validation_photo_intake.json").read_text())["passed"]


@pytest.mark.parametrize(
    "goal,format,content,kind,props",
    [
        ("Read 5 words", "read_aloud", "higher", "read", "word cards"),
        ("Read the story", "read_aloud", "The cat is taller than the dog.", "read", "book"),
        ("Write 5 words", "write", "higher", "write", "practice paper"),
        ("Build 7 words", "write", "tall + -er", "build", "word-part tiles"),
        ("Choose a word", "circle", "tall", "choose", "choice cards"),
    ],
)
def test_suffix_scenes_model_different_learner_procedures(
    tmp_path: Path, goal: str, format: str, content: str, kind: str, props: str
) -> None:
    from render.live_scene import scene_action, scene_prompt
    from theme.schema import ThemeConfig

    current = context(tmp_path, count=1)
    current.design_spec.specific_skill = "suffix_er_est"
    section = current.design_spec.sections[0]
    section.micro_goal = goal
    section.items[0].response_format = format
    section.items[0].content = content
    assert isinstance(current.theme, ThemeConfig)
    contract = scene_action(current.design_spec, current.theme)
    assert contract.kind == kind and props in contract.props
    prompt = scene_prompt(current.design_spec, current.theme, None)
    assert "Focus ONLY on section 1: " + goal in prompt
    assert contract.action in prompt


def test_illustration_is_placed_once_beside_its_declared_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from render.composed_pdf import render_composed_pdf
    from theme.schema import ThemeConfig

    mock_images(monkeypatch)
    current = context(tmp_path, count=20)
    assert isinstance(current.adapted, AdaptedActivityModel)
    assert isinstance(current.theme, ThemeConfig)
    second = current.adapted.chunks[0].model_copy(deep=True)
    second.chunk_id = 2
    second.micro_goal = "Build 20 words"
    current.adapted.chunks.append(second)
    current = replace(
        current,
        design_spec=compile_worksheet_design_spec(
            current.adapted,
            current.theme,
            LearnerProfile(name="Test Learner", grade_level="2"),
            render_mode="hybrid_shell",
        ),
    )
    assert isinstance(current.adapted, AdaptedActivityModel)
    assert isinstance(current.theme, ThemeConfig)
    scene = generate_scene(current)
    assert scene
    render_composed_pdf(
        current.adapted, current.theme, current.output_path, tmp_path, scene, "Test Learner"
    )
    report = json.loads((tmp_path / "layout_report.json").read_text())
    assert report["artwork_section"] == 2 and len(report["artwork_pages"]) == 1
    with fitz.open(current.output_path) as pdf:
        assert sum(len(page.get_images()) for page in pdf) == 1
        page = pdf[report["artwork_pages"][0] - 1]
        assert "Section 2: Build 20 words" in page.get_text()
