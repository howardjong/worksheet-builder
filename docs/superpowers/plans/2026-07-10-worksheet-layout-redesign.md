# Worksheet Layout Redesign + Capitalization Gate Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the cover page (goal moves into page banners), constrain page typography, vary the Learning Buddy pose per page, replace the affect-only checklist with a structured print-only feedback panel, and fix the capitalization gate's title-word false positive (G14).

**Architecture:** All page-level visual changes land in the image_gen prompt builder (pages are one-shot AI images; the prompt is the layout engine). A new `FeedbackPanel` model replaces `self_assessment: list[str]` end-to-end (engine → section_cap → design spec → both renderers → validators). Cover code is deleted outright. The gate fix adds two corroborating heuristics to proper-noun inference.

**Tech Stack:** Python 3.13 (CI mypy on 3.11), Pydantic v2, ReportLab, PyMuPDF, pytest.

**Spec:** `docs/superpowers/specs/2026-07-10-worksheet-layout-redesign-design.md`

## Global Constraints

- Work in the main checkout `/Users/hjong/Documents/Projects/worksheet-builder` on branch `claude/review-recent-refactoring-rma786` (the worktree lacks `.venv`, `profiles/`, `data/`).
- Run tests with `.venv/bin/python -m pytest`; full gates via `make test`, `make lint`, `make typecheck`.
- Commits: NO `Co-Authored-By` trailer (pre-commit hook blocks it). If pre-commit needs a fresh hook install, prefix with `env -u PIP_UPLOADED_PRIOR_TO`.
- `ruff-format` pre-commit may reformat and abort the first commit — re-stage (`git add -u`) and commit again.
- TDD: every behavior change lands with its failing test first.
- Exact child-facing copy (do not paraphrase):
  - child prompt: `How did it go? Circle one for each part.`
  - parent box title: `Grown-up quick log`
  - decision hint: `Mostly green + 9 of 10 right + no help: move on. Mixed or some help: practice again with fresh words. Mostly red or lots of help: step back one lesson.`
  - phonics goal: `I can read words with the {specific_skill} pattern`
  - fluency goal: `I can read the story smoothly`
  - other domains: `I can practice {domain with underscores → spaces} skills`

**Design note (amendment to spec §4):** the grown-up log rows render on EVERY sheet (covering that sheet's sections), not only the last sheet — a last-sheet-only box cannot enumerate other sheets' sections without cross-sheet plumbing (design specs compile per worksheet). The decision hint still renders only on the last sheet (`show_decision_hint`). The spec file carries the same amendment note.

---

### Task 1: Capitalization gate fix (G14)

**Files:**
- Modify: `validate/blocking_gates.py:292-311` (`_known_proper_nouns`)
- Test: `tests/test_blocking_gates.py` (extend; reuse existing `_worksheet`/`_chunk`/`_item` helpers and the `_june_ledger` construction pattern around lines 190-227)

**Interfaces:**
- Produces: `_known_proper_nouns(ledger) -> frozenset[str]` — same signature, stricter inference. No caller changes.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_blocking_gates.py`, mirroring how `_june_ledger()` builds a ledger with one source item (copy its construction, change only `content`):

```python
def _puppy_ledger() -> ObjectiveLedger:
    # Passage source item: title-case heading line + body with lowercase "puppy".
    # Build exactly like _june_ledger() but with this content:
    content = "Lily's Puppy\nLily has a puppy. The puppy runs fast."
    ...  # same ledger/source-item scaffolding as _june_ledger()


def test_title_case_heading_does_not_create_proper_nouns() -> None:
    ws = _worksheet([_chunk([_item(content="Write puppy here.", response_format="write")])])
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)


def test_lowercase_occurrence_exonerates_capitalized_token() -> None:
    # "Puppy" appears capitalized mid-title AND lowercase in the body →
    # lowercase evidence wins; not a proper noun.
    ws = _worksheet([_chunk([_item(content="Feed the puppy today.", response_format="read_aloud")])])
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)


