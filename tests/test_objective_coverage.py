"""Tests for validate/objective_coverage.py — package-level coverage validator (T6).

Strict red-green TDD: every test below pins one of the nine mandated behaviors of
the deterministic objective-coverage validator, plus a determinism check. Ledgers
are mostly hand-built via the T1 schema so each edge (distinctness, role exclusion,
confidence, required-form, package bounds) is exercised in isolation; the
roll-and-read PASS case is also driven from a committed fixture for realism.
"""

from __future__ import annotations

import json
from pathlib import Path

from adapt.objective_ledger import (
    ClassifiedSourceItem,
    LedgerWord,
    ObjectiveCell,
    ObjectiveLedger,
    build_objective_ledger,
)
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from skill.schema import LiteracySkillModel
from tests.objective_corpus_fixture import fixture_corpus_lookup
from validate.objective_coverage import (
    build_evidence_index,
    evaluate_objective_coverage,
)

_FIX = Path(__file__).parent / "fixtures" / "objective_ledger"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _load_skill(name: str) -> LiteracySkillModel:
    return LiteracySkillModel(**json.loads((_FIX / f"{name}.json").read_text()))


def _item(
    item_id: int,
    content: str,
    response_format: str = "read_aloud",
    *,
    options: list[str] | None = None,
    answer: str | None = None,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> ActivityItem:
    return ActivityItem(
        item_id=item_id,
        content=content,
        response_format=response_format,
        options=options,
        answer=answer,
        metadata=metadata or {},
    )


def _chunk(
    chunk_id: int,
    items: list[ActivityItem],
    *,
    response_format: str = "read_aloud",
    time_estimate: str = "About 3 minutes",
    worked_example: bool = False,
) -> ActivityChunk:
    from adapt.schema import Example

    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal=f"Goal {chunk_id}",
        instructions=[Step(number=1, text="Read each word out loud.")],
        worked_example=(
            Example(instruction="Watch me:", content="example") if worked_example else None
        ),
        items=items,
        response_format=response_format,
        time_estimate=time_estimate,
    )


def _worksheet(
    chunks: list[ActivityChunk],
    *,
    number: int = 1,
    count: int = 1,
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce",
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=number,
        worksheet_count=count,
    )


def _ledger(
    objectives: list[ObjectiveCell],
    *,
    corpus_status: str = "matched",
    primary_pattern: str | None = "u_e",
    source_items: list[ClassifiedSourceItem] | None = None,
) -> ObjectiveLedger:
    return ObjectiveLedger(
        source_skill_hash="hash",
        lesson_number=58,
        corpus_status=corpus_status,  # type: ignore[arg-type]
        corpus_version="v1",
        corpus_lesson_id="ufli_58",
        primary_pattern=primary_pattern,
        objectives=objectives,
        source_items=source_items or [],
    )


def _decode_cell(
    target_words: list[str],
    *,
    min_count: int = 6,
    contrast_words: list[str] | None = None,
) -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_decode",
        objective_type="decode_target_pattern",
        display_name="Decode u_e words",
        concept="cvce",
        target_pattern="u_e",
        importance="essential",
        required_forms=[],
        target_words=target_words,
        contrast_words=contrast_words or [],
        min_practice_count=min_count,
        max_recommended_count=12,
        acceptable_response_formats=["read_aloud", "circle", "write"],
        sufficiency_rule="decode rule",
    )


def _hi_word(norm: str) -> LedgerWord:
    """A high-confidence target_pattern ledger word (for the word-role index)."""
    return LedgerWord(
        text=norm,
        normalized=norm,
        role="target_pattern",
        role_confidence="high",
        role_source="corpus_exact",
        reason="hi",
    )


def _lo_word(norm: str) -> LedgerWord:
    """A low-confidence target_pattern ledger word (advisory only)."""
    return LedgerWord(
        text=norm,
        normalized=norm,
        role="target_pattern",
        role_confidence="low",
        role_source="pattern_rule",
        reason="lo",
    )


