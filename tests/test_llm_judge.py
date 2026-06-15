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
)
from adapt.objective_ledger import EvidenceItem, build_objective_ledger
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from skill.schema import LiteracySkillModel, SourceItem
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
            "self_assessment": ["I can read CVCe words"],
        }
    )


def test_judge_prompt_shows_adhd_supports() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet_with_supports()])

    assert "About 2 minutes" in prompt  # time estimate per section
    assert "1. Read it aloud." in prompt  # numbered instruction steps
    assert "Stand up and stretch!" in prompt  # brain break between worksheets
    assert "I can read CVCe words" in prompt  # self-check list


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
    ledger = build_objective_ledger(skill)
    decode = next(o for o in ledger.objectives if o.objective_id == "obj_decode")
    package = [_obj_worksheet(decode.target_words[:7])]
    gates = run_blocking_gates(package, ledger)
    evidence = build_evidence_index(package, ledger)
    coverage = evaluate_objective_coverage(ledger, evidence, package)
    return _build_objective_judge_prompt(ledger, gates, coverage, package, evidence)


def test_objective_prompt_contains_every_objective_id() -> None:
    skill = _obj_skill()
    ledger = build_objective_ledger(skill)
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
    ledger = build_objective_ledger(skill)
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
