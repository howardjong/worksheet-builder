"""Tests for transform/engine wiring of the planner-v2 path."""

from __future__ import annotations

import pytest

from transform import _skip_ai_review


def test_skip_ai_review_for_planner_v2_output() -> None:
    assert _skip_ai_review({"planner_version": 2, "approved": True}) is True


def test_run_ai_review_for_legacy_and_deterministic_output() -> None:
    assert _skip_ai_review({"approved": True}) is False
    assert _skip_ai_review({"enabled": False}) is False


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