def _pool_item(words: list[LedgerWord], item_id: str = "src_pool") -> ClassifiedSourceItem:
    return ClassifiedSourceItem(
        source_item_id=item_id,
        item_type="roll_and_read",
        content=" ".join(w.normalized for w in words),
        normalized_content=" ".join(w.normalized for w in words),
        coverage_class="samplable_pool",
        word_roles=words,
        objective_ids=["obj_decode"],
        mandatory=False,
    )


# --------------------------------------------------------------------------- #
# Case 1: roll-and-read sampled (7/18) but distinct threshold met → decode PASS
# --------------------------------------------------------------------------- #


def test_case1_roll_and_read_sampled_but_threshold_met_passes() -> None:
    """The S5 false-rejection must not recur: a samplable pool is satisfied at the
    distinct high-confidence threshold, NOT exhausted."""
    skill = _load_skill("lesson58")
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    pool = decode.target_words  # high-confidence u_e words from the corpus pool
    assert len(pool) >= 12
    # Practice only 7 of the pool words (>= the min of 6), in read_aloud form.
    sampled = pool[:7]
    items = [_item(i, w, "read_aloud") for i, w in enumerate(sampled)]
    package = [_worksheet([_chunk(1, items)])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)

    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")
    assert decode_res.distinct_high_confidence_count == 7
    assert decode_res.status == "pass"


# --------------------------------------------------------------------------- #
# Case 2: target word only as answer-key / distractor → does NOT count
# --------------------------------------------------------------------------- #


