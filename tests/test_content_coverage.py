"""Tests for deterministic content coverage validation."""

from __future__ import annotations

from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from skill.schema import LiteracySkillModel, SourceItem
from validate.content_coverage import (
    validate_content_coverage,
    validate_content_coverage_for_package,
)


def _word_work_skill(target_words: list[str] | None = None) -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read and spell CVCe words"],
        target_words=target_words or ["grade", "slide", "quite"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, slide, quite",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="tune -> tone -> cone -> cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sentence",
                content="The slide is quite tall.",
                source_region_index=2,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _decodable_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=["Read a decodable passage"],
        target_words=["slide", "quite", "grade"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="passage",
                content=(
                    "A Fine Slide. The slide was quite tall. "
                    "The kids made a line and took turns."
                ),
                source_region_index=0,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_decodable_story",
    )


def _adapted(contents: list[str], response_format: str = "write") -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="1",
        domain="phonics" if response_format != "read_aloud" else "fluency",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice source content",
                instructions=[Step(number=1, text="Read each item.")],
                worked_example=None,
                items=[
                    ActivityItem(
                        item_id=i + 1,
                        content=text,
                        response_format=response_format,
                    )
                    for i, text in enumerate(contents)
                ],
                response_format=response_format,
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="roblox_obby",
        decoration_zones=[],
    )


def _adapted_with_answer_only_coverage() -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice source content",
                instructions=[Step(number=1, text="Read each item.")],
                worked_example=None,
                items=[
                    ActivityItem(
                        item_id=1,
                        content="grade",
                        response_format="write",
                    ),
                    ActivityItem(
                        item_id=2,
                        content="slide",
                        response_format="write",
                    ),
                    ActivityItem(
                        item_id=3,
                        content="tune tone cone",
                        response_format="circle",
                        answer="quite cane The slide is quite tall.",
                    ),
                ],
                response_format="write",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="roblox_obby",
        decoration_zones=[],
    )


def test_content_coverage_passes_when_targets_chain_and_sentence_present() -> None:
    result = validate_content_coverage(
        _word_work_skill(),
        _adapted(
            [
                "grade",
                "slide",
                "quite",
                "tune tone cone cane",
                "The slide is quite tall.",
            ]
        ),
    )

    assert result.passed


def test_content_coverage_fails_when_fewer_than_four_targets_are_not_all_present() -> None:
    result = validate_content_coverage(
        _word_work_skill(target_words=["grade", "chase", "froze"]),
        _adapted(["grade", "chase", "tune tone cone cane", "The slide is quite tall."]),
    )

    assert not result.passed
    assert any(v.check == "target_word_coverage" for v in result.violations)


def test_content_coverage_does_not_count_hidden_answer_text() -> None:
    result = validate_content_coverage(
        _word_work_skill(),
        _adapted_with_answer_only_coverage(),
    )

    assert not result.passed
    checks = {v.check for v in result.violations}
    assert "target_word_coverage" in checks
    assert "word_chain_coverage" in checks
    assert "source_sentence_coverage" in checks


def test_package_coverage_counts_student_facing_production_answers() -> None:
    result = validate_content_coverage_for_package(
        _word_work_skill(),
        [
            _adapted(
                [
                    "grade",
                    'Start with "tune." Change u to o. Write the new word.',
                    'Start with "tone." Change t to c. Write the new word.',
                ]
            ).model_copy(
                update={
                    "chunks": [
                        ActivityChunk(
                            chunk_id=1,
                            micro_goal="Practice word chains",
                            instructions=[Step(number=1, text="Write each new word.")],
                            worked_example=None,
                            items=[
                                ActivityItem(
                                    item_id=1,
                                    content="grade",
                                    response_format="write",
                                ),
                                ActivityItem(
                                    item_id=2,
                                    content='Start with "tune." Change u to o. Write the new word.',
                                    response_format="write",
                                    metadata={"display": "chain_step"},
                                    answer="tone",
                                ),
                                ActivityItem(
                                    item_id=3,
                                    content='Start with "tone." Change t to c. Write the new word.',
                                    response_format="write",
                                    metadata={"display": "chain_step"},
                                    answer="cone",
                                ),
                            ],
                            response_format="write",
                            time_estimate="About 2 minutes",
                        )
                    ]
                }
            ),
            _adapted(["quite"]).model_copy(
                update={
                    "chunks": [
                        ActivityChunk(
                            chunk_id=1,
                            micro_goal="Practice a fill-in sentence",
                            instructions=[Step(number=1, text="Write the missing word.")],
                            worked_example=None,
                            items=[
                                ActivityItem(
                                    item_id=1,
                                    content='Start with "cone." Change o to a. Write the new word.',
                                    response_format="write",
                                    metadata={"display": "chain_step"},
                                    answer="cane",
                                ),
                                ActivityItem(
                                    item_id=2,
                                    content="The ________ is quite tall.",
                                    response_format="fill_blank",
                                    answer="slide",
                                ),
                            ],
                            response_format="fill_blank",
                            time_estimate="About 2 minutes",
                        )
                    ]
                }
            ),
        ],
    )

    assert result.passed


def test_content_coverage_allows_twenty_percent_missing_when_four_or_more_targets_exist() -> None:
    skill = _word_work_skill(target_words=["grade", "slide", "quite", "these", "froze"])
    result = validate_content_coverage(
        skill,
        _adapted(
            [
                "grade",
                "slide",
                "quite",
                "these",
                "tune tone cone cane",
                "The slide is quite tall.",
            ]
        ),
    )

    assert result.passed


def test_content_coverage_passes_when_one_of_multiple_sentences_is_present() -> None:
    skill = _word_work_skill()
    skill.source_items.append(
        SourceItem(
            item_type="sentence",
            content="These froze in the cave.",
            source_region_index=3,
        )
    )

    result = validate_content_coverage(
        skill,
        _adapted(["grade", "slide", "quite", "tune tone cone cane", "The slide is quite tall."]),
    )

    assert result.passed


def test_content_coverage_fails_when_word_chain_tokens_are_missing() -> None:
    result = validate_content_coverage(
        _word_work_skill(),
        _adapted(["grade", "slide", "quite", "tune tone cone", "The slide is quite tall."]),
    )

    assert not result.passed
    assert any(v.check == "word_chain_coverage" for v in result.violations)


def test_content_coverage_fails_when_short_source_sentence_is_missing() -> None:
    result = validate_content_coverage(
        _word_work_skill(),
        _adapted(["grade", "slide", "quite", "tune tone cone cane"]),
    )

    assert not result.passed
    assert any(v.check == "source_sentence_coverage" for v in result.violations)


def test_content_coverage_passes_with_normalized_source_sentence() -> None:
    result = validate_content_coverage(
        _word_work_skill(),
        _adapted(["grade", "slide", "quite", "tune tone cone cane", "the slide is quite tall"]),
    )

    assert result.passed


def test_decodable_passage_passes_with_read_aloud_title() -> None:
    result = validate_content_coverage(
        _decodable_skill(),
        _adapted(["Read aloud: A Fine Slide"], response_format="read_aloud"),
    )

    assert result.passed


def test_decodable_passage_fails_without_read_aloud_passage_coverage() -> None:
    result = validate_content_coverage(
        _decodable_skill(),
        _adapted(["Write the word grade.", "Circle slide."], response_format="write"),
    )

    assert not result.passed
    assert any(v.check == "decodable_passage_coverage" for v in result.violations)
