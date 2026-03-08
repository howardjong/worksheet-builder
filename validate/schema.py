"""Validation result schema shared across all validators."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationViolation(BaseModel):
    """A single validation violation."""

    check: str  # e.g., "domain_preserved", "chunk_size_limit"
    severity: str  # "error" | "warning"
    message: str
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Result of a validation pass."""

    validator: str  # "skill_parity" | "age_band" | "adhd_compliance"
    passed: bool
    violations: list[ValidationViolation] = Field(default_factory=list)
    checks_run: int = 0

    def add_violation(
        self,
        check: str,
        message: str,
        severity: str = "error",
        details: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        self.violations.append(
            ValidationViolation(
                check=check,
                severity=severity,
                message=message,
                details=details or {},
            )
        )
        if severity == "error":
            self.passed = False
