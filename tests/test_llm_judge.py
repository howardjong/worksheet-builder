"""Tests for adapt/llm_judge.py — full-text pedagogical judge prompt."""

from __future__ import annotations

import pytest

from adapt.llm_judge import (
    JudgeVerdict,
    _aggregate_verdicts,
    _build_judge_prompt,
    judge_adaptation_samples,
)
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from skill.schema import LiteracySkillModel, SourceItem

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
