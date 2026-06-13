# Coverage Contract — Implementation Plan (planner coverage variance)

> Derived from `plans/2026-06-13-planner-coverage-architecture-research.md` + the Session 48 B4
> finding (planner-generation variance on content coverage is the binding instability; vision is
> frozen, judge is stable at median-of-3). REQUIRED SUB-SKILL: strict red-green TDD per task.
> One commit per task, exact paths only, no `Co-Authored-By` trailer, never touch `.claude/settings.json`.

## Goal & success criteria

Drive planner content-coverage variance to ~zero by replacing "preserve everything" prose with a
**deterministic, ID-based coverage contract**, while keeping the LLM free to author engaging,
child-facing practice. "Done" = on the 3 frozen images, `--runs 2` with the contract on shows
**no approve/reject flips caused by missing source content**, with no human-rated engagement drop
vs current planner-v2 and no rise in invalid worked examples / answer-key errors.

Hard rules carried over: do NOT lower the 0.70 judge bar; Tasks 13–15 of the parent plan stay
BLOCKED; everything new is gated behind `WORKSHEET_PLANNER_SLOT_CONTRACT=1` (default OFF) so
production (planner-v2 OFF, old loop default) is byte-identical until promotion is earned.

## Design (Stage 1 = ID contract on the existing free-form planner)

The research's destination is `CoverageLedger → SlotPack → SlotAuthor`. We earn it in two stages.
**Stage 1 keeps the current single free-form planning call** (max activity variety) and wraps it in a
deterministic contract; **Stage 2 (conditional)** adds slot-packing only if Stage 1's evidence
demands it. Four review refinements are baked in:

1. **No trust loophole.** The model's `covered_source_item_ids` claim is verified deterministically
   against the *actual authored text* (exact_text must appear) — a claim alone never counts.
2. **Variety preserved.** Stage 1 does not pin activity types; the LLM still authors freely. The
   contract only guarantees coverage; deterministic repair fills gaps as a backstop.
3. **Cost flat.** One planner call (unchanged) + one deterministic repair pass (no extra LLM call).
4. Stage-1 coverage is guaranteed *before* the judge runs (repair closes gaps), so the judge's
   content_coverage stops being the variance source without any approval-logic change.

```
frozen LiteracySkillModel
  -> build_coverage_ledger()                      [deterministic, Task S0]
  -> planner prompt carries the ledger + asks for covered_source_item_ids  [Task S1]
  -> ONE planner call -> LessonPlan (PlannedItems tagged with claimed ids)
  -> verify_coverage(plan, ledger)                [deterministic claim+exact-text, Task S2]
  -> repair_coverage(plan, missing)               [deterministic catch-up items, Task S3]
  -> _translate_plan + enforce_section_cap         (existing)
  -> judge (median-of-N)                           (existing)
  -> fallback                                       (existing)
```

---

### Task S0: Deterministic CoverageLedger

**Files:** create `adapt/coverage_ledger.py`; test `tests/test_coverage_ledger.py`.

Build the hard contract from the frozen skill model (no LLM).

```python
class CoverageLedgerEntry(BaseModel):
    source_item_id: str            # stable, e.g. "word_003", "chain_001_step_2", "sentence_002"
    item_type: Literal["word", "word_chain", "word_chain_step", "sentence",
                       "passage", "roll_and_read_word", "sight_word"]
    exact_text: str                # the text that MUST appear in an authored item
    parent_source_text: str | None # e.g. the full chain a step came from
    priority: Literal["required", "optional_enrichment"]
    allowed_practice_forms: list[str]
```

`build_coverage_ledger(skill: LiteracySkillModel) -> list[CoverageLedgerEntry]`:
- one `word` entry per deduped `target_words` / `word_list` content token;
- one `word_chain` entry per `word_chain` source item, plus one `word_chain_step` per arrow-split step;
- one `sentence` entry per `sentence`/`practice_sentences` source item (full text preserved);
- one `passage` entry per `passage` source item;
- `sight_word` entries from sight-word source items;
- IDs are deterministic and stable across runs (index-based per type).
- `required` = words, chain steps, sentences, passage; `optional_enrichment` = pure repetition/roll&read duplicates already covered.

- [ ] **RED:** `tests/test_coverage_ledger.py` — feed a synthetic skill model with a chain
  `mule -> mute -> cute`, two sentences, a passage; assert one entry per word/step/sentence/passage,
  stable IDs, exact_text preserved verbatim, chain steps carry `parent_source_text`.
- [ ] **GREEN:** implement `build_coverage_ledger`.
- [ ] Commit: `feat: deterministic CoverageLedger from the frozen skill model`.

### Task S1: Ledger in the planner prompt + claimed IDs in the schema

**Files:** `adapt/llm_adapt.py` (`PlannedItem`), `adapt/llm_planner.py` (`_build_planner_prompt`);
tests `tests/test_llm_adapt.py`, `tests/test_llm_planner.py`.

- Add `covered_source_item_ids: list[str] = Field(default_factory=list)` to `PlannedItem`.
- In `_build_planner_prompt`, when `WORKSHEET_PLANNER_SLOT_CONTRACT=1`, render a "## Coverage
  contract" block listing every `required` ledger entry as `id | type | exact_text`, plus the
  instruction: every required id MUST be covered by at least one item, and each item MUST list the
  ids it covers in `covered_source_item_ids`, using the exact_text verbatim. Extend the output-format
  JSON to show `"covered_source_item_ids": ["..."]`. Flag OFF ⇒ prompt unchanged.

