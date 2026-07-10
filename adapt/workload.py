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
from typing import Literal

from pydantic import BaseModel

from adapt.objective_ledger import build_objective_ledger
from adapt.rules import AccommodationRules
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


def derive_package_budget(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
) -> PackageBudget:
    """Balance objective demand against the evidence-based attention budget.

    Objectives push the sheet count UP (they must be met first); the attention
    budget is the hard ceiling (an unfinishable package teaches nothing). When
    demand exceeds the ceiling, the package is capped and the overflow is
    flagged loudly — the remainder belongs to a second sitting, not this one.
    """
    segment_minutes, session_minutes = GRADE_WORKLOAD.get(
        skill.grade_level, GRADE_WORKLOAD["1"]
    )

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
            adjustments.append(
                f"session {session_minutes}->{reduced} min (chunking_level=small)"
            )
            session_minutes = reduced

    attention_max = max(1, session_minutes // segment_minutes)

    essential, sections_needed = _objective_demand(skill, rules)
    sheets_needed = max(1, math.ceil(sections_needed / rules.max_sections_per_worksheet))
    max_worksheets = min(attention_max, sheets_needed)
    overflow = sheets_needed > attention_max

    rationale = (
        f"grade {skill.grade_level}: segment {segment_minutes} min, session "
        f"{session_minutes} min -> attention ceiling {attention_max} sheet(s); "
        f"{essential} essential objective(s) -> {sections_needed} section(s) -> "
        f"{sheets_needed} sheet(s) needed -> cap {max_worksheets}"
    )
    if adjustments:
        rationale += "; adjustments: " + ", ".join(adjustments)
    if overflow:
        rationale += (
            "; OVERFLOW: objectives exceed one session — capped at the attention "
            "ceiling, remainder belongs to a second sitting"
        )

    return PackageBudget(
        grade=skill.grade_level,
        segment_minutes=segment_minutes,
        session_minutes=session_minutes,
        attention_max_worksheets=attention_max,
        essential_objectives=essential,
        sections_needed=sections_needed,
        sheets_needed=sheets_needed,
        max_worksheets=max_worksheets,
        objectives_overflow=overflow,
        rationale=rationale,
    )


def _objective_demand(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> tuple[int, int]:
    """(essential objective count, practice sections needed to meet them).

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
            return len(essential), sections
    except Exception as exc:
        logger.warning("Workload budget: objective ledger unavailable (%s)", exc)

    categories = {si.item_type for si in skill.source_items}
    sections = max(1, len(categories))
    return 0, sections


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
