"""Tests for adapt/llm_adapt.py — widened plan schema and authored-item translation."""

from __future__ import annotations

import json

from adapt.llm_adapt import (
    ActivityPlan,
    LessonPlan,
    PlannedItem,
    WorksheetPlan,
    _parse_lesson_plan,
    _translate_plan,
)
from adapt.rules import build_rules
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="cake, ride, home",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="t", grade_level="1", accommodations=Accommodations())


def test_lesson_plan_parses_authored_items() -> None:
    payload = {
        "concept_focus": "CVCe magic-e",
        "pedagogical_rationale": "Practice the pattern",
        "worksheets": [
            {
                "title": "Magic E",
                "activities": [
                    {
                        "activity_type": "fill_blank",
                        "micro_goal": "Complete each CVCe word",
                        "items": [
                            {
                                "content": "The dog wants to r__de in the car.",
                                "response_format": "fill_blank",
                                "options": ["i", "o", "a"],
                                "answer": "i",
                            }
                        ],
                        "instructions": ["Fill in the missing letter."],
                        "worked_example": "c__ke -> cake (the magic e!)",
                        "response_format": "fill_blank",
                        "time_estimate_minutes": 2,
                        "rationale": "Targets the vowel in the CVCe unit",
                    }
                ],
            }
        ],
    }
    plan = _parse_lesson_plan(json.dumps(payload))

    assert plan is not None
    item = plan.worksheets[0].activities[0].items[0]
    assert item.content == "The dog wants to r__de in the car."
    assert item.options == ["i", "o", "a"]
    assert item.answer == "i"


def test_translate_prefers_authored_items() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Magic E",
                activities=[
                    ActivityPlan(
                        activity_type="fill_blank",
                        micro_goal="Complete each word",
                        items=[
                            PlannedItem(
                                content="r__de",
                                response_format="fill_blank",
                                options=["i", "o"],
                                answer="i",
                            ),
                            PlannedItem(content="h__me", answer="o"),
                        ],
                        words=["ignored"],
                        instructions=["Fill in the blank."],
                        response_format="fill_blank",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    assert [i.content for i in items] == ["r__de", "h__me"]
    assert items[0].options == ["i", "o"]
    assert items[0].answer == "i"
    # Unspecified per-item format inherits the activity format
    assert items[1].response_format == "fill_blank"


def test_translate_clamps_authored_items_to_chunk_cap() -> None:
    rules = build_rules(_profile())  # grade 1 medium -> 4 items max
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Too Many",
                activities=[
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write words",
                        items=[PlannedItem(content=f"word{i}") for i in range(10)],
                        instructions=["Write each word."],
                        response_format="write",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", rules)

    assert len(worksheets[0].chunks[0].items) == rules.max_items_per_chunk


def test_translate_degrades_to_template_expansion_without_items() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Plain",
                activities=[
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write words",
                        words=["cake", "ride"],
                        instructions=["Write each word."],
                        response_format="write",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    assert [i.content for i in worksheets[0].chunks[0].items] == ["cake", "ride"]


def test_match_activities_use_mechanical_builder_even_with_items() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Match",
                activities=[
                    ActivityPlan(
                        activity_type="match",
                        micro_goal="Match words to pictures",
                        items=[
                            PlannedItem(content="cake"),
                            PlannedItem(content="ride"),
                        ],
                        instructions=["Draw a line."],
                        response_format="match",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    # Mechanical builder ran: picture prompts + shuffled options contract intact
    assert all(i.picture_prompt for i in items)
    assert all(i.options for i in items)
