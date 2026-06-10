"""Fixture-backed worksheet quality report aggregation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from validate.schema import ValidationResult


class WorksheetQualityReport(BaseModel):
    """Combined pass/fail report for a worksheet quality case."""

    case_id: str = Field(description="Stable quality case identifier.")
    content_coverage_passed: bool = Field(description="Whether content coverage passed.")
    adhd_passed: bool = Field(description="Whether ADHD compliance passed.")
    skill_parity_passed: bool = Field(description="Whether skill parity passed.")
    buddy_identity_checked: bool = Field(description="Whether Learning Buddy identity was checked.")
    print_quality_passed: bool = Field(description="Whether print quality passed.")
    blocking_issues: list[str] = Field(
        default_factory=list,
        description="Quality issues that block accepting the worksheet.",
    )


def build_quality_report(
    *,
    case_id: str,
    content_coverage: ValidationResult,
    adhd: ValidationResult,
    skill_parity: ValidationResult,
    print_quality: ValidationResult,
    buddy_required: bool,
    buddy_identity_checked: bool,
) -> WorksheetQualityReport:
    """Combine validator results and buddy identity status into one report."""
    blocking_issues: list[str] = []

    if not content_coverage.passed:
        blocking_issues.append("Content coverage failed")
    if not adhd.passed:
        blocking_issues.append("ADHD compliance failed")
    if not skill_parity.passed:
        blocking_issues.append("Skill parity failed")
    if buddy_required and not buddy_identity_checked:
        blocking_issues.append("Learning Buddy identity check missing")
    if not print_quality.passed:
        blocking_issues.append("Print quality failed")

    return WorksheetQualityReport(
        case_id=case_id,
        content_coverage_passed=content_coverage.passed,
        adhd_passed=adhd.passed,
        skill_parity_passed=skill_parity.passed,
        buddy_identity_checked=buddy_identity_checked,
        print_quality_passed=print_quality.passed,
        blocking_issues=blocking_issues,
    )
