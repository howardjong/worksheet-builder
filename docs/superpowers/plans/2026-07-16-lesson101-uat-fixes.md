# Lesson-101 UAT Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close both lesson-101 UAT defects (spec `docs/superpowers/specs/2026-07-16-lesson101-uat-fixes-design.md`): D48 — LLM-planned `word_chain` activities can never count as manipulation coverage evidence; D49 — the judge's handed facts describe a multi-hop chain that single suffixes (`-ly`) structurally cannot form.

**Architecture:** No new modules. D48 lands in `adapt/llm_adapt.py` (route `word_chain` through the deterministic stamped parsers, with D1-parity suffix support) plus `adapt/llm_planner.py` (prompt + retry-feedback format guidance). D49 lands in `adapt/objective_ledger.py` (chain-shape-aware `sufficiency_rule` authored at ledger build) plus `adapt/llm_judge.py` (one rubric guard line). The deterministic coverage evaluator is deliberately untouched — verified passing for single-hop packages already.

**Tech Stack:** Python 3.13 local / 3.11 CI, pytest, pydantic v2, OpenAI + Gemini APIs (mocked in tests; live only in Task 4).

## Global Constraints

- **Models (owner directive, complexity-matched):** Task 1 → Sonnet 5 implement, Sonnet 5 review. Task 2 → Sonnet 5 implement, Sonnet 5 review. Task 3 → Opus 4.8 implement, Opus 4.8 review (cross-module prompt-fact wording with a byte-identical regression bar). Task 4 → Opus 4.8 (live-run interpretation against session-61 baselines). Final whole-branch review → Fable 5, including the per-defect traceability audit.
- **Per-defect traceability (goal contract):** each task report lists the defect(s) it closes (D48/D49) and, per defect, the named test(s) with RED evidence (command + failing output BEFORE the fix) and GREEN evidence (command + passing output AFTER). The final review receives the assembled 2-row table at `.superpowers/sdd/lesson101-fix-traceability.md`; a row missing either piece is a blocking finding.
- **Dispatch rule (G19):** implementer subagents work synchronously with their OWN tool calls; do NOT use the Agent tool; nothing runs "in the background".
- **Reviewer gate (G17):** every task review runs FULL `make typecheck` (never per-file mypy) plus `make test` and `make lint`.
- **Deterministic evaluator untouched:** no changes to `validate/objective_coverage.py` logic. `_evaluate_manipulation_cell` already passes single-hop packages (spec "Root-cause verification" #3); any task that thinks it needs to touch it has misread the spec — stop and surface.
- **Lesson-100 regression bar:** multi-hop lessons' manipulation-cell facts must stay byte-identical (`sufficiency_rule == "≥1 coherent build/change chain (count steps, not words)"`).
- **Photo path untouched:** all changes are planner-v2 / lesson-mode / shared-template scoped; existing photo tests pass unchanged.
- **No PROMPT_VERSION bump:** the page prompt is untouched this cycle. The planner/judge prompts carry no version constant — do not invent one.
- **Repo rules:** NO `Co-Authored-By` trailers (pre-commit hook blocks them). If pre-commit needs a fresh hook install, commit with `env -u PIP_UPLOADED_PRIOR_TO git commit ...`. If ruff-format rewrites files during commit, `git add -u` and retry once.
- Run commands from the repo root with `.venv/bin/python -m pytest` / `make test` / `make lint` / `make typecheck`.

---

### Task 1: D48 — word_chain becomes a mechanical format; suffix-aware translation parser

**Model:** Sonnet 5 (implement + review)

**Files:**
- Modify: `adapt/llm_adapt.py:374` (`_MECHANICAL_FORMATS`)
- Modify: `adapt/llm_adapt.py:445-465` (`_build_items_from_activity` word_chain branch)
- Modify: `tests/test_llm_adapt.py:191-217` (existing fixture adaptation, see Step 5)
- Test: `tests/test_llm_adapt.py`

**Interfaces:**
- Consumes: `adapt.engine._parse_chain_steps(chains: list[str]) -> list[dict[str, str]]` (keys `from_word`/`to_word`/`old_letter`/`new_letter`), `adapt.engine._parse_suffix_chain_steps(chains: list[str], suffixes: list[str]) -> list[dict[str, str]]` (keys `from_word`/`to_word`/`suffix`), `skill.taxonomy.is_suffix_skill(specific_skill: str) -> bool`, `skill.taxonomy.suffixes_for_skill(specific_skill: str) -> list[str]` — all existing, unchanged.
- Produces: LLM-plan `word_chain` activities now yield `ActivityItem`s stamped `metadata={"display": "chain_step"}` built from `activity.words` arrow strings; authored `items` on `word_chain` are always discarded. Task 2's prompt changes and Task 4's live runs rely on this behavior.

- [ ] **Step 1: Write the failing tests**

In `tests/test_llm_adapt.py`, add after `test_match_activities_use_mechanical_builder_even_with_items` (line ~189). Reuse the module's existing imports (`ActivityPlan`, `LessonPlan`, `PlannedItem`, `WorksheetPlan`, `_translate_plan`, `build_rules`, `LiteracySkillModel`, `SourceItem`) and its `_profile()` helper:

```python
def _suffix_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="suffix_ly",
        learning_objectives=["Add -ly to base words"],
        target_words=["quickly", "lightly", "deeply"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="quick → quickly",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _word_chain_plan(words: list[str], items: list[PlannedItem]) -> LessonPlan:
    return LessonPlan(
        worksheets=[
            WorksheetPlan(
                title="Word Builder",
                activities=[
                    ActivityPlan(
                        activity_type="word_chain",
                        micro_goal="Build new words",
                        words=words,
                        items=items,
                        instructions=["Read the word.", "Add the ending."],
                        response_format="write",
                    )
                ],
            )
        ]
    )


def test_suffix_word_chain_uses_mechanical_builder_even_with_items() -> None:
    """D48 RED (suffix): authored word_chain items today bypass the stamped
    deterministic parser, so no item can ever count as chain evidence."""
    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[
            PlannedItem(content="Make quick. Add -ly. Write the new word.", answer="quickly"),
        ],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    items = worksheets[0].chunks[0].items
    assert items, "word_chain activity must not vanish"
    assert all(i.metadata.get("display") == "chain_step" for i in items)
    # Deterministic suffix template, not the model's prose.
    assert items[0].content == "quick + -ly → ______"
    assert items[0].answer == "quickly"
    assert [i.answer for i in items] == ["quickly", "lightly", "deeply"]


def test_letter_word_chain_uses_mechanical_builder_even_with_items() -> None:
    """D48 RED (letter chain): same stamp bypass on non-suffix lessons."""
    plan = _word_chain_plan(
        words=["mule → mute"],
        items=[
            PlannedItem(
                content='Start with "mule". Change the "l" to "t". Write the new word.',
                answer="mute",
            ),
        ],
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    assert items, "word_chain activity must not vanish"
    assert all(i.metadata.get("display") == "chain_step" for i in items)
    assert items[0].answer == "mute"


def test_suffix_word_chain_words_parse_to_items() -> None:
    """D48 RED (WS1.2 parser parity): suffix-pair words currently parse to 0
    items — _build_items_from_activity only knows letter-substitution chains."""
    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    assert worksheets, "suffix chain worksheet must survive translation"
    items = worksheets[0].chunks[0].items
    assert [i.content for i in items] == [
        "quick + -ly → ______",
        "light + -ly → ______",
        "deep + -ly → ______",
    ]


def test_translated_suffix_chain_passes_manipulation_coverage() -> None:
    """D48 GREEN acceptance: translated stamped items satisfy the manipulation
    cell through the real evidence layer (spec exit criterion 1)."""
    from adapt.objective_ledger import ClassifiedSourceItem, ObjectiveCell, ObjectiveLedger
    from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage

    plan = _word_chain_plan(
        words=["quick → quickly", "light → lightly", "deep → deeply"],
        items=[],
    )
    worksheets = _translate_plan(
        plan, _suffix_skill(), _profile(), "default", build_rules(_profile())
    )

    ledger = ObjectiveLedger(
        source_skill_hash="hash",
        lesson_number=101,
        corpus_status="matched",
        corpus_version="v1",
        corpus_lesson_id="ufli_101",
        primary_pattern=None,
        objectives=[
            ObjectiveCell(
                objective_id="obj_manipulation",
                objective_type="phoneme_grapheme_manipulation",
                display_name="Build and change words",
                concept="manipulation",
                target_pattern=None,
                importance="essential",
                required_forms=["word_chain", "chain_script"],
                min_practice_count=1,
                max_recommended_count=1,
                acceptable_response_formats=["word_chain"],
                sufficiency_rule="one coherent chain",
            )
        ],
        source_items=[
            ClassifiedSourceItem(
                source_item_id="src_chain",
                item_type="word_chain",
                content="quick → quickly",
                normalized_content="quick → quickly",
                coverage_class="required_form",
                required_form="word_chain",
                objective_ids=["obj_manipulation"],
                mandatory=True,
            )
        ],
    )
    evidence = build_evidence_index(worksheets, ledger)
    result = evaluate_objective_coverage(ledger, evidence)
    manip = next(r for r in result.objective_results if r.objective_id == "obj_manipulation")

    assert manip.required_forms_present is True
    assert manip.status == "pass"
```

- [ ] **Step 2: Run the new tests to verify they fail (RED evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_llm_adapt.py -k "word_chain or manipulation_coverage" -v`
Expected: all 4 new tests FAIL —
- `test_suffix_word_chain_uses_mechanical_builder_even_with_items`: authored item content `"Make quick. Add -ly. Write the new word."` has no `chain_step` stamp (metadata assertion fails).
- `test_letter_word_chain_uses_mechanical_builder_even_with_items`: same stamp failure.
- `test_suffix_word_chain_words_parse_to_items`: IndexError/assert on empty worksheets or items — suffix pairs parse to 0 steps.
- `test_translated_suffix_chain_passes_manipulation_coverage`: `required_forms_present is False` ("no authored build/change chain present").

Save the command + output verbatim for the task report (D48 RED evidence).

- [ ] **Step 3: Implement**

In `adapt/llm_adapt.py`, change line 374:

```python
# Formats whose renderer/evidence contracts (shuffled picture options, phoneme
# boxes, stamped chain steps) must stay mechanically constructed even when the
# model authors items. word_chain is here because the coverage evaluator's
# chain-evidence discriminator counts ONLY parser-stamped items
# (validate/objective_coverage.py::_CHAIN_DISPLAYS) — authored chain items can
# never count, by anti-gaming design, so they must not be preferred (D48).
_MECHANICAL_FORMATS = {"match", "sound_box", "word_chain"}
```

Replace the `word_chain` branch of `_build_items_from_activity` (lines 445-465) with:

```python
    if activity.activity_type == "word_chain":
        # Parse chains into build/change steps. Suffix lessons take the
        # add-the-ending parser (D1 parity with adapt/engine.py:1061-1068 —
        # letter-substitution parsing yields 0 steps for length-changing
        # pairs like "quick → quickly").
        from adapt.engine import _parse_chain_steps, _parse_suffix_chain_steps
        from skill.taxonomy import is_suffix_skill, suffixes_for_skill

        if is_suffix_skill(skill.specific_skill):
            for suffix_step in _parse_suffix_chain_steps(
                activity.words, suffixes_for_skill(skill.specific_skill)
            )[:max_items]:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=(
                            f"{suffix_step['from_word']} + "
                            f"-{suffix_step['suffix']} → ______"
                        ),
                        response_format="write",
                        metadata={"display": "chain_step"},
                        answer=suffix_step["to_word"],
                    )
                )
        else:
            chain_steps = _parse_chain_steps(activity.words)
            for step in chain_steps[:max_items]:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=(
                            f'Start with "{step["from_word"]}". '
                            f'Change the "{step["old_letter"]}" '
                            f'to "{step["new_letter"]}". '
                            f"Write the new word."
                        ),
                        response_format="write",
                        metadata={"display": "chain_step"},
                        answer=step["to_word"],
                    )
                )