def test_title_only_word_without_lowercase_evidence_still_safe() -> None:
    # Word appears ONLY in the title-case heading ("Lily's") — heading exclusion
    # alone must keep it out of the proper-noun set... unless it also shows up
    # capitalized mid-sentence in a body line (like June in a word list).
    ws = _worksheet([_chunk([_item(content="Say lily out loud.", response_format="verbal")])])
    result = run_blocking_gates([ws], _puppy_ledger())
    assert "capitalization" not in _gate_names(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_blocking_gates.py -k "puppy or title_case or lowercase_occurrence or lily" -v`
Expected: the new tests FAIL (gate fires on "puppy"/"lily"); existing June tests still pass.

- [ ] **Step 3: Implement**

Replace `_known_proper_nouns` in `validate/blocking_gates.py`:

```python
def _known_proper_nouns(ledger: ObjectiveLedger) -> frozenset[str]:
    """Proper nouns = tokens capitalized NOT at sentence/line start in source.

    Example: in "cube, mute, fuse, tune, rule, June" the token `June` is
    capitalized mid-list, so it's a proper noun. Two guards against false
    positives from passage titles (G14, "Lily's Puppy"):

    1. Title-case segments (every alpha token capitalized, >= 2 tokens) are
       headings, not sentences — they contribute no proper-noun evidence.
    2. A token seen lowercase ANYWHERE in the source is exonerated: real
       proper nouns are never written lowercase in curriculum text.
    """
    candidates: set[str] = set()
    lowercase_seen: set[str] = set()
    for src in ledger.source_items:
        for segment in re.split(r"[\n.!?]", src.content):
            tokens = [t for t in re.split(r"[\s,]+", segment) if t]
            stripped_tokens = [
                re.sub(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$", "", t) for t in tokens
            ]
            alpha = [t for t in stripped_tokens if t and t[0].isalpha()]
            if len(alpha) >= 2 and all(t[0].isupper() for t in alpha):
                continue  # title-case heading: no proper-noun evidence
            for pos, stripped in enumerate(stripped_tokens):
                if not stripped:
                    continue
                if stripped == stripped.lower():
                    lowercase_seen.add(stripped.casefold())
                if pos == 0:
                    continue  # sentence/line-initial: ambiguous, skip
                if len(stripped) >= 2 and stripped[0].isupper() and stripped[1:].islower():
                    candidates.add(stripped.casefold())
    return frozenset(candidates - lowercase_seen)
```

- [ ] **Step 4: Run the gate test file**

Run: `.venv/bin/python -m pytest tests/test_blocking_gates.py -v`
Expected: ALL pass, including the three pre-existing June capitalization tests.

- [ ] **Step 5: Update context doc + commit**

In `.claude/worksheet-project-context.md`, set G14 status from OPEN to FIXED (this task, today's date).

```bash
git add validate/blocking_gates.py tests/test_blocking_gates.py .claude/worksheet-project-context.md
git commit -m "fix: capitalization gate no longer infers proper nouns from passage titles (G14)"
```

---

### Task 2: FeedbackPanel model + builders; retire self_assessment upstream

**Files:**
- Modify: `adapt/schema.py:55-73` (add `FeedbackPanel` before `AdaptedActivityModel`; swap field)
- Create: `adapt/feedback.py`
- Modify: `adapt/engine.py` (imports; lines 89, 106, 127, 358, 401, 435; delete `_build_self_assessment` at 2007-2022)
- Modify: `adapt/section_cap.py` (both cap functions)
- Modify: `validate/adhd_compliance.py:136-143`
- Modify: `validate/content_coverage.py:123-124,136-137`
- Modify: `validate/ai_review.py:134-136`
- Test: `tests/test_feedback.py` (new), `tests/test_section_cap.py`, `tests/test_adapt.py`, `tests/test_validate.py`

**Interfaces:**
- Produces (relied on by Tasks 3-5):
  - `adapt.schema.FeedbackPanel(goal_statement: str, child_prompt: str = "How did it go? Circle one for each part.", parent_log_title: str = "Grown-up quick log", show_decision_hint: bool = False)`
  - `AdaptedActivityModel.feedback: FeedbackPanel | None = None` (field `self_assessment` REMOVED)
  - `adapt.feedback.learning_goal_statement(domain: str, specific_skill: str) -> str`
  - `adapt.feedback.build_feedback_panel(domain: str, specific_skill: str) -> FeedbackPanel`
  - `adapt.feedback.DECISION_HINT: str` (exact copy from Global Constraints)
  - `enforce_package_cap(worksheets, max_worksheets, fallback_feedback: FeedbackPanel | None = None)`

- [ ] **Step 1: Write failing tests** — new file `tests/test_feedback.py`:

```python
"""FeedbackPanel builders and placement (spec 2026-07-10)."""

from adapt.feedback import DECISION_HINT, build_feedback_panel, learning_goal_statement
from adapt.rules import AccommodationRules
from adapt.schema import FeedbackPanel
from adapt.section_cap import enforce_package_cap, enforce_section_cap


def test_goal_statement_per_domain() -> None:
    assert learning_goal_statement("phonics", "y") == "I can read words with the y pattern"
    assert learning_goal_statement("fluency", "y") == "I can read the story smoothly"
    assert learning_goal_statement("sight_words", "the") == "I can practice sight words skills"


def test_build_feedback_panel_defaults() -> None:
    panel = build_feedback_panel("phonics", "a_e")
    assert panel.goal_statement == "I can read words with the a_e pattern"
    assert panel.child_prompt == "How did it go? Circle one for each part."
    assert panel.parent_log_title == "Grown-up quick log"
    assert panel.show_decision_hint is False
    assert "move on" in DECISION_HINT


def test_section_cap_keeps_feedback_on_every_part_hint_on_last() -> None:
    # Build a worksheet with feedback and more chunks than the cap so it splits
    # (reuse the worksheet-construction helper pattern from tests/test_section_cap.py).
    ...
    parts = enforce_section_cap([ws], rules)
    assert all(p.feedback is not None for p in parts)
    assert [p.feedback.show_decision_hint for p in parts] == [False] * (len(parts) - 1) + [True]


def test_package_cap_backfills_feedback_and_hint() -> None:
    # Two worksheets with feedback=None, cap to 2, fallback provided.
    ...
    capped = enforce_package_cap(sheets, 2, fallback_feedback=build_feedback_panel("phonics", "y"))
    assert all(w.feedback is not None for w in capped)
    assert [w.feedback.show_decision_hint for w in capped] == [False, True]
```

(Fill the `...` bodies using the existing fixture builders already present in `tests/test_section_cap.py` — copy their minimal `AdaptedActivityModel` constructions, swapping `self_assessment=` for `feedback=`.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_feedback.py -v`
Expected: FAIL with `ImportError` (`adapt.feedback` does not exist).

- [ ] **Step 3: Implement the model and builders**

`adapt/schema.py` — insert before `AdaptedActivityModel`:

```python
class FeedbackPanel(BaseModel):
    """Print-only feedback capture (spec 2026-07-10).

    Child traffic-light strip + grown-up log rows render on every sheet; the
    decision hint renders only where show_decision_hint is True (last sheet).
    Field shape deliberately matches a future --record-results ingestion loop.
    """

    goal_statement: str  # child-friendly "I can..." goal; also the page banner ribbon
    child_prompt: str = "How did it go? Circle one for each part."
    parent_log_title: str = "Grown-up quick log"
    show_decision_hint: bool = False
```

In `AdaptedActivityModel`, replace line 69:

```python
    feedback: FeedbackPanel | None = None  # print-only feedback panel (spec 2026-07-10)
```

New `adapt/feedback.py`:

```python
"""Learning-goal statements and the print-only feedback panel builder."""

from __future__ import annotations

from adapt.schema import FeedbackPanel

# Next-step hint for the grown-up, printed on the package's last sheet.
# Thresholds: Betts reading levels + UFLI-aligned practice (spec 2026-07-10).
DECISION_HINT = (
    "Mostly green + 9 of 10 right + no help: move on. "
    "Mixed or some help: practice again with fresh words. "
    "Mostly red or lots of help: step back one lesson."
)


def learning_goal_statement(domain: str, specific_skill: str) -> str:
    """Child-friendly 'I can...' goal shown in page banners and feedback strips."""
    if domain == "phonics":
        return f"I can read words with the {specific_skill} pattern"
    if domain == "fluency":
        return "I can read the story smoothly"
    return f"I can practice {domain.replace('_', ' ')} skills"


def build_feedback_panel(domain: str, specific_skill: str) -> FeedbackPanel:
    return FeedbackPanel(goal_statement=learning_goal_statement(domain, specific_skill))
```

- [ ] **Step 4: Switch adapt/engine.py**

Add import `from adapt.feedback import build_feedback_panel`. Then:
- Line 88-89: comment becomes `# Build the print-only feedback panel`; `self_assessment = _build_self_assessment(skill)` → `feedback = build_feedback_panel(skill.domain, skill.specific_skill)`
- Line 106: `self_assessment=self_assessment,` → `feedback=feedback,`
- Line 127: `fallback_self_assessment=_build_self_assessment(skill),` → `fallback_feedback=build_feedback_panel(skill.domain, skill.specific_skill),`
- Lines 358, 435: `self_assessment=_build_self_assessment(skill),` → `feedback=build_feedback_panel(skill.domain, skill.specific_skill),`
- Line 401: `self_assessment=None,` → `feedback=build_feedback_panel(skill.domain, skill.specific_skill),` (every sheet now carries the child strip)
- Delete `_build_self_assessment` (lines 2007-2022).

- [ ] **Step 5: Switch adapt/section_cap.py**

Import: `from adapt.schema import AdaptedActivityModel, FeedbackPanel`.

`enforce_section_cap`: delete line 49 (`"self_assessment": ws.self_assessment if is_last_part else None,`) — parts inherit the parent's `feedback` via `model_copy`. In the final renumber loop (lines 65-73), add to the update dict:

```python
                    "feedback": (
                        ws.feedback.model_copy(update={"show_decision_hint": is_last})
                        if ws.feedback
                        else None
                    ),
```

`enforce_package_cap`: rename param `fallback_self_assessment: list[str] | None = None` → `fallback_feedback: FeedbackPanel | None = None`. Replace lines 142-144 and the update dict (lines 145-153) with:

```python
        feedback = ws.feedback or fallback_feedback
        final.append(
            ws.model_copy(
                update={
                    "worksheet_number": idx + 1,
                    "worksheet_count": total,
                    "break_prompt": break_prompt,
                    "feedback": (
                        feedback.model_copy(update={"show_decision_hint": is_last})
                        if feedback
                        else None
                    ),
                }
            )
        )
```

- [ ] **Step 6: Switch the three validators**

`validate/adhd_compliance.py:136-143`:

```python
    # Check 7: Feedback panel
    result.checks_run += 1
    if not adapted.feedback:
        result.add_violation(
            check="feedback_panel_present",
            message="Feedback panel is missing",
            severity="warning",
        )
```

`validate/content_coverage.py:123-124`:

```python
            "feedback_goals": [
                adapted.feedback.goal_statement
                for adapted in adapted_worksheets
                if adapted.feedback
            ],
```

`validate/content_coverage.py:136-137`:

```python
    if adapted.feedback:
        parts.append(adapted.feedback.goal_statement)
        parts.append(adapted.feedback.child_prompt)
```

`validate/ai_review.py:134-136` (keep the surrounding label format at line 135):

```python
    if adapted.feedback:
        worksheet_text += "\nFeedback panel:\n"
        worksheet_text += f"  - Goal: {adapted.feedback.goal_statement}\n"
        worksheet_text += f"  - {adapted.feedback.child_prompt}"
```

- [ ] **Step 7: Fix directly-affected tests, run, commit**

Update `tests/test_section_cap.py`, `tests/test_adapt.py`, `tests/test_validate.py`: replace `self_assessment=[...]`/assertions with `feedback=FeedbackPanel(goal_statement="...")` equivalents; the adhd-compliance test asserting `self_assessment_present` now asserts `feedback_panel_present`. (Other test files break too — they are swept in Task 7; only make these three + test_feedback green here.)

Run: `.venv/bin/python -m pytest tests/test_feedback.py tests/test_section_cap.py tests/test_adapt.py tests/test_validate.py -v`
Expected: PASS.

```bash
git add adapt/ validate/ tests/test_feedback.py tests/test_section_cap.py tests/test_adapt.py tests/test_validate.py
git commit -m "feat: structured FeedbackPanel replaces affect-only self-assessment checklist"
```

---

### Task 3: Design spec carries learning_goal + feedback

**Files:**
- Modify: `render/design_spec.py` (fields at 144/164, compile at 210, `_required_text` at 257)
- Test: `tests/test_worksheet_design_spec.py`

**Interfaces:**
- Consumes: `FeedbackPanel`, `learning_goal_statement` (Task 2)
- Produces (relied on by Task 4): `WorksheetDesignSpec.learning_goal: str`, `WorksheetDesignSpec.feedback: FeedbackPanel | None`, `spec_version == "worksheet_design_spec_v2"`; `self_assessment` field REMOVED; `required_text` includes the goal and (when feedback present) the child prompt.

- [ ] **Step 1: Failing tests** — in `tests/test_worksheet_design_spec.py` add (reusing that file's existing compile fixtures):

```python
def test_spec_carries_learning_goal_and_feedback() -> None:
    spec = _compile_default_spec()  # existing fixture helper in this file
    assert spec.spec_version == "worksheet_design_spec_v2"
    assert spec.learning_goal.startswith("I can ")
    assert spec.feedback is not None
    assert spec.learning_goal in spec.required_text
    assert spec.feedback.child_prompt in spec.required_text
```

Run: `.venv/bin/python -m pytest tests/test_worksheet_design_spec.py -v` → new test FAILS.

- [ ] **Step 2: Implement**

`render/design_spec.py`:
- Import: `from adapt.feedback import learning_goal_statement` and add `FeedbackPanel` to the `adapt.schema` import.
- Line 144: `spec_version: str = Field(default="worksheet_design_spec_v2")`
- Replace line 164 (`self_assessment: ...`) with:

```python
    learning_goal: str = Field(description="Child-friendly 'I can...' goal for the page banner.")
    feedback: FeedbackPanel | None = None
```

- Add module-level helper and use it in both places:

```python
def _learning_goal(adapted: AdaptedActivityModel) -> str:
    if adapted.feedback:
        return adapted.feedback.goal_statement
    return learning_goal_statement(adapted.domain, adapted.specific_skill)
```

- Line 210: `self_assessment=list(adapted.self_assessment or []),` → `learning_goal=_learning_goal(adapted), feedback=adapted.feedback,`
- `_required_text` (line 257): the initial list becomes:

```python
    text: list[str] = [
        _worksheet_title(adapted),
        _learning_goal(adapted),
    ]
    if adapted.feedback:
        text.append(adapted.feedback.child_prompt)
```

- [ ] **Step 3: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_worksheet_design_spec.py -v` → PASS.

```bash
git add render/design_spec.py tests/test_worksheet_design_spec.py
git commit -m "feat: design spec v2 — learning goal + feedback panel replace self_assessment"
```

---

### Task 4: Page prompt — goal ribbon, typography rules, buddy pose, feedback strip

**Files:**
- Modify: `render/pose_planner.py` (add rotation)
- Modify: `render/image_prompt_builder.py` (goal ribbon, typography block, buddy action, feedback section, PROMPT_VERSION v3)
- Modify: `render/image_gen.py:88-95` (pass buddy_action)
- Test: `tests/test_image_prompt_builder.py`

**Interfaces:**
- Consumes: `spec.learning_goal`, `spec.feedback` (Task 3), `DECISION_HINT` (Task 2)
- Produces: `pose_planner.page_pose(worksheet_number: int) -> str`; `build_page_prompt(spec, *, character_block="", scene_guidelines="", theme_environment="", theme_palette="", art_style="", buddy_action="")`; `PROMPT_VERSION == "page_prompt_v3"`.

- [ ] **Step 1: Failing tests** — in `tests/test_image_prompt_builder.py` (reuse its existing spec fixture; set `feedback=FeedbackPanel(goal_statement="I can read words with the y pattern", show_decision_hint=True)` and `learning_goal` on the fixture spec):

```python
from render.pose_planner import PAGE_POSE_ROTATION, page_pose


def test_goal_ribbon_on_sheet_one_running_line_after() -> None:
    p1 = build_page_prompt(_spec(worksheet_number=1))
    p2 = build_page_prompt(_spec(worksheet_number=2))
    assert 'goal ribbon with exact text: "I can read words with the y pattern"' in p1
    assert "running goal line" in p2
    assert "Skill focus" not in p1  # replaced by the goal ribbon


def test_typography_rules_present() -> None:
    prompt = build_page_prompt(_spec())
    assert "## Typography rules (required)" in prompt
    assert "exactly THREE text sizes" in prompt
    assert "60%" in prompt


def test_buddy_action_threaded_and_rotation_distinct() -> None:
    prompt = build_page_prompt(_spec(), character_block="blocky boy", buddy_action=page_pose(2))
    assert page_pose(2) in prompt
    assert page_pose(1) != page_pose(2) != page_pose(3)
    assert page_pose(1 + len(PAGE_POSE_ROTATION)) == page_pose(1)


def test_feedback_strip_and_parent_log() -> None:
    prompt = build_page_prompt(_spec())
    assert 'exact text: "How did it go? Circle one for each part."' in prompt
    assert 'titled with exact text: "Grown-up quick log"' in prompt
    assert "smooth / choppy" in prompt
    assert "step back one lesson" in prompt  # hint present when show_decision_hint=True


def test_prompt_version_bumped() -> None:
    assert PROMPT_VERSION == "page_prompt_v3"
```

Run: `.venv/bin/python -m pytest tests/test_image_prompt_builder.py -v` → new tests FAIL.

- [ ] **Step 2: pose_planner.py rotation**

```python
# Per-page Learning Buddy actions — deterministic rotation by worksheet number
# so every sheet shows the buddy doing something different (owner, session 60).
PAGE_POSE_ROTATION: tuple[str, ...] = (
    "pointing at the first activity banner with an encouraging smile",
    "writing on a small clipboard with a pencil beside soft obby blocks",
    "mid-jump between two obby platforms, cheering",
    "sitting cross-legged reading a small storybook",
    "stacking letter blocks into a short tower",
    "giving a thumbs-up beside a checkpoint flag",
)


def page_pose(worksheet_number: int) -> str:
    """Deterministic per-sheet buddy action (worksheet_number is 1-indexed)."""
    return PAGE_POSE_ROTATION[(max(1, worksheet_number) - 1) % len(PAGE_POSE_ROTATION)]
```

- [ ] **Step 3: image_prompt_builder.py**

- Bump + document version:

```python
# v3: goal ribbon replaces the skill-focus badge, typography rules constrain
# text sizes, per-page buddy action, structured feedback strip + grown-up log.
PROMPT_VERSION = "page_prompt_v3"
```

- Signature: add `buddy_action: str = ""` keyword to `build_page_prompt`.
- In the initial `parts` list, change the theme line (was line 55) to `f"Theme: {spec.theme_name}."` and immediately after the title-banner line append:

```python
    if spec.worksheet_number == 1:
        parts.append(
            f'Directly under the title banner, a goal ribbon with exact text: "{spec.learning_goal}"'
        )
    else:
        parts.append(
            f'A small running goal line in the header area, exact text: "{spec.learning_goal}"'
        )
```

(Move these `append`s to right after the `parts` list literal, before `"## Visual style"` — restructure the literal so `"## Visual style"` is appended after the conditional.)

- In the Learning Buddy block (after the reference-image sentence, before `scene_guidelines`):

```python
        if buddy_action:
            parts.append(
                f"In this page's scene the Learning Buddy is {buddy_action}. Keep "
                "the identity exactly as described; only the pose and action "
                "change from other pages."
            )
```

- Replace the `if spec.self_assessment:` block (lines 85-90) with:

```python
    if spec.feedback:
        fb = spec.feedback
        section_rows = ", ".join(f"Part {s.chunk_id}" for s in spec.sections)
        parts.append(
            f'Final section: a compact feedback strip titled with exact text: "{fb.child_prompt}" '
            f"with one row per activity section ({section_rows}); each row shows the part "
            "number and three small circles colored green, yellow, and red for the child "
            "to circle one."
        )
        log_lines = "\n".join(
            f'Log row exact text: "Part {s.chunk_id}: ___ of {len(s.items)} correct   '
            'smooth / choppy   help: none / some / lots"'
            for s in spec.sections
        )
        hint = (
            f'\nLast line in smaller text, exact text: "{DECISION_HINT}"'
            if fb.show_decision_hint
            else ""
        )
        parts.append(
            "Below the feedback strip, a thin outlined box titled with exact text: "
            f'"{fb.parent_log_title}" containing one log row per section:\n{log_lines}{hint}'
        )
```

with import `from adapt.feedback import DECISION_HINT`.

- Insert the typography block immediately before `parts.append("## Calm-focus rules (required)")`:

```python
    parts.append("## Typography rules (required)")
    parts.append(
        "- Use exactly THREE text sizes on the page: (1) title and section "
        "banners, (2) practice words and answer items — the largest body text, "
        "and (3) ONE consistent smaller size shared by all instructions, time "
        "cues, and labels.\n"
        "- No text on the page may be smaller than 60% of the practice-word "
        "height.\n"
        "- Use one plain, evenly spaced font family throughout, like a "
        "children's school workbook; no decorative or stylized lettering "
        "outside the title banner."
    )
```

- [ ] **Step 4: image_gen.py** — thread the pose. Add `from render.pose_planner import page_pose` and in the `build_page_prompt(...)` call (line 88) add `buddy_action=page_pose(spec.worksheet_number),`.

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_image_prompt_builder.py -v` → PASS.

```bash
git add render/pose_planner.py render/image_prompt_builder.py render/image_gen.py tests/test_image_prompt_builder.py
git commit -m "feat: page prompt v3 — goal ribbon, typography rules, per-page buddy pose, feedback strip"
```

---

### Task 5: Classic PDF renderer parity

**Files:**
- Modify: `render/pdf.py` (callers 204-233, `_estimate_self_assessment_height` 472-475, `_draw_self_assessment` 1317-1350, `_draw_header` before the accent underline at ~519)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `adapted.feedback`, `DECISION_HINT`.
- Produces: `_draw_feedback_panel(c, adapted, theme, sizes, y, effective_bottom)` and `_estimate_feedback_panel_height(adapted, sizes)` (internal; `_draw_self_assessment`/`_estimate_self_assessment_height` deleted).

- [ ] **Step 1: Failing test** — in `tests/test_render.py` (reuse its existing render fixture that produces a PDF from an `AdaptedActivityModel`; give the model `feedback=FeedbackPanel(goal_statement="I can read words with the y pattern", show_decision_hint=True)`):

```python
def test_classic_pdf_renders_feedback_panel_and_goal(tmp_path) -> None:
    pdf_path = _render_fixture_worksheet(tmp_path)  # existing helper pattern
    text = _extract_pdf_text(pdf_path)  # existing helper or fitz get_text()
    assert "I can read words with the y pattern" in text
    assert "How did it go? Circle one for each part." in text
    assert "Grown-up quick log" in text
    assert "step back one lesson" in text
```

Run: `.venv/bin/python -m pytest tests/test_render.py -k feedback -v` → FAIL.

- [ ] **Step 2: Implement**

Imports: `from adapt.feedback import DECISION_HINT`. Module constant near other colors:

```python
_TRAFFIC_LIGHT_COLORS = ("#2E9E44", "#E5B800", "#D64545")  # green / yellow / red
```

Replace `_estimate_self_assessment_height` with:

```python
def _estimate_feedback_panel_height(adapted: AdaptedActivityModel, sizes: dict[str, int]) -> float:
    """Estimate the feedback panel block height (child strip + grown-up log)."""
    body = sizes["body"]
    small = sizes["small"]
    rows = len(adapted.chunks)
    child = body + 10 + rows * (body + 6)
    parent = body + 10 + rows * (small + 6)
    hint = small + 6 if adapted.feedback and adapted.feedback.show_decision_hint else 0
    return child + parent + hint + 20
```

Replace `_draw_self_assessment` with:

```python
def _draw_feedback_panel(
    c: Canvas,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    effective_bottom: float = CONTENT_BOTTOM,
) -> float:
    """Child traffic-light strip + grown-up quick log (spec 2026-07-10)."""
    panel = adapted.feedback
    if panel is None:
        return y
    body = sizes["body"]
    small = sizes["small"]
    if y - _estimate_feedback_panel_height(adapted, sizes) < effective_bottom:
        c.showPage()
        y = CONTENT_TOP

    c.setFont(theme.fonts.heading, body)
    c.setFillColor(HexColor(theme.colors.rewards))
    c.drawString(MARGIN, y - body, panel.child_prompt)
    y -= body + 10
    for chunk in adapted.chunks:
        c.setFont(theme.fonts.primary, body)
        c.setFillColor(HexColor(theme.colors.text))
        c.drawString(MARGIN + 10, y - body + 2, f"Part {chunk.chunk_id}")
        x = MARGIN + 90
        for color in _TRAFFIC_LIGHT_COLORS:
            c.setStrokeColor(HexColor(color))
            c.circle(x, y - body / 2, body / 2.5, fill=0, stroke=1)
            x += body + 12
        y -= body + 6

    c.setFont(theme.fonts.heading, body)
    c.setFillColor(HexColor(theme.colors.directions))
    c.drawString(MARGIN, y - body, panel.parent_log_title)
    y -= body + 10
    c.setFont(theme.fonts.primary, small)
    c.setFillColor(HexColor(theme.colors.text))
    for chunk in adapted.chunks:
        line = (
            f"Part {chunk.chunk_id}: ___ of {len(chunk.items)} correct   "
            "smooth / choppy   help: none / some / lots"
        )
        c.drawString(MARGIN + 10, y - small, line)
        y -= small + 6
    if panel.show_decision_hint:
        c.drawString(MARGIN + 10, y - small, DECISION_HINT)
        y -= small + 6
    return y
```

Callers (lines 204-233): change both `adapted.self_assessment` conditions to `adapted.feedback`, the estimate call to `_estimate_feedback_panel_height(adapted, sizes)`, and the draw call to `_draw_feedback_panel(c, adapted, theme, sizes, y, effective_bottom=content_bottom)`.

`_draw_header`: insert immediately before the `# Header accent underline` comment (~line 519):

```python
    if adapted.feedback:
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        c.drawString(MARGIN, y - sizes["small"], adapted.feedback.goal_statement)
        y -= _line_spacing(sizes["small"])
```

- [ ] **Step 3: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_render.py -v` → PASS (update any old self_assessment-based render tests in this file to the new field while here).

```bash
git add render/pdf.py tests/test_render.py
git commit -m "feat: classic renderer parity — feedback panel + goal line in header"
```

---

### Task 6: Remove the cover page

**Files:**
- Modify: `transform.py` (line 36 import; call site 979-990; `_merge_lesson_package` 1041-1102)
- Modify: `render/merge.py` (drop cover param; stamp all pages)
- Modify: `render/pdf.py` (delete `render_cover_page`, lines 1470-1590, plus imports/constants only it used)
- Modify: `render/asset_gen.py` (delete `generate_cover_image`, `_build_cover_prompt`, `_generate_cover_with_chain`, `_generate_local_cover_image`, and helpers only they use)
- Delete: `tests/test_cover_image_gen.py`
- Test: `tests/test_merge.py`, `tests/test_transform_lesson.py`

**Interfaces:**
- Produces: `merge_worksheet_package(worksheet_paths: list[str], output_path: str, *, cleanup: bool = True) -> str` (cover param REMOVED).

- [ ] **Step 1: Failing tests**

`tests/test_merge.py`: update to the new signature; assert the merged PDF page count equals the sum of worksheet pages (no +1) and that page 1 is stamped `Page 1 of N`.

`tests/test_transform_lesson.py`: extend the stubbed-pipeline test (`_stub_lesson_pipeline` helper) with:

```python
def test_lesson_pdf_has_no_cover_page(tmp_path, monkeypatch) -> None:
    # Run the stubbed pipeline; open the merged lesson PDF with fitz.
    # Assert page_count == worksheet count (previously worksheets + 1 cover)
    # and that page 1 contains a section banner, not "What's Inside".
    ...
```

Run: `.venv/bin/python -m pytest tests/test_merge.py tests/test_transform_lesson.py -v` → new/updated tests FAIL.

- [ ] **Step 2: render/merge.py**

New signature and body (docstring updated; stamp every page):

```python
def merge_worksheet_package(
    worksheet_paths: list[str],
    output_path: str,
    *,
    cleanup: bool = True,
) -> str:
    """Merge worksheet PDFs into a single lesson package (no cover page —
    owner decision 2026-07-10). Stamps "Page X of Y" on every page.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    merged = fitz.open()
    for ws_path in worksheet_paths:
        ws_doc = fitz.open(ws_path)
        merged.insert_pdf(ws_doc)
        ws_doc.close()

    total_pages = merged.page_count
    for page_idx in range(total_pages):
        page = merged.load_page(page_idx)
        stamp_text = f"Page {page_idx + 1} of {total_pages}"
        rect = fitz.Rect(
            _PAGE_WIDTH / 2,
            page.rect.height - _FOOTER_Y - 4,
            _PAGE_WIDTH - _MARGIN,
            page.rect.height - _FOOTER_Y + 10,
        )
        page.insert_textbox(
            rect, stamp_text, fontname="helv", fontsize=8,
            color=(0.78, 0.8, 0.82), align=fitz.TEXT_ALIGN_RIGHT,
        )

    merged.save(output_path)
    merged.close()
    if cleanup:
        for p in worksheet_paths:
            try:
                Path(p).unlink()
            except OSError:
                pass
    logger.info(
        "Merged lesson package: %s (%s worksheets, %s pages)",
        output_path, len(worksheet_paths), total_pages,
    )
    return output_path
```

- [ ] **Step 3: transform.py**

Remove `from render.pdf import render_cover_page` (line 36). Replace `_merge_lesson_package` (1041-1102) entirely:

```python
def _merge_lesson_package(content_hash: str, pdf_paths: list[str], output: Path) -> list[str]:
    """Merge all worksheet PDFs into a single lesson package (no cover page).

    Owner decision 2026-07-10: the cover delivered zero practice value; the
    learning goal moved into page banners. Printed pages == budgeted sheets.
    """
    from render.merge import merge_worksheet_package

    merged_path = str(output / f"lesson_{content_hash}.pdf")
    merge_worksheet_package(pdf_paths, merged_path, cleanup=True)
    return [merged_path]
```

Call site (979-990) becomes:

```python
    # Merge worksheets into a single lesson PDF (no cover — session 60)
    if strategy.produces_pdf:
        pdf_paths = _merge_lesson_package(
            content_hash=content_hash, pdf_paths=pdf_paths, output=output
        )
```

(The `skill_model=`, `worksheets=`, `theme=`, `theme_id=`, `profile=` arguments disappear; run `make lint` to catch newly unused imports in transform.py and remove them.)

- [ ] **Step 4: Delete cover code**

- `render/pdf.py`: delete `render_cover_page` (1470-1590). Run `grep -n "render_cover_page" -r . --include="*.py"` → only stale references should be tests updated in Step 5.
- `render/asset_gen.py`: delete `generate_cover_image` (586-649), `_build_cover_prompt` (263+), `_generate_cover_with_chain` (656+), `_generate_local_cover_image`, and any helper now unreferenced (verify each with grep before deleting).
- `git rm tests/test_cover_image_gen.py`

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_merge.py tests/test_transform_lesson.py tests/test_render.py -v` → PASS.

```bash
git add -A transform.py render/merge.py render/pdf.py render/asset_gen.py tests/
git commit -m "feat: remove cover page — learning goal lives in page banners (owner decision, session 60)"
```

---

### Task 7: Repo-wide sweep + full gates

**Files:**
- Modify: remaining test files referencing the old field: `tests/test_adapt.py`, `tests/test_image_prompt_builder.py`, `tests/test_llm_judge.py`, `tests/test_rag_backfill.py`, `tests/test_transform_quality_gates.py`, `tests/test_worksheet_design_spec.py` (and any missed)

- [ ] **Step 1: Sweep**

Run: `grep -rn "self_assessment\|_build_self_assessment\|fallback_self_assessment\|render_cover_page\|generate_cover_image" --include="*.py" .`
Expected after fixes: zero hits outside `docs/`. Convert each remaining fixture/assertion to `feedback=FeedbackPanel(goal_statement=...)` / new interfaces.

- [ ] **Step 2: Full gates**

Run: `make test && make lint && make typecheck`
Expected: all green. (CI runs mypy on 3.11 — avoid 3.13-only syntax.)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: migrate remaining fixtures to FeedbackPanel / coverless package"
```

---

### Task 8: Live verification (lesson 74)

- [ ] **Step 1: Run the pipeline into a fresh dir**

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
.venv/bin/python transform.py --lesson 74 --profile profiles/ian.yaml \
  --theme roblox_obby --output ./output/lesson74_redesign/
```

- [ ] **Step 2: Verify, in order**

1. Merged PDF page count == worksheet count (2 expected; no cover).
2. Render pages to PNG (PyMuPDF, dpi=110) and eyeball: goal ribbon "I can read words with the y pattern" on sheet 1, running goal line on sheet 2; ≤3 visible text sizes per page; Learning Buddy doing a *different* action on each sheet; "How did it go?" strip on both sheets; "Grown-up quick log" rows on both; decision hint only on the last sheet.
3. `artifacts/planner_attempts.json`: capitalization gate no longer fires on "puppy". If all gates pass, check whether the package ships `objective_approved` (judge_verdict.json written this run).
4. WARNING/ERROR scan of the log — expected leftovers only: coverage ERRORs (P3), grade age-band warning (P4).
5. Page cache regenerated (PROMPT_VERSION v3 invalidates old entries) — confirm new `page_*` cache dirs.

- [ ] **Step 3: Report results to the owner** (PNG renders + planner outcome). Do NOT commit output artifacts.
