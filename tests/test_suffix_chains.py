"""Suffix-aware word chains + chain hygiene (spec 2026-07-13, defects D1/D13)."""

from adapt.engine import _build_builder_chunks, _parse_suffix_chain_steps
from adapt.rules import AccommodationRules
from skill.schema import LiteracySkillModel


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
    # Chains no parser understands still must not print answers.
    chunks = _build_builder_chunks(["run → sprinted"], [], [], _skill("y"), _rules())
    chain_items = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain"]
    for item in chain_items:
        assert "______" in item.content
        assert item.answer
