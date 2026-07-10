# Adaptive Dosage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive worksheet dosage (segment minutes, session minutes, page count) from the learner's birthdate, jurisdiction, and ADHD severity; add minutes-based page escalation; fix P4 (lesson grade no longer drives the attention budget).

**Architecture:** A new pure-derivation module `companion/dosage.py` computes age/grade/segment/session from profile facts at run time (nothing stored, nothing stale). `adapt/workload.py::derive_package_budget` consumes those derivations, switches its grade source from lesson to child, rounds the attention ceiling, and adds essential-minutes demand alongside section-count demand. A handful of consumers swap `profile.grade_level` for the derived current grade.

**Tech Stack:** Python 3.13 (CI mypy 3.11 — `datetime.date` only, no 3.12+ syntax), Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-07-10-adaptive-dosage-profile-design.md`

## Global Constraints

- Work in `/Users/hjong/Documents/Projects/worksheet-builder` on branch `claude/review-recent-refactoring-rma786`; venv `.venv/bin/python`; gates `make test` / `make lint` / `make typecheck`.
- Commits: NO Co-Authored-By trailer; `env -u PIP_UPLOADED_PRIOR_TO git commit ...` if hooks need installing; if ruff-format reformats and aborts, `git add -u` and retry.
- TDD: failing test first for every behavior change.
- Exact policy values (verbatim from spec): severity multipliers mild **0.85** / moderate **0.70** / severe **0.55**, default severity **"moderate"**; age factor **1.5 min/year**; segment clamp **[4, 12]**; session norm **10 × grade_number** clamped **[12, 30]** (K → 12), CA-* jurisdictions only (initially `CA-ON`); grade rolls **July 1**, entry cutoff Dec 31, `grade_number = school_year_start_year − birth_year − 5` clamped K..3; attention ceiling **round-half-up**(session/segment); objective nominal minutes `obj_decode 4, obj_encode 4, obj_manipulation 4, obj_connected_text 8, obj_irregular 3` (unknown ids → 4).
- **Privacy (binding):** `birthdate` never appears in LLM prompts, `WorksheetDesignSpec`, rendered pages, or artifacts. Artifacts may carry derived `age_years` (1 decimal) and derived grade.
- **Intended behavior changes** (do not "fix" back): (a) the budget's grade source becomes the CHILD (derived or profile grade), never `skill.grade_level`; (b) minutes-demand escalation applies to ALL profiles — legacy sheet counts may rise (e.g. legacy grade-2 lesson 74: essential 20 min / 8-min segments → 3 sheets, was 2).
- Rounding is **half-up** everywhere (`math.floor(x + 0.5)`), never Python's banker's `round()`.

---

### Task 1: Profile fields + `companion/dosage.py` derivations

**Files:**
- Modify: `companion/schema.py` (`LearnerProfile`, ~line 118)
- Create: `companion/dosage.py`
- Test: `tests/test_dosage.py` (new)

**Interfaces:**
- Produces (relied on by Tasks 2-3):
  - `LearnerProfile.birthdate: date | None = None`, `.jurisdiction: str | None = None`, `.adhd_severity: Literal["mild","moderate","severe"] | None = None`
  - `companion.dosage.age_years(birthdate: date, today: date) -> float`
  - `companion.dosage.severity(profile: LearnerProfile) -> str`
  - `companion.dosage.derived_grade(birthdate: date, jurisdiction: str, today: date) -> str | None`
  - `companion.dosage.grade_with_source(profile: LearnerProfile, today: date | None = None) -> tuple[str, str]` (source `"derived"` or `"profile"`)
  - `companion.dosage.current_grade(profile: LearnerProfile, today: date | None = None) -> str`
  - `companion.dosage.segment_minutes(profile: LearnerProfile, today: date | None = None) -> int | None` (None → caller uses grade table)
  - `companion.dosage.session_minutes(profile: LearnerProfile, today: date | None = None) -> int | None` (None → caller uses grade table)

- [ ] **Step 1: Write the failing tests** — new file `tests/test_dosage.py`:

```python
"""Dosage derivations from profile facts (spec 2026-07-10)."""

from datetime import date

import pytest

