"""Tests for adapt/llm_judge.py — full-text pedagogical judge prompt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapt.llm_judge import (
    SEVERE_DEFECT_TYPES,
    JudgeVerdict,
    _aggregate_verdicts,
    _build_judge_prompt,
    _build_objective_judge_prompt,
    judge_adaptation_samples,
    openai_text_model,
)
from adapt.objective_ledger import EvidenceItem, build_objective_ledger
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    FeedbackPanel,
    ScaffoldConfig,
    Step,
)
from skill.schema import LiteracySkillModel, SourceItem
from tests.objective_corpus_fixture import fixture_corpus_lookup
from validate.blocking_gates import run_blocking_gates
from validate.objective_coverage import (
    PRACTICE_STUDENT,
    build_evidence_index,
    evaluate_objective_coverage,
)

LONG_ITEM = (
    "The little dog likes to ride home in the big red wagon while the cat "
    "naps on the warm stone step."
)


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[SourceItem(item_type="sentence", content=LONG_ITEM, source_region_index=0)],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _worksheet() -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Read the sentence",
                instructions=[Step(number=1, text="Read it aloud.")],
                worked_example=Example(instruction="Try this first:", content="cake has a magic e"),
                items=[
                    ActivityItem(
                        item_id=1,
                        content=LONG_ITEM,
                        response_format="fill_blank",
                        options=["i", "o", "a"],
                        answer="i",
                    )
                ],
                response_format="fill_blank",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=1,
        worksheet_count=1,
        worksheet_title="Magic E",
    )


def test_openai_text_model_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """One knob (WORKSHEET_OPENAI_TEXT_MODEL) swaps the judge/planner/review model."""
    monkeypatch.delenv("WORKSHEET_OPENAI_TEXT_MODEL", raising=False)
    assert openai_text_model() == "gpt-5.4"

    monkeypatch.setenv("WORKSHEET_OPENAI_TEXT_MODEL", "gpt-6-mini")
    assert openai_text_model() == "gpt-6-mini"


def test_judge_prompt_carries_full_item_text() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert LONG_ITEM in prompt  # not truncated to 60 chars


def test_judge_prompt_includes_options_answers_instructions_examples() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert "options=['i', 'o', 'a']" in prompt
    assert "answer='i'" in prompt
    assert "Read it aloud." in prompt
    assert "cake has a magic e" in prompt


def test_judge_prompt_includes_structural_criteria() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert "truncated" in prompt
    assert "garbled" in prompt


def _worksheet_with_supports() -> AdaptedActivityModel:
    return _worksheet().model_copy(
        update={
            "break_prompt": "Stand up and stretch!",
            "feedback": FeedbackPanel(goal_statement="I can read CVCe words"),
        }
    )


def test_judge_prompt_shows_adhd_supports() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet_with_supports()])

    assert "About 2 minutes" in prompt  # time estimate per section
    assert "1. Read it aloud." in prompt  # numbered instruction steps
    assert "Stand up and stretch!" in prompt  # brain break between worksheets
    assert "I can read CVCe words" in prompt  # feedback panel goal statement


def _verdict(
    overall: float,
    *,
    concept: float = 0.8,
    coverage: float = 0.8,
    flow: float = 0.8,
    adhd: float = 0.8,
    approved: bool = True,
) -> JudgeVerdict:
    return JudgeVerdict(
        approved=approved,
        overall_score=overall,
        concept_alignment=concept,
        content_coverage=coverage,
        lesson_flow=flow,
        adhd_compliance=adhd,
        feedback=[f"fb-{overall}"],
        rationale=f"r-{overall}",
    )


def test_aggregate_single_verdict_unchanged() -> None:
    v = _verdict(0.91)
    assert _aggregate_verdicts([v]) is v


def test_aggregate_medians_and_recomputes_approval() -> None:
    verdicts = [
        _verdict(0.60, coverage=0.45, approved=False),
        _verdict(0.72, coverage=0.55, approved=True),
        _verdict(0.90, coverage=0.80, approved=True),
    ]
    agg = _aggregate_verdicts(verdicts)

    assert agg.overall_score == 0.72  # median overall
    assert agg.content_coverage == 0.55  # median criterion
    assert agg.approved is True  # 0.72 >= 0.70 and every median criterion >= 0.50
    assert agg.rationale == "r-0.72"  # prose from the representative (median) sample


def test_aggregate_rejects_when_median_criterion_below_floor() -> None:
    verdicts = [
        _verdict(0.72, coverage=0.40),
        _verdict(0.75, coverage=0.45),
        _verdict(0.90, coverage=0.48),
    ]
    agg = _aggregate_verdicts(verdicts)

    assert agg.overall_score == 0.75
    assert agg.content_coverage == 0.45
    assert agg.approved is False  # median coverage 0.45 < 0.50 floor


def test_judge_samples_calls_judge_n_times(monkeypatch: pytest.MonkeyPatch) -> None:
    seq = iter([_verdict(0.60), _verdict(0.72), _verdict(0.90)])
    calls: list[int] = []

    def fake(skill: object, worksheets: object) -> JudgeVerdict:
        calls.append(1)
        return next(seq)

    monkeypatch.setattr("adapt.llm_judge.judge_adaptation", fake)
    agg = judge_adaptation_samples(_skill(), [_worksheet()], 3)

    assert len(calls) == 3
    assert agg is not None
    assert agg.overall_score == 0.72


def test_judge_samples_returns_none_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("adapt.llm_judge.judge_adaptation", lambda s, w: None)
    assert judge_adaptation_samples(_skill(), [_worksheet()], 3) is None


# =========================================================================== #
# T7: objective-sufficiency judge input contract + evidence-index serialization
#
# These tests pin the NEW objective-sufficiency judge prompt (the judge scores
# the QUALITY of the handed ledger; counts / required-form / distinctness are
# decided deterministically by T6 and handed in as facts). They also pin the
# pre-work additions to EvidenceItem (stable provenance id + typed practice
# role). The OLD judge functions above must stay unchanged (flag-OFF byte-
# identical), so these live alongside them.
# =========================================================================== #

_FIX = Path(__file__).parent / "fixtures" / "objective_ledger"


def _obj_skill(name: str = "lesson59") -> LiteracySkillModel:
    return LiteracySkillModel(**json.loads((_FIX / f"{name}.json").read_text()))


def _obj_worksheet(words: list[str]) -> AdaptedActivityModel:
    """A small adapted package practicing ``words`` as read-aloud items."""
    items = [
        ActivityItem(item_id=i, content=w, response_format="read_aloud")
        for i, w in enumerate(words)
    ]
    chunk = ActivityChunk(
        chunk_id=1,
        micro_goal="Read the words",
        instructions=[Step(number=1, text="Read each word out loud.")],
        items=items,
        response_format="read_aloud",
        time_estimate="About 3 minutes",
    )
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce",
        chunks=[chunk],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=1,
        worksheet_count=1,
        worksheet_title="Word Discovery",
    )


def _build_objective_prompt() -> str:
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    package = [_obj_worksheet(decode.target_words[:7])]
    gates = run_blocking_gates(package, ledger)
    evidence = build_evidence_index(package, ledger)
    coverage = evaluate_objective_coverage(ledger, evidence, package)
    return _build_objective_judge_prompt(ledger, gates, coverage, package, evidence)


def test_objective_prompt_contains_every_objective_id() -> None:
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    prompt = _build_objective_prompt()
    for cell in ledger.objectives:
        assert cell.objective_id in prompt


def test_objective_prompt_does_not_require_full_pools() -> None:
    prompt = _build_objective_prompt().lower()
    # Must instruct that samplable pools / Roll-and-Read items need NOT be exhausted.
    assert "roll" in prompt and "read" in prompt
    assert "every" in prompt  # "do not require every source word / Roll and Read item"
    assert "sample" in prompt or "samplable" in prompt
    assert "need not" in prompt or "do not require" in prompt


def test_objective_prompt_omits_reproduce_all_source_language() -> None:
    prompt = _build_objective_prompt().lower()
    # The OLD prompt's "ALL source words ... Nothing should be dropped" framing
    # must be absent from the NEW objective prompt.
    assert "all source words" not in prompt
    assert "nothing should be dropped" not in prompt
    assert "reproduce all source" not in prompt


def test_objective_prompt_enumerates_all_severe_defects_and_cite_evidence() -> None:
    prompt = _build_objective_prompt()
    assert len(SEVERE_DEFECT_TYPES) == 5
    for defect in SEVERE_DEFECT_TYPES:
        assert defect in prompt
    assert "cite" in prompt.lower() and "evidence" in prompt.lower()


def test_objective_prompt_quality_scores_are_advisory_not_thresholds() -> None:
    prompt = _build_objective_prompt().lower()
    assert "advisory" in prompt or "diagnostic" in prompt
    # Explicitly NOT a pass/fail threshold.
    assert "not a pass/fail" in prompt or "not pass/fail" in prompt or "not a threshold" in prompt


def test_objective_prompt_forbids_approving_blocked_package() -> None:
    prompt = _build_objective_prompt().lower()
    assert "block" in prompt
    assert "must not approve" in prompt or "never approve" in prompt


def test_objective_prompt_forbids_create_reclassify_offtarget_counting() -> None:
    prompt = _build_objective_prompt().lower()
    assert "must not create" in prompt or "never create" in prompt
    assert "reclassif" in prompt  # "reclassify" / "reclassifying"
    assert "contrast" in prompt and "review" in prompt and "irregular" in prompt


# --- pre-work: EvidenceItem provenance id + typed practice role -------------- #


def test_evidence_item_round_trips_evidence_item_id() -> None:
    ev = EvidenceItem(
        visible_text="cube",
        practice_role=PRACTICE_STUDENT,
        response_format="read_aloud",
        is_student_production=False,
        evidence_item_id="ws0_chunk1_item0",
    )
    assert ev.evidence_item_id == "ws0_chunk1_item0"
    again = EvidenceItem.model_validate_json(ev.model_dump_json())
    assert again.evidence_item_id == "ws0_chunk1_item0"


def test_evidence_item_id_defaults_to_none() -> None:
    ev = EvidenceItem(
        visible_text="cube",
        practice_role=PRACTICE_STUDENT,
        response_format="read_aloud",
        is_student_production=False,
    )
    assert ev.evidence_item_id is None


def test_build_evidence_index_populates_stable_ids() -> None:
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    package = [_obj_worksheet(decode.target_words[:5])]

    ev1 = build_evidence_index(package, ledger)
    ev2 = build_evidence_index(package, ledger)
    assert ev1, "expected evidence items"
    for ev in ev1:
        assert ev.evidence_item_id is not None
        assert ev.evidence_item_id != ""
    # Deterministic + stable across runs.
    assert [e.evidence_item_id for e in ev1] == [e.evidence_item_id for e in ev2]
    # Unique per evidence item.
    ids = [e.evidence_item_id for e in ev1]
    assert len(ids) == len(set(ids))


def test_evidence_item_practice_role_is_typed_literal() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            visible_text="cube",
            practice_role="not_a_real_role",  # type: ignore[arg-type]
            response_format="read_aloud",
            is_student_production=False,
        )


# =========================================================================== #
# T8: objective-sufficiency judge OUTPUT schema + per-cell aggregation +
# the AUTHORITATIVE tri-state derivation.
#
# These pin: per-cell median quality across N samples; the CONSERVATIVE
# severe-defect vote (2/3 -> reject, 1/3 -> abstain, never ignored); and the
# tri-state approval policy. No LLM needed — verdicts are constructed directly.
# =========================================================================== #

from adapt.llm_judge import (  # noqa: E402
    ObjectiveJudgeCellScore,
    ObjectiveJudgeVerdict,
    SevereDefect,
    aggregate_objective_verdicts,
    derive_objective_approval,
    judge_objective_adaptation_samples,
)
from validate.blocking_gates import BlockingGateResult  # noqa: E402
from validate.objective_coverage import (  # noqa: E402
    ObjectiveCoverageResult,
    PackageBoundResult,
)


def _cell(
    objective_id: str,
    quality: float,
    *,
    defects: list[str] | None = None,
) -> ObjectiveJudgeCellScore:
    severe = [
        SevereDefect(defect_type=d, evidence=f"ws0_chunk1_item0: {d}")  # type: ignore[arg-type]
        for d in (defects or [])
    ]
    return ObjectiveJudgeCellScore(
        objective_id=objective_id,
        quality=quality,
        severe_defects=severe,
        evidence_item_ids=["ws0_chunk1_item0"],
        rationale=f"rat-{objective_id}-{quality}",
    )


def _obj_verdict(
    cells: list[ObjectiveJudgeCellScore],
    *,
    overall: float = 0.80,
    objective_sufficiency: float = 0.80,
    skill_form: float = 0.80,
    structured: float = 0.80,
    adhd: float = 0.80,
    flow: float = 0.80,
    recommendation: str = "approve",
) -> ObjectiveJudgeVerdict:
    return ObjectiveJudgeVerdict(
        objective_scores=cells,
        objective_sufficiency=objective_sufficiency,
        skill_form_fidelity=skill_form,
        structured_literacy_alignment=structured,
        adhd_cognitive_load_fit=adhd,
        lesson_flow_and_usability=flow,
        overall_score=overall,
        approval_recommendation=recommendation,  # type: ignore[arg-type]
        feedback=[f"fb-{overall}"],
    )


# --- output schema / parse ------------------------------------------------- #


def test_objective_verdict_fixes_contract_version() -> None:
    v = _obj_verdict([_cell("obj_decode", 0.8)])
    assert v.contract_version == "objective_sufficiency_judge_v1"


def test_objective_cell_default_vote_is_none() -> None:
    c = _cell("obj_decode", 0.8)
    assert c.severe_defect_vote == "none"


# --- per-cell median quality + conservative severe-defect vote ------------- #


def test_aggregate_per_cell_median_quality_across_three_samples() -> None:
    samples = [
        _obj_verdict([_cell("obj_decode", 0.40)], overall=0.70),
        _obj_verdict([_cell("obj_decode", 0.60)], overall=0.75),
        _obj_verdict([_cell("obj_decode", 0.90)], overall=0.80),
    ]
    agg = aggregate_objective_verdicts(samples)
    cell = next(c for c in agg.objective_scores if c.objective_id == "obj_decode")
    assert cell.quality == 0.60  # median of 0.40 / 0.60 / 0.90
    assert agg.overall_score == 0.75  # median overall


def test_aggregate_severe_defect_two_of_three_votes_reject() -> None:
    samples = [
        _obj_verdict([_cell("obj_decode", 0.8, defects=["wrong_cognitive_task"])]),
        _obj_verdict([_cell("obj_decode", 0.8, defects=["wrong_cognitive_task"])]),
        _obj_verdict([_cell("obj_decode", 0.8)]),
    ]
    agg = aggregate_objective_verdicts(samples)
    cell = next(c for c in agg.objective_scores if c.objective_id == "obj_decode")
    assert cell.severe_defect_vote == "reject"
    assert any(d.defect_type == "wrong_cognitive_task" for d in cell.severe_defects)


def test_aggregate_severe_defect_one_of_three_votes_abstain_not_ignored() -> None:
    samples = [
        _obj_verdict([_cell("obj_decode", 0.8, defects=["wrong_cognitive_task"])]),
        _obj_verdict([_cell("obj_decode", 0.8)]),
        _obj_verdict([_cell("obj_decode", 0.8)]),
    ]
    agg = aggregate_objective_verdicts(samples)
    cell = next(c for c in agg.objective_scores if c.objective_id == "obj_decode")
    assert cell.severe_defect_vote == "abstain"  # NOT ignored, NOT none
    assert any(d.defect_type == "wrong_cognitive_task" for d in cell.severe_defects)


def test_aggregate_single_sample_reject_when_cell_has_defect() -> None:
    agg = aggregate_objective_verdicts(
        [_obj_verdict([_cell("obj_decode", 0.8, defects=["child_cannot_reasonably_answer"])])]
    )
    cell = next(c for c in agg.objective_scores if c.objective_id == "obj_decode")
    assert cell.severe_defect_vote == "reject"  # N=1, c/N=1 >= 2/3


def test_aggregate_single_sample_none_when_no_defect() -> None:
    agg = aggregate_objective_verdicts([_obj_verdict([_cell("obj_decode", 0.8)])])
    cell = next(c for c in agg.objective_scores if c.objective_id == "obj_decode")
    assert cell.severe_defect_vote == "none"


# --- tri-state derivation -------------------------------------------------- #


def _ledger() -> object:
    return build_objective_ledger(_obj_skill(), corpus_lookup=fixture_corpus_lookup)


def _essential_ids(ledger: object) -> list[str]:
    return [c.objective_id for c in ledger.objectives if c.importance == "essential"]  # type: ignore[attr-defined]


def _pass_gate() -> BlockingGateResult:
    return BlockingGateResult(passed=True, violations=[])


def _fail_gate() -> BlockingGateResult:
    return BlockingGateResult(passed=False, violations=[])


def _coverage(status: str) -> ObjectiveCoverageResult:
    return ObjectiveCoverageResult(
        status=status,  # type: ignore[arg-type]
        passed=(status == "pass"),
        objective_results=[],
        package_bounds=PackageBoundResult(
            passed=True,
            total_estimated_minutes=10,
            total_item_count=5,
            dense_text_block_count=0,
            max_objectives_in_a_worksheet=1,
        ),
    )


def _clean_judge(ledger: object, *, quality: float = 0.8) -> ObjectiveJudgeVerdict:
    cells = [_cell(oid, quality) for oid in _essential_ids(ledger)]
    agg = aggregate_objective_verdicts([_obj_verdict(cells, overall=0.85, adhd=0.80)])
    return agg


def test_derive_approve_when_everything_clean() -> None:
    ledger = _ledger()
    judge = _clean_judge(ledger, quality=0.80)
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "approve"


def test_derive_reject_when_judge_none() -> None:
    ledger = _ledger()
    out = derive_objective_approval(None, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_reject_when_blocking_failed() -> None:
    ledger = _ledger()
    judge = _clean_judge(ledger, quality=0.80)
    out = derive_objective_approval(judge, _fail_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_reject_when_coverage_fail() -> None:
    ledger = _ledger()
    judge = _clean_judge(ledger, quality=0.80)
    out = derive_objective_approval(judge, _pass_gate(), _coverage("fail"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_abstain_when_coverage_needs_verification() -> None:
    ledger = _ledger()
    judge = _clean_judge(ledger, quality=0.80)
    out = derive_objective_approval(
        judge,
        _pass_gate(),
        _coverage("needs_verification"),
        ledger,  # type: ignore[arg-type]
    )
    assert out == "abstain"


def test_derive_abstain_essential_cell_quality_058_no_defect() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    # one essential cell at 0.58 (in [0.50, 0.65) abstain band), rest clean.
    cells = [_cell(oid, 0.80) for oid in essential[1:]]
    cells.insert(0, _cell(essential[0], 0.58))
    judge = aggregate_objective_verdicts([_obj_verdict(cells, overall=0.85, adhd=0.80)])
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_reject_essential_cell_quality_045() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    cells = [_cell(oid, 0.80) for oid in essential[1:]]
    cells.insert(0, _cell(essential[0], 0.45))  # < 0.50 -> reject
    judge = aggregate_objective_verdicts([_obj_verdict(cells, overall=0.85, adhd=0.80)])
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_reject_severe_defect_two_of_three_on_essential_cell() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    eid = essential[0]
    samples = [
        _obj_verdict(
            [_cell(eid, 0.80, defects=["wrong_cognitive_task"])]
            + [_cell(o, 0.80) for o in essential[1:]],
            overall=0.85,
            adhd=0.80,
        ),
        _obj_verdict(
            [_cell(eid, 0.80, defects=["wrong_cognitive_task"])]
            + [_cell(o, 0.80) for o in essential[1:]],
            overall=0.85,
            adhd=0.80,
        ),
        _obj_verdict(
            [_cell(o, 0.80) for o in essential],
            overall=0.85,
            adhd=0.80,
        ),
    ]
    judge = aggregate_objective_verdicts(samples)
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_abstain_severe_defect_one_of_three_on_essential_cell() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    eid = essential[0]
    samples = [
        _obj_verdict(
            [_cell(eid, 0.80, defects=["wrong_cognitive_task"])]
            + [_cell(o, 0.80) for o in essential[1:]],
            overall=0.85,
            adhd=0.80,
        ),
        _obj_verdict([_cell(o, 0.80) for o in essential], overall=0.85, adhd=0.80),
        _obj_verdict([_cell(o, 0.80) for o in essential], overall=0.85, adhd=0.80),
    ]
    judge = aggregate_objective_verdicts(samples)
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_reject_when_overall_below_070() -> None:
    ledger = _ledger()
    judge = aggregate_objective_verdicts(
        [_obj_verdict([_cell(o, 0.80) for o in _essential_ids(ledger)], overall=0.65, adhd=0.80)]
    )
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


def test_derive_reject_when_adhd_below_050() -> None:
    ledger = _ledger()
    judge = aggregate_objective_verdicts(
        [_obj_verdict([_cell(o, 0.80) for o in _essential_ids(ledger)], overall=0.85, adhd=0.40)]
    )
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "reject"


# --- completeness guard (C1: false-approve when judge omits essential cells) #
#
# derive_objective_approval must NOT auto-approve unless the judge actually
# scored EVERY essential ledger cell. A missing essential cell carries no
# quality signal, so the conservative, spec-consistent outcome is "abstain"
# ("did not auto-approve; route to fallback"). All four degenerate verdicts
# below otherwise satisfy the approve preconditions (overall>=0.70, adhd>=0.50,
# gates pass, coverage pass) — only the missing essential cell(s) differ.


def test_derive_abstain_when_judge_omits_one_essential_cell() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    # Score every essential cell EXCEPT the last one — that cell goes unscored.
    cells = [_cell(oid, 0.80) for oid in essential[:-1]]
    judge = aggregate_objective_verdicts([_obj_verdict(cells, overall=0.85, adhd=0.80)])
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_abstain_when_judge_returns_zero_scores() -> None:
    ledger = _ledger()
    # Empty objective_scores parses fine (defaults to []) but scores no cells.
    judge = aggregate_objective_verdicts([_obj_verdict([], overall=0.85, adhd=0.80)])
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_abstain_when_judge_scores_only_unknown_objective() -> None:
    ledger = _ledger()
    # Only an objective_id not in the ledger is scored; real essentials go unscored.
    judge = aggregate_objective_verdicts(
        [_obj_verdict([_cell("obj_not_in_ledger", 0.80)], overall=0.85, adhd=0.80)]
    )
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_abstain_when_judge_omits_the_cell_that_would_fail() -> None:
    ledger = _ledger()
    essential = _essential_ids(ledger)
    # Score all essentials cleanly EXCEPT the first — the omitted cell is exactly
    # the one that, had it been scored as failing, would have driven a reject.
    cells = [_cell(oid, 0.80) for oid in essential[1:]]
    judge = aggregate_objective_verdicts([_obj_verdict(cells, overall=0.85, adhd=0.80)])
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "abstain"


def test_derive_approve_when_all_essential_cells_scored_clean() -> None:
    # Positive guard: the completeness guard must NOT over-trigger when every
    # essential cell is scored at/above the pass band with no defects.
    ledger = _ledger()
    judge = _clean_judge(ledger, quality=0.80)
    out = derive_objective_approval(judge, _pass_gate(), _coverage("pass"), ledger)  # type: ignore[arg-type]
    assert out == "approve"


# --- samples plumbing ------------------------------------------------------ #


def test_judge_objective_samples_calls_n_times_returns_raw_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = iter(
        [
            _obj_verdict([_cell("obj_decode", 0.40)]),
            _obj_verdict([_cell("obj_decode", 0.60)]),
            _obj_verdict([_cell("obj_decode", 0.90)]),
        ]
    )
    calls: list[int] = []

    def fake(*args: object, **kwargs: object) -> ObjectiveJudgeVerdict:
        calls.append(1)
        return next(seq)

    monkeypatch.setattr("adapt.llm_judge.judge_objective_adaptation", fake)
    out = judge_objective_adaptation_samples(None, None, None, None, None, 3)  # type: ignore[arg-type]

    assert len(calls) == 3
    assert len(out) == 3  # RAW list, not aggregated
    assert [c.objective_scores[0].quality for c in out] == [0.40, 0.60, 0.90]


def test_judge_objective_samples_drops_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    seq = iter([_obj_verdict([_cell("obj_decode", 0.5)]), None, None])
    monkeypatch.setattr("adapt.llm_judge.judge_objective_adaptation", lambda *a, **k: next(seq))
    out = judge_objective_adaptation_samples(None, None, None, None, None, 3)  # type: ignore[arg-type]
    assert len(out) == 1


def test_objective_output_format_section_names_required_fields() -> None:
    prompt = _build_objective_prompt()
    for field in (
        "objective_scores",
        "quality",
        "severe_defects",
        "objective_sufficiency",
        "skill_form_fidelity",
        "structured_literacy_alignment",
        "adhd_cognitive_load_fit",
        "lesson_flow_and_usability",
        "overall_score",
        "approval_recommendation",
    ):
        assert field in prompt


# =========================================================================== #
# judge_package_objective (P3b) — public wrapper composing the objective-judge
# machinery (ledger + evidence + deterministic coverage + prompt + provider
# call + parse) into a single advisory entry point transform.py Stage 5c can
# call. Mocked at the module's OpenAI-call boundary (_call_openai), same style
# as the planner-chain tests in tests/test_llm_planner.py.
# =========================================================================== #


def test_judge_package_objective_returns_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_judge import judge_package_objective

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    worksheets = [_obj_worksheet(decode.target_words[:7])]

    approving_json = json.dumps(
        {
            "objective_scores": [
                {
                    "objective_id": cell.objective_id,
                    "quality": 0.85,
                    "severe_defects": [],
                    "evidence_item_ids": [],
                    "rationale": "solid",
                }
                for cell in ledger.objectives
            ],
            "objective_sufficiency": 0.85,
            "skill_form_fidelity": 0.85,
            "structured_literacy_alignment": 0.85,
            "adhd_cognitive_load_fit": 0.85,
            "lesson_flow_and_usability": 0.85,
            "overall_score": 0.85,
            "approval_recommendation": "approve",
            "feedback": ["Looks good."],
        }
    )

    monkeypatch.setattr("adapt.llm_judge._call_openai", lambda *a, **k: approving_json)

    verdict = judge_package_objective(skill, worksheets)

    assert verdict is not None
    assert verdict.approval_recommendation == "approve"


def test_judge_package_objective_none_on_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_judge import judge_package_objective

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    worksheets = [_obj_worksheet(decode.target_words[:7])]

    def _boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("boundary exploded")

    monkeypatch.setattr("adapt.llm_judge._call_openai", _boom)

    verdict = judge_package_objective(skill, worksheets)

    assert verdict is None


# =========================================================================== #
# D11 — objective judge truncation retry. The judge's max_completion_tokens
# was 1024, too small for the full JSON verdict; a truncated response fails
# JSON parsing and the package ships unjudged via the "unavailable" path.
# Fix: call at 4096 tokens, and on a parse failure retry the SAME request
# once before giving up (cost bound: +1 judge call, only on parse failure).
# =========================================================================== #


def test_objective_judge_retries_once_on_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_judge import judge_objective_adaptation

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    worksheets = [_obj_worksheet(decode.target_words[:7])]
    gates = run_blocking_gates(worksheets, ledger)
    evidence = build_evidence_index(worksheets, ledger)
    coverage = evaluate_objective_coverage(ledger, evidence, worksheets)

    good = json.dumps(
        {
            "objective_scores": [
                {
                    "objective_id": cell.objective_id,
                    "quality": 0.85,
                    "severe_defects": [],
                    "evidence_item_ids": [],
                    "rationale": "solid",
                }
                for cell in ledger.objectives
            ],
            "objective_sufficiency": 0.85,
            "skill_form_fidelity": 0.85,
            "structured_literacy_alignment": 0.85,
            "adhd_cognitive_load_fit": 0.85,
            "lesson_flow_and_usability": 0.85,
            "overall_score": 0.85,
            "approval_recommendation": "approve",
            "feedback": ["Looks good."],
        }
    )

    calls: list[int] = []

    def fake_call(prompt: str, max_completion_tokens: int = 1024) -> str:
        calls.append(max_completion_tokens)
        return '{"truncated": ' if len(calls) == 1 else good

    monkeypatch.setattr("adapt.llm_judge._call_openai", fake_call)

    verdict = judge_objective_adaptation(ledger, gates, coverage, worksheets, evidence)

    assert verdict is not None
    assert len(calls) == 2
    assert all(t >= 4096 for t in calls)


def test_objective_judge_gives_up_after_second_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt.llm_judge import judge_objective_adaptation

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    skill = _obj_skill()
    ledger = build_objective_ledger(skill, corpus_lookup=fixture_corpus_lookup)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    worksheets = [_obj_worksheet(decode.target_words[:7])]
    gates = run_blocking_gates(worksheets, ledger)
    evidence = build_evidence_index(worksheets, ledger)
    coverage = evaluate_objective_coverage(ledger, evidence, worksheets)

    monkeypatch.setattr("adapt.llm_judge._call_openai", lambda *a, **k: '{"nope": ')

    verdict = judge_objective_adaptation(ledger, gates, coverage, worksheets, evidence)

    assert verdict is None
