# Adaptive dosage from learner profile (birthdate / jurisdiction / severity)

**Date:** 2026-07-10
**Status:** Draft for owner review (session 60)
**Scope:** `adapt/workload.py`, `companion/schema.py`, small consumer updates; P4 fix included

## Background

The workload budget answers "how many pages, how many minutes" but currently
derives everything from a single grade string — and the wrong one:

- `derive_package_budget` looks up segment/session minutes by
  **`skill.grade_level`** (the LESSON's grade), not the child's — gotcha P4.
  For Ian (profile grade 1, lesson 74 grade 2) the lesson decided his
  attention span.
- Grade is a stored snapshot that goes stale (`profiles/ian.yaml` still says
  `'1'`; Ian enters grade 2 in September 2026).
- Demand is measured in section COUNT only. Lesson 74: "4 essential
  objectives → 5 sections → 2 sheets," while the shipped 2 sheets carry ~9 of
  24 budgeted minutes and the essential connected-text objective (whose
  sufficiency rule says "1 page chunk") gets trimmed. Pages are treated as the
  scarce resource; minutes are the actual scarce resource.
- ADHD severity is not an input anywhere; the grade table has one implicit
  severity baked in.

Owner intent (this session): profile facts — birthdate 2019-09-21, entering
grade 2, Markham ON (YRDSB) — should drive dosage; reading/sentence work
should ship when minutes allow.

## Design

### 1. Profile schema (`companion/schema.py::LearnerProfile`)

Three new optional fields (all backward compatible; absent → legacy behavior):

```yaml
birthdate: 2019-09-21        # ISO date
jurisdiction: CA-ON          # ISO country-subdivision code
adhd_severity: moderate      # mild | moderate | severe
grade_level: '2'             # kept: legacy fallback + manual override
```

- `birthdate: date | None = None`
- `jurisdiction: str | None = None` (validated against a small supported set;
  initially `CA-ON`; unknown values log a warning and behave as None)
- `adhd_severity: Literal["mild","moderate","severe"] | None = None`
  (None → "moderate": matches the calibration implicit in today's table,
  and this is an ADHD-focused product)

**Privacy rule (binding):** `birthdate` is derivation-only. It never enters
LLM prompts, the design spec, rendered pages, or any artifact. Artifacts may
carry the derived `age_years` (one decimal) and derived grade only.

### 2. Derivations (new module `companion/dosage.py`)

All computed at run time from `birthdate` — never stored, never stale.

- `age_years(birthdate, today) -> float`
- `derived_grade(birthdate, jurisdiction, today) -> str | None` — CA-ON:
  entry cutoff Dec 31; the grade rolls **July 1** (Ontario classes end in
  June — summer practice targets the INCOMING grade, matching how parents
  describe it: "going into grade two"). So
  `school_year_start_year = today.year if today.month >= 7 else today.year - 1`
  and `grade_number = school_year_start_year - birth_year - 5`, clamped to
  K..3 (this product's range; out-of-range logs a warning). Ian in July
  2026: 2026 − 2019 − 5 = 2 ✓ (and still 2 through June 2027).
- `current_grade(profile, today) -> str` — derived grade when
  birthdate+jurisdiction present, else `profile.grade_level`. When both exist
  and disagree, derived wins and a stale-profile warning names the mismatch.
- `segment_minutes(profile, today) -> int` —
  `clamp(round(age_years × 1.5 × severity_mult), 4, 12)` with severity_mult
  mild 0.85 / moderate 0.70 / severe 0.55.
  Calibration anchor: typical mid-cohort grade-2 child (7.5y, moderate) →
  7.5 × 1.5 × 0.70 = 7.9 → 8 min — exactly today's grade-2 value. All four
  grade-table values reproduce within ±1 min at mid-cohort ages.
  Fallback (no birthdate): `GRADE_WORKLOAD[current_grade].segment`.
- `session_minutes(profile, today) -> int` — jurisdiction homework norm:
  CA-* uses the 10-minutes-per-grade guideline → `clamp(10 × grade_number,
  12, 30)` (K → 12). Fallback (no jurisdiction):
  `GRADE_WORKLOAD[current_grade].session`. Existing downward adjusters
  (observed `avg_session_duration`, `chunking_level=small`) apply after,
  unchanged.

### 3. Budget changes (`adapt/workload.py::derive_package_budget`)

1. **P4 fix — the child owns the attention budget.** Segment/session come
   from the profile derivations above; `skill.grade_level` no longer feeds
   the workload table. (Lesson grade keeps driving content difficulty and
   accommodation rules exactly as today — no change to `adapt/rules.py`
   keying; that separation is deliberate: lesson grade = what is practiced,
   child age = how much at a time, child grade = format expectations.)
2. **Attention ceiling rounds instead of floors:**
   `attention_max = max(1, round(session / segment))`. Segments are separated
   by restorative movement breaks; ±half a segment is inside norm noise.
   No drift at any legacy table value (12/5→2, 18/6→3, 24/8→3, 30/10→3).
3. **Minutes-based demand joins section-count demand.** New per-form nominal
   minutes (policy encoding, same spirit as GRADE_WORKLOAD):
   `decode 4, encode 4, manipulation 4, connected_text 8, irregular 3`.
   `essential_minutes = sum(nominal minutes of essential ledger cells)`;
   `minute_sheets = ceil(essential_minutes / segment_minutes)`;
   `sheets_needed = max(section_sheets, minute_sheets)`;
   `max_worksheets = min(attention_max, sheets_needed)` (unchanged rule,
   richer demand). Overflow flag unchanged.
4. `PackageBudget` gains additive fields: `age_years: float | None`,
   `severity: str`, `essential_minutes: int`, `minute_sheets: int`,
   `grade_source: Literal["derived","profile"]`; `grade` now
   reports the grade the BUDGET used (child grade). Rationale string names
   every derivation ("age 6.8y × moderate → 7-min segments; CA-ON grade 2 →
   20-min session; …").

### 4. Consumer updates (small)

- `adapt/rules.py:161`, `transform.py` age-band validation, and the three
  prompt `Grade:` lines switch from `profile.grade_level` to
  `current_grade(profile, today)` — same value for legacy profiles, current
  value for birthdate profiles.
- `profiles/ian.yaml` updated: `birthdate: 2019-09-21`,
  `jurisdiction: CA-ON`, `adhd_severity: moderate`, `grade_level: '2'`.

### Worked example (Ian, lesson 74, run in July 2026)

age 6.8y × 1.5 × 0.70 → **7-min segments**; CA-ON grade 2 → **20-min
session**; ceiling round(20/7) = **3 sheets**. Demand: sections 5 → 2 sheets;
minutes 4+4+4+8 = 20 → ceil(20/7) = **3 sheets**; needed = 3; cap =
min(3, 3) = **3** → the Story Time sheet (passage + sentence writing) ships,
total ≈ 21 practice minutes. In September (age 7.0) the same math holds; as
he ages the segments lengthen automatically.

## Testing

TDD throughout: derivation unit tests (age, CA-ON grade math incl. Dec-31
cutoff edges and Sept-1 rollover, clamps, severity multipliers, disagree
warning); budget tests (legacy profile → identical segment/session table
values — note the minutes-demand escalation intentionally applies to ALL
profiles, so legacy sheet counts may rise where essential minutes exceed
section-count demand; birthdate profile → worked-example numbers;
rounding ceiling non-drift at all four table values); privacy test (birthdate
string absent from every prompt artifact and the design spec); ian.yaml
round-trip. Full gates: `make test`, `make lint`, `make typecheck` (CI mypy
3.11 — `datetime.date` handling must be 3.11-clean).

## Out of scope

- Objective-aware package trimming (spawned task `task_46163d0f` — remains
  the safety net when a plan is rejected and the cap still binds).
- Jurisdiction → curriculum-standards mapping (separate feature).
- `--record-results` ingestion (the FeedbackPanel loop; observed data will
  eventually override these population norms — the `avg_session_duration`
  hook already models the pattern).
- P3 (coverage rubric alignment) — separate, still the top blocker for
  `objective_approved`.