from companion.dosage import (
    age_years,
    current_grade,
    derived_grade,
    grade_with_source,
    segment_minutes,
    session_minutes,
    severity,
)
from companion.schema import LearnerProfile

IAN_BD = date(2019, 9, 21)
JULY = date(2026, 7, 10)


def _profile(**overrides) -> LearnerProfile:
    data = {"name": "Ian", "grade_level": "2"}
    data.update(overrides)
    return LearnerProfile.model_validate(data)


def test_age_years_ian_in_july_2026() -> None:
    assert age_years(IAN_BD, JULY) == pytest.approx(6.80, abs=0.02)


def test_derived_grade_rolls_july_first() -> None:
    assert derived_grade(IAN_BD, "CA-ON", JULY) == "2"          # summer -> incoming grade
    assert derived_grade(IAN_BD, "CA-ON", date(2026, 6, 30)) == "1"   # still last school year
    assert derived_grade(IAN_BD, "CA-ON", date(2027, 6, 30)) == "2"   # holds through June
    assert derived_grade(IAN_BD, "CA-ON", date(2027, 7, 1)) == "3"


def test_derived_grade_dec31_cutoff_and_clamps() -> None:
    # Dec-2019-born child is the same cohort as Ian (cutoff Dec 31).
    assert derived_grade(date(2019, 12, 30), "CA-ON", JULY) == "2"
    # Too young / too old clamp to product range.
    assert derived_grade(date(2022, 5, 1), "CA-ON", JULY) == "K"
    assert derived_grade(date(2014, 5, 1), "CA-ON", JULY) == "3"


def test_unsupported_jurisdiction_returns_none() -> None:
    assert derived_grade(IAN_BD, "US-NY", JULY) is None


def test_grade_source_and_stale_profile_fallbacks() -> None:
    derived = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", grade_level="1")
    assert grade_with_source(derived, JULY) == ("2", "derived")  # derived wins over stale '1'
    legacy = _profile(grade_level="1")
    assert grade_with_source(legacy, JULY) == ("1", "profile")
    unsupported = _profile(birthdate=IAN_BD, jurisdiction="US-NY", grade_level="1")
    assert grade_with_source(unsupported, JULY) == ("1", "profile")
    assert current_grade(derived, JULY) == "2"


def test_severity_default_and_explicit() -> None:
    assert severity(_profile()) == "moderate"
    assert severity(_profile(adhd_severity="severe")) == "severe"


def test_segment_minutes_worked_example_and_clamps() -> None:
    ian = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate")
    assert segment_minutes(ian, JULY) == 7            # 6.80 * 1.5 * 0.70 = 7.14 -> 7
    assert segment_minutes(_profile(), JULY) is None  # no birthdate -> table fallback
    mild_teenish = _profile(birthdate=date(2013, 1, 1), adhd_severity="mild")
    assert segment_minutes(mild_teenish, JULY) == 12  # 13.5*1.5*0.85=17.2 -> clamp 12
    severe_toddler = _profile(birthdate=date(2023, 1, 1), adhd_severity="severe")
    assert segment_minutes(severe_toddler, JULY) == 4  # 3.5*1.5*0.55=2.9 -> clamp 4


def test_session_minutes_norm_and_clamps() -> None:
    ian = _profile(birthdate=IAN_BD, jurisdiction="CA-ON")
    assert session_minutes(ian, JULY) == 20                     # 10 * grade 2
    assert session_minutes(_profile(), JULY) is None            # no jurisdiction -> table
    k_kid = _profile(birthdate=date(2021, 3, 1), jurisdiction="CA-ON")
    assert session_minutes(k_kid, JULY) == 12                   # K -> clamp floor 12
    g1 = _profile(jurisdiction="CA-ON", grade_level="1")        # no birthdate: profile grade
    assert session_minutes(g1, JULY) == 12                      # 10 -> clamp 12


def test_profile_yaml_roundtrip_with_new_fields(tmp_path) -> None:
    from companion.schema import load_profile, save_profile

    p = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate")
    path = tmp_path / "p.yaml"
    save_profile(p, path)
    loaded = load_profile(path)
    assert loaded.birthdate == IAN_BD
    assert loaded.jurisdiction == "CA-ON"
    assert loaded.adhd_severity == "moderate"


