# Lesson-100 UAT fixes: suffix-lesson translation + content/render quality

**Date:** 2026-07-13
**Status:** Approved direction (session 61); owner decisions embedded below
**Scope:** skill taxonomy (morphology), deterministic engine content templates, page-prompt/render fidelity, judge/planner robustness
**Source:** owner UAT of `output/lesson100_uat/lesson_71b7321cf001.pdf` (lesson 100, `-er/-est`) + run findings; all defects verified against run artifacts

## Background

Lesson 100 was the first cross-lesson translation test of the finished
pipeline (lesson 74 = `y` vowel pattern; lesson 100 = `-er/-est`
comparative suffixes). The run shipped via `WORKSHEET_SHIP_UNAPPROVED=1`
after the objective judge's JSON response truncated (parse failure →
"unavailable" tri-state, correct per D40). The PDF surfaced twelve
defects. Root-cause analysis traced each to a specific mechanism; one
upstream bug (skill misclassification) amplifies several others.

### Defect ledger (all confirmed in artifacts)

| # | Defect | Root cause | Location |
|---|--------|-----------|----------|
| 1 | Chain sections show full answers (`slow → slower → slowest`) + orphan write line; chunks 1 and 2 byte-identical; same chain twice per chunk | `_parse_chain_steps` only parses single-letter changes; suffix chains fail into a fallback that prints raw chain strings verbatim and double-batches | `adapt/engine.py:789-884, 1909-1932` |
| 2 | "Write the missing letter" but options `a,e,i,o,u` present — circling is the natural action | fill-blank affordance hardcodes handwriting line; instruction template says write | `render/image_prompt_builder.py:25`, `adapt/engine.py:929-930` |
| 3 | Feedback area ≈ ⅓ of page (traffic lights + quick log both render) | both blocks hard-required by `_required_text` | `render/design_spec.py:267-289`, `image_prompt_builder.py:101-123` |
| 4 | Match pictures aligned with their own words (nothing to figure out); worked example leaks "a simple cartoon representing higher" and asserts the wrong pairing | engine authors a seeded derangement but the page prompt never passes `picture_prompt` per row — image model draws the row's own word | `image_prompt_builder.py:28-33`, `engine.py:614-657, 1533-1535, 1935-1955` |
| 5 | Three identical "Write 5 words" sections | encode word list split into uniform chunks, no form variety | `adapt/engine.py` builder chunking |
| 6 | "Make the word slow." rendered as a sentence-completion item | teacher-script filter misses the "make the word" dictation stem | `skill/lesson_loader.py:181-212` |
| 7 | Sentence blank has multiple plausible answers (`shortest/higher/lower/older/newer`) | word bank = answer + arbitrary target words; no uniqueness check | `adapt/engine.py:1210-1214, 1460-1482` |
| 8 | Story passage one dense 148-word block, text too small; first chunk missing worked example | passages have no typography size class and no paragraph/chunking rule; this is also the exact judge rejection on lessons 74 AND 100 (`overwhelming_or_adhd_unsafe`) | `image_prompt_builder.py:138-149`, `engine.py:1259-1286` |
| 9 | Check-understanding options not row-aligned with their question | circle-format affordance doesn't pin options to the question row | `image_prompt_builder.py` circle affordance |
| 10 | "Page X of 3" stamped over the Take a Break box, all 3 pages (print-check true positive at (517,760)) | a post-render footer stamp at fixed bottom-right coordinates collides with the layout's bottom-right box; page number ALSO appears in the header ("3 of 3" badge) so the footer stamp is redundant | stamping site TBD in transform/render merge step (diagnose first, like T5) |
| 11 | Judge verdict JSON truncated mid-string → unavailable path | `max_completion_tokens=1024` too small for objective verdicts; no retry on parse failure | `adapt/llm_judge.py:156-175, 197-204, 645-652` |
| 12 | LLM planner never authors the required word-chain activity (0/4 attempts across lessons 74+100, even with retry feedback) | authoring block states the requirement but shows no concrete example | `adapt/llm_planner.py` prompt |
| 13 | **Root:** lesson 100 classified `specific_skill=r_controlled`; banner teaches "I can read words with the r controlled pattern" on a morphology lesson | no morphology category in the taxonomy; grapheme matcher sees "er" | `skill/taxonomy.py:97-198`, goal text at `adapt/feedback.py:26-32` |

### Owner decisions (this session)

- **Feedback panel: Grown-up quick log only.** Drop the child traffic-light
  strip entirely (model field, required-text entry, prompt block). Keep
  `parent_log_title`, per-part log rows, and the decision hint. Rationale:
  the log carries the objective adaptation data; age-6 self-ratings are
  unreliable; page space is the constraint.
- **Encode practice: vary the forms.** Replace the three identical
  "Write 5 words" sections with three distinct forms: (a) say-and-write,
  (b) add-the-ending transform (`tall + -er → ______`), (c)
  choose-the-form in a mini sentence. Directly answers the judge's
  "encoding the pattern, not just copying prompted words" critique.
- Execution model unchanged from the finish-line cycle: Sonnet 5
  implements and task-reviews; Fable 5 runs the final whole-branch review
  with per-task red/green TDD-evidence audit.

## Design

### WS1 — Morphology skill identity (fixes the root)

1. **Taxonomy:** add a morphology tier to `skill/taxonomy.py`, matched
   BEFORE grapheme patterns. Detection: hyphen-prefixed suffix tokens in
   the concept label (`-er`, `-est`, `-ing`, `-ed`, `-s`, `-es`, `-ly`).
   `"-er, -est"` → `specific_skill="suffix_er_est"`, domain stays
   `phonics` (UFLI's own framing); downstream code tests the `suffix_`
   name prefix (one helper `is_suffix_skill(skill) -> bool` in
   `skill/taxonomy.py`, no schema change). Concepts
   without suffix tokens keep today's behavior byte-identical (lesson 74
   regression bar).
