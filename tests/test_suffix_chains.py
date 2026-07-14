"""Suffix-aware word chains + chain hygiene (spec 2026-07-13, defects D1/D13)."""

from adapt.engine import _build_builder_chunks, _build_discovery_chunks, _parse_suffix_chain_steps
from adapt.objective_ledger import ClassifiedSourceItem, ObjectiveCell, ObjectiveLedger
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
    # SINGLE chain, WITH the canonical ledger chain (review round 2): the
    # engine spends the first suffix hop (slow + -er → slower) on the worked
    # example, so the authored items alone reconstruct only [slow, slowest].
    # The ledger's word_chain source item makes _chain_covers actually run
    # against the full canonical sequence — the stitcher must recover the
    # modeled worked-example hop or a correct single-chain suffix lesson
    # false-fails with "authored chain is incomplete".
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
        source_items=[
            ClassifiedSourceItem(
                source_item_id="src_chain",
                item_type="word_chain",
                content="slow -> slower -> slowest",
                normalized_content="slow -> slower -> slowest",
                coverage_class="required_form",
                required_form="word_chain",
                objective_ids=["obj_manipulation"],
                mandatory=True,
            )
        ],
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


# --------------------------------------------------------------------------- #
# Defect D5: lesson-100's PDF had three IDENTICAL "Write 5 words" sections.
# Suffix lessons must cycle three distinct encode-practice forms across write
# batches; non-suffix lessons (e.g. lesson 74 "y") keep today's uniform
# "Write N words" batches byte-identical.
# --------------------------------------------------------------------------- #

SUFFIX_WORDS = [
    "taller",
    "tallest",
    "shorter",
    "shortest",
    "faster",
    "fastest",
    "slower",
    "slowest",
    "harder",
    "hardest",
    "softer",
    "softest",
]


def test_suffix_write_batches_use_three_distinct_forms() -> None:
    chunks = _build_discovery_chunks(
        SUFFIX_WORDS,
        _skill("suffix_er_est"),
        _rules(),
        format_order=["write"],
        preserve_all_words=True,
    )
    write_like = [c for c in chunks if c.micro_goal.startswith(("Write", "Add", "Choose"))]
    goals = {c.micro_goal.split()[0] for c in write_like}
    assert {"Write", "Add", "Choose"} <= goals, "three distinct encode forms required"

    add_chunk = next(c for c in write_like if c.micro_goal.startswith("Add"))
    for item in add_chunk.items:
        assert "+ -" in item.content and "______" in item.content
        assert item.answer and item.answer not in item.content

    choose_chunk = next(c for c in write_like if c.micro_goal.startswith("Choose"))
    for item in choose_chunk.items:
        assert item.response_format == "circle"
        assert item.options and item.answer in item.options


# Lesson-100 acceptance-run word order: er/est pairs straddle batch
# boundaries (taller lands in batch 0, tallest in batch 2, ...). Naive
# within-batch pairing finds ZERO pairs and emits circle-labeled chunks
# of pure write items — the live-run defect the advisory judge rejected
# as misleading_or_wrong_instruction.
LESSON_100_WORD_ORDER = [
    "taller",
    "shortest",
    "faster",
    "smallest",
    "quicker",
    "higher",
    "lower",
    "older",
    "newer",
    "louder",
    "smaller",
    "quickest",
    "tallest",
    "shorter",
    "fastest",
]


def test_choose_chunks_have_real_pairs_when_pairs_straddle_batches() -> None:
    chunks = _build_discovery_chunks(
        LESSON_100_WORD_ORDER,
        _skill("suffix_er_est"),
        _rules(),
        format_order=["write"],
        preserve_all_words=True,
    )
    write_like = [c for c in chunks if c.micro_goal.startswith(("Write", "Add", "Choose"))]
    choose_chunks = [c for c in write_like if c.micro_goal.startswith("Choose")]
    assert choose_chunks, "pool has complete er/est pairs — a Choose chunk must exist"
    for chunk in choose_chunks:
        circle_items = [i for i in chunk.items if i.response_format == "circle"]
        assert circle_items, "Choose-labeled chunk must contain real circle pairs"
        assert chunk.response_format == "circle"
    # Honest labels: no circle-labeled chunk of pure write items anywhere.
    for chunk in write_like:
        if chunk.response_format == "circle":
            assert any(i.response_format == "circle" for i in chunk.items)
        else:
            assert not chunk.micro_goal.startswith("Choose")
    # Word conservation: every word appears exactly once across write batches.
    seen_words: list[str] = []
    for chunk in write_like:
        for item in chunk.items:
            if item.response_format == "circle" and item.options:
                seen_words.extend(item.options)
            elif item.answer:
                seen_words.append(item.answer)
            else:
                seen_words.append(item.content)
    assert sorted(seen_words) == sorted(LESSON_100_WORD_ORDER)


def test_choose_chunks_are_pure_circle_with_accurate_count() -> None:
    # Review round 2 ruling (b): a "Choose" chunk must contain ONLY circle
    # items — its instructions ("Read the question. / Circle the right
    # word.") are wrong for a bare say-and-write filler word, the same
    # misleading_or_wrong_instruction class the judge rejected. The 15-word
    # lesson-100 pool forces an odd leftover into the choose slot under
    # fill-to-size allocation (2 pairs = 4 words + 1 filler in a 5-word slot).
    chunks = _build_discovery_chunks(
        LESSON_100_WORD_ORDER,
        _skill("suffix_er_est"),
        _rules(),
        format_order=["write"],
        preserve_all_words=True,
    )
    write_like = [c for c in chunks if c.micro_goal.startswith(("Write", "Add", "Choose"))]
    choose_chunks = [c for c in write_like if c.micro_goal.startswith("Choose")]
    assert choose_chunks, "pool has complete er/est pairs — a Choose chunk must exist"
    for chunk in choose_chunks:
        assert all(item.response_format == "circle" for item in chunk.items), (
            "no say-and-write filler under a Choose label"
        )
        # "Choose the right word N times" — N must equal the circle-item count.
        count = int(chunk.micro_goal.split()[4])
        assert count == len(chunk.items)
    # Word conservation: fillers must be rerouted, never dropped.
    seen_words: list[str] = []
    for chunk in write_like:
        for item in chunk.items:
            if item.response_format == "circle" and item.options:
                seen_words.extend(item.options)
            elif item.answer:
                seen_words.append(item.answer)
            else:
                seen_words.append(item.content)
    assert sorted(seen_words) == sorted(LESSON_100_WORD_ORDER)


def test_non_suffix_write_batches_unchanged() -> None:
    # Same construction with specific_skill="y": all write batches keep
    # today's "Write N words" shape (lesson-74 regression bar).
    chunks = _build_discovery_chunks(
        SUFFIX_WORDS,
        _skill("y"),
        _rules(),
        format_order=["write"],
        preserve_all_words=True,
    )
    write_like = [c for c in chunks if c.micro_goal.startswith(("Write", "Add", "Choose"))]
    assert write_like, "must produce write batches to exercise the regression bar"
    assert all(c.micro_goal.startswith("Write") for c in write_like)
