"""Skill contract registry: per-suffix-family correctness facts as data."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from skill.contract import SUFFIX_CONTRACTS, contract_for_skill, known_suffix_tokens

if TYPE_CHECKING:
    from companion.schema import LearnerProfile
    from skill.schema import LiteracySkillModel

CORPUS = Path("data/ufli/normalized.jsonl")

# Exact strings currently hardcoded in adapt/objective_ledger.py:809-815.
SINGLE_HOP_RULE = (
    "≥2 add-the-ending transformations (base + suffix → new word); this "
    "suffix forms no multi-step chain, so independent pairs ARE this "
    "lesson's manipulation form"
)
MULTI_HOP_RULE = "≥1 coherent build/change chain (count steps, not words)"


def test_registry_covers_exactly_the_current_morphology_tokens() -> None:
    # Byte-identity bar for the migration: same token universe as
    # skill/taxonomy.py MORPHOLOGY_SUFFIXES before this branch.
    assert known_suffix_tokens() == frozenset(
        {
            "s",
            "es",
            "er",
            "est",
            "ed",
            "ly",
            "less",
            "ful",
            "ness",
            "or",
            "ist",
            "ish",
            "y",
            "ment",
            "able",
            "ible",
        }
    )


def test_er_est_contract_carries_the_bespoke_goal_text() -> None:
    contract = contract_for_skill("suffix_er_est")
    assert contract is not None
    assert contract.goal_statement == "I can add -er and -est to compare things"
    assert contract.skill_slug == "suffix_er_est"


def test_ly_contract_matches_current_generic_goal_text() -> None:
    contract = contract_for_skill("suffix_ly")
    assert contract is not None
    assert contract.goal_statement == "I can add -ly to words"


def test_all_contracts_carry_current_manipulation_wording() -> None:
    for contract in SUFFIX_CONTRACTS:
        assert contract.manipulation_rule_single_hop == SINGLE_HOP_RULE
        assert contract.manipulation_rule_multi_hop == MULTI_HOP_RULE


def test_unknown_and_non_suffix_slugs_return_none() -> None:
    assert contract_for_skill("suffix_zzz") is None  # registered slug universe only
    assert contract_for_skill("cvc_blending") is None


def test_token_order_does_not_matter_for_lookup() -> None:
    assert contract_for_skill("suffix_est_er") is contract_for_skill("suffix_er_est")


def test_no_two_contracts_share_a_token_set() -> None:
    # Registry lint: duplicate token-sets would make contract_for_skill
    # order-of-registration dependent — a silent authoring hazard.
    seen = [frozenset(c.suffixes) for c in SUFFIX_CONTRACTS]
    assert len(seen) == len(set(seen))


def test_taxonomy_token_set_is_derived_from_the_registry() -> None:
    from skill.taxonomy import MORPHOLOGY_SUFFIXES

    assert MORPHOLOGY_SUFFIXES == known_suffix_tokens()
    assert MORPHOLOGY_SUFFIXES is not known_suffix_tokens()  # derived, not aliased per-call


def test_goal_statement_comes_from_contract_when_registered() -> None:
    from adapt.feedback import learning_goal_statement

    # Both must match the contract entries verbatim (byte-identity bar).
    assert (
        learning_goal_statement("phonics", "suffix_er_est")
        == "I can add -er and -est to compare things"
    )
    assert learning_goal_statement("phonics", "suffix_ly") == "I can add -ly to words"


def test_goal_statement_falls_back_for_unregistered_suffix_slugs() -> None:
    from adapt.feedback import learning_goal_statement

    # A combined slug with no contract keeps the generic joiner behavior.
    assert learning_goal_statement("phonics", "suffix_ed_es") == "I can add -ed and -es to words"


def test_manipulation_cell_wording_comes_from_contract() -> None:
    # tests/objective_corpus_fixture.py is a corpus-lookup helper, not a
    # LiteracySkillModel builder, so build the skill the way
    # tests/test_objective_ledger.py::_chain_skill does (construction copied
    # verbatim) and read the manipulation cell back out of the built ledger.
    from adapt.objective_ledger import build_objective_ledger
    from skill.contract import contract_for_skill
    from skill.schema import LiteracySkillModel, SourceItem

    skill_model = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_ly",
        learning_objectives=["objective"],
        target_words=["quickly"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_chain", content=c, source_region_index=i)
            for i, c in enumerate(["quick → quickly", "light → lightly", "deep → deeply"])
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )
    ledger = build_objective_ledger(skill_model, corpus_lookup=lambda n: None)
    cell = next(c for c in ledger.objectives if c.objective_id == "obj_manipulation")
    contract = contract_for_skill("suffix_ly")
    assert contract is not None
    assert cell.sufficiency_rule == contract.manipulation_rule_single_hop


# --- Task 5: new suffix families as contract data only (H1a red -> green) ---


def test_less_ful_classifies_as_a_suffix_lesson() -> None:
    # Live-verified 2026-07-17: returns None on main — lesson 102 falls
    # through to grapheme classification (the D13/D48/D49 defect class).
    from skill.taxonomy import match_morphology_pattern

    assert match_morphology_pattern("-less, -ful") == "suffix_less_ful"


def test_ness_classifies_as_a_suffix_lesson() -> None:
    from skill.taxonomy import match_morphology_pattern

    assert match_morphology_pattern("-ness") == "suffix_ness"


def test_new_families_get_goal_text_and_manipulation_wording() -> None:
    from adapt.feedback import learning_goal_statement

    assert (
        learning_goal_statement("phonics", "suffix_less_ful") == "I can add -less and -ful to words"
    )
    assert learning_goal_statement("phonics", "suffix_ness") == "I can add -ness to words"
    assert contract_for_skill("suffix_less_ful") is not None
    assert contract_for_skill("suffix_ness") is not None


@pytest.mark.skipif(not CORPUS.exists(), reason="UFLI corpus is local-only (gitignored)")
def test_corpus_classification_delta_is_exactly_lessons_102_and_124() -> None:
    """Sweep all corpus concepts: adding the new tokens must reclassify ONLY
    lessons 102 and 124 — any other delta is an unintended veto change."""
    import json

    from skill.taxonomy import match_morphology_pattern

    reclassified: dict[str, str | None] = {}
    with CORPUS.open() as f:
        for line in f:
            record = json.loads(line)
            concept = record.get("concept") or ""
            result = match_morphology_pattern(concept)
            if result in ("suffix_less_ful", "suffix_ness"):
                reclassified[str(record.get("lesson_id"))] = result
    assert reclassified == {"102": "suffix_less_ful", "124": "suffix_ness"}


@pytest.mark.skipif(not CORPUS.exists(), reason="UFLI corpus is local-only (gitignored)")
def test_lesson_102_adapts_end_to_end_offline() -> None:
    """The deterministic engine must produce a package for the newly-classified
    lesson without exceptions, with add-the-ending manipulation items present."""
    import re

    from adapt.engine import adapt_lesson
    from companion.schema import Accommodations, LearnerProfile
    from skill.lesson_loader import skill_model_from_lesson

    skill_model = skill_model_from_lesson(102)
    assert skill_model.specific_skill == "suffix_less_ful"

    profile = LearnerProfile(
        name="Test G1",
        grade_level="1",
        accommodations=Accommodations(
            chunking_level="medium",
            response_format_prefs=["write", "circle"],
        ),
    )
    worksheets = adapt_lesson(skill_model, profile)
    assert worksheets, "lesson 102 must adapt to at least one worksheet"

    add_the_ending = re.compile(r"\+\s*-(less|ful)\s*→")
    chain_items = [
        item.content
        for ws in worksheets
        for chunk in ws.chunks
        for item in chunk.items
        if add_the_ending.search(item.content or "")
    ]
    assert chain_items, "at least one add-the-ending chain item must be present"


def _profile_for_planner_path() -> "LearnerProfile":
    from companion.schema import Accommodations, LearnerProfile

    return LearnerProfile(name="t", grade_level="1", accommodations=Accommodations())


def _less_ful_skill() -> "LiteracySkillModel":
    from skill.schema import LiteracySkillModel, SourceItem

    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_less_ful",
        learning_objectives=["Add -less and -ful to base words"],
        target_words=["painless", "painful", "harmless", "harmful"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="pain → painless → painful",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def test_planner_path_translates_a_less_ful_word_chain() -> None:
    """Planner-path guard (D48 generalization): a word_chain activity for
    suffix_less_ful must translate to deterministic add-the-ending items the
    same way suffix_ly does. Modeled on
    tests/test_llm_adapt.py::test_suffix_word_chain_words_parse_to_items."""
    from adapt.llm_adapt import (
        ActivityPlan,
        LessonPlan,
        WorksheetPlan,
        _translate_plan,
    )
    from adapt.rules import build_rules

    profile = _profile_for_planner_path()
    plan = LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Word Builder",
                activities=[
                    ActivityPlan(
                        activity_type="word_chain",
                        micro_goal="Build new words",
                        words=[
                            "pain → painless → painful",
                            "harm → harmless → harmful",
                        ],
                        items=[],
                        instructions=["Read the word.", "Add the ending."],
                        response_format="write",
                    )
                ],
            )
        ]
    )
    worksheets = _translate_plan(plan, _less_ful_skill(), profile, "default", build_rules(profile))

    assert worksheets, "suffix chain worksheet must survive translation"
    items = worksheets[0].chunks[0].items
    assert [i.content for i in items] == [
        "pain + -less → ______",
        "pain + -ful → ______",
        "harm + -less → ______",
        "harm + -ful → ______",
    ]
    assert all(i.metadata.get("display") == "chain_step" for i in items)