def test_case2_word_only_in_key_or_distractor_does_not_count() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    pool_words = [_hi_word(w) for w in cell.target_words]
    ledger = _ledger([cell], source_items=[_pool_item(pool_words)])

    # 'cube' appears ONLY as a wrong distractor option; 'mute' ONLY as the answer
    # key of a circle item whose content does not practice it. Neither must count.
    item_distractor = _item(
        1,
        "Circle the word that says hat.",
        "circle",
        options=["hat", "cube"],  # cube is a distractor, not the answer
        answer="hat",
    )
    item_key = _item(
        2,
        "Circle the picture.",
        "circle",
        options=["pic_a", "pic_b"],
        answer="mute",  # in the key only; not student-practiced text
    )
    package = [_worksheet([_chunk(1, [item_distractor, item_key], response_format="circle")])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    # Neither cube nor mute counted → zero distinct high-confidence practice.
    assert decode_res.distinct_high_confidence_count == 0
    # Essential cell with zero high-confidence distinct practice → needs_verification.
    assert decode_res.status == "needs_verification"


# --------------------------------------------------------------------------- #
# Case 3: incomplete chain (missing early transformation steps) → required-form FAIL
# --------------------------------------------------------------------------- #


def _manip_cell() -> ObjectiveCell:
    return ObjectiveCell(
        objective_id="obj_manipulation",
        objective_type="phoneme_grapheme_manipulation",
        display_name="Build and change words",
        concept="manipulation",
        target_pattern="u_e",
        importance="essential",
        required_forms=["word_chain", "chain_script"],
        min_practice_count=1,
        max_recommended_count=1,
        acceptable_response_formats=["word_chain"],
        sufficiency_rule="one coherent chain",
    )


def _chain_source(content: str) -> ClassifiedSourceItem:
    return ClassifiedSourceItem(
        source_item_id="src_chain",
        item_type="word_chain",
        content=content,
        normalized_content=content.lower(),
        coverage_class="required_form",
        required_form="word_chain",
        objective_ids=["obj_manipulation"],
        mandatory=True,
    )


def test_case3_incomplete_chain_required_form_fail() -> None:
    # Ledger chain has 4 steps; authored worksheet preserves only the last 2 →
    # missing early transformation steps → required-form FAIL.
    ledger = _ledger(
        [_manip_cell()],
        source_items=[_chain_source("mule -> mute -> cute -> cube")],
    )
    chain_item = _item(
        1,
        "cute -> cube",  # only the tail of the ledger chain
        "word_chain",
        metadata={"display": "chain"},
    )
    package = [_worksheet([_chunk(1, [chain_item], response_format="word_chain")])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip_res.required_forms_present is False
    assert manip_res.status == "fail"
    assert result.status == "fail"


def test_case3b_complete_chain_required_form_pass() -> None:
    ledger = _ledger(
        [_manip_cell()],
        source_items=[_chain_source("mule -> mute -> cute -> cube")],
    )
    chain_item = _item(
        1,
        "mule -> mute -> cute -> cube",
        "word_chain",
        metadata={"display": "chain"},
    )
    package = [_worksheet([_chunk(1, [chain_item], response_format="word_chain")])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")
    assert manip_res.required_forms_present is True
    assert manip_res.status == "pass"


# --------------------------------------------------------------------------- #
# Case 3c/3d: deterministic-engine chain-step items stitch into chain evidence
# (P3a scope extension). The engines (adapt/engine.py::_build_builder_chunks and
# adapt/llm_adapt.py::_build_items_from_activity) author chains as per-step
# write items — from-word in the quoted content, target word in `answer`, and
# metadata {"display": "chain_step"} stamped ONLY by our own deterministic
# derivation (_parse_chain_steps); a model cannot assert the stamp. Those items
# must be recognized as manipulation evidence.
# --------------------------------------------------------------------------- #


def _chain_step_item(item_id: int, from_word: str, old: str, new: str, answer: str) -> ActivityItem:
    """An engine-shaped chain-step item (adapt/engine.py:739-751 template)."""
    return _item(
        item_id,
        f'Start with "{from_word}". Change the "{old}" to "{new}". Write the new word.',
        "write",
        answer=answer,
        metadata={"display": "chain_step"},
    )


def test_case3c_engine_chain_steps_stitch_into_chain_evidence() -> None:
    # Ledger chain mule -> mute -> cute; the engine authors it as write items
    # whose target word lives in `answer` (the child writes it). Stitched in
    # item order they reconstruct the full transformation sequence → PASS.
    ledger = _ledger(
        [_manip_cell()],
        source_items=[_chain_source("mule -> mute -> cute")],
    )
    items = [
        _chain_step_item(1, "mule", "l", "t", "mute"),
        _chain_step_item(2, "mute", "m", "c", "cute"),
    ]
    package = [_worksheet([_chunk(1, items, response_format="write")])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip_res.required_forms_present is True
    assert manip_res.status == "pass"


def test_case3d_worked_example_first_hop_completes_engine_chain() -> None:
    # The engine spends the chain's FIRST step on the chunk's worked example
    # (adapt/engine.py:713-724) and authors the rest as chain-step items. The
    # modeled first hop counts as part of the stitched chain (the UFLI chain
    # activity includes the modeled first hop) — chain evidence only; worked
    # examples still never satisfy any other cell type.
    from adapt.schema import Example

    ledger = _ledger(
        [_manip_cell()],
        source_items=[_chain_source("mule -> mute -> cute -> cube")],
    )
    chunk = ActivityChunk(
        chunk_id=1,
        micro_goal="Build 2 new words",
        instructions=[Step(number=1, text="Read the starting word.")],
        worked_example=Example(
            instruction="Watch how the letters change:",
            content='mule → mute  (change the "l" to "t")',
        ),
        items=[
            _chain_step_item(1, "mute", "m", "c", "cute"),
            _chain_step_item(2, "cute", "t", "b", "cube"),
        ],
        response_format="write",
        time_estimate="About 1 minute",
    )
    package = [_worksheet([chunk])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip_res.required_forms_present is True
    assert manip_res.status == "pass"


def test_case3e_disconnected_worked_example_does_not_prefix_chain() -> None:
    # A worked example that does NOT model the chain's first step (its target
    # word is not the first authored from-word) must not be stitched in — the
    # chain stays incomplete and the required form FAILS.
    from adapt.schema import Example

    ledger = _ledger(
        [_manip_cell()],
        source_items=[_chain_source("mule -> mute -> cute -> cube")],
    )
    chunk = ActivityChunk(
        chunk_id=1,
        micro_goal="Build 1 new word",
        instructions=[Step(number=1, text="Read the starting word.")],
        worked_example=Example(
            instruction="Watch how the letters change:",
            content='fuse → fume  (change the "s" to "m")',  # unrelated hop
        ),
        items=[
            _chain_step_item(1, "cute", "t", "b", "cube"),  # tail only
        ],
        response_format="write",
        time_estimate="About 1 minute",
    )
    package = [_worksheet([chunk])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip_res = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip_res.required_forms_present is False
    assert manip_res.status == "fail"


# --------------------------------------------------------------------------- #
# Case 4: decode cell satisfied only by contrast/review words → FAIL
# --------------------------------------------------------------------------- #


def test_case4_satisfied_only_by_contrast_words_fail() -> None:
    # Cell needs 6 distinct u_e targets. The worksheet practices only contrast
    # words (mop, jazz, ...) which are NOT in target_words → they never count.
    cell = _decode_cell(
        ["cube", "mute", "fuse", "tune", "rule", "mule"],
        contrast_words=["mop", "jazz", "tab", "sit", "led", "fan", "rug"],
    )
    pool = [_hi_word(w) for w in cell.target_words]
    contrast = [
        LedgerWord(
            text=w,
            normalized=w,
            role="contrast_word",
            role_confidence="high",
            role_source="pattern_rule",
            reason="contrast",
        )
        for w in cell.contrast_words
    ]
    ledger = _ledger([cell], source_items=[_pool_item(pool + contrast)])

    items = [_item(i, w, "read_aloud") for i, w in enumerate(cell.contrast_words)]
    package = [_worksheet([_chunk(1, items)])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    assert decode_res.distinct_high_confidence_count == 0
    assert decode_res.status == "fail"
    assert result.status == "fail"


# --------------------------------------------------------------------------- #
# Case 5: threshold met only by repeating one word → FAIL (distinctness)
# --------------------------------------------------------------------------- #


def test_case5_repeated_word_fails_distinctness() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    pool = [_hi_word(w) for w in cell.target_words]
    ledger = _ledger([cell], source_items=[_pool_item(pool)])

    # 'cube' practiced 8 times — only counts once.
    items = [_item(i, "cube", "read_aloud") for i in range(8)]
    package = [_worksheet([_chunk(1, items)])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    assert decode_res.distinct_high_confidence_count == 1
    assert decode_res.status == "fail"
    assert result.status == "fail"


# --------------------------------------------------------------------------- #
# Case 6: above threshold on high-confidence + extra low-confidence → PASS + advisory
# --------------------------------------------------------------------------- #


def test_case6_extra_low_confidence_passes_with_advisory() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    pool = [_hi_word(w) for w in cell.target_words]
    # Two extra low-confidence target words present in the ledger word-role index.
    lows = [_lo_word("duke"), _lo_word("rude")]
    ledger = _ledger([cell], source_items=[_pool_item(pool + lows)])

    practiced = cell.target_words + ["duke", "rude"]  # 6 high + 2 low
    items = [_item(i, w, "read_aloud") for i, w in enumerate(practiced)]
    package = [_worksheet([_chunk(1, items)])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    assert decode_res.distinct_high_confidence_count == 6
    assert decode_res.advisory_low_confidence_count == 2
    assert decode_res.status == "pass"
    assert result.status == "pass"
    # Advisory surfaced for the judge.
    assert any("advisor" in n.lower() or "low" in n.lower() for n in decode_res.notes)


# --------------------------------------------------------------------------- #
# Case 7: essential cell with ONLY low-confidence evidence → needs_verification
# --------------------------------------------------------------------------- #


def test_case7_only_low_confidence_needs_verification() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    # The ledger word-role index marks every practiced word low-confidence.
    lows = [_lo_word(w) for w in ["puke", "dune", "duke", "rude", "tube", "fume", "muse"]]
    ledger = _ledger([cell], source_items=[_pool_item(lows)], corpus_status="missing")

    items = [_item(i, w.normalized, "read_aloud") for i, w in enumerate(lows)]
    package = [_worksheet([_chunk(1, items)])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    assert decode_res.distinct_high_confidence_count == 0
    assert decode_res.advisory_low_confidence_count >= 6
    assert decode_res.status == "needs_verification"
    # No hard failure anywhere → package routes to ABSTAIN, not REJECT.
    assert result.status == "needs_verification"
    assert result.passed is False


# --------------------------------------------------------------------------- #
# Case 8: objective split across two worksheets → aggregates → PASS
# --------------------------------------------------------------------------- #


def test_case8_objective_split_across_worksheets_aggregates_pass() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    pool = [_hi_word(w) for w in cell.target_words]
    ledger = _ledger([cell], source_items=[_pool_item(pool)])

    # 3 distinct words on worksheet 1, the other 3 on worksheet 2.
    ws1_items = [_item(i, w, "read_aloud") for i, w in enumerate(cell.target_words[:3])]
    ws2_items = [_item(i + 10, w, "read_aloud") for i, w in enumerate(cell.target_words[3:])]
    package = [
        _worksheet([_chunk(1, ws1_items)], number=1, count=2),
        _worksheet([_chunk(2, ws2_items)], number=2, count=2),
    ]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")

    assert decode_res.distinct_high_confidence_count == 6
    assert decode_res.status == "pass"
    assert result.status == "pass"


# --------------------------------------------------------------------------- #
# Case 9: every cell met but package exceeds total-minutes / total-items → FAIL
# --------------------------------------------------------------------------- #


def test_case9_package_bound_minutes_breach_fails() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"])
    pool = [_hi_word(w) for w in cell.target_words]
    ledger = _ledger([cell], source_items=[_pool_item(pool)])

    items = [_item(i, w, "read_aloud") for i, w in enumerate(cell.target_words)]
    # One chunk with a huge time estimate to blow the package minute budget.
    chunk = _chunk(1, items, time_estimate="About 999 minutes")
    package = [_worksheet([chunk])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence, package)

    decode_res = next(r for r in result.objective_results if r.objective_id == "obj_decode")
    assert decode_res.status == "pass"  # the cell itself is fine
    assert result.package_bounds.passed is False
    assert result.status == "fail"
    assert any("minute" in b.lower() for b in result.package_bounds.breaches)


def test_case9b_package_bound_items_breach_fails() -> None:
    cell = _decode_cell(["cube", "mute", "fuse", "tune", "rule", "mule"], min_count=6)
    pool = [_hi_word(w) for w in cell.target_words]
    ledger = _ledger([cell], source_items=[_pool_item(pool)])

    # 6 distinct target words (cell passes) padded out to > PACKAGE_MAX_TOTAL_ITEMS
    # by repeating distinct target words across many items.
    practiced = cell.target_words
    items = [_item(i, practiced[i % len(practiced)], "read_aloud") for i in range(50)]
    package = [_worksheet([_chunk(1, items[:25]), _chunk(2, items[25:])])]

    evidence = build_evidence_index(package, ledger)
    result = evaluate_objective_coverage(ledger, evidence, package)

    assert result.package_bounds.total_item_count == 50
    assert result.package_bounds.passed is False
    assert result.status == "fail"
    assert any("item" in b.lower() for b in result.package_bounds.breaches)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_determinism_identical_json() -> None:
    skill = _load_skill("lesson58")
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    items = [_item(i, w, "read_aloud") for i, w in enumerate(decode.target_words[:7])]
    package = [_worksheet([_chunk(1, items)])]

    ev1 = build_evidence_index(package, ledger)
    ev2 = build_evidence_index(package, ledger)
    r1 = evaluate_objective_coverage(ledger, ev1)
    r2 = evaluate_objective_coverage(ledger, ev2)
    assert r1.model_dump_json() == r2.model_dump_json()
    # EvidenceItem index is itself stable.
    assert [e.model_dump_json() for e in ev1] == [e.model_dump_json() for e in ev2]
