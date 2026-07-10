"""Evidence-informed workload budget — how many mini-worksheets THIS lesson earns.

Owner directive 2026-07-07: the learning objectives must be met first, at the
expense of more pages — but bounded by what the science says an ADHD child of
this age can sustain. So the package cap is DERIVED per lesson at the start of
adaptation (objective demand vs. attention budget), not a generic constant.

Evidence base (full citations in docs/research/adhd-workload-budget.md):

- Assigned-task attention norms for typically developing children: roughly
  5-10 minutes for a kindergartner on an ASSIGNED (not self-chosen) task,
  rising to ~15-25 minutes by grades 2-3; a common developmental heuristic is
  "minutes ≈ age" for a single assigned task.
- ADHD discount: children with ADHD show significantly shorter on-task spans
  during academic seatwork than matched classmates (Imeraj et al. 2013,
  J Sch Psychol, doi:10.1016/j.jsp.2013.05.004 — ~75% vs 88% classroom on-task
  time, with the gap widest during individual academic work). Segment budgets
  below sit at or below the LOW end of the typical-child assigned-task range.
- Shortened assignments are a first-line documented ADHD classroom
  accommodation (CDC ADHD classroom guidance; CHADD assignment accommodations).
- Movement breaks between work segments measurably restore on-task behavior
  (school-based active-break trials) — which is why the budget is expressed as
  a few SHORT segments (one mini-worksheet each, brain break between) rather
  than one long sitting.

The numbers are a policy encoding of that evidence, not measurements from any
single study; they are deliberately conservative and per-child adjustable (the
profile's observed avg_session_duration overrides the table downward).
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Literal

from pydantic import BaseModel

from adapt.objective_ledger import build_objective_ledger
from adapt.rules import AccommodationRules
from companion import dosage
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)

# Per-grade (segment_minutes, session_minutes): one mini-worksheet is one
# continuous seatwork segment; a session is all segments with movement breaks
# between them. attention_max = session // segment (K: 2 sheets, 1-3: 3).
GRADE_WORKLOAD: dict[str, tuple[int, int]] = {
    "K": (5, 12),
    "1": (6, 18),
    "2": (8, 24),
    "3": (10, 30),
}

# Nominal essential-practice minutes per objective (policy encoding, same
# spirit as GRADE_WORKLOAD; connected text is larger per its "1 page chunk"
# sufficiency rule in adapt/objective_ledger.py).
OBJECTIVE_MINUTES: dict[str, int] = {
    "obj_decode": 4,
    "obj_encode": 4,
    "obj_manipulation": 4,
    "obj_connected_text": 8,
    "obj_irregular": 3,
}
_DEFAULT_OBJECTIVE_MINUTES = 4


class PackageBudget(BaseModel):
    """Derived workload budget for one lesson + learner."""

    grade: str
    segment_minutes: int
    session_minutes: int
    attention_max_worksheets: int
    essential_objectives: int
    sections_needed: int
    sheets_needed: int
    max_worksheets: int
    objectives_overflow: bool
    rationale: str
    age_years: float | None = None
    severity: str = "moderate"
    essential_minutes: int = 0
    minute_sheets: int = 1
    grade_source: Literal["derived", "profile"] = "profile"


def derive_package_budget(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    today: date | None = None,
) -> PackageBudget:
    """Balance objective demand against the evidence-based attention budget.

    The CHILD owns the attention budget (derived from birthdate/jurisdiction/
    severity when present, else the profile grade's table row) — the lesson's
    grade never sets dosage (P4). Objectives push the sheet count UP in two
    currencies (sections AND essential minutes); the attention ceiling is the
    hard cap.
    """
    today = today or date.today()
    budget_grade, grade_source = dosage.grade_with_source(profile, today)
    table_segment, table_session = GRADE_WORKLOAD.get(budget_grade, GRADE_WORKLOAD["1"])
    derived_segment = dosage.segment_minutes(profile, today)
    segment_minutes = derived_segment if derived_segment is not None else table_segment
    derived_session = dosage.session_minutes(profile, today)
    session_minutes = derived_session if derived_session is not None else table_session
    child_age = (
        round(dosage.age_years(profile.birthdate, today), 1)
        if profile.birthdate is not None
        else None
    )
    child_severity = dosage.severity(profile)

    adjustments: list[str] = []

    # Per-child evidence beats the population table: if we have observed how
    # long this child actually works, never budget a longer session than that
    # (but always at least one segment).
    signals = profile.operational_signals
    if signals is not None and signals.avg_session_duration > 0:
        observed = int(round(signals.avg_session_duration))
        bounded = max(segment_minutes, min(session_minutes, observed))
        if bounded != session_minutes:
            adjustments.append(
                f"session {session_minutes}->{bounded} min (observed avg_session_duration)"
            )
            session_minutes = bounded

    # A "small" chunking accommodation signals higher distraction impact:
    # budget one fewer segment.
    if profile.accommodations.chunking_level == "small":
        reduced = max(segment_minutes, session_minutes - segment_minutes)
        if reduced != session_minutes:
            adjustments.append(f"session {session_minutes}->{reduced} min (chunking_level=small)")
            session_minutes = reduced

    attention_max = max(1, math.floor(session_minutes / segment_minutes + 0.5))

    essential, sections_needed, essential_minutes = _objective_demand(skill, rules)
    section_sheets = max(1, math.ceil(sections_needed / rules.max_sections_per_worksheet))
    minute_sheets = (
        max(1, math.ceil(essential_minutes / segment_minutes)) if essential_minutes else 1
    )
    sheets_needed = max(section_sheets, minute_sheets)
    max_worksheets = min(attention_max, sheets_needed)
    overflow = sheets_needed > attention_max

    rationale = (
        f"grade {budget_grade} ({grade_source}): segment {segment_minutes} min, session "
        f"{session_minutes} min -> attention ceiling {attention_max} sheet(s); "
        f"{essential} essential objective(s) -> {sections_needed} section(s) + "
        f"{essential_minutes} essential min -> {sheets_needed} sheet(s) needed "
        f"-> cap {max_worksheets}"
    )
    if child_age is not None:
        rationale += f"; dosage: age {child_age}y x {child_severity}"
    if adjustments:
        rationale += "; adjustments: " + ", ".join(adjustments)
    if overflow:
        rationale += (
            "; OVERFLOW: objectives exceed one session — capped at the attention "
            "ceiling, remainder belongs to a second sitting"
        )

    return PackageBudget(
        grade=budget_grade,
        segment_minutes=segment_minutes,
        session_minutes=session_minutes,
        attention_max_worksheets=attention_max,
        essential_objectives=essential,
        sections_needed=sections_needed,
        sheets_needed=sheets_needed,
        max_worksheets=max_worksheets,
        objectives_overflow=overflow,
        rationale=rationale,
        age_years=child_age,
        severity=child_severity,
        essential_minutes=essential_minutes,
        minute_sheets=minute_sheets,
        grade_source=grade_source,
    )


def _objective_demand(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> tuple[int, int, int]:
    """(essential count, sections needed, essential nominal minutes).

    Each essential objective cell needs ceil(min_practice_count /
    max_items_per_chunk) sections. Falls back to a per-source-item-category
    estimate if the ledger cannot be built.
    """
    try:
        ledger = build_objective_ledger(skill)
        essential = [c for c in ledger.objectives if c.importance == "essential"]
        if essential:
            sections = sum(
                max(1, math.ceil(cell.min_practice_count / rules.max_items_per_chunk))
                for cell in essential
            )
            minutes = sum(
                OBJECTIVE_MINUTES.get(cell.objective_id, _DEFAULT_OBJECTIVE_MINUTES)
                for cell in essential
            )
            return len(essential), sections, minutes
    except Exception as exc:
        logger.warning("Workload budget: objective ledger unavailable (%s)", exc)

    categories = {si.item_type for si in skill.source_items}
    return 0, max(1, len(categories)), 0


CapMode = Literal["auto"]


def resolve_package_cap(
    raw: str,
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
) -> tuple[int | None, PackageBudget | None]:
    """Resolve WORKSHEET_MAX_WORKSHEETS into a concrete cap.

    "auto" -> evidence-based budget; positive int -> fixed cap; anything else
    (unset, "0", junk) -> no cap (the photo path's split-never-trim default).
    """
    value = raw.strip().lower()
    if value == "auto":
        budget = derive_package_budget(skill, profile, rules)
        return budget.max_worksheets, budget
    try:
        fixed = int(value)
    except ValueError:
        return None, None
    return (fixed, None) if fixed >= 1 else (None, None)