- [ ] **RED:** `PlannedItem` parses `covered_source_item_ids`; prompt includes the ledger ids +
  the `covered_source_item_ids` schema key only when the flag is set (monkeypatch env).
- [ ] **GREEN:** implement.
- [ ] Commit: `feat: planner prompt carries coverage ledger + per-item covered ids (flagged)`.

### Task S2: Deterministic coverage verifier (claim + exact-text)

**Files:** `adapt/coverage_ledger.py`; test `tests/test_coverage_ledger.py`.

`verify_coverage(plan: LessonPlan, ledger) -> CoverageReport` where
`CoverageReport(missing: list[CoverageLedgerEntry], unknown_claims: list[str])`.

For each `required` entry it is **covered** iff some `PlannedItem` (a) lists the id in
`covered_source_item_ids` AND (b) the entry's `exact_text` actually appears (normalized:
casefold, collapse whitespace) in that item's `content`, `options`, or `answer`. A claimed id with
no matching text does NOT count (closes the trust loophole). Ids claimed that aren't in the ledger
go to `unknown_claims`.

- [ ] **RED:** plan that claims `word_001` but omits its text → entry in `missing`; plan that
  includes the text under the right id → empty `missing`; bogus id → `unknown_claims`.
- [ ] **GREEN:** implement.
- [ ] Commit: `feat: deterministic coverage verifier (claim + exact-text presence)`.

### Task S3: Deterministic repair pass

**Files:** `adapt/coverage_ledger.py`; test `tests/test_coverage_ledger.py`.

`repair_coverage(plan: LessonPlan, missing: list[CoverageLedgerEntry]) -> LessonPlan`: append a
deterministic "Catch-up practice" `WorksheetPlan`/`ActivityPlan` whose `PlannedItem`s cover each
missing required entry — a read/write item per word/sentence/passage (content = exact_text), a build
activity for a missing chain — each tagged with the right `covered_source_item_ids`. No LLM call.
`enforce_section_cap` (already wired downstream) splits any overflow into more mini-worksheets.

- [ ] **RED:** given a plan missing two words and a sentence, `repair_coverage` returns a plan for
  which `verify_coverage` reports zero missing; existing covered items untouched; no missing entry →
  plan returned unchanged.
- [ ] **GREEN:** implement.
- [ ] Commit: `feat: deterministic coverage repair appends catch-up practice for dropped source`.

### Task S4: Wire the contract into `plan_lesson_llm` (flagged)

**Files:** `adapt/llm_planner.py`; test `tests/test_llm_planner.py`.

When `WORKSHEET_PLANNER_SLOT_CONTRACT=1`: build the ledger, and after `_parse_lesson_plan` run
`verify_coverage` → if `missing`, `repair_coverage` → then the existing `_translate_plan` +
`enforce_section_cap` → judge. Log a `coverage` line (required / covered / repaired counts) into the
planner log entry. Flag OFF ⇒ the function is byte-identical to today.

- [ ] **RED:** with the flag on and a planner stub returning a plan that drops a required word, the
  final worksheets contain a practice item with that word (repair fired). Flag off + same stub ⇒
  word absent (current behavior), proving the gate.
- [ ] **GREEN:** implement.
- [ ] Commit: `feat: enforce coverage contract in plan_lesson_llm behind WORKSHEET_PLANNER_SLOT_CONTRACT`.

### Task S5: Falsification experiment (live, owner environment)

Not offline. Re-run the trustworthy gate with the contract on:

```
SSL_CERT_FILE=$(.venv/bin/python -c "import certifi; print(certifi.where())") \
WORKSHEET_EXTRACTION_CACHE=samples/output/extraction_cache \
WORKSHEET_PLANNER_SLOT_CONTRACT=1 WORKSHEET_JUDGE_SAMPLES=3 WORKSHEET_LLM_ADAPT=1 \
.venv/bin/python adapt_battery.py \
  --input samples/input/IMG_0003.JPG --input samples/input/IMG_0004.JPG \
  --input samples/input/IMG_0005.JPG --profile profiles/ian.yaml \
  --theme roblox_obby --runs 2
```

- [ ] Compare against the Session 48 baseline (`20260612_220801`, `20260612_222046`): do the
  coverage-driven approve/reject flips disappear? Record both scorecards in the context doc.
- [ ] Blind-review current planner-v2 vs contract output on the same images for engagement and for
  repair-filler quality. **Success:** zero missing required ids; no coverage flips; no engagement
  drop; no new worked-example/answer-key defects. **Falsified if:** worksheets go flat/repetitive,
  repair produces many unnatural filler items, or reviewers prefer plain planner-v2.

### Task S6: Full SlotPack — CONDITIONAL (only if S5 is falsified)

If S5 shows residual variance or low-quality repair filler, graduate to the research's deterministic
`SlotPack`: pack ledger entries into ADHD-safe slots *before* authoring and have the LLM author per
slot, choosing among `allowed_practice_forms` (NOT a single pinned `activity_family`, to keep
variety). Keep ID-equality + exact-text verification and the existing fallback/judge/render path.
Do NOT build this preemptively — earn it with S5 evidence.

---

## After the contract passes (unchanged from the plan of record)

C-small human approve-precision check on ~15–20 approved+cusp plans + a Gemini cross-vendor
second-opinion judge BEFORE flipping the default (Tasks 13–14). Governing metric: judge-approve
precision vs human; stop and build the full calibration set if ≥~20% of approved plans are defective.
Hold Task 15 (delete old path) until 1–2 weeks of production telemetry.
