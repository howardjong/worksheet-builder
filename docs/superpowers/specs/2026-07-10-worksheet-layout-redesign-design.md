# Worksheet layout redesign + capitalization gate fix

**Date:** 2026-07-10
**Status:** Approved by owner (session 60)
**Scope:** lesson-mode image_gen render path, feedback capture, blocking gate G14

## Background

Owner review of the lesson 74 rerun (3-page PDF: cover + 2 practice sheets, image_gen
render mode) found four problems:

1. The cover page wastes a full printed page: bottom ~60% empty, objectives in
   near-invisible gray footer text, duplicated "Practice time!" blurbs.
2. Practice pages show a wide, inconsistent range of text sizes. Root cause: pages
   are one-shot AI-generated images built from `page_prompt.md`, and the prompt
   never constrains typography — the image model picks sizes freely.
3. The Learning Buddy avatar looks identical on every page (same standing,
   front-facing pose). The prompt requests the buddy "exactly once" but specifies
   no pose; `render/pose_planner.py` poses are only used for cover art.
4. The "How did I do?" section is three affect-only checkboxes. It captures no
   accuracy, fluency, or independence signal — insufficient to judge whether
   content is working or to adapt the next session.

Separately, G14 (open gotcha): the capitalization blocking gate infers "Puppy" as a
proper noun from the passage title "Lily's Puppy" and blocks valid lowercase
mid-sentence uses. Two consecutive runs confirmed it as the sole gate rejection —
the last known blocker to an `objective_approved` smart-planner run.

Research basis (session 60): no instructional-design source supports a cover page
on 2-4 page practice sheets; learning goals belong at the point of work as "I can…"
statements (Hattie learning-intentions). ADHD guidance: minimize steps to task
start. Self-assessment at 6-8 years: 3-point visual scales (traffic light). Parent
adaptation needs four signals: accuracy, fluency, independence, affect. Decision
thresholds: ≥90% accurate + automatic + independent → advance; 70-90% or slow or
helped → repeat; <70% or frustrated → step back (Betts / UFLI-aligned practice).

## Design

### 1. Remove the cover page; move the goal into page banners

- `transform.py::_merge_lesson_package` no longer generates or merges a cover
  page. Cover-only code (`render/pdf.py::render_cover_page`,
  `render/asset_gen.py::generate_cover_image` and helpers) is deleted. Rollback
  is git history, not a flag.
- The page prompt's `Skill focus: …` line is upgraded to a child-friendly goal
  ribbon under the title banner: e.g. "I can read words with the y pattern",
  derived from the skill model the same way the current self-assessment first
  item is (per-domain wording). Sheet 2+ repeats the goal as a small running
  header line.
- Printed pages now equal budgeted worksheets (workload budget never counted the
  cover; dosage is unchanged).
- Each run saves one image-generation + character-judge round.
- Parent-facing cover metadata (grade, objectives, print instructions) already
  lives in artifacts (`skill_model.json`, `workload_budget.json`); nothing
  child-facing is lost.

### 2. Typography rules in the page prompt

Add a `## Typography rules` section to the image_gen prompt builder:

- Exactly three text sizes per page: (1) section banner, (2) practice words /
  answer items (largest body text), (3) instructions and time cues (one
  consistent smaller size, never below ~60% of practice-word height).
- One font style throughout; no extra sizes, no decorative type.

Same mechanism as the existing calm-focus rules, which the image model follows
reliably.

### 3. Per-page avatar pose variation

- Thread a pose + scene action into the Learning Buddy prompt section, chosen by
  deterministic rotation keyed on worksheet number (e.g. sheet 1: pointing at the
  first activity; sheet 2: writing with a pencil; then thinking, building, …)
  using the existing `render/pose_planner.py` vocabulary.
- Pose text lands in the prompt, so the page cache key (prompt hash) changes
  automatically — no stale-cache collisions.
- Identity/likeness rules are unchanged; only pose/action varies.

### 4. Feedback capture redesign (print-only)

Replace `self_assessment: list[str]` in `adapt/schema.py` with a structured
`FeedbackPanel`:

- **Every sheet — child strip ("How did it go?"):** one traffic-light row
  (green / yellow / red circle) per section on that sheet. Child circles one per
  section.
- **Last sheet only — parent quick-log box:** per section `__ / N correct`;
  smooth vs. choppy circle; help level (none / some / lots); plus a printed
  next-step hint using the research thresholds:
  - mostly green + ≥90% correct + no help → next lesson
  - mixed / slow / some help → repeat this skill with fresh words
  - lots of red or <70% correct → step back one lesson
- Placement logic in `adapt/section_cap.py` (last-sheet-only) applies to the
  parent box; the child strip appears on every sheet.
- `adapt/engine.py::_build_self_assessment` becomes the `FeedbackPanel` builder.
- Renderers: image_gen prompt final-section text updated; classic
  `render/pdf.py::_draw_self_assessment` updated for parity.
- `validate/adhd_compliance.py` presence check targets the new panel.
- Field shape deliberately matches a future `--record-results` ingestion loop
  (accuracy, fluency, independence, affect per section) — no digital loop ships
  now.

### 5. Capitalization gate fix (G14)

Two corroborating changes to `validate/blocking_gates.py::_known_proper_nouns`:

1. **Title-line exclusion:** skip segments where every alpha token (≥2 tokens)
   is capitalized — these are headings/titles ("Lily's Puppy"), not sentences.
2. **Lowercase corroboration:** a token qualifies as a proper noun only if it
   never appears lowercase anywhere in the ledger's source items. "puppy"
   appears lowercase in the passage body → exonerated; "June" in a word list
   never does → still caught.

Existing gate tests (June word-list cases) must keep passing.

## Testing

TDD per change:

- Gate: title-case line does not create proper nouns; lowercase-corroboration
  exoneration; June cases regress-free.
- FeedbackPanel: builder output per domain; last-sheet-only parent box;
  child strip on all sheets; ADHD compliance check.
- Prompt builder: typography section present; goal ribbon text; pose rotation
  deterministic by worksheet number and distinct across sheets.
- transform: no cover page in merged PDF; page count == worksheet count.

Then `make test`, `make lint`, `make typecheck` (CI runs mypy on 3.11), and a
live lesson 74 run into a fresh output dir. Acceptance: 2 pages total; goal
ribbon on sheet 1 and running header on sheet 2; ≤3 text sizes by inspection;
visibly different buddy poses per sheet; new feedback panel renders; and with
the gate fixed, check whether the smart planner ships `objective_approved`.

## Out of scope

- Digital feedback ingestion (`--record-results`) — future session.
- P3 (coverage validator / advisory judge objective-sufficiency alignment), P4
  (grade precedence), photo-path Roll-and-Read pattern filtering, unifying the
  four concept-pattern implementations — tracked separately.
