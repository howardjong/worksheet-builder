"""Post-hoc objective-sufficiency validation for a finished lesson package.

Thin composition of the machinery the LLM planner already uses, so the
package validator and the planner can never disagree about what "covered"
means (Q4/P3a). Photo path keeps validate/content_coverage.py.
"""

from __future__ import annotations

from adapt.objective_ledger import build_objective_ledger
from adapt.schema import AdaptedActivityModel
from skill.schema import LiteracySkillModel
from validate.objective_coverage import (
    ObjectiveCoverageResult,
    build_evidence_index,
    evaluate_objective_coverage,
)

__all__ = ["validate_objective_package", "ObjectiveCoverageResult"]


def validate_objective_package(
    skill_model: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
) -> ObjectiveCoverageResult:
    ledger = build_objective_ledger(skill_model)
    evidence = build_evidence_index(worksheets, ledger)
    return evaluate_objective_coverage(ledger, evidence, worksheets=worksheets)
