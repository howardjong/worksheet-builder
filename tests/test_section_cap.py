"""Tests for adapt/section_cap.py — split over-cap worksheets, never drop content."""

from __future__ import annotations

import logging

import pytest

from adapt.rules import AccommodationRules, build_rules
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from adapt.section_cap import enforce_package_cap, enforce_section_cap
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


def test_at_target_worksheet_count_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """3 worksheets (the AGENTS.md target) should not trigger the overflow warning."""
    with caplog.at_level(logging.WARNING, logger="adapt.section_cap"):
        enforce_section_cap([_worksheet(9, self_assessment=["I can read"])], _rules("1"))
    assert not caplog.records


def test_over_target_worksheet_count_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Splitting past the 3-worksheet target logs a warning but still preserves content."""
    package = [_worksheet(13, self_assessment=["I can read"])]
    with caplog.at_level(logging.WARNING, logger="adapt.section_cap"):
        result = enforce_section_cap(package, _rules("1"))

    # Grade 1 cap is 3 sections/worksheet: 13 sections -> 5 worksheets.
    assert len(result) == 5
    contents = [item.content for ws in result for ch in ws.chunks for item in ch.items]
    assert sorted(contents) == sorted(f"word{i + 1}" for i in range(13))
    assert len(caplog.records) == 1
    assert "5 mini-worksheets" in caplog.records[0].message
    assert "not dropped" in caplog.records[0].message


def _part(family: str, part: int, total: int, number: int) -> AdaptedActivityModel:
    ws = _worksheet(2, number=number, count=total, title=f"{family} (Part {part})")
    return ws


class TestEnforcePackageCap:
    def test_under_cap_is_untouched(self) -> None:
        package = [_part("Word Discovery", 1, 2, 1), _part("Story Time", 1, 2, 2)]
        assert enforce_package_cap(package, 3) is package

    def test_round_robin_keeps_every_family(self) -> None:
        """10-part package (4 Discovery, 4 Builder, 2 Story) → one of each family."""
        package = (
            [_part("Word Discovery", i, 10, i) for i in range(1, 5)]
            + [_part("Word Builder", i, 10, 4 + i) for i in range(1, 5)]
            + [_part("Story Time", i, 10, 8 + i) for i in range(1, 3)]
        )
        result = enforce_package_cap(package, 3)

        titles = [ws.worksheet_title for ws in result]
        assert titles == [
            "Word Discovery (Part 1)",
            "Word Builder (Part 1)",
            "Story Time (Part 1)",
        ]
        assert [ws.worksheet_number for ws in result] == [1, 2, 3]
        assert all(ws.worksheet_count == 3 for ws in result)
        # Breaks between worksheets, none after the last.
        assert result[0].break_prompt is not None
        assert result[1].break_prompt is not None
        assert result[2].break_prompt is None

    def test_second_round_fills_remaining_slots(self) -> None:
        package = [_part("Word Discovery", i, 4, i) for i in range(1, 5)]
        result = enforce_package_cap(package, 2)
        titles = [ws.worksheet_title for ws in result]
        assert titles == ["Word Discovery (Part 1)", "Word Discovery (Part 2)"]

    def test_last_worksheet_gets_fallback_self_assessment(self) -> None:
        package = (
            [_part("Word Discovery", i, 10, i) for i in range(1, 5)]
            + [_part("Word Builder", i, 10, 4 + i) for i in range(1, 5)]
            + [_part("Story Time", i, 10, 8 + i) for i in range(1, 3)]
        )
        result = enforce_package_cap(package, 3, fallback_self_assessment=["I did it"])
        assert result[-1].self_assessment == ["I did it"]
        assert all(ws.self_assessment is None for ws in result[:-1])

    def test_cap_logs_dropped_titles(self, caplog: pytest.LogCaptureFixture) -> None:
        package = [_part("Word Discovery", i, 4, i) for i in range(1, 5)]
        with caplog.at_level(logging.WARNING, logger="adapt.section_cap"):
            enforce_package_cap(package, 1)
        joined = " ".join(r.message for r in caplog.records)
        assert "keeping 1 of 4" in joined
        assert "Word Discovery (Part 2)" in joined
