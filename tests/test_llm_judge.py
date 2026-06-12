"""Tests for adapt/llm_judge.py — full-text pedagogical judge prompt."""

from __future__ import annotations

from adapt.llm_judge import _build_judge_prompt
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
