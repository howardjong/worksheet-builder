"""Drop-E spelling-rule contract and deterministic adaptation regressions."""

from __future__ import annotations

import pytest

from adapt.engine import (
    _build_builder_chunks,
    _build_discovery_chunks,
    adapt_lesson,
)
from adapt.feedback import learning_goal_statement
from adapt.objective_ledger import build_objective_ledger
from adapt.rules import AccommodationRules
from adapt.schema import AdaptedActivityModel, ScaffoldConfig
from skill.contract import DROP_E_RULE_MANIPULATION, DROP_E_RULE_SKILL, contract_for_skill_id
from skill.schema import LiteracySkillModel, SourceItem
from skill.taxonomy import match_phonics_pattern
from skill.transformation import analyze_chain
from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage

CHAINS = [
    "smile → smiled → smiling",
    "close → closed → closing",
    "cute → cuter → cutest",
    "brave → braver → bravest",
]


def _rules() -> AccommodationRules:
    return AccommodationRules(
        max_items_per_chunk=5,
        instruction_max_words=20,
        instruction_max_steps=3,
        allowed_response_formats=["write", "circle"],
        font_size_min=14,
        color_system={"primary": "#000000"},
        time_estimate_minutes=5,
    )


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="3",
        domain="phonics",
        specific_skill=DROP_E_RULE_SKILL,
        learning_objectives=["Drop final e before adding an ending"],
        target_words=["smiled", "smiling", "closed", "closing", "cuter", "cutest"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(item_type="word_chain", content=chain, source_region_index=i)
            for i, chain in enumerate(CHAINS)
        ],
        extraction_confidence=1.0,
        template_type="ufli_word_work",
        lesson_number=109,
    )


def test_drop_e_concept_has_its_own_skill_and_goal() -> None:
    assert match_phonics_pattern("Drop E Rule") == DROP_E_RULE_SKILL
    assert match_phonics_pattern("Drop -e Rule") == DROP_E_RULE_SKILL
    assert (
        learning_goal_statement("phonics", DROP_E_RULE_SKILL)
        == "I can drop final e before adding an ending"
    )


def test_parse_drop_e_chains_as_base_anchored_spelling_steps() -> None:
    contract = contract_for_skill_id(DROP_E_RULE_SKILL)
    assert contract is not None
    steps = analyze_chain(CHAINS[0], contract)
    assert [(step.from_word, step.to_word, step.ending) for step in steps] == [
        ("smile", "smiled", "ed"),
        ("smile", "smiling", "ing"),
    ]


def test_drop_e_builder_is_truthful_and_hides_answers() -> None:
    chunks = _build_builder_chunks(CHAINS, [], [], _skill(), _rules())
    chain_chunks = [
        chunk
        for chunk in chunks
        if any(item.metadata.get("spelling_rule") == DROP_E_RULE_SKILL for item in chunk.items)
    ]
    assert chain_chunks
    assert len(chain_chunks) == 1
    first = chain_chunks[0]
    assert first.worked_example is not None
    assert "drop the final e" in first.worked_example.content.lower()
    assert "one letter changes" not in first.worked_example.content.lower()
    assert [step.text for step in first.instructions] == [
        "Read the base word in each problem.",
        "Drop the final e in each base word.",
        "Add the printed ending; write each complete new word.",
    ]
    for chunk in chain_chunks:
        for item in chunk.items:
            assert "Drop the final e" in item.content
            assert item.answer
            assert item.answer not in item.content
            assert "______" in item.content
    assert {item.metadata.get("spelling_rule") for item in first.items} == {DROP_E_RULE_SKILL}
    assert {item.content.split("Add -", 1)[1].split(".", 1)[0] for item in first.items} == {
        "ed",
        "ing",
        "er",
        "est",
    }


def test_drop_e_contract_and_authored_steps_pass_manipulation_coverage() -> None:
    skill = _skill()
    ledger = build_objective_ledger(skill, corpus_lookup=lambda _n: None)
    manip = next(cell for cell in ledger.objectives if cell.objective_id == "obj_manipulation")
    assert manip.sufficiency_rule == DROP_E_RULE_MANIPULATION
    assert manip.display_name == "Apply drop final e and add the ending"

    worksheet = AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="3",
        domain="phonics",
        specific_skill=DROP_E_RULE_SKILL,
        chunks=_build_builder_chunks(CHAINS, [], [], skill, _rules()),
        scaffolding=ScaffoldConfig(),
        theme_id="geometry_dash",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=1,
        worksheet_count=1,
    )
    evidence = build_evidence_index([worksheet], ledger)
    result = evaluate_objective_coverage(ledger, evidence, [worksheet])
    manip_result = next(
        cell for cell in result.objective_results if cell.objective_id == "obj_manipulation"
    )
    encode_result = next(
        cell for cell in result.objective_results if cell.objective_id == "obj_encode"
    )
    assert manip_result.required_forms_present is True
    assert manip_result.status == "pass"
    assert encode_result.required_forms_present is True
    assert encode_result.status == "pass"


def test_asset_free_discovery_never_authors_picture_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_SKIP_ASSET_GEN", "1")
    chunks = _build_discovery_chunks(
        ["baking", "smiled", "sliced", "hoped", "larger"],
        _skill(),
        _rules(),
        format_order=["circle", "write"],
    )

    assert chunks
    assert chunks[0].response_format == "circle"
    assert all(chunk.response_format != "match" for chunk in chunks)
    assert all(item.picture_prompt is None for chunk in chunks for item in chunk.items)


def test_drop_e_package_omits_generic_copy_families(monkeypatch: pytest.MonkeyPatch) -> None:
    from companion.schema import Accommodations, LearnerProfile

    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)
    monkeypatch.delenv("WORKSHEET_MAX_WORKSHEETS", raising=False)
    profile = LearnerProfile(
        name="Test",
        grade_level="2",
        accommodations=Accommodations(response_format_prefs=["write", "circle"]),
    )

    skill = _skill()
    skill = skill.model_copy(
        update={
            "source_items": [
                *skill.source_items,
                SourceItem(
                    item_type="passage",
                    content=(
                        "The Baker\n\nRashawn is a baker. He has been baking a pie. "
                        "He smiled as he made it. His friend liked the pie."
                    ),
                    source_region_index=10,
                ),
            ]
        }
    )
    worksheets = adapt_lesson(skill, profile, theme_id="geometry_dash")

    assert [worksheet.worksheet_title for worksheet in worksheets] == ["Word Work", "Story Time"]
    assert all(
        not chunk.micro_goal.startswith(("Fill in", "Complete"))
        for worksheet in worksheets
        for chunk in worksheet.chunks
    )