2. **Learning goal:** `learning_goal_statement` maps suffix skills to
   "I can add -er and -est to compare things." (generic form:
   "I can add {endings} to words."). No more r-controlled banner on
   suffix lessons.
3. **Suffix-aware chains:** for suffix skills, chain steps become
   `base + -suffix → ______` items (content `"slow + -er → ______"`,
   `answer="slower"`), one hop per item, produced by a deterministic
   suffix-chain parser that reuses the existing chain_step item shape —
   so the evidence stitcher, chain-stamp discriminator, and coverage
   machinery keep working unmodified. Instructions template: "Read the
   word. Add the ending. Write the new word." Worked example shows one
   completed hop (`slow + -er → slower`).

### WS2 — Engine content quality

4. **Chain dedup + no-answer display (all lesson types):** dedup chain
   inputs before batching; fix the fallback double-chunk bug (chunks 1/2
   identical); chain items never display the full chain as prompt text —
   display shows the from-state and a blank, answer lives in `answer`.
   TDD reproduces the duplicate-chunk state from a lesson-100 fixture.
5. **Fill-blank with options = circle format:** when a fill_blank item
   has options, instructions become "Circle the missing letter." and the
   affordance renders large circleable letters beside the word — no
   handwriting line.
6. **Teacher-script filter:** add "make the word" (and "add the ending",
   "change the word") stems to the home-practice exclusion list.
7. **Distractor hygiene:** sentence word banks shrink to answer + 2
   distractors; extend the existing AI quality review checklist with
   "exactly one option fits each sentence blank" — flagged distractors
   are removed (floor: 2 options). No new LLM call; rides the existing
   review pass.
8. **Passage chunking:** the engine formats decodable text into
   paragraphs of ≤ 2-4 sentences separated by blank lines with a small
   stop-mark cue; the prompt renders them as visually separated blocks.
   First chunk of every worksheet gets a worked example (closes the
   recurring ADHD-compliance warning). This is the direct fix for the
   judge's `overwhelming_or_adhd_unsafe` rejection on both lessons.
9. **Match worked example:** compose from the row's actual (shuffled)
   picture word in child language — "The first picture shows something
   newer — draw a line to the word 'newer'." Never emit raw
   `picture_prompt` text; never assert a same-row pairing.

### WS3 — Renderer fidelity

10. **Match rows carry their pictures:** each match item line in the page
    prompt includes its `picture_prompt` and the explicit constraint that
    the picture must NOT depict the word on its own row. Add a page-gate
    check (the vision gate already reads every page): "does any
    right-column picture depict the left-column word on its row?" —
    expected NO for all rows; a YES rejects the page attempt.
11. **Circle alignment:** circle-format options render on the same line
    as their question, right side, evenly spaced.
12. **Passage typography:** read-aloud passage text joins size class (2)
    (practice-word size), not instruction size.
13. **Feedback block:** remove the traffic-light strip per owner decision
    — from the FeedbackPanel model (`child_prompt` field), the
    `_required_text` gate, the prompt builder block, and all tests.
    Quick log + decision hint remain; log rows unchanged.
14. **Pagination stamp:** diagnose where the bottom-right "Page X of Y"
    footer stamp is applied post-render; it is redundant with the header
    page badge — remove it (or relocate to bottom-center inside the
    margin if any consumer needs it). Print-check overlap warnings at
    (517,760) must disappear.

### WS4 — Pipeline robustness

15. **Judge:** `max_completion_tokens` → 4096 for objective judge calls;
    ONE retry on parse failure (same request), then the existing
    unavailable path. Cost bound: at most +1 judge call, only on parse
    failure.
16. **Planner authoring block:** embed one concrete word-chain activity
    example (valid plan-JSON fragment) and a one-line budget reminder
    ("plan total must fit {session_minutes} minutes"). Sole purpose:
    close the 0/4 word-chain authoring record.
17. **Bound accounting sanity:** after content fixes land, re-check the
    package item-count accounting (run showed `total_item_count=45` vs
    `role_counts.student_practice=56` — reconcile what counts as an
    item) and re-verify the 40-item bound on both lessons.

## Exit criteria

1. Every implementation task's report carries RED and GREEN TDD evidence;
   Fable 5 final review = READY TO MERGE with per-task TDD-evidence audit.
2. `make test`, `make lint`, `make typecheck` green (mypy verified under
   CI's 3.11 semantics).
3. Live acceptance runs of BOTH lesson 74 and lesson 100 (no override):
   each either ships judge-approved, or fails pre-render for a reason the
   owner accepts. Neither PDF (when shipped) may show any of the 13
   ledger defects: correct "I can" goal per lesson type, chains with
   blanks and no printed answers, no duplicate sections, circle-format
   missing letters, shuffled match preserved on the page, three distinct
   encode forms, no dictation imperatives as sentences, single-answer
   word banks, chunked passage at practice-word size with worked example,
   row-aligned comprehension options, quick-log-only feedback block, no
   footer/illustration overlap.
4. Photo path untouched and regression-free (all changes are lesson-mode
   or shared-template scoped; existing photo tests unchanged and green).

## Out of scope

`--record-results` ingestion; jurisdiction→curriculum mapping; full
morphology coverage beyond suffix detection (prefix lessons, base-word
morphology) — the taxonomy hook is built to extend but only `-er/-est`
class suffixes are wired now; unifying the four concept-pattern
implementations (known debt); gpt-5.4 → gpt-5.6-terra swap (still paused
by owner).
