"""Tests for transform/engine wiring of the planner-v2 path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from transform import _skip_ai_review


def test_skip_ai_review_for_planner_v2_output() -> None:
    assert _skip_ai_review({"planner_version": 2, "approved": True}) is True


def test_review_does_not_edit_any_approved_package() -> None:
    assert _skip_ai_review({"approved": True}) is True
    assert _skip_ai_review({"enabled": False}) is False
    assert _skip_ai_review({"planner_version": 2, "approved": False}) is False


def test_engine_routes_to_planner_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import engine
    from adapt.llm_adapt import ActivityPlan, LessonPlan, WorksheetPlan, _translate_plan
    from adapt.rules import build_rules
    from companion.schema import Accommodations, LearnerProfile
    from skill.schema import LiteracySkillModel, SourceItem

    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc",
        learning_objectives=["Read CVC words"],
        target_words=["cat"],
        response_types=["write"],
        source_items=[SourceItem(item_type="word_list", content="cat", source_region_index=0)],
        extraction_confidence=0.9,
        template_type="ufli_word_work",
    )
    profile = LearnerProfile(name="t", grade_level="1", accommodations=Accommodations())
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="CVC",
                activities=[
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write CVC words",
                        words=["cat"],
                        instructions=["Write the word."],
                        response_format="write",
                    )
                ],
            )
        ]
    )
    canned = _translate_plan(plan, skill, profile, "default", build_rules(profile))

    monkeypatch.setenv("WORKSHEET_PLANNER_V2", "1")
    called: list[str] = []

    def _fake_planner(*args: object, **kwargs: object) -> list[object]:
        called.append("planner")
        return list(canned)

    monkeypatch.setattr("adapt.llm_planner.plan_lesson_llm", _fake_planner)

    result = engine.adapt_lesson(skill, profile)

    assert called == ["planner"]
    assert result[0].chunks[0].items[0].content == "cat"


def test_chunk_assets_skipped_for_image_gen() -> None:
    from transform import _should_generate_chunk_assets

    assert _should_generate_chunk_assets("pdf_classic") is True
    assert _should_generate_chunk_assets("image_prompt") is True
    assert _should_generate_chunk_assets("image_gen") is False


def test_objective_planner_approval_reaches_artwork_and_frozen_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the real planner writer -> transform reader -> scene/PDF boundary."""
    import transform
    from adapt import llm_planner
    from adapt.approval import package_hash
    from adapt.llm_judge import ObjectiveJudgeVerdict
    from render.replay import FrozenRenderPackage
    from tests.test_live_composition import mock_images
    from tests.test_llm_planner import (
        _PLAN_JSON,
        _coverage,
        _gates,
        _obj_verdict,
        _objective_env,
        _profile,
        _skill,
        _tiny_ledger,
    )
    from theme.engine import load_theme

    _objective_env(monkeypatch)
    monkeypatch.setenv("WORKSHEET_PLANNER_V2", "1")
    monkeypatch.setattr(llm_planner, "build_objective_ledger", lambda s: _tiny_ledger())
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "mock-planner"))
    monkeypatch.setattr(llm_planner, "run_blocking_gates", lambda w, ld: _gates(True))
    monkeypatch.setattr(
        llm_planner, "evaluate_objective_coverage", lambda ld, e, w: _coverage("pass")
    )
    judged_hashes: list[str] = []

    def judge(*args: object) -> list[ObjectiveJudgeVerdict]:
        from adapt.schema import AdaptedActivityModel

        worksheets = args[3]
        assert isinstance(worksheets, list)
        assert all(isinstance(ws, AdaptedActivityModel) for ws in worksheets)
        judged_hashes.append(package_hash(worksheets))
        return [_obj_verdict(0.83)]

    monkeypatch.setattr(llm_planner, "judge_objective_adaptation_samples", judge)
    # Controlled coverage is unrelated to the writer/reader handshake under test.
    monkeypatch.setattr(transform, "_validate_package_objective_coverage", lambda *args: True)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("an approved planner package must not be re-judged or edited")

    monkeypatch.setattr("adapt.llm_judge.judge_package_objective", forbidden)
    monkeypatch.setattr(transform, "review_adapted_worksheet", forbidden)
    calls = mock_images(monkeypatch)
    result = transform._run_multi_worksheet_pipeline(
        skill_model=_skill(),
        profile=_profile(),
        theme=load_theme("space"),
        theme_id="space",
        source_image_path="ufli_lesson:100",
        source_image_hash="mock-source",
        extracted_text="",
        template_type="ufli_word_work",
        ocr_engine="none",
        region_count=0,
        output=tmp_path,
        artifacts=tmp_path,
        rag_prior_adaptations=None,
        rag_curriculum_references=None,
        render_mode="hybrid_shell",
    )
    assert calls == ["first"]
    assert len(result.pdf_paths) == 1 and Path(result.pdf_paths[0]).is_file()
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["approved"] is True and verdict["approval_decision"] == "approve"
    frozen = FrozenRenderPackage.model_validate_json(
        (tmp_path / "frozen_render_package.json").read_text()
    )
    frozen.verify()
    assert judged_hashes == [frozen.package_hash]
    assert frozen.coverage_mode == "lesson_objective"
    assert result.validation_results["approval_matches_delivery"] is True


