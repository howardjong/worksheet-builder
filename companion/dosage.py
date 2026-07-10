"""Run-time dosage derivations from the learner profile (spec 2026-07-10).

Everything is computed from the profile at call time — nothing stored, so
nothing goes stale. birthdate is derivation-only: it must never enter LLM
prompts, design specs, rendered pages, or artifacts; derived age_years and
grade may.
"""

from __future__ import annotations

import logging
import math
from datetime import date

from companion.schema import LearnerProfile

logger = logging.getLogger(__name__)

_SEVERITY_MULTIPLIER = {"mild": 0.85, "moderate": 0.70, "severe": 0.55}
# "moderate" matches the calibration implicit in adapt/workload.GRADE_WORKLOAD
# (typical grade-2 child at 7.5y: 7.5 * 1.5 * 0.70 = 7.9 -> 8 min, the table value).
_DEFAULT_SEVERITY = "moderate"
_AGE_MINUTES_PER_YEAR = 1.5
_SEGMENT_MIN, _SEGMENT_MAX = 4, 12
# Homework-norm session: 10 minutes per grade number (K=0), clamped.
_SESSION_PER_GRADE = 10
_SESSION_MIN, _SESSION_MAX = 12, 30
_SUPPORTED_JURISDICTIONS = {"CA-ON"}


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def age_years(birthdate: date, today: date) -> float:
    return (today - birthdate).days / 365.25


def severity(profile: LearnerProfile) -> str:
    return profile.adhd_severity or _DEFAULT_SEVERITY


def derived_grade(birthdate: date, jurisdiction: str, today: date) -> str | None:
    """CA-ON grade: Dec-31 entry cutoff; rolls July 1 (Ontario classes end in
    June — summer practice targets the INCOMING grade). None if unsupported."""
    if jurisdiction not in _SUPPORTED_JURISDICTIONS:
        logger.warning(
            "dosage: unsupported jurisdiction %r; using profile grade_level", jurisdiction
        )
        return None
    school_year_start = today.year if today.month >= 7 else today.year - 1
    number = school_year_start - birthdate.year - 5
    if number <= 0:
        if number < 0:
            logger.warning("dosage: derived grade below K; clamping to K")
        return "K"
    if number > 3:
        logger.warning("dosage: derived grade %s above product range; clamping to 3", number)
        return "3"
    return str(number)


def grade_with_source(profile: LearnerProfile, today: date | None = None) -> tuple[str, str]:
    """The child's current grade and where it came from ("derived"|"profile")."""
    today = today or date.today()
    if profile.birthdate is not None and profile.jurisdiction is not None:
        derived = derived_grade(profile.birthdate, profile.jurisdiction, today)
        if derived is not None:
            if derived != profile.grade_level:
                logger.warning(
                    "dosage: profile grade_level=%r is stale; derived grade is %r",
                    profile.grade_level,
                    derived,
                )
            return derived, "derived"
    return profile.grade_level, "profile"


def current_grade(profile: LearnerProfile, today: date | None = None) -> str:
    return grade_with_source(profile, today)[0]


def segment_minutes(profile: LearnerProfile, today: date | None = None) -> int | None:
    """Age-based attention segment; None when no birthdate (use grade table)."""
    if profile.birthdate is None:
        return None
    age = age_years(profile.birthdate, today or date.today())
    raw = age * _AGE_MINUTES_PER_YEAR * _SEVERITY_MULTIPLIER[severity(profile)]
    return min(_SEGMENT_MAX, max(_SEGMENT_MIN, _round_half_up(raw)))


def session_minutes(profile: LearnerProfile, today: date | None = None) -> int | None:
    """Jurisdiction homework-norm session; None when unsupported (use grade table)."""
    if profile.jurisdiction not in _SUPPORTED_JURISDICTIONS:
        return None
    grade = current_grade(profile, today)
    number = 0 if grade == "K" else int(grade)
    return min(_SESSION_MAX, max(_SESSION_MIN, _SESSION_PER_GRADE * number))
