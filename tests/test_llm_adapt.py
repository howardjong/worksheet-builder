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


def _suffix_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_ly",
        learning_objectives=["Add -ly to base words"],
        target_words=["quickly", "lightly", "deeply"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="quick → quickly",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _word_chain_plan(words: list[str], items: list[PlannedItem]) -> LessonPlan:
    return LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Word Builder",
                activities=[
                    ActivityPlan(
                        activity_type="word_chain",
                        micro_goal="Build new words",
                        words=words,
                        items=items,
                        instructions=["Read the word.", "Add the ending."],
                        response_format="write",
                    )
                ],
            )
        ]
    )


def test_suffix_word_chain_uses_mechanical_builder_even_with_items() -> None:
    """D48 RED (suffix): authored word_chain items today bypass the stamped
    deterministic parser, so no item can ever count as chain evidence."""
    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[
            PlannedItem(content="Make quick. Add -ly. Write the new word.", answer="quickly"),
        ],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    items = worksheets[0].chunks[0].items
    assert items, "word_chain activity must not vanish"
    assert all(i.metadata.get("display") == "chain_step" for i in items)
    # Deterministic suffix template, not the model's prose.
    assert items[0].content == "quick + -ly → ______"
    assert items[0].answer == "quickly"
    assert [i.answer for i in items] == ["quickly", "lightly", "deeply"]


def test_letter_word_chain_uses_mechanical_builder_even_with_items() -> None:
    """D48 RED (letter chain): same stamp bypass on non-suffix lessons."""
    plan = _word_chain_plan(
        words=["mule → mute"],
        items=[
            PlannedItem(
                content='Start with "mule". Change the "l" to "t". Write the new word.',
                answer="mute",
            ),
        ],
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    assert items, "word_chain activity must not vanish"
    assert all(i.metadata.get("display") == "chain_step" for i in items)
    assert items[0].answer == "mute"


def test_suffix_word_chain_words_parse_to_items() -> None:
    """D48 RED (WS1.2 parser parity): suffix-pair words currently parse to 0
    items — _build_items_from_activity only knows letter-substitution chains."""
    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    assert worksheets, "suffix chain worksheet must survive translation"
    items = worksheets[0].chunks[0].items
    assert [i.content for i in items] == [
        "quick + -ly → ______",
        "light + -ly → ______",
        "deep + -ly → ______",
    ]


def test_translated_suffix_chain_passes_manipulation_coverage() -> None:
    """D48 GREEN acceptance: translated stamped items satisfy the manipulation
    cell through the real evidence layer (spec exit criterion 1)."""
    from adapt.objective_ledger import ClassifiedSourceItem, ObjectiveCell, ObjectiveLedger
    from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage

    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    ledger = ObjectiveLedger(
        source_skill_hash="hash",
        lesson_number=101,
        corpus_status="matched",
        corpus_version="v1",
        corpus_lesson_id="ufli_101",
        primary_pattern=None,
        objectives=[
            ObjectiveCell(
                objective_id="obj_manipulation",
                objective_type="phoneme_grapheme_manipulation",
                display_name="Build and change words",
                concept="manipulation",
                target_pattern=None,
                importance="essential",
                required_forms=["word_chain", "chain_script"],
                min_practice_count=1,
                max_recommended_count=1,
                acceptable_response_formats=["word_chain"],
                sufficiency_rule="one coherent chain",
            )
        ],
        source_items=[
            ClassifiedSourceItem(
                source_item_id="src_chain",
                item_type="word_chain",
                content="quick → quickly",
                normalized_content="quick → quickly",
                coverage_class="required_form",
                required_form="word_chain",
                objective_ids=["obj_manipulation"],
                mandatory=True,
            )
        ],
    )
    evidence = build_evidence_index(worksheets, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip.required_forms_present is True
    assert manip.status == "pass"


def test_translate_drops_self_negating_worked_example() -> None:
    """A worked example that models a WRONG answer (e.g. "Write cate? No.")
    confuses the child and must never be printed."""
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Magic E",
                activities=[
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Change one letter",
                        words=["cute", "cake"],
                        instructions=["Change one letter to make a new word."],
                        worked_example="make cute. Change u to a. Write cate? No.",
                        response_format="write",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    assert worksheets[0].chunks[0].worked_example is None


def test_translate_keeps_valid_worked_example() -> None:
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Magic E",
                activities=[
                    ActivityPlan(
                        activity_type="fill_blank",
                        micro_goal="Complete each word",
                        items=[
                            PlannedItem(content="r__de"),
                            PlannedItem(content="h__me"),
                        ],
                        instructions=["Fill in the blank."],
                        worked_example="c__ke -> cake (the magic e!)",
                        response_format="fill_blank",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    worked = worksheets[0].chunks[0].worked_example
    assert worked is not None
    assert worked.content == "c__ke -> cake (the magic e!)"


def test_translate_plan_gives_every_worksheet_a_feedback_panel() -> None:
    """Every sheet in the package gets a feedback panel (child strip + parent
    log), not just the last one — show_decision_hint is what's last-sheet-only,
    and section_cap recomputes that flag separately."""
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title=f"Sheet {n}",
                activities=[
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write words",
                        items=[PlannedItem(content="cake")],
                        instructions=["Write the word."],
                        response_format="write",
                    )
                ],
            )
            for n in range(1, 4)
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    assert len(worksheets) == 3
    assert all(ws.feedback is not None for ws in worksheets)


def test_planned_item_parses_covered_source_item_ids() -> None:
    item = PlannedItem.model_validate(
        {"content": "cake", "covered_source_item_ids": ["word_001", "chain_001_step_2"]}
    )
    assert item.covered_source_item_ids == ["word_001", "chain_001_step_2"]


def test_planned_item_defaults_covered_ids_to_empty() -> None:
    item = PlannedItem(content="cake")
    assert item.covered_source_item_ids == []
