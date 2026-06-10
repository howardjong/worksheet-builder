"""Tests for fixture-backed worksheet quality reports."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from validate.quality_report import WorksheetQualityReport, build_quality_report
from validate.schema import ValidationResult


class ExpectedQualityFields(BaseModel):
    domain: str
    specific_skill: str
    target_words: list[str]
    must_include_activity_types: list[str]
    max_items_per_chunk_small: int
    buddy_required: bool


class QualityCaseFixture(BaseModel):
    case_id: str
    profile: str
    theme_id: str
    expected: ExpectedQualityFields


def _validation_result(validator: str, passed: bool) -> ValidationResult:
    return ValidationResult(validator=validator, passed=passed, checks_run=1)


def test_failed_content_coverage_produces_blocking_issue() -> None:
    report = build_quality_report(
        case_id="lesson_cvce_case",
        content_coverage=_validation_result("content_coverage", passed=False),
        adhd=_validation_result("adhd_compliance", passed=True),
        skill_parity=_validation_result("skill_parity", passed=True),
        print_quality=_validation_result("print_quality", passed=True),
        buddy_required=False,
        buddy_identity_checked=False,
    )

    assert not report.content_coverage_passed
    assert "Content coverage failed" in report.blocking_issues


def test_missing_buddy_identity_check_blocks_when_expected() -> None:
    report = build_quality_report(
        case_id="lesson_cvce_case",
        content_coverage=_validation_result("content_coverage", passed=True),
        adhd=_validation_result("adhd_compliance", passed=True),
        skill_parity=_validation_result("skill_parity", passed=True),
        print_quality=_validation_result("print_quality", passed=True),
        buddy_required=True,
        buddy_identity_checked=False,
    )

    assert not report.buddy_identity_checked
    assert "Learning Buddy identity check missing" in report.blocking_issues


def test_all_quality_gates_pass_without_blocking_issues() -> None:
    report = build_quality_report(
        case_id="lesson_cvce_case",
        content_coverage=_validation_result("content_coverage", passed=True),
        adhd=_validation_result("adhd_compliance", passed=True),
        skill_parity=_validation_result("skill_parity", passed=True),
        print_quality=_validation_result("print_quality", passed=True),
        buddy_required=True,
        buddy_identity_checked=True,
    )

    assert report.blocking_issues == []
    roundtrip = WorksheetQualityReport.model_validate_json(report.model_dump_json())
    assert roundtrip == report


def test_quality_case_fixture_loads_and_validates_expected_fields() -> None:
    fixture_path = Path("tests/fixtures/quality_cases/lesson_cvce_case.json")
    fixture = QualityCaseFixture.model_validate(json.loads(fixture_path.read_text()))

    assert fixture.case_id == "lesson_cvce_case"
    assert fixture.profile == "profiles/ian.yaml"
    assert fixture.theme_id == "roblox_obby"
    assert fixture.expected.domain == "phonics"
    assert fixture.expected.specific_skill == "cvce_pattern"
    assert fixture.expected.target_words == ["grade", "slide", "quite"]
    assert fixture.expected.must_include_activity_types == ["word_chain", "write", "read_aloud"]
    assert fixture.expected.max_items_per_chunk_small == 3
    assert fixture.expected.buddy_required is True