def test_invalid_severity_rejected() -> None:
    with pytest.raises(ValueError):
        _profile(adhd_severity="extreme")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_dosage.py -v`
Expected: FAIL with `ImportError: cannot import name ... from 'companion.dosage'` (module does not exist).

- [ ] **Step 3: Add the schema fields** — in `companion/schema.py`, add `from datetime import date` and `from typing import Literal` to imports, then in `LearnerProfile` after `accommodations`:

```python
    # --- Dosage inputs (spec 2026-07-10; all optional, absent -> legacy) ---
    # birthdate is DERIVATION-ONLY: never emit it into prompts, design specs,
    # rendered pages, or artifacts (derived age/grade are fine).
    birthdate: date | None = None
    jurisdiction: str | None = None  # ISO country-subdivision, e.g. "CA-ON"
    adhd_severity: Literal["mild", "moderate", "severe"] | None = None
```

- [ ] **Step 4: Create `companion/dosage.py`**

```python
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


def grade_with_source(
    profile: LearnerProfile, today: date | None = None
) -> tuple[str, str]:
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dosage.py tests/test_companion.py -v`
Expected: all PASS (test_companion.py guards the schema change is backward compatible).

- [ ] **Step 6: Commit**

```bash
git add companion/schema.py companion/dosage.py tests/test_dosage.py
git commit -m "feat: dosage derivations from birthdate/jurisdiction/severity (derivation-only privacy)"
```

---

### Task 2: Workload budget — child-owned dosage + minutes-based escalation

**Files:**
- Modify: `adapt/workload.py` (`derive_package_budget` lines 72-145, `_objective_demand` lines 148-172, `PackageBudget` lines 57-69)
- Test: `tests/test_workload.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces: `derive_package_budget(skill, profile, rules, today: date | None = None) -> PackageBudget`; `PackageBudget` gains `age_years: float | None = None`, `severity: str = "moderate"`, `essential_minutes: int = 0`, `minute_sheets: int = 1`, `grade_source: str = "profile"`; `PackageBudget.grade` now reports the grade the budget used (the CHILD's). `resolve_package_cap` signature unchanged.

- [ ] **Step 1: Write the failing tests** — extend `tests/test_workload.py` (reuse its existing skill/profile/rules fixture builders; add `from datetime import date` and the Ian constants):

```python
IAN_BD = date(2019, 9, 21)
JULY = date(2026, 7, 10)


def test_budget_uses_child_grade_not_lesson_grade() -> None:
    # P4: lesson grade 2, profile grade 1, no birthdate -> table row "1" (6/18).
    skill = _skill(grade_level="2")          # existing fixture builder pattern
    profile = _profile(grade_level="1")
    budget = derive_package_budget(skill, profile, _rules(), today=JULY)
    assert budget.grade == "1"
    assert budget.grade_source == "profile"
    assert (budget.segment_minutes, budget.session_minutes) == (6, 18)


def test_budget_worked_example_ian_lesson74_shape() -> None:
    # Spec worked example: 7-min segments, 20-min session, ceiling 3,
    # essential minutes 20 (decode+encode+manip 4 each + connected 8) -> 3 sheets.
    skill = _skill_with_essentials(                # build a skill whose ledger yields
        ["obj_decode", "obj_encode", "obj_manipulation", "obj_connected_text"]
    )                                              # (word_list + word_chain + passage sources)
    profile = _profile(
        grade_level="2", birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate"
    )
    budget = derive_package_budget(skill, profile, _rules(), today=JULY)
    assert budget.segment_minutes == 7
    assert budget.session_minutes == 20
    assert budget.attention_max_worksheets == 3     # round(20/7) = 3, not floor 2
    assert budget.essential_minutes == 20
    assert budget.minute_sheets == 3
    assert budget.max_worksheets == 3
    assert budget.age_years == pytest.approx(6.8, abs=0.05)
    assert budget.grade_source == "derived"
    assert "age 6.8" in budget.rationale


def test_minutes_demand_escalates_legacy_profiles_too() -> None:
    # Same essential mix, plain grade-2 profile: 8-min segments, 24-min session,
    # sections say 2 sheets but 20 essential minutes / 8 = 3 -> cap 3.
    skill = _skill_with_essentials(
        ["obj_decode", "obj_encode", "obj_manipulation", "obj_connected_text"]
    )
    budget = derive_package_budget(skill, _profile(grade_level="2"), _rules(), today=JULY)
    assert budget.minute_sheets == 3
    assert budget.max_worksheets == 3


def test_attention_ceiling_rounding_no_drift_at_table_values() -> None:
    # 12/5 -> 2, 18/6 -> 3, 24/8 -> 3, 30/10 -> 3 (half-up must not change these).
    for grade, expected in (("K", 2), ("1", 3), ("2", 3), ("3", 3)):
        budget = derive_package_budget(
            _skill(grade_level=grade), _profile(grade_level=grade), _rules(), today=JULY
        )
        assert budget.attention_max_worksheets == expected
```

(`_skill_with_essentials` is a test helper to add in this file: build a `LiteracySkillModel` via the existing fixture pattern whose `source_items` include a word list, at least one `word_chain`, and a `passage` — the ledger then yields exactly those four essential cells, as in the lesson-74 artifact. Copy the source-item shapes from existing ledger tests in `tests/test_objective_ledger.py` if present, else from `tests/test_workload.py`'s own skill builder.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_workload.py -v`
Expected: new tests FAIL (`unexpected keyword argument 'today'`, missing fields).

- [ ] **Step 3: Implement** — in `adapt/workload.py`:

Add imports:

```python
from datetime import date

from companion import dosage
```

Add the nominal-minutes table next to `GRADE_WORKLOAD`:

```python
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
```

Extend `PackageBudget` (additive, defaults keep old constructions valid):

```python
    age_years: float | None = None
    severity: str = "moderate"
    essential_minutes: int = 0
    minute_sheets: int = 1
    grade_source: str = "profile"
```

Rewrite the head of `derive_package_budget` (signature + grade/dosage resolution replacing lines 84-86) and the demand block (lines 113-125). Replacement body:

```python
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
    segment_minutes = dosage.segment_minutes(profile, today) or table_segment
    session_minutes = dosage.session_minutes(profile, today) or table_session
    child_age = (
        round(dosage.age_years(profile.birthdate, today), 1)
        if profile.birthdate is not None
        else None
    )
    child_severity = dosage.severity(profile)
```

Keep the existing `adjustments` block (observed `avg_session_duration`, `chunking_level=small`) verbatim after this. Then replace the ceiling/demand/rationale block:

```python
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
```

`_objective_demand` returns a triple now:

```python
def _objective_demand(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> tuple[int, int, int]:
    """(essential count, sections needed, essential nominal minutes)."""
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
```

- [ ] **Step 4: Fix existing workload tests that encoded the old behavior**

Existing tests in `tests/test_workload.py` that (a) fed mismatched skill/profile grades expecting the LESSON grade's table row, or (b) assert the old rationale format (`"grade 2: segment"` — new format is `"grade 2 (profile): segment"` and the demand clause gained `+ N essential min`), or (c) assert sheet counts that minutes-demand now raises — update them to the new intended behavior, noting each change in the commit body. Do NOT weaken assertions; encode the new exact values.

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_workload.py tests/test_dosage.py -v` → PASS.
Also run: `.venv/bin/python -m pytest tests/test_transform_lesson.py -v` (budget rationale flows into logs/artifacts there; fix any stale string assertions the same way).

```bash
git add adapt/workload.py tests/test_workload.py tests/test_transform_lesson.py
git commit -m "feat: child-owned attention budget + minutes-based page escalation (P4 fix)"
```

---

### Task 3: Consumers use current_grade; ian.yaml gains dosage facts; privacy guard

**Files:**
- Modify: `adapt/rules.py:161`, `transform.py:1085`, `transform.py:1210`, `adapt/direct_compiler.py:69`, `adapt/llm_adapt.py:130`, `adapt/llm_planner.py:312`, `profiles/ian.yaml`
- Test: `tests/test_dosage.py` (privacy test), plus touched assertions in `tests/test_llm_planner.py` / `tests/test_rules.py` if any encode `profile.grade_level` mismatches

**Interfaces:**
- Consumes: `companion.dosage.current_grade(profile)`.

- [ ] **Step 1: Write the failing privacy + consumer tests** — append to `tests/test_dosage.py`:

```python
def test_birthdate_never_enters_prompts_or_design_spec() -> None:
    from adapt.llm_planner import build_planner_prompt  # use the module's actual prompt builder name
    # If llm_planner exposes no single builder, grep its `Grade:` f-string function and call that.
    profile = _profile(
        birthdate=IAN_BD, jurisdiction="CA-ON", adhd_severity="moderate", grade_level="1"
    )
    prompt = _build_any_planner_prompt(profile)  # helper: call the real prompt-building path
    assert "2019" not in prompt
    assert "birthdate" not in prompt.lower()
    assert "Grade: 2" in prompt  # derived grade, not the stale '1'


def test_rules_use_current_grade() -> None:
    from adapt.rules import AccommodationRules

    profile = _profile(birthdate=IAN_BD, jurisdiction="CA-ON", grade_level="1")
    rules = AccommodationRules.from_profile(profile)  # match the actual constructor at rules.py:155-165
    assert rules.max_sections_per_worksheet == _expected_grade2_sections(rules)
```

(Adapt the two helpers to the file's real APIs — `adapt/rules.py:161` shows the constructor reading `profile.grade_level`; call whatever function wraps that line. The binding assertions are: derived grade drives rules; prompt shows the derived grade; the birthdate string appears nowhere.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_dosage.py -v`
Expected: new tests FAIL (`Grade: 1` in prompt; rules built from grade 1).

- [ ] **Step 3: Implement the consumer swaps** — identical one-line pattern, six places. Add `from companion.dosage import current_grade` to each file's imports, then:

- `adapt/rules.py:161`: `grade = profile.grade_level` → `grade = current_grade(profile)`
- `transform.py:1085` and `transform.py:1210`: `validate_age_band(adapted, profile.grade_level)` → `validate_age_band(adapted, current_grade(profile))`
- `adapt/direct_compiler.py:69`, `adapt/llm_adapt.py:130`, `adapt/llm_planner.py:312`: `Grade: {profile.grade_level}` → `Grade: {current_grade(profile)}`

- [ ] **Step 4: Update `profiles/ian.yaml`** — change `grade_level: '1'` to `grade_level: '2'` and add (top-level keys, alphabetical placement is fine):

```yaml
adhd_severity: moderate
birthdate: 2019-09-21
jurisdiction: CA-ON
```

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_dosage.py tests/test_llm_planner.py tests/test_llm_adapt.py -v` → PASS (fix any test that stubbed `profile.grade_level` expectations, encoding the new derived-grade values).

```bash
git add adapt/rules.py transform.py adapt/direct_compiler.py adapt/llm_adapt.py adapt/llm_planner.py profiles/ian.yaml tests/
git commit -m "feat: consumers use derived current grade; ian.yaml carries dosage facts"
```

---

### Task 4: Full gates + live lesson-74 verification

- [ ] **Step 1: Full gates**

Run: `make test && make lint && make typecheck`
Expected: all green (CI mypy is 3.11 — verify no 3.12+-only syntax crept in).

- [ ] **Step 2: Sweep for privacy**

Run: `grep -rn "birthdate" adapt/ render/ validate/ skill/ --include="*.py" | grep -v test`
Expected: zero hits outside `companion/` (dosage + schema) — no production consumer touches the raw field.

- [ ] **Step 3: Live run (controller performs this — it spends API budget and needs visual judgment)**

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
.venv/bin/python transform.py --lesson 74 --profile profiles/ian.yaml \
  --theme roblox_obby --output ./output/lesson74_dosage/
```

Verify in order: `workload_budget.json` shows segment 7 / session 20 / ceiling 3 / essential_minutes 20 / cap 3 / `grade_source: derived` / age ≈ 6.8; the merged PDF has **3 pages** including a reading/sentence-writing (Story Time) sheet; feedback strip on all sheets, decision hint on the last only; no "2019" anywhere in artifacts' prompt files (`grep -r 2019 output/lesson74_dosage/artifacts/render_*/page_prompt.md`).

- [ ] **Step 4: Commit only if any fix was needed; otherwise no commit (verification only).**
