# Lesson-100 UAT Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 13 defects from the lesson-100 UAT (spec `docs/superpowers/specs/2026-07-13-lesson100-uat-fixes-design.md`) with per-defect red/green TDD traceability.

**Architecture:** One root fix (morphology tier in the skill taxonomy) plus targeted fixes in the deterministic engine's content templates, the page-prompt builder, the merge stamp, and the judge/planner LLM plumbing. No new modules; every change lands in an existing file beside its tests.

**Tech Stack:** Python 3.13 local / 3.11 CI, pytest, pydantic v2, PyMuPDF, OpenAI + Gemini APIs (mocked in tests).

## Global Constraints

- **Models (owner directive):** Sonnet 5 for every implementer and every task reviewer; Fable 5 ONLY for the final whole-branch review, which must audit the per-defect traceability table (see below).
- **Per-defect traceability (goal contract):** each task report MUST list the ledger defect number(s) it closes (D1-D13 from the spec) and, per defect, the named test with RED evidence (command + failing output BEFORE the fix) and GREEN evidence (command + passing output AFTER). The final review receives the assembled 13-row table; any row missing either piece is a blocking finding.
- **PROMPT_VERSION:** bumped EXACTLY ONCE this cycle — `"page_prompt_v3"` → `"page_prompt_v4"` in Task 3. No other task bumps it again.
- **Photo path untouched:** all changes are lesson-mode or shared-template scoped; existing photo tests must pass unchanged.
- **Privacy:** no birthdate or profile PII in prompts, specs, or fixtures.
- **Repo rules:** NO `Co-Authored-By` trailers (pre-commit hook blocks them). If pre-commit needs a fresh hook install, commit with `env -u PIP_UPLOADED_PRIOR_TO git commit ...`. If ruff-format rewrites files during commit, `git add -u` and retry once.
- **CI note:** CI runs mypy on Python 3.11; do not claim CI-clean from a 3.13 local typecheck alone.
- Run commands from the repo root with `.venv/bin/python -m pytest` / `make test` / `make lint` / `make typecheck`.

---

### Task 1: Morphology taxonomy tier + suffix learning goal (defect D13)

