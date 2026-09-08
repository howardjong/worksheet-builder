"""System-wide contract tests for unambiguous worksheet instructions."""

from __future__ import annotations

from adapt.instruction_clarity import (
    canonical_instruction_texts,
    instruction_clarity_issues,
    instructions_are_clear,
)
from adapt.llm_adapt import ActivityPlan, LessonPlan, PlannedItem, WorksheetPlan, _translate_plan
from adapt.rules import build_rules
from adapt.schema import ActivityChunk, ActivityItem, Step
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Reader", grade_level="2")


def _non_ufli_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="2",
        domain="fluency",
        specific_skill="phrase_fluency",
        learning_objectives=["Read a word list smoothly"],
        target_words=["drift", "glide", "float"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="drift, glide, float",
                source_region_index=0,
            )
        ],
        extraction_confidence=1.0,
        template_type="teacher_created_word_list",
    )


def test_clarity_contract_flags_vague_action_and_reference() -> None:
    assert "attempt_without_action" in instruction_clarity_issues("Try the list three times.")
    assert "vague_reference" in instruction_clarity_issues("Read those words again.")
    assert "subjective_choice" in instruction_clarity_issues("Circle the right word.")
    assert "unnamed_ending" in instruction_clarity_issues("Add the ending.")


def test_roll_and_read_contract_names_action_object_and_repetition() -> None:
    chunk = ActivityChunk(
        chunk_id=1,
        micro_goal="Read three words smoothly",
        instructions=[Step(number=1, text="Try the list three times.")],
        items=[
            ActivityItem(
                item_id=1,
                content="drift",
                response_format="read_aloud",
                metadata={"display": "roll_and_read"},
            )
        ],
        response_format="read_aloud",
        time_estimate="About 1 minute",
    )

    assert canonical_instruction_texts(chunk) == [
        "Read every word aloud at a smooth pace.",
        "Read the entire list aloud three times.",
        "Point to each word while you read it.",
    ]


def test_provider_instructions_are_repaired_for_non_ufli_content() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Smooth reading",
                activities=[
                    ActivityPlan(
                        activity_type="read_aloud",
                        micro_goal="Read three words smoothly",
                        items=[
                            PlannedItem(content="drift", response_format="read_aloud"),
                            PlannedItem(content="glide", response_format="read_aloud"),
                            PlannedItem(content="float", response_format="read_aloud"),
                        ],
                        instructions=["Try the list three times."],
                        response_format="read_aloud",
                    )
                ],
            )
        ]
    )

    worksheets = _translate_plan(
        plan,
        _non_ufli_skill(),
        _profile(),
        "default",
        build_rules(_profile()),
    )

    chunk = worksheets[0].chunks[0]
    assert instructions_are_clear(chunk)
    assert [step.text for step in chunk.instructions] == [
        "Read every word aloud at a smooth pace.",
        "Read the entire list aloud three times.",
        "Point to each word while you read it.",
    ]


def test_clear_provider_instructions_are_preserved_and_renumbered() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Smooth reading",
                activities=[
                    ActivityPlan(
                        activity_type="read_aloud",
                        micro_goal="Read three words smoothly",
                        items=[PlannedItem(content="drift", response_format="read_aloud")],
                        instructions=["Read the entire list aloud three times."],
                        response_format="read_aloud",
                    )
                ],
            )
        ]
    )

    worksheets = _translate_plan(
        plan,
        _non_ufli_skill(),
        _profile(),
        "default",
        build_rules(_profile()),
    )

    assert [step.model_dump() for step in worksheets[0].chunks[0].instructions] == [
        {"number": 1, "text": "Read the entire list aloud three times."}
    ]
