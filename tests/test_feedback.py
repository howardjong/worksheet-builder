"""FeedbackPanel builders and placement (spec 2026-07-10)."""

from __future__ import annotations

from adapt.feedback import DECISION_HINT, build_feedback_panel, learning_goal_statement
from adapt.rules import AccommodationRules, build_rules
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
from adapt.section_cap import enforce_package_cap, enforce_section_cap
from companion.schema import Accommodations, LearnerProfile


def _rules(grade: str = "1") -> AccommodationRules:
    profile = LearnerProfile(name="t", grade_level=grade, accommodations=Accommodations())
    return build_rules(profile)


def _chunk(chunk_id: int) -> ActivityChunk:
    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal=f"Goal {chunk_id}",
        instructions=[Step(number=1, text="Do the task.")],
        items=[
            ActivityItem(
                item_id=chunk_id * 10,
                content=f"word{chunk_id}",
                response_format="write",
            )
        ],
        response_format="write",
        time_estimate="About 2 minutes",
    )


def _worksheet(
    chunk_count: int,
    *,
    number: int = 1,
    count: int = 1,
    title: str | None = "Word Work",
    break_prompt: str | None = None,
    feedback: FeedbackPanel | None = None,
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvc",
        chunks=[_chunk(i + 1) for i in range(chunk_count)],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=number,
        worksheet_count=count,
        worksheet_title=title,
        break_prompt=break_prompt,
        feedback=feedback,
    )


def _feedback(ws: AdaptedActivityModel) -> FeedbackPanel:
    assert ws.feedback is not None
    return ws.feedback


def test_goal_statement_per_domain() -> None:
    assert learning_goal_statement("phonics", "y") == "I can read words with the y pattern"
    assert learning_goal_statement("fluency", "y") == "I can read the story smoothly"
    assert learning_goal_statement("sight_words", "the") == "I can practice sight words skills"


def test_build_feedback_panel_defaults() -> None:
    panel = build_feedback_panel("phonics", "a_e")
    assert panel.goal_statement == "I can read words with the a_e pattern"
    assert panel.child_prompt == "How did it go? Circle one for each part."
    assert panel.parent_log_title == "Grown-up quick log"
    assert panel.show_decision_hint is False
    assert "move on" in DECISION_HINT


def test_section_cap_keeps_feedback_on_every_part_hint_on_last() -> None:
    # Build a worksheet with feedback and more chunks than the cap so it splits
    # (reuse the worksheet-construction helper pattern from tests/test_section_cap.py).
    panel = build_feedback_panel("phonics", "cvc")
    rules = _rules("1")
    ws = _worksheet(9, feedback=panel)
    parts = enforce_section_cap([ws], rules)
    assert all(p.feedback is not None for p in parts)
    assert [_feedback(p).show_decision_hint for p in parts] == [False] * (len(parts) - 1) + [True]


def test_package_cap_backfills_feedback_and_hint() -> None:
    # Three worksheets with feedback=None, cap to 2, fallback provided.
    sheets = [
        _worksheet(2, number=1, count=3, title="Word Discovery"),
        _worksheet(2, number=2, count=3, title="Word Builder"),
        _worksheet(2, number=3, count=3, title="Story Time"),
    ]
    capped = enforce_package_cap(sheets, 2, fallback_feedback=build_feedback_panel("phonics", "y"))
    assert len(capped) == 2
    assert all(w.feedback is not None for w in capped)
    assert [_feedback(w).show_decision_hint for w in capped] == [False, True]