**Files:**
- Modify: `skill/taxonomy.py` (after `PHONICS_PATTERNS`, ~line 171; and top of `match_phonics_pattern`, ~line 183)
- Modify: `adapt/feedback.py:26-32` (`learning_goal_statement`)
- Modify: `tests/fixtures/` lesson corpus — add the lesson-100 record if absent (copy the `"lesson_id": "100"` line verbatim from `data/ufli/normalized.jsonl` into the fixture corpus file used by `tests/test_lesson_loader.py`; look at how lesson 74's record got there and mirror it)
- Test: `tests/test_skill.py`, `tests/test_feedback.py`, `tests/test_lesson_loader.py`

**Interfaces:**
- Consumes: existing `PHONICS_PATTERNS` / `match_phonics_pattern(concept_text) -> str | None`.
- Produces (later tasks rely on these EXACT names): `MORPHOLOGY_SUFFIXES: frozenset[str]`, `match_morphology_pattern(concept_text: str) -> str | None`, `is_suffix_skill(specific_skill: str) -> bool`, `suffixes_for_skill(specific_skill: str) -> list[str]` — all in `skill/taxonomy.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_skill.py` add:

```python
def test_suffix_concept_maps_to_morphology_not_r_controlled() -> None:
    from skill.taxonomy import match_phonics_pattern

    assert match_phonics_pattern("-er, -est") == "suffix_er_est"


def test_morphology_helpers() -> None:
    from skill.taxonomy import is_suffix_skill, match_morphology_pattern, suffixes_for_skill

    assert match_morphology_pattern("-er, -est") == "suffix_er_est"
    assert match_morphology_pattern("-ed") == "suffix_ed"
    # Rime-family lessons stay phonics: any non-suffix hyphen token vetoes.
    assert match_morphology_pattern("-ing, -ang, -ong, -ung") is None
    assert match_morphology_pattern("ai/ay") is None
    assert is_suffix_skill("suffix_er_est") is True
    assert is_suffix_skill("r_controlled") is False
    assert suffixes_for_skill("suffix_er_est") == ["er", "est"]
    assert suffixes_for_skill("cvce") == []


def test_existing_patterns_unchanged() -> None:
    from skill.taxonomy import match_phonics_pattern

    assert match_phonics_pattern("-ing, -ang, -ong, -ung") == "cvc_blending"
    assert match_phonics_pattern("ai/ay") == "vowel_teams"
    assert match_phonics_pattern("er") == "r_controlled"  # bare grapheme, no hyphen
```

In `tests/test_feedback.py` add:

```python
def test_suffix_learning_goal() -> None:
    from adapt.feedback import learning_goal_statement

    assert (
        learning_goal_statement("phonics", "suffix_er_est")
        == "I can add -er and -est to compare things"
    )
    assert learning_goal_statement("phonics", "suffix_ed") == "I can add -ed to words"
```

In `tests/test_lesson_loader.py` add (after adding the lesson-100 fixture record):

```python
def test_lesson_100_classified_as_suffix_lesson() -> None:
    skill = _load_fixture_lesson(100)  # use this module's existing fixture-loading helper
    assert skill.specific_skill == "suffix_er_est"
    assert "r controlled" not in skill.specific_skill
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_skill.py tests/test_feedback.py tests/test_lesson_loader.py -k "suffix or morphology or unchanged" -v`
Expected: FAIL — `match_phonics_pattern("-er, -est")` returns `"r_controlled"`; `match_morphology_pattern` does not exist; goal text says "r controlled pattern". Capture this output as RED evidence for D13.

- [ ] **Step 3: Implement**

In `skill/taxonomy.py`, after `PHONICS_PATTERNS` (~line 171):

```python
# Morphological suffixes UFLI teaches as morphology, not rime families.
# A concept is a suffix lesson ONLY when every hyphen-prefixed token is in
# this set — "-ing, -ang, -ong" is a rime-family lesson ("ang" vetoes),
# "-er, -est" is morphology. "-ing" alone stays a family (PHONICS_PATTERNS)
# until UFLI suffix--ing lessons are wired; extending = add the token here.
MORPHOLOGY_SUFFIXES = frozenset({"er", "est", "ed", "ly", "es"})


def match_morphology_pattern(concept_text: str) -> str | None:
    """Match a concept label to a morphology (suffix) skill, e.g.
    '-er, -est' -> 'suffix_er_est'. None when any hyphen token is not a
    known suffix (rime families) or no hyphen tokens exist."""
    import re

    tokens = re.findall(r"-([a-z]+)", concept_text.lower())
    if tokens and all(t in MORPHOLOGY_SUFFIXES for t in tokens):
        ordered = sorted(set(tokens), key=tokens.index)
        return "suffix_" + "_".join(ordered)
    return None


def is_suffix_skill(specific_skill: str) -> bool:
    return specific_skill.startswith("suffix_")


def suffixes_for_skill(specific_skill: str) -> list[str]:
    if not is_suffix_skill(specific_skill):
        return []
    return specific_skill.removeprefix("suffix_").split("_")
```

At the top of `match_phonics_pattern` (before the sorted-patterns loop):

```python
    morphology = match_morphology_pattern(concept_text)
    if morphology:
        return morphology
```

In `adapt/feedback.py`, at the top of `learning_goal_statement`:

```python
    if specific_skill.startswith("suffix_"):
        endings = specific_skill.removeprefix("suffix_").split("_")
        if endings == ["er", "est"]:
            return "I can add -er and -est to compare things"
        joined = " and ".join(f"-{e}" for e in endings)
        return f"I can add {joined} to words"
```

(String-prefix check on purpose — avoids importing `skill.taxonomy` into `adapt/feedback`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_skill.py tests/test_feedback.py tests/test_lesson_loader.py -v`
Expected: PASS, including all pre-existing tests (regression bar: lesson-74 and photo-path classification unchanged).

- [ ] **Step 5: Commit**

```bash
git add skill/taxonomy.py adapt/feedback.py tests/
git commit -m "feat(taxonomy): morphology tier — '-er, -est' is a suffix lesson, not r-controlled (D13)"
```

---

### Task 2: Suffix-aware chains, chain dedup, no printed answers (defects D1 + D13-chains)

**Files:**
- Modify: `adapt/engine.py` — `_build_builder_chunks` (:788-884), new `_parse_suffix_chain_steps` beside `_parse_chain_steps` (:1909)
- Test: create `tests/test_suffix_chains.py`

**Interfaces:**
- Consumes: `is_suffix_skill` / `suffixes_for_skill` from Task 1; `skill: LiteracySkillModel` already a parameter of `_build_builder_chunks`.
- Produces: chain items ALWAYS have `metadata={"display": "chain_step"}` (or `"chain"` on the unparseable fallback), a non-null `answer`, and NEVER contain the answer in `content`. The evidence layer (`validate/objective_coverage.py`) reads exactly these fields — do not change item shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_suffix_chains.py`:

```python
"""Suffix-aware word chains + chain hygiene (spec 2026-07-13, defects D1/D13)."""

from adapt.engine import _build_builder_chunks, _parse_suffix_chain_steps
from adapt.rules import AccommodationRules


def _rules() -> AccommodationRules:
    return AccommodationRules(max_items_per_chunk=5)  # match existing test construction
    # If AccommodationRules needs more fields, copy the construction used in
    # existing engine tests (grep "AccommodationRules(" in tests/).


def _skill(specific_skill: str = "suffix_er_est"):
    # Copy the minimal LiteracySkillModel construction from tests/test_dosage.py
    # (grade_level, domain="phonics", specific_skill, learning_objectives,
    #  target_words, response_types, source_items=[], extraction_confidence,
    #  template_type="ufli_word_work") and set specific_skill from the argument.
    ...


DUP_CHAINS = [
    "slow → slower → slowest",
    "long → longer → longest",
    "slow → slower → slowest",  # source repeats — must not duplicate output
]


def test_parse_suffix_chain_steps_uses_chain_base() -> None:
    steps = _parse_suffix_chain_steps(["slow → slower → slowest"], ["er", "est"])
    assert steps == [
        {"from_word": "slow", "to_word": "slower", "suffix": "er"},
        {"from_word": "slow", "to_word": "slowest", "suffix": "est"},
    ]


def test_suffix_chain_items_hide_answers() -> None:
    chunks = _build_builder_chunks(DUP_CHAINS, [], [], _skill(), _rules())
    chain_items = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain_step"]
    assert chain_items, "suffix lesson must produce chain_step items"
    for item in chain_items:
        assert item.answer, "every chain item carries its answer"
        assert item.answer not in item.content, "answer must never be printed"
        assert "______" in item.content
    # Worked example consumed one hop; instructions speak suffix language.
    chain_chunks = [c for c in chunks if any(i.metadata.get("display") == "chain_step" for i in c.items)]
    assert any("Add the ending" in s.text for s in chain_chunks[0].instructions)


def test_duplicate_chains_produce_no_duplicate_chunks_or_items() -> None:
    chunks = _build_builder_chunks(DUP_CHAINS, [], [], _skill(), _rules())
    signatures = [tuple(i.content for i in c.items) for c in chunks]
    assert len(signatures) == len(set(signatures)), "no two chunks may be identical"
    all_contents = [i.content for c in chunks for i in c.items]
    assert len(all_contents) == len(set(all_contents)), "no repeated items"


def test_letter_chain_lessons_unchanged() -> None:
    # Lesson-74-style single-letter chains still parse through _parse_chain_steps
    chunks = _build_builder_chunks(["cry → try → dry"], [], [], _skill("y"), _rules())
    steps = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain_step"]
    assert steps and all(i.answer for i in steps)


def test_unparseable_chain_fallback_blanks_answers() -> None:
    # Chains no parser understands still must not print answers.
    chunks = _build_builder_chunks(
        ["run → sprinted"], [], [], _skill("y"), _rules()
    )
    chain_items = [i for c in chunks for i in c.items if i.metadata.get("display") == "chain"]
    for item in chain_items:
        assert "______" in item.content
        assert item.answer
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_suffix_chains.py -v`
Expected: FAIL — `_parse_suffix_chain_steps` doesn't exist; duplicate chunks produced; fallback items contain full chains. RED evidence for D1 (and the chain half of D13).

- [ ] **Step 3: Implement in `adapt/engine.py`**

(a) New parser beside `_parse_chain_steps` (~line 1933):

```python
def _parse_suffix_chain_steps(chains: list[str], suffixes: list[str]) -> list[dict[str, str]]:
    """Parse suffix chains ('slow → slower → slowest') into add-the-ending
    hops measured from the chain BASE word: (slow, slower, er), (slow, slowest, est)."""
    steps: list[dict[str, str]] = []
    for chain in chains:
        words = [w.strip().lower() for w in re.split(r"\s*(?:->|→)\s*", chain) if w.strip()]
        if len(words) < 2:
            continue
        base = words[0]
        for derived in words[1:]:
            suffix = next(
                (s for s in suffixes if derived.endswith(s) and len(derived) > len(s) + 1),
                None,
            )
            if suffix is None:
                continue
            steps.append({"from_word": base, "to_word": derived, "suffix": suffix})
    return steps
```

(b) In `_build_builder_chunks`, FIRST dedupe the chain inputs (top of the `if chains:` block, before parsing — this alone kills the lesson-100 twin chunks and twin items):

```python
        seen_chains: set[str] = set()
        deduped: list[str] = []
        for chain in chains:
            key = re.sub(r"\s+", " ", chain.lower())
            if key not in seen_chains:
                seen_chains.add(key)
                deduped.append(chain)
        chains = deduped
```

(c) Branch on skill type when parsing:

```python
        from skill.taxonomy import is_suffix_skill, suffixes_for_skill

        if is_suffix_skill(skill.specific_skill):
            suffix_steps = _parse_suffix_chain_steps(chains, suffixes_for_skill(skill.specific_skill))
        else:
            suffix_steps = []
```

If `suffix_steps` is non-empty: worked example = first step, content `f"{s['from_word']} + -{s['suffix']} → {s['to_word']}"`, instruction "Watch how to add the ending:"; activity items from the remaining steps with content `f"{s['from_word']} + -{s['suffix']} → ______"`, `answer=s["to_word"]`, `metadata={"display": "chain_step"}`; chunk instructions `["Read the word.", "Add the ending.", "Write the new word."]`. Otherwise fall through to the existing `_parse_chain_steps` path unchanged.

(d) Fix the unparseable-chain fallback (currently prints raw chains, engine.py:856-884): skip `chains[0]` (it's in the worked example — the code comment already claims this), and build each item as:

```python
                    parts = [w.strip() for w in re.split(r"\s*(?:->|→)\s*", chain) if w.strip()]
                    content = parts[0] + "".join(" → ______" for _ in parts[1:])
                    items.append(
                        ActivityItem(
                            item_id=item_id,
                            content=content,
                            response_format="write",
                            metadata={"display": "chain"},
                            answer=", ".join(parts[1:]),
                        )
                    )
```

- [ ] **Step 4: Run the new tests AND the evidence-layer suite**

Run: `.venv/bin/python -m pytest tests/test_suffix_chains.py tests/test_objective_coverage.py tests/test_objective_package.py tests/test_adapt.py -v`
Expected: all PASS. The objective-coverage suite guards the chain-evidence machinery (stitcher + discriminator) that this task must not break.

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py tests/test_suffix_chains.py
git commit -m "fix(engine): suffix-aware chains, chain dedup, answers never printed (D1, D13)"
```

---

### Task 3: Circle-the-letter fill-blanks + PROMPT_VERSION v4 (defect D2)

**Files:**
- Modify: `adapt/engine.py:928-931` (fill-blank chunk instructions)
- Modify: `render/image_prompt_builder.py:21` (PROMPT_VERSION), `:25` (fill_blank affordance)
- Test: `tests/test_image_prompt_builder.py`, `tests/test_adapt.py`

**Interfaces:**
- Produces: `PROMPT_VERSION = "page_prompt_v4"` — THE one bump for this cycle (Global Constraints). Later render tasks (5, 6, 7) edit prompt text but must NOT bump again.

- [ ] **Step 1: Write the failing tests**

In `tests/test_image_prompt_builder.py` add (mirror this module's existing spec-construction helper for a minimal `WorksheetDesignSpec` with one fill_blank item carrying `options=["a", "e", "i", "o", "u"]`):

```python
def test_fill_blank_with_options_renders_circle_affordance() -> None:
    prompt = build_page_prompt(_spec_with_fill_blank_options())
    assert "circle" in prompt.lower()
    assert "handwriting line below" not in prompt


def test_prompt_version_bumped_for_uat_fixes() -> None:
    from render.image_prompt_builder import PROMPT_VERSION

    assert PROMPT_VERSION == "page_prompt_v4"
```

In `tests/test_adapt.py` add:

```python
def test_fill_blank_instructions_say_circle() -> None:
    # Build any word-work model with words that produce fill-blank items
    # (reuse this module's existing builder-chunk test setup), then:
    fill_chunks = [c for c in chunks if c.response_format == "fill_blank"]
    assert fill_chunks
    texts = " ".join(s.text for s in fill_chunks[0].instructions)
    assert "Circle the missing letter" in texts
    assert "Write the missing letter" not in texts
```

- [ ] **Step 2: Run to verify failure** — RED evidence for D2.

Run: `.venv/bin/python -m pytest tests/test_image_prompt_builder.py tests/test_adapt.py -k "fill_blank or prompt_version" -v`

- [ ] **Step 3: Implement**

`adapt/engine.py` fill-blank instructions become:

```python
                    instructions=[
                        Step(number=1, text="Look at the word with a missing letter."),
                        Step(number=2, text="Circle the missing letter."),
                    ],
```

`render/image_prompt_builder.py`: `PROMPT_VERSION = "page_prompt_v4"` with a comment line `# v4: circle-format fill-blanks, per-row match pictures, chunked passages, quick-log-only feedback (spec 2026-07-13)`. Affordance:

```python
    "fill_blank": (
        "the text with a clearly visible blank; print the option letters beside it "
        "as large, well-spaced letters a child can circle — no handwriting line"
    ),
```

- [ ] **Step 4: Run to verify pass**, including the full `tests/test_image_prompt_builder.py` and `tests/test_image_gen_renderer.py` (cache-key consumers).

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py render/image_prompt_builder.py tests/
git commit -m "fix: fill-blank becomes circle-the-letter; PROMPT_VERSION v4 (D2)"
```

---

### Task 4: Dictation-stem filter + single-answer word banks (defects D6, D7)

**Files:**
- Modify: `skill/lesson_loader.py:169-178` (`_SCRIPT_STEMS`)
- Modify: `adapt/engine.py:1210-1214` (sentence word bank)
- Modify: `validate/ai_review.py` (ambiguity check + `remove_option` suggestion handling — read the module first; wire the new check into the existing checklist prompt and the new suggestion type into the existing suggestion-application loop)
- Test: `tests/test_lesson_loader.py`, `tests/test_adapt.py`, `tests/test_validate.py` (or the module that covers `validate/ai_review.py` — grep `ai_review` in tests/)

- [ ] **Step 1: Write the failing tests**

`tests/test_lesson_loader.py`:

```python
def test_make_the_word_is_teacher_script_not_sentence() -> None:
    from skill.lesson_loader import _home_practice_items

    _, sentences = _home_practice_items(
        "Make the word slow. Are you older than your brother? Add the ending to tall."
    )
    assert sentences == ["Are you older than your brother?"]
```

`tests/test_adapt.py` (extend the story-chunk test setup):

```python
def test_sentence_word_bank_capped_at_three_options() -> None:
    # build story chunks with >=6 target words; every fill_blank item's bank:
    for item in sentence_items:
        assert len(item.options) <= 3
        assert item.answer in item.options
```

AI-review test (in the module covering `validate/ai_review.py`): feed the reviewer-response parser a fake model reply containing a `remove_option` suggestion `{"item_id": 3, "option": "higher"}` and assert the applied model's item 3 no longer offers "higher" but still has ≥2 options including the answer. Mirror the module's existing fake-response test pattern exactly.

- [ ] **Step 2: Run to verify failure** — RED for D6 (sentence survives today) and D7 (bank = max_items options, no removal path).

- [ ] **Step 3: Implement**

(a) `_SCRIPT_STEMS` gains `"make the word"` and `"add the ending"` (note `"change the"` and `"add the"` already exist — check for overlap and keep the tuple deduplicated; `"add the"` already covers `"add the ending"`, so only `"make the word"` may be genuinely new — verify against the tuple at :169-178 and add exactly what's missing).
(b) Word bank: `_limit_options([removed_word, *target_words], required=removed_word, max_items=3)`.
(c) `validate/ai_review.py`: add one checklist line to the review prompt — `"For every sentence with a word bank: does EXACTLY ONE option fit the sentence? If more than one fits, emit suggestion {\"action\": \"remove_option\", \"item_id\": N, \"option\": \"word\"} for each extra plausible option."` — and handle `remove_option` in the suggestion-application code: remove the named option only if the item keeps ≥2 options and never remove the answer.

- [ ] **Step 4: Run to verify pass** — full `tests/test_lesson_loader.py`, `tests/test_adapt.py`, ai-review module tests.

- [ ] **Step 5: Commit**

```bash
git add skill/lesson_loader.py adapt/engine.py validate/ai_review.py tests/
git commit -m "fix: dictation stems filtered, 3-option banks, AI-review ambiguity pruning (D6, D7)"
```

---

### Task 5: Passage chunking, passage type size, sentence worked example (defect D8)

**Files:**
- Modify: `adapt/engine.py` — new `_format_passage` helper; `_build_story_chunks` (:1203-1286)
- Modify: `render/image_prompt_builder.py:34` (read_aloud affordance), `:138-149` (typography rules)
- Test: create `tests/test_story_format.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Story passage chunking + worked examples (spec 2026-07-13, defect D8)."""

from adapt.engine import _format_passage


def test_format_passage_groups_sentences_into_short_paragraphs() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(1, 10))
    formatted = _format_passage(text)
    paragraphs = [p for p in formatted.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 3
    for p in paragraphs:
        assert p.count(".") <= 3, "at most 3 sentences per paragraph"


def test_format_passage_preserves_every_sentence() -> None:
    text = "One is here. Two is here! Three is here? Four is here."
    formatted = _format_passage(text)
    for s in ["One is here.", "Two is here!", "Three is here?", "Four is here."]:
        assert s in formatted


def test_story_chunks_use_formatted_passage_and_worked_example() -> None:
    # Build story chunks (reuse tests/test_adapt.py story setup) with a
    # 9-sentence passage and >=2 convertible sentences, then:
    read_chunks = [c for c in chunks if c.response_format == "read_aloud"]
    assert "\n\n" in read_chunks[0].items[0].content
    sentence_chunks = [c for c in chunks if "sentence" in c.micro_goal.lower()]
    assert sentence_chunks[0].worked_example is not None
    # Worked example consumed the first convertible sentence — not repeated as an item.
    assert all(
        sentence_chunks[0].worked_example.content.split(" → ")[0] != i.content
        for i in sentence_chunks[0].items
    )
```

Plus in `tests/test_image_prompt_builder.py`:

```python
def test_read_aloud_affordance_demands_paragraph_blocks_and_large_text() -> None:
    prompt = build_page_prompt(_spec_with_read_aloud_passage())
    assert "paragraph" in prompt.lower()
    assert "practice-word size" in prompt or "size (2)" in prompt
```

- [ ] **Step 2: Run to verify failure** — RED for D8 (`_format_passage` absent; worked_example is None at :1248; affordance has no paragraph rule).

- [ ] **Step 3: Implement**

(a) `_format_passage` in `adapt/engine.py`:

```python
def _format_passage(text: str) -> str:
    """Break a passage into short paragraphs (<=3 sentences) separated by
    blank lines — ADHD stopping points (spec 2026-07-13 D8)."""
    normalized = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]", normalized) if s.strip()]
    if not sentences:
        return text.strip()
    paragraphs = [" ".join(sentences[i : i + 3]) for i in range(0, len(sentences), 3)]
    return "\n\n".join(paragraphs)
```

Preserve any title line: if the raw passage's first line has no terminal punctuation (lesson passages start with a title like "Growth Spurt"), keep it as its own first paragraph before formatting the rest.

(b) Story passage items: `content=_format_passage(passage)` (engine :1269).

(c) Sentence-completion worked example: when ≥1 item converted to fill_blank, pop the FIRST converted item and set the chunk's `worked_example=Example(instruction="Watch me do the first one:", content=f"{blank_sent} → {removed_word}")`. Skip when only unconverted (plain-write) items exist.

(d) `read_aloud` affordance:

```python
    "read_aloud": (
        "the passage inside a soft reading box with a small read-aloud icon; each "
        "paragraph is its own visually separated block with a blank line between "
        "paragraphs and a small dot marker at each paragraph start"
    ),
```

(e) Typography rules — add one line to the block at :138-149: `"- Story and passage sentences use size (2), the practice-word size — never the smaller instruction size."`

- [ ] **Step 4: Run to verify pass**: `tests/test_story_format.py`, `tests/test_adapt.py`, `tests/test_image_prompt_builder.py`, plus `tests/test_worksheet_design_spec.py` (required-text now includes the reformatted passage — the gate reads item content; confirm `\n\n` content doesn't break `_required_text` consumers).

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py render/image_prompt_builder.py tests/
git commit -m "fix: passages chunked into short paragraphs at practice-word size; sentence worked example (D8)"
```

---

### Task 6: Match-shuffle fidelity end-to-end + circle row alignment (defects D4, D9)

**Files:**
- Modify: `adapt/engine.py:1533-1535` (`_match_example_content` + its call site :649-652)
- Modify: `render/image_prompt_builder.py` — `_section_text` (:157-178) match branch; `circle` affordance (:27)
- Modify: `render/design_spec.py` — confirm the section item spec carries `picture_prompt` through to the prompt builder (grep `picture_prompt` in design_spec.py; add the field passthrough if it is dropped)
- Modify: `render/page_gates.py` — new match-alignment check
- Test: `tests/test_image_prompt_builder.py`, `tests/test_page_gates.py`, `tests/test_adapt.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_image_prompt_builder.py`:

```python
def test_match_items_carry_shuffled_picture_and_mismatch_constraint() -> None:
    # Spec with match items: word "higher" whose picture_prompt describes "newer"
    prompt = build_page_prompt(_spec_with_match_rows())
    assert "NOT the word on this row" in prompt
    # The row's picture description (the shuffled word's picture) must be present:
    assert "newer" in prompt.split('word "higher"')[1].split("Item")[0]


def test_circle_options_pinned_to_question_row() -> None:
    prompt = build_page_prompt(_spec_with_circle_question())
    assert "same row" in prompt.lower()
```

`tests/test_adapt.py`:

```python
def test_match_worked_example_uses_shuffled_picture_no_prompt_leak() -> None:
    # Build match chunks (existing discovery-chunk setup), then:
    we = match_chunk.worked_example
    assert "simple cartoon" not in we.content  # no raw picture_prompt leak
    assert "representing" not in we.content
    # It must reference the row-1 PICTURE's word (the shuffled one), which by
    # derangement is never the row-1 word itself:
    assert match_chunk.items[0].options[0] in we.content
    assert match_chunk.items[0].content not in we.content.split('"')[1::2]
```

`tests/test_page_gates.py`: mirror the module's existing fake-vision-response pattern; feed a gate response reporting one match row whose picture depicts its own row word, and assert the page attempt is REJECTED with a `match_rows_aligned` (or equivalent) reason; a response reporting zero aligned rows passes.

- [ ] **Step 2: Run to verify failure** — RED for D4 (prompt has no per-row picture text; worked example leaks) and D9 (no same-row rule).

- [ ] **Step 3: Implement**

(a) `_match_example_content` — new signature and text (update the single call site at :651 to pass `shuffled_pictures[0]`):

```python
def _match_example_content(picture_word: str) -> str:
    return (
        f'The first picture shows "{picture_word}". '
        f'Draw a line from it to the word "{picture_word}".'
    )
```

(b) `_section_text` match branch — replace the generic item line for `response_format == "match"` items that have a `picture_prompt`:

```python
        if item.response_format == "match" and getattr(item, "picture_prompt", None):
            lines.append(
                f'Item {item.item_id}: word "{item.content}" in the left column. '
                f"The picture on THIS row shows {item.picture_prompt} — deliberately "
                f'NOT the word on this row. Never draw a picture of "{item.content}" '
                "on this row."
            )
            continue
```

(preserving the two-column layout language once per section rather than per item is fine — move the column description into the section header line for match sections).

(c) `circle` affordance:

```python
    "circle": (
        "the answer choices printed on the SAME row as their question, to the "
        "right, evenly spaced with room around each so a child can circle one"
    ),
```

(d) `render/page_gates.py`: when the design spec has match sections, add to the vision-gate request one question per match row — "does the picture on the row of word X depict X?" — and reject the attempt if any answer is yes, surfacing the reason in the gates JSON (follow the existing missing/misspelled reason plumbing).

- [ ] **Step 4: Run to verify pass** — the three test modules plus `tests/test_worksheet_design_spec.py`.

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py render/image_prompt_builder.py render/design_spec.py render/page_gates.py tests/
git commit -m "fix(render): match shuffle survives to pixels + gate check; circle options row-aligned (D4, D9)"
```

---

### Task 7: Feedback panel = grown-up quick log only (defect D3)

**Files:**
- Modify: `adapt/schema.py:55-67` (remove `child_prompt` from `FeedbackPanel`)
- Modify: `render/design_spec.py:273` (drop the `child_prompt` required-text append)
- Modify: `render/image_prompt_builder.py:101-123` (delete the traffic-light strip block; the quick log becomes the final section)
- Modify: every other `child_prompt` reference — run `grep -rn "child_prompt\|Circle one for each part" --include="*.py" .` and update ALL hits (expect: `render/pdf.py` classic-renderer parity block, possibly `adapt/llm_adapt.py` / `adapt/direct_compiler.py`, and tests)
- Test: `tests/test_feedback.py`, `tests/test_worksheet_design_spec.py`, `tests/test_image_prompt_builder.py`, `tests/test_render.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_feedback_panel_has_no_child_strip() -> None:
    from adapt.schema import FeedbackPanel

    assert "child_prompt" not in FeedbackPanel.model_fields


def test_page_prompt_renders_quick_log_without_traffic_strip() -> None:
    prompt = build_page_prompt(_spec_with_feedback())
    assert "Grown-up quick log" in prompt
    assert "Circle one for each part" not in prompt
    assert "green, yellow, and red" not in prompt
```

- [ ] **Step 2: Run to verify failure** — RED for D3.

- [ ] **Step 3: Implement** — remove the field, the required-text line, and the strip block (the quick-log box paragraph at :120-123 stays, retitled as the final section); sweep every grep hit including the classic PDF renderer's strip-drawing code and all test fixtures constructing `FeedbackPanel(child_prompt=...)`.

- [ ] **Step 4: Run to verify pass** — `make test` (this one is a cross-cutting sweep; the full suite is the safety net).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(feedback): quick-log-only panel — drop child traffic-light strip (D3, owner decision)"
```

---

### Task 8: Remove the merge footer stamp (defect D10)

**Files:**
- Modify: `render/merge.py` — delete the stamp loop (:34-51) and the `_MARGIN/_PAGE_WIDTH/_FOOTER_Y` constants; update the docstring
- Test: `tests/test_merge.py`

- [ ] **Step 1: Write the failing test**

```python
def test_merged_package_has_no_footer_page_stamp(tmp_path) -> None:
    # Build 2 one-page PDFs with fitz (existing test pattern in this module),
    # merge, reopen, and:
    import fitz

    doc = fitz.open(str(out))
    for page in doc:
        assert "Page 1 of" not in page.get_text()
        assert "Page 2 of" not in page.get_text()
```

Also UPDATE (don't delete) any existing test asserting the stamp exists — invert it; that inversion is part of the RED/GREEN record.

- [ ] **Step 2: Run to verify failure** — RED for D10 (stamp is currently inserted).

- [ ] **Step 3: Implement** — remove the stamping loop; the page identity already lives in the page header via the prompt ("This is worksheet N of M"). Docstring notes the removal reason: fixed-coordinate stamp collided with full-bleed page art (print-check true positive at (517,760), spec 2026-07-13 D10).

- [ ] **Step 4: Run to verify pass** — `tests/test_merge.py` full module.

- [ ] **Step 5: Commit**

```bash
git add render/merge.py tests/test_merge.py
git commit -m "fix(merge): drop redundant footer page stamp that overlapped page art (D10)"
```

---

### Task 9: Judge truncation retry + planner word-chain example (defects D11, D12)

**Files:**
- Modify: `adapt/llm_judge.py` — `judge_objective_adaptation` (:655+; the `_call_openai` invocation below the prompt build)
- Modify: `adapt/llm_planner.py` — `_objective_authoring_block` (grep the def)
- Test: `tests/test_llm_judge.py`, `tests/test_llm_planner.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_judge.py` (mirror the module's existing monkeypatch style for `_call_openai`):

```python
def test_objective_judge_retries_once_on_parse_failure(monkeypatch) -> None:
    calls: list[int] = []
    good = _valid_objective_verdict_json()  # reuse/craft the module's valid-verdict fixture

    def fake_call(prompt, max_completion_tokens=1024):
        calls.append(max_completion_tokens)
        return '{"truncated": ' if len(calls) == 1 else good

    monkeypatch.setattr("adapt.llm_judge._call_openai", fake_call)
    verdict = judge_objective_adaptation(...)  # existing test fixtures
    assert verdict is not None
    assert len(calls) == 2
    assert all(t >= 4096 for t in calls)


def test_objective_judge_gives_up_after_second_parse_failure(monkeypatch) -> None:
    monkeypatch.setattr("adapt.llm_judge._call_openai", lambda *a, **k: '{"nope": ')
    assert judge_objective_adaptation(...) is None
```

`tests/test_llm_planner.py`:

```python
def test_authoring_block_contains_concrete_chain_example_and_budget_line() -> None:
    block = _objective_authoring_block(...)  # existing fixtures
    assert "→ ______" in block          # the concrete example item
    assert "MUST include" in block
    assert "minutes" in block.lower()   # budget reminder
```

- [ ] **Step 2: Run to verify failure** — RED for D11 (single call at 1024, None returned) and D12 (no example in block).

- [ ] **Step 3: Implement**

Judge call site becomes:

```python
    text = _call_openai(prompt, max_completion_tokens=4096)
    if text is None:
        return None
    verdict = _parse_objective_verdict(text)
    if verdict is None:
        logger.warning("  Objective judge: verdict parse failed — retrying once")
        text = _call_openai(prompt, max_completion_tokens=4096)
        verdict = _parse_objective_verdict(text) if text else None
    return verdict
```

(adapt to the exact surrounding code — the function also sets `severe_defect_vote` post-parse in the current version; keep that logic applied to whichever parse succeeds).

Planner authoring block — append:

```
Example of a compliant build/change-chain activity (adapt words to THIS lesson):
  items like {"content": "slow + -er → ______", "answer": "slower"} for suffix
  lessons, or {"content": "Start with \"dry\". Change the \"d\" to \"t\". Write
  the new word.", "answer": "try"} for letter-pattern lessons.
Your plan MUST include one such build/change chain activity, and the plan's
total estimated minutes MUST fit the session budget stated above.
```

- [ ] **Step 4: Run to verify pass** — both modules fully.

- [ ] **Step 5: Commit**

```bash
git add adapt/llm_judge.py adapt/llm_planner.py tests/
git commit -m "fix(llm): judge 4096 tokens + one parse retry; planner gets concrete chain example (D11, D12)"
```

---

### Task 10: Varied encode-practice forms for suffix lessons (defect D5)

**Files:**
- Modify: `adapt/engine.py` — `_build_discovery_chunks` write branch (:698-745 area)
- Test: extend `tests/test_suffix_chains.py` (same fixtures) or `tests/test_adapt.py`

**Interfaces:**
- Consumes: `is_suffix_skill` / `suffixes_for_skill` (Task 1). The write branch has access to `skill` — verify `_build_discovery_chunks` receives it (grep its `def`; thread `skill` from the :408 call site if absent — mirror how `_build_builder_chunks` gets it).

- [ ] **Step 1: Write the failing test**

```python
def test_suffix_write_batches_use_three_distinct_forms() -> None:
    words = ["taller", "tallest", "shorter", "shortest", "faster", "fastest",
             "slower", "slowest", "harder", "hardest", "softer", "softest"]
    chunks = _build_discovery_chunks(...)  # suffix_er_est skill, preserve_all_words path,
                                           # format_order ["write"], max_items 5 — reuse module setup
    write_like = [c for c in chunks if c.micro_goal.startswith(("Write", "Add", "Choose"))]
    goals = {c.micro_goal.split()[0] for c in write_like}
    assert {"Write", "Add", "Choose"} <= goals, "three distinct encode forms required"
    add_chunk = next(c for c in write_like if c.micro_goal.startswith("Add"))
    for item in add_chunk.items:
        assert "+ -" in item.content and "______" in item.content
        assert item.answer and item.answer not in item.content
    choose_chunk = next(c for c in write_like if c.micro_goal.startswith("Choose"))
    for item in choose_chunk.items:
        assert item.response_format == "circle"
        assert item.answer in item.options


def test_non_suffix_write_batches_unchanged() -> None:
    # Same construction with specific_skill="y": all write batches keep
    # today's "Write N words" shape (lesson-74 regression bar).
    assert all(c.micro_goal.startswith("Write") for c in write_like)
```

- [ ] **Step 2: Run to verify failure** — RED for D5 (all batches identical "Write N words").

- [ ] **Step 3: Implement** — in the write branch, when `is_suffix_skill(skill.specific_skill)` and there are ≥2 batches, cycle batch templates by `batch_index % 3`:

  - **0 — say-and-write** (today's items, unchanged).
  - **1 — add-the-ending:** for each word that cleanly decomposes (`word.endswith(sfx) and word.removesuffix(sfx)` ≥ 3 letters for some `sfx` in the skill's suffixes): content `f"{base} + -{sfx} → ______"`, `answer=word`, `response_format="write"`. Words that don't decompose stay say-and-write items. `micro_goal=f"Add the ending to {len(items)} words"`, instructions `["Read the word part.", "Add the ending.", "Write the whole word."]`.
  - **2 — choose-the-form:** pair words sharing a base (`taller`/`tallest`); per pair emit `content='Which word means "the most"?'`, `options=[er_word, est_word]`, `answer=est_word`, `response_format="circle"`, alternating with `'Which word compares two things?'` → answer the `-er` form. Unpaired words stay say-and-write. `micro_goal=f"Choose the right word {len(items)} times"`, instructions `["Read the question.", "Circle the right word."]`.

  Non-suffix skills: code path untouched (regression test above enforces it).

- [ ] **Step 4: Run to verify pass** — new tests + `tests/test_adapt.py` + `tests/test_section_cap.py` (the cap/carrier logic consumes these chunks).

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py tests/
git commit -m "feat(engine): suffix lessons vary encode forms — write / add-ending / choose-form (D5)"
```

---

### Task 11: Gates, live acceptance (lessons 74 + 100), traceability table, Fable exit review

**Files:**
- No production code expected (fixes discovered here go back through a fix dispatch)
- Produce: `.superpowers/sdd/uat-fix-traceability.md` (the 13-row table), review package for the final review

- [ ] **Step 1: Full gates**

Run: `make test && make lint && make typecheck`
Expected: all green. Also verify mypy under 3.11 semantics per repo convention.

- [ ] **Step 2: Bound-accounting reconciliation (spec §17)**

Compare `total_item_count` vs `role_counts` semantics in `validate/objective_coverage.py` package-bounds code against the lesson-100 artifact discrepancy (45 items vs 56 student_practice roles). If the accounting is wrong, this becomes a fix dispatch with its own red/green test; if it is correct-by-definition (e.g. items vs evidence-units), write the one-paragraph explanation into the traceability doc.

- [ ] **Step 3: Live acceptance runs (fresh output dirs, NO override)**

```bash
.venv/bin/python transform.py --lesson 74  --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson74_acceptance/
.venv/bin/python transform.py --lesson 100 --profile profiles/ian.yaml --theme roblox_obby --output ./output/lesson100_acceptance/
```

For each: either it ships (render pages to PNG and verify NONE of the 13 defects appears — checklist in spec exit criterion 4) or it fails pre-render with the policy error (record the judge's stated reasons; escalate to the owner for accept/reject of that outcome). Expected after this plan: passage chunking + worked examples remove the judge's `overwhelming_or_adhd_unsafe` rejection; the planner example closes the word-chain gap.

- [ ] **Step 4: Assemble the traceability table**

`.superpowers/sdd/uat-fix-traceability.md`: 13 rows — defect ID, one-line defect, fixing task, named test(s), RED evidence pointer (task report + commit), GREEN evidence pointer, live-run confirmation (page/artifact reference).

- [ ] **Step 5: Final whole-branch review (Fable 5)**

`scripts/review-package MERGE_BASE HEAD` (MERGE_BASE = commit before Task 1), dispatch the final code reviewer on Fable 5 with the package path + the traceability table + spec path. The review MUST include the row-by-row traceability audit. Findings → ONE fix dispatch with the complete list, then re-review.

- [ ] **Step 6: Commit any artifacts and report exit status against all 5 spec exit criteria.**
