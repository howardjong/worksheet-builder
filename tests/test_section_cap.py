"""Tests for adapt/section_cap.py — split over-cap worksheets, never drop content."""

from __future__ import annotations

from adapt.rules import AccommodationRules, build_rules
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from adapt.section_cap import enforce_section_cap
from companion.schema import Accommodations, LearnerProfile


def _rules(grade: str = "1") -> AccommodationRules:
    profile = LearnerProfile(name="t", grade_level=grade, accommodations=Accommodations())
    return build_rules(profile)


def _chunk(chunk_id: int) -> ActivityChunk:
    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal=f"Goal {chunk_id}",
        instructions=[Step(number=1, text="Do the task.")],
        items=[
            ActivityItem(
                item_id=chunk_id * 10,
                content=f"word{chunk_id}",
                response_format="write",
            )
        ],
        response_format="write",
        time_estimate="About 2 minutes",
    )


def _worksheet(
    chunk_count: int,
    *,
    number: int = 1,
    count: int = 1,
    title: str | None = "Word Work",
    break_prompt: str | None = None,
    self_assessment: list[str] | None = None,
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvc",
        chunks=[_chunk(i + 1) for i in range(chunk_count)],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=number,
        worksheet_count=count,
        worksheet_title=title,
        break_prompt=break_prompt,
        self_assessment=self_assessment,
    )


def test_compliant_package_unchanged() -> None:
    package = [
        _worksheet(2, number=1, count=2, break_prompt="Stretch!"),
        _worksheet(3, number=2, count=2, self_assessment=["I can read"]),
    ]
    result = enforce_section_cap(package, _rules("1"))

    assert len(result) == 2
    assert [ws.worksheet_number for ws in result] == [1, 2]
    assert all(ws.worksheet_count == 2 for ws in result)
    assert result[0].break_prompt == "Stretch!"
    assert result[1].break_prompt is None
    assert result[1].self_assessment == ["I can read"]


def test_nine_section_worksheet_splits_without_dropping_content() -> None:
    package = [_worksheet(9, self_assessment=["I can read"])]
    result = enforce_section_cap(package, _rules("1"))

    # Grade 1 cap is 3: 9 sections -> 3 worksheets of 3.
    assert len(result) == 3
    assert all(len(ws.chunks) <= 3 for ws in result)
    contents = [item.content for ws in result for ch in ws.chunks for item in ch.items]
    assert sorted(contents) == sorted(f"word{i + 1}" for i in range(9))
    # Renumbered package
    assert [ws.worksheet_number for ws in result] == [1, 2, 3]
    assert all(ws.worksheet_count == 3 for ws in result)
    # Chunk ids restart at 1 within each part
    assert [ch.chunk_id for ch in result[1].chunks] == [1, 2, 3]
    # Titles disambiguated
    assert result[0].worksheet_title == "Word Work (Part 1)"
    assert result[2].worksheet_title == "Word Work (Part 3)"
    # Self-assessment only on the final part; breaks on non-final parts
    assert result[0].self_assessment is None
    assert result[2].self_assessment == ["I can read"]
    assert result[0].break_prompt is not None
    assert result[1].break_prompt is not None
    assert result[2].break_prompt is None


def test_split_uses_grade_cap() -> None:
    result = enforce_section_cap([_worksheet(4)], _rules("K"))

    assert len(result) == 2
    assert all(len(ws.chunks) <= 2 for ws in result)