```

Note: the letter-chain arm is today's code unchanged; the suffix arm is new and mirrors `adapt/engine.py:1082-1092`'s item template exactly (same content format, same stamp), minus the engine's worked-example consumption — the translation path takes all parsed steps up to `max_items`.

- [ ] **Step 4: Run the new tests to verify they pass (GREEN evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_llm_adapt.py -k "word_chain or manipulation_coverage" -v`
Expected: all 4 PASS. Save command + output (D48 GREEN evidence).

- [ ] **Step 5: Adapt the one existing test this intentionally breaks**

`test_translate_drops_self_negating_worked_example` (`tests/test_llm_adapt.py:191-217`) uses `activity_type="word_chain"` with authored items `cute`/`cake` and no words — after this change those items are discarded, the salvage words (`["cute", "cake"]` — no arrows) parse to 0 steps, the chunk vanishes, and the test errors. Its intent (self-negating worked examples are dropped) is activity-type-agnostic. Change ONLY its fixture: `activity_type="word_chain"` → `activity_type="write"`, delete its `items=[...]` list, and add `words=["cute", "cake"]`. Keep the `worked_example` string and the final assertion unchanged. Do not touch any other test.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/test_llm_adapt.py -v` then `make test && make lint && make typecheck`
Expected: all green. If any OTHER existing test breaks, stop and surface it in the task report rather than adapting it — the spec predicts exactly one casualty (Step 5's).

- [ ] **Step 7: Commit**

```bash
git add adapt/llm_adapt.py tests/test_llm_adapt.py
git commit -m "fix(adapt): route word_chain plans through the stamped deterministic parsers (D48)"
```

---

### Task 2: D48 — planner prompt words-format + retry-feedback format hint

**Model:** Sonnet 5 (implement + review)

**Files:**
- Modify: `adapt/llm_planner.py:267-272` (build/change-chain example block inside the objective authoring template)
- Modify: `adapt/llm_planner.py:367-368` (CRITICAL RULES rule 5)
- Modify: `adapt/llm_planner.py:554-570` (`_coverage_feedback_block`)
- Test: `tests/test_llm_planner.py`

**Interfaces:**
- Consumes: Task 1's behavior — authored `word_chain` items are discarded; `activity.words` arrow strings are the only channel that produces chain items.
- Produces: prompt text only; no signatures change. `_coverage_feedback_block(coverage: ObjectiveCoverageResult) -> str` keeps its signature.

- [ ] **Step 1: Write the failing tests**

In `tests/test_llm_planner.py`, add near the existing D12 test (`test_authoring_block_contains_concrete_chain_example_and_budget_line`, line ~448). Reuse the module's `_skill()` / `_profile()` helpers and existing imports; add `_coverage_feedback_block` to the `from adapt.llm_planner import ...` block and `from adapt.objective_ledger import ObjectiveCellResult, ObjectiveCoverageResult, PackageBounds` if not already imported (mirror however `ObjectiveCoverageResult` is constructed elsewhere in this file or in `tests/test_objective_coverage.py` — copy an existing minimal constructor call from those tests rather than inventing field values):

```python
def test_prompt_rule5_and_chain_example_use_words_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D48: after Task 1, authored word_chain items are discarded — the prompt
    must direct chain content into "words" arrow strings for BOTH lesson types."""
    monkeypatch.setenv("WORKSHEET_OBJECTIVE_COVERAGE", "1")
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    # Rule 5 covers word_chain alongside match/sound_box.
    assert '"match", "sound_box", and "word_chain"' in prompt
    # The chain example shows the words-format for suffix AND letter lessons.
    assert '"words": ["quick → quickly", "light → lightly"]' in prompt
    assert '"words": ["cry → try → dry"]' in prompt
    # And explicitly warns authored word_chain items are ignored.
    assert "do NOT author word_chain" in prompt


def test_coverage_feedback_names_word_chain_words_format() -> None:
    """D48: the ONE coverage retry must tell the model the structural fix,
    not just restate the miss."""
    coverage = _failing_manip_coverage()  # helper below
    block = _coverage_feedback_block(coverage)

    assert "obj_manipulation" in block
    assert '"words"' in block
    assert "quick → quickly" in block
    assert "cry → try → dry" in block
```

For `_failing_manip_coverage()`, construct the minimal `ObjectiveCoverageResult` whose `objective_results` contains one failing cell with `missing_required_forms=["word_chain"]` — copy the construction pattern from an existing `ObjectiveCoverageResult` in `tests/test_objective_coverage.py` (search for `ObjectiveCoverageResult(` there and reuse its required-field values verbatim, changing only `objective_id="obj_manipulation"`, `status="fail"`, `missing_required_forms=["word_chain"]`).

- [ ] **Step 2: Run to verify they fail (RED evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_llm_planner.py -k "words_format" -v`
Expected: both FAIL — rule 5 currently reads `For "match" and "sound_box" activities`, the example block authors `items`, and the feedback block has no format hint.

- [ ] **Step 3: Implement**

(a) `adapt/llm_planner.py:267-272` — replace the example block (note: this text sits inside an f-string template; keep `{{` / `}}` brace doubling exactly as shown):

```python
Example of a compliant build/change-chain activity (adapt words to THIS lesson):
  {{"activity_type": "word_chain", "words": ["quick → quickly", "light → lightly"], "items": []}}
  for suffix lessons, or
  {{"activity_type": "word_chain", "words": ["cry → try → dry"], "items": []}}
  for letter-pattern lessons. The rendering system builds the student-facing
  steps mechanically from these arrow strings — do NOT author word_chain
  "items"; they are ignored.
Your plan MUST include one such build/change chain activity, and the plan's
total estimated minutes MUST fit the session budget stated below.
```

(b) `adapt/llm_planner.py:367-368` — replace rule 5:

```python
5. For "match", "sound_box", and "word_chain" activities, list the words in
   "words" and leave "items" empty — the rendering system constructs those
   mechanically. word_chain "words" are arrow strings: one pair per string
   for suffix lessons ("quick → quickly"), the full chain for letter-pattern
   lessons ("cry → try → dry").
```

(c) `_coverage_feedback_block` (lines 560-567) — extend the failing-cell loop:

```python
    for cell in coverage.objective_results:
        if cell.status != "fail":
            continue
        missing = ", ".join(cell.missing_required_forms) or "insufficient distinct practice"
        line = (
            f"- {cell.objective_id}: REJECTED — missing/insufficient: {missing}. "
            f"Your revised plan MUST satisfy this objective IN its required form."
        )
        if "word_chain" in cell.missing_required_forms:
            line += (
                ' Provide the chain as arrow strings in the activity\'s "words" '
                '(suffix lessons: one pair per string, e.g. "quick → quickly"; '
                'letter lessons: the full chain, e.g. "cry → try → dry") with '
                '"items" empty — authored word_chain items are ignored.'
            )
        lines.append(line)
```

- [ ] **Step 4: Run to verify they pass (GREEN evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_llm_planner.py -v`
Expected: new tests PASS. The existing D12 test (`test_authoring_block_contains_concrete_chain_example_and_budget_line`) asserts `"→ ______"` in the block — the new example text no longer contains `→ ______`. Update that ONE assertion to match the new format: replace `assert "→ ______" in block` with `assert '"words": ["quick → quickly"' in block`. Its other assertions (`MUST include`, `minutes`) stand. If `test_prompt_authors_chain_in_required_form_when_flag_on` fails on the `"tone" in prompt` assertion, that word comes from the ledger cell block (source chain content), not the example — it should still pass; if it doesn't, stop and surface rather than weakening it.

- [ ] **Step 5: Full gates**

Run: `make test && make lint && make typecheck`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add adapt/llm_planner.py tests/test_llm_planner.py
git commit -m "fix(planner): word_chain authored via words arrow-format; retry feedback names the format (D48)"
```

---

### Task 3: D49 — shape-aware manipulation facts + judge rubric guard

**Model:** Opus 4.8 (implement + review) — cross-module prompt-fact wording with a byte-identical regression bar on multi-hop lessons.

**Files:**
- Modify: `adapt/objective_ledger.py:505-507` (call site) and `:779-792` (`_make_manipulation_cell`)
- Modify: `adapt/llm_judge.py:343-348` (`_SEVERE_DEFECT_GLOSS["wrong_cognitive_task"]`)
- Test: `tests/test_objective_ledger.py`, `tests/test_llm_judge.py`

**Interfaces:**
- Consumes: `skill.taxonomy.is_suffix_skill(specific_skill: str) -> bool`; `_ARROW_RE` (module-level in `adapt/objective_ledger.py:465`); the existing `_make_manipulation_cell(ctx: PatternContext) -> ObjectiveCell`.
- Produces: `_make_manipulation_cell(skill: LiteracySkillModel, ctx: PatternContext) -> ObjectiveCell` (signature change, mirrors `_make_decode_cell(skill, ctx)`); new module-private helper `_chain_shape(skill: LiteracySkillModel) -> str` returning `"single_hop" | "multi_hop"`. The single-hop `sufficiency_rule` EXACT text (Task 4's live runs and the judge prompt tests depend on it): `"≥2 add-the-ending transformations (base + suffix → new word); this suffix forms no multi-step chain, so independent pairs ARE this lesson's manipulation form"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_objective_ledger.py`, add (reuse the module's existing imports; `build_objective_ledger` is already imported there):

```python
def _chain_skill(specific_skill: str, chain_contents: list[str]) -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill=specific_skill,
        learning_objectives=["objective"],
        target_words=["quickly"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_chain", content=c, source_region_index=i)
            for i, c in enumerate(chain_contents)
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _manip_rule(skill: LiteracySkillModel) -> str:
    ledger = build_objective_ledger(skill, corpus_lookup=lambda n: None)
    cell = next(c for c in ledger.objectives if c.objective_id == "obj_manipulation")
    return cell.sufficiency_rule


def test_single_hop_suffix_lesson_gets_pair_sufficiency_rule() -> None:
    """D49 RED: lesson-101-shaped facts (single suffix, 2-word chains only)
    currently hand the judge a multi-hop rule the lesson cannot satisfy."""
    rule = _manip_rule(
        _chain_skill("suffix_ly", ["quick → quickly", "light → lightly", "deep → deeply"])
    )
    assert rule == (
        "≥2 add-the-ending transformations (base + suffix → new word); this "
        "suffix forms no multi-step chain, so independent pairs ARE this "
        "lesson's manipulation form"
    )


def test_multi_hop_suffix_lesson_keeps_chain_rule_byte_identical() -> None:
    """Lesson-100 regression bar: -er/-est (3-word chains) facts unchanged."""
    rule = _manip_rule(
        _chain_skill("suffix_er_est", ["slow → slower → slowest", "long → longer → longest"])
    )
    assert rule == "≥1 coherent build/change chain (count steps, not words)"


def test_mixed_chain_suffix_lesson_counts_as_multi_hop() -> None:
    """Any 3+-word chain anywhere → the lesson CAN form a real chain."""
    rule = _manip_rule(_chain_skill("suffix_er_est", ["quick → quickly", "slow → slower → slowest"]))
    assert rule == "≥1 coherent build/change chain (count steps, not words)"


def test_non_suffix_lesson_keeps_chain_rule_even_with_pair_chains() -> None:
    """Letter-chain lessons never get the add-the-ending wording, even when a
    source chain happens to be a 2-word pair."""
    rule = _manip_rule(_chain_skill("cvce_pattern", ["mule → mute"]))
    assert rule == "≥1 coherent build/change chain (count steps, not words)"
```

(If `SourceItem` / `LiteracySkillModel` are not yet imported in `tests/test_objective_ledger.py`, add `from skill.schema import LiteracySkillModel, SourceItem`.)

In `tests/test_llm_judge.py`, add near the `_build_objective_prompt` helper cluster (line ~267). Look at how `_build_objective_prompt()` constructs its ledger/gates/coverage/worksheets fixtures and mirror the same construction, swapping in a single-hop manipulation cell:

```python
def test_objective_prompt_carries_single_hop_manipulation_rule() -> None:
    """D49: the judge's handed facts must state the single-hop form. The cell's
    sufficiency_rule flows through _render_objectives verbatim — assert the
    distinctive fragment lands in the final prompt."""
    # Build the prompt exactly as _build_objective_prompt() does, but override
    # the manipulation cell's sufficiency_rule with the Task 3 single-hop text
    # before rendering (cell.model_copy(update={"sufficiency_rule": ...}) on the
    # fixture ledger's obj_manipulation cell).
    prompt = _build_objective_prompt_with_manip_rule(
        "≥2 add-the-ending transformations (base + suffix → new word); this "
        "suffix forms no multi-step chain, so independent pairs ARE this "
        "lesson's manipulation form"
    )
    assert "independent pairs ARE this lesson's manipulation form" in prompt


def test_wrong_cognitive_task_gloss_defers_to_sufficiency_rule() -> None:
    """D49: the rubric guard — the judge must not veto the form the handed
    facts declare correct."""
    prompt = _build_objective_prompt()
    assert "Do NOT vote this defect when the package exercises the cognitive task" in prompt
    assert "sufficiency_rule" in prompt
```

Implement `_build_objective_prompt_with_manip_rule(rule: str) -> str` as a thin wrapper: copy `_build_objective_prompt`'s body, and where it builds/receives its ledger, replace the manipulation cell via `ledger.model_copy(update={"objectives": [...]})` (or reconstruct the cell list) so `obj_manipulation.sufficiency_rule == rule`. Keep it in the test file.

- [ ] **Step 2: Run to verify they fail (RED evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_objective_ledger.py -k "sufficiency_rule or chain_rule or multi_hop" -v && .venv/bin/python -m pytest tests/test_llm_judge.py -k "single_hop or defers_to" -v`
Expected: `test_single_hop_suffix_lesson_gets_pair_sufficiency_rule` FAILS (rule is the multi-hop text); the three regression-shaped ledger tests PASS already (they pin current behavior — that is fine; they are the guard rail, not the red). `test_objective_prompt_carries_single_hop_manipulation_rule` PASSES already if `_render_objectives` pipes the rule through (it does — this test guards the seam); `test_wrong_cognitive_task_gloss_defers_to_sufficiency_rule` FAILS (guard text absent). The task report's D49 RED evidence = the two genuinely-failing tests' output; note explicitly in the report which tests were born-green guards.

- [ ] **Step 3: Implement**

(a) `adapt/objective_ledger.py` — add above `_make_manipulation_cell`:

```python
def _chain_shape(skill: LiteracySkillModel) -> str:
    """"single_hop" iff this is a suffix lesson whose chain source items are
    ALL 2-word pairs (no chain has a second hop to build through) — e.g.
    lesson 101's "quick → quickly". Any 3+-word chain, or any non-suffix
    lesson, is "multi_hop" (the classic build/change chain shape). Descriptive
    only: consumed by the sufficiency_rule text the judge reads, never by the
    deterministic evaluator."""
    from skill.taxonomy import is_suffix_skill

    if not is_suffix_skill(skill.specific_skill):
        return "multi_hop"
    longest = 0
    for item in skill.source_items:
        if item.item_type not in ("word_chain", "chain_script"):
            continue
        words = [w for w in _ARROW_RE.split(item.content) if w.strip()]
        longest = max(longest, len(words))
    return "single_hop" if 0 < longest <= 2 else "multi_hop"
```

(b) Replace `_make_manipulation_cell` (lines 779-792):

```python
def _make_manipulation_cell(skill: LiteracySkillModel, ctx: PatternContext) -> ObjectiveCell:
    if _chain_shape(skill) == "single_hop":
        rule = (
            "≥2 add-the-ending transformations (base + suffix → new word); this "
            "suffix forms no multi-step chain, so independent pairs ARE this "
            "lesson's manipulation form"
        )
    else:
        rule = "≥1 coherent build/change chain (count steps, not words)"
    return ObjectiveCell(
        objective_id="obj_manipulation",
        objective_type="phoneme_grapheme_manipulation",
        display_name="Build and change words (word chain)",
        concept="phoneme-grapheme manipulation",
        target_pattern=ctx.pattern_key or None,
        importance="essential",
        required_forms=["word_chain", "chain_script"],
        min_practice_count=_MANIP_MIN,
        max_recommended_count=_MANIP_MAX,
        acceptable_response_formats=list(_MANIP_FORMATS),
        sufficiency_rule=rule,
    )
```

(c) Update the call site (`adapt/objective_ledger.py:506`): `manip_cell = _make_manipulation_cell(skill, pattern_ctx)`.

(d) `adapt/llm_judge.py:344-348` — replace the `wrong_cognitive_task` gloss:

```python
    "wrong_cognitive_task": (
        "the activity makes the child do a different cognitive task than the "
        "objective names (e.g. a copying/tracing task where the objective is "
        "decoding). Do NOT vote this defect when the package exercises the cognitive task "
        "named in that cell's sufficiency_rule — the sufficiency_rule states the "
        "approved form for THIS lesson"
    ),
```

- [ ] **Step 4: Run to verify green (GREEN evidence — capture output)**

Run: `.venv/bin/python -m pytest tests/test_objective_ledger.py tests/test_llm_judge.py -v`
Expected: all PASS, including every pre-existing test (the ledger is embedded in many snapshots — if any golden/round-trip test pins the old manipulation `sufficiency_rule` for a SINGLE-hop suffix fixture, that pin is the defect being fixed: update it and say so in the report; if it pins a multi-hop or non-suffix fixture, the implementation is wrong — stop).

- [ ] **Step 5: Full gates**

Run: `make test && make lint && make typecheck`
Expected: green. `make test` sweeps `tests/test_adapt.py`, `tests/test_suffix_chains.py`, `tests/test_objective_coverage.py` and the engine tests that build ledgers — the signature change must not leak (only one call site exists; `grep -rn "_make_manipulation_cell" --include="*.py" .` must show exactly the definition, the call site, and tests).

- [ ] **Step 6: Commit**

```bash
git add adapt/objective_ledger.py adapt/llm_judge.py tests/test_objective_ledger.py tests/test_llm_judge.py
git commit -m "fix(judge): shape-aware manipulation sufficiency facts for single-suffix lessons (D49)"
```

---

### Task 4: Offline regression snapshot + live acceptance + traceability assembly

**Model:** Opus 4.8 — live-run interpretation against session-61 baselines; must surface, never override.

**Files:**
- Create: `.superpowers/sdd/lesson101-fix-traceability.md`
- Read: task reports from Tasks 1-3, `output/lesson101_uat_r2/artifacts/judge_verdict.json` (produced here)
- No production-code changes. If this task finds a code problem, STOP and report — do not fix inline.

**Interfaces:**
- Consumes: Tasks 1-3 merged into the working branch; their task reports with RED/GREEN evidence.
- Produces: the 2-row traceability table (D48, D49 → named tests → RED/GREEN command+output) and live-acceptance evidence for the final Fable 5 review.

- [ ] **Step 1: Offline deterministic snapshot (no network)**

Run:

```bash
WORKSHEET_LLM_ADAPT=0 WORKSHEET_PLANNER_V2=0 .venv/bin/python - <<'EOF'
from skill.lesson_loader import skill_model_from_lesson
from adapt.objective_ledger import build_objective_ledger

for lesson in (74, 100, 101):
    ledger = build_objective_ledger(skill_model_from_lesson(lesson))
    manip = next((c for c in ledger.objectives if c.objective_id == "obj_manipulation"), None)
    print(lesson, repr(manip.sufficiency_rule) if manip else "no manipulation cell")
EOF
```

Expected: lesson 101 prints the single-hop rule (`"≥2 add-the-ending transformations..."`); lessons 74 and 100 print the multi-hop rule byte-identical to `"≥1 coherent build/change chain (count steps, not words)"` (or `no manipulation cell` for 74 if its skill model carries no chain items — record whichever it is). Capture output.

- [ ] **Step 2: Live acceptance — lesson 101 (spec exit criterion 3)**

Run (NO `WORKSHEET_SHIP_UNAPPROVED`; requires `.env` API keys):

```bash
.venv/bin/python transform.py --lesson 101 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson101_uat_r2/
```

Then read `./output/lesson101_uat_r2/artifacts/judge_verdict.json` and `planner_attempts.json`. Record:
- planner outcome (did an LLM plan pass coverage this time? which attempt?),
- per-objective judge scores and severe defects,
- whether `obj_manipulation` has ANY severe-defect votes.

PASS condition: ships judge-approved, OR fails pre-render with `obj_manipulation` carrying zero severe defects (the known `obj_connected_text` / `overwhelming_or_adhd_unsafe` blocker is EXPECTED and owner-accepted — task_202def01). If `obj_manipulation` still draws severe-defect votes: STOP, do not re-run in a loop, do not override — record the verdict verbatim for the owner (the spec's residual-risk fallbacks are an owner decision).

- [ ] **Step 3: Live acceptance — lessons 74 and 100 regression (spec exit criterion 4)**

```bash
.venv/bin/python transform.py --lesson 74  --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson74_uat_r3/
.venv/bin/python transform.py --lesson 100 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson100_uat_r3/
```

Baselines (session 61): both abort pre-render on exactly ONE criterion — `obj_connected_text` (`overwhelming_or_adhd_unsafe`); everything else clean (L74 overall 0.79, L100 run-2 overall 0.74; judge score noise 0.52-0.68 on identical content is KNOWN — compare failing criteria sets, not raw scores). PASS condition: same failing-criteria set as baseline (connected-text only, or clean ship). Any NEW failing criterion — especially `obj_manipulation` on lesson 100 — is a blocking regression: STOP and report.

- [ ] **Step 4: Assemble the traceability table**

Write `.superpowers/sdd/lesson101-fix-traceability.md`:

```markdown
# Lesson-101 fix traceability (spec 2026-07-16, D48/D49)

| Defect | Fix commit(s) | Named test(s) | RED evidence | GREEN evidence |
|--------|---------------|---------------|--------------|----------------|
| D48 | <Task 1 + Task 2 commit SHAs> | test_suffix_word_chain_uses_mechanical_builder_even_with_items; test_letter_word_chain_uses_mechanical_builder_even_with_items; test_suffix_word_chain_words_parse_to_items; test_translated_suffix_chain_passes_manipulation_coverage; test_prompt_rule5_and_chain_example_use_words_format; test_coverage_feedback_names_word_chain_words_format | <command + failing output from Task 1 Step 2 and Task 2 Step 2> | <command + passing output from Task 1 Step 4 and Task 2 Step 4> |
| D49 | <Task 3 commit SHA> | test_single_hop_suffix_lesson_gets_pair_sufficiency_rule; test_wrong_cognitive_task_gloss_defers_to_sufficiency_rule (guards: test_multi_hop_suffix_lesson_keeps_chain_rule_byte_identical; test_mixed_chain_suffix_lesson_counts_as_multi_hop; test_non_suffix_lesson_keeps_chain_rule_even_with_pair_chains; test_objective_prompt_carries_single_hop_manipulation_rule) | <command + failing output from Task 3 Step 2> | <command + passing output from Task 3 Step 4> |

## Live acceptance evidence

### Lesson 101 (r2): <outcome + judge verdict summary + planner outcome>
### Lesson 74 (r3): <failing-criteria set vs baseline>
### Lesson 100 (r3): <failing-criteria set vs baseline>

## Offline snapshot
<Step 1 output verbatim>
```

Fill every `<...>` with the actual captured evidence — an empty cell is a blocking finding at final review.

- [ ] **Step 5: Full gates one last time**

Run: `make test && make lint && make typecheck`
Expected: green (mypy note: pyproject pins `python_version = "3.11"`, so the full local run targets CI syntax semantics; do not claim CI-clean beyond that).

- [ ] **Step 6: Commit**

```bash
git add .superpowers/sdd/lesson101-fix-traceability.md
git commit -m "docs: lesson-101 fix traceability + live acceptance evidence (D48/D49)"
```

---

### Final review (not a task — dispatch after Task 4)

**Model:** Fable 5, whole-branch review per superpowers:requesting-code-review, with the per-defect traceability audit: verify both rows of `.superpowers/sdd/lesson101-fix-traceability.md` carry RED and GREEN evidence, spot-check the named tests exist and assert what the table claims, and confirm the live-acceptance evidence matches the spec's exit criteria 3-5. Any missing evidence, any `obj_manipulation` severe-defect vote on the lesson-101 re-run, or any new failing criterion on lessons 74/100 is a blocking finding for the owner, not something to fix silently.