@pytest.mark.parametrize(
    "payload,bind_hash",
    [
        ({"approval_recommendation": "approve"}, True),
        ({"approved": None, "approval_recommendation": "approve"}, True),
        ({"approved": False, "approval_recommendation": "approve"}, True),
        ({"approved": "true"}, True),
        ({"approved": True}, False),
    ],
)
def test_live_artwork_rejects_unknown_or_unbound_approval_without_paid_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, object],
    bind_hash: bool,
) -> None:
    import transform
    from adapt.approval import package_hash
    from adapt.schema import AdaptedActivityModel
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel, SourceItem
    from tests.test_live_composition import context

    current = context(tmp_path, count=2)
    assert isinstance(current.adapted, AdaptedActivityModel)
    worksheet = current.adapted
    record = {**payload, "planner_version": 2, "overall_score": 0.83}
    if bind_hash:
        record["package_hash"] = package_hash([worksheet])

    def adapt(*args: object, **kwargs: object) -> list[AdaptedActivityModel]:
        (tmp_path / "judge_verdict.json").write_text(json.dumps(record))
        return [worksheet]

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid approval must stop before re-judging, review or artwork")

    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setattr(transform, "adapt_lesson", adapt)
    monkeypatch.setattr("adapt.llm_judge.judge_adaptation", forbidden)
    monkeypatch.setattr("adapt.llm_judge.judge_package_objective", forbidden)
    monkeypatch.setattr(transform, "review_adapted_worksheet", forbidden)
    monkeypatch.setattr("render.live_scene.generate_scene", forbidden)
    skill = LiteracySkillModel(
        grade_level="2",
        domain="phonics",
        specific_skill="cvc",
        learning_objectives=["Read and write CVC words"],
        target_words=["cat"],
        response_types=["write"],
        source_items=[SourceItem(item_type="word_list", content="cat", source_region_index=0)],
        extraction_confidence=1,
        template_type="unknown",
    )
    with pytest.raises(transform.UnapprovedPackageError, match="affirmative package approval"):
        transform._run_multi_worksheet_pipeline(
            skill_model=skill,
            profile=LearnerProfile(name="Anonymous", grade_level="2"),
            theme=current.theme,
            theme_id="space",
            source_image_path="source.png",
            source_image_hash="source",
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
    saved = AdaptedActivityModel.model_validate_json(
        (tmp_path / "adapted_model_1.json").read_text()
    )
    assert package_hash([saved]) == package_hash([worksheet])
    assert not (tmp_path / "frozen_render_package.json").exists()
