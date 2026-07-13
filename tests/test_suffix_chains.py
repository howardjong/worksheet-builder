"""Suffix-aware word chains + chain hygiene (spec 2026-07-13, defects D1/D13)."""

from adapt.engine import _build_builder_chunks, _parse_suffix_chain_steps
from adapt.objective_ledger import ObjectiveCell, ObjectiveLedger
from adapt.rules import AccommodationRules
from adapt.schema import AdaptedActivityModel, ScaffoldConfig
from skill.schema import LiteracySkillModel
from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage


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


def _skill(specific_skill: str = "suffix_er_est") -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill=specific_skill,
        learning_objectives=["Read CVCe words"],
        target_words=["cake"],
        response_types=["write"],
        source_items=[],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


DUP_CHAINS = [
    "slow → slower → slowest",
    "long → longer → longest",
    "slow → slower → slowest",  # source repeats — must not duplicate output
]


def test_parse_suffix_chain_steps_uses_chain_base() -> None:
    steps = _parse_suffix_chain_steps(["slow → slower → slowest"], ["er", "est"])
    assert steps == [
        {"from_word": "slow", "to_word": "slower", "suffix": "er"},
        {"from_word": "slow", "to_word": "slowest", "suffix": "est"},
    ]


def test_suffix_chain_items_hide_answers() -> None:
    chunks = _build_builder_chunks(DUP_CHAINS, [], [], _skill(), _rules())
    chain_items = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain_step"]
    assert chain_items, "suffix lesson must produce chain_step items"
    for item in chain_items:
        assert item.answer, "every chain item carries its answer"
        assert item.answer not in item.content, "answer must never be printed"
        assert "______" in item.content
    # Worked example consumed one hop; instructions speak suffix language.
    chain_chunks = [
        c for c in chunks if any(i.metadata.get("display") == "chain_step" for i in c.items)
    ]
    assert any("Add the ending" in s.text for s in chain_chunks[0].instructions)


def test_duplicate_chains_produce_no_duplicate_chunks_or_items() -> None:
    chunks = _build_builder_chunks(DUP_CHAINS, [], [], _skill(), _rules())
    signatures = [tuple(i.content for i in c.items) for c in chunks]
    assert len(signatures) == len(set(signatures)), "no two chunks may be identical"
    all_contents = [i.content for c in chunks for i in c.items]
    assert len(all_contents) == len(set(all_contents)), "no repeated items"


def test_letter_chain_lessons_unchanged() -> None:
    # Lesson-74-style single-letter chains still parse through _parse_chain_steps
    chunks = _build_builder_chunks(["cry → try → dry"], [], [], _skill("y"), _rules())
    steps = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain_step"]
    assert steps and all(i.answer for i in steps)


def test_unparseable_chain_fallback_blanks_answers() -> None:
    # Chains no parser understands still must not print answers. Two chains,
    # not one: chains[0] is always consumed by the fallback worked example
    # (adapt/engine.py:872-875), so a single-chain input leaves chain_items
    # empty and this loop body never runs — de-vacuized per Task 2 review.
    chunks = _build_builder_chunks(
        ["run → sprinted", "jump → leaped"], [], [], _skill("y"), _rules()
    )
    chain_items = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain"]
    assert chain_items, "fallback path must actually produce items to exercise"
    for item in chain_items:
        assert "______" in item.content
        assert item.answer
        assert item.answer not in item.content


# --------------------------------------------------------------------------- #
# End-to-end: engine-built suffix chunks pushed through the objective-coverage
# evidence layer (Task 2 review Finding 2). Finding 1's unit test pins
# _chain_step_pair directly; this test guards the full seam — nothing else
# exercised _build_builder_chunks's suffix output through build_evidence_index
# before a real evaluate_objective_coverage() run.
# --------------------------------------------------------------------------- #


def _manip_cell() -> ObjectiveCell:
    return ObjectiveCell(
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


def test_engine_suffix_chunks_satisfy_manipulation_cell_end_to_end() -> None:
    chain = "slow → slower → slowest"
    chunks = _build_builder_chunks([chain], [], [], _skill(), _rules())

    ledger = ObjectiveLedger(
        source_skill_hash="hash",
        lesson_number=1,
        corpus_status="matched",
        corpus_version="v1",
        corpus_lesson_id="ufli_1",
        primary_pattern=None,
        objectives=[_manip_cell()],
        source_items=[],
    )
    worksheet = AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_er_est",
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=1,
        worksheet_count=1,
    )

    evidence = build_evidence_index([worksheet], ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip_res.required_forms_present is True
    assert manip_res.status == "pass"
