# Planner Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Gemini-plans → GPT-judges → retry → GPT-takeover orchestration loop with ONE strong planning call that authors worksheet items directly, judged on full text, with a single feedback regeneration and a deterministic fallback — so every shipped worksheet carries a judge verdict and the 9-section page becomes impossible.

**Architecture:** A new `adapt/llm_planner.py` makes a single planning call through a provider chain (gpt-5.4 → gemini-3.5-flash, env-configurable like the image-provider chain). The prompt carries the FULL source items plus canonical corpus lesson content from the deterministic `corpus/ufli/lookup.lookup_lesson`. A widened `LessonPlan` schema lets the model author item content/options/answers/worked examples; deterministic code clamps the result to `adapt/rules.py` ADHD limits and a new grade-scaled section cap (split, never drop). The GPT-5.4 judge evaluates the full item text (no 60-char truncation, structural criteria folded in from `validate/ai_review.py`): approve → ship; reject → one regeneration with feedback → judge again; reject again → deterministic engine. The new path lands behind `WORKSHEET_PLANNER_V2=1`; an A/B battery compares it against the old loop on live lessons; only after the owner reviews the comparison does a gated task flip LLM adaptation default-on and delete the old loop.

**Tech Stack:** Python 3.11+, Pydantic v2, `openai` SDK (already used in `adapt/llm_judge.py`), `google-genai` SDK (already used in `adapt/llm_adapt.py`), pytest with monkeypatch (no network in tests), mypy strict repo-wide including tests.

**Owner decisions locked in (2026-06-12):**
- Planner: **gpt-5.4 primary, gemini-3.5-flash fallback** (Gemini model upgraded from `gemini-3-flash-preview` to the latest). Chain configurable via `WORKSHEET_PLANNER_PROVIDERS` (default `openai,gemini`), per D26 provider redundancy.
- Judge policy: **gate with one regeneration, then deterministic fallback.** A child never receives content that failed the judge twice. Every shipped artifact carries a verdict (advisory on the deterministic path, where no further fallback exists).
- LLM adaptation becomes **default-on only after the A/B gate** (owner reviews old-vs-new outputs first). `WORKSHEET_LLM_ADAPT=0` becomes the explicit opt-out; no-key/offline runs auto-fall back to the deterministic engine.
- Item G (skip per-chunk scene/word-picture asset generation under `image_gen` render mode): **included in this plan.**
- Section caps **K:2, 1:3, 2:4, 3:4** with split-don't-drop applied to BOTH the LLM and deterministic paths; `validate/ai_review.py` mutation loop skipped on the LLM path but kept on the deterministic path; `adapt/direct_compiler.py` deleted as superseded; old orchestrator deleted in the gated finale.

---

## Context for an engineer with zero prior exposure

- **Pipeline:** photo → capture → extract → `LiteracySkillModel` → adapt → `AdaptedActivityModel` (1–3 mini-worksheets) → theme → render → validate. Entry point `transform.py`, orchestration in `run_pipeline_collect_artifacts()`, multi-worksheet flow in `_run_multi_worksheet_pipeline()`.
- **The layer being replaced:** `adapt/engine.py:adapt_lesson()` currently tries `adapt/direct_compiler.py` (inert experiment, provider returns `None`), then `adapt/llm_orchestrator.py:orchestrate_llm_adaptation()` (Gemini plans → GPT 5.4 judges → retry with feedback → GPT takeover **unjudged**), then the deterministic rule engine. In every observed live run (Sessions 41–43) the outcome was `gpt_takeover_unjudged`: two rejected Gemini plans (overall 0.40–0.43, content coverage as low as 0.08), then GPT's plan shipped without a verdict.
- **Why plans were bad:** `adapt/llm_adapt.py:_build_adapt_prompt()` summarizes source items; `ActivityPlan` only carries `words` + a fixed `activity_type` vocabulary, and `_build_items_from_activity()` mechanically expands words into template items — the LLM never authors item content. `adapt/llm_judge.py:_build_judge_prompt()` truncates each item to 60 chars, so the judge scores a lossy summary. One live run shipped NINE sections on one page (violates the consolidated plan's "one main task per page" rule); `validate/adhd_compliance.py` has no sections-per-worksheet check.
- **A second LLM loop:** `validate/ai_review.py:review_adapted_worksheet()` runs per worksheet from `transform.py` (up to 3 iterations each — up to 9 LLM calls per lesson) and MUTATES items post-judging. Its structural criteria (truncation, garbled text, artifacts) overlap the judge.
- **Corpus ground truth:** `corpus/ufli/lookup.py:lookup_lesson(n)` deterministically returns `concept`, `decodable_text`, `additional_text` (Roll and Read), `home_practice_text` for UFLI lessons 1–128. `skill/extractor.py:_enrich_from_corpus()` already injects passage + roll-and-read into `source_items`; `home_practice_text` and `concept` are currently unused by any planner.
- **Telemetry is polluted:** `adapt/llm_orchestrator.py:_log_performance()` appends to the global `logs/llm_adaptation_log.jsonl` even under pytest. The file's 311 entries are ~95% the `consonant_le` test fixture with canned 0.85/None scores. `logs/` is gitignored.
- **Contracts that must keep holding:** `validate/skill_parity.py` (skill-preserving, not page-faithful), `validate/content_coverage.py` (deterministic source-coverage check), `adapt/rules.py` chunking/instruction limits enforced deterministically AFTER any LLM call, offline/no-key runs work end-to-end via the deterministic engine.
- **Renderer state:** `image_gen` (full-page AI images) is validated and pending promotion to default by a parallel session; `pdf_classic` is the deterministic fallback. `transform.py:_run_multi_worksheet_pipeline()` runs `generate_worksheet_assets()` (per-chunk scene/word images) unconditionally, but only pdf_classic-style layouts consume them.
- **Env conventions:** `.env` auto-loaded by `transform.py`. Keys `OPENAI_API_KEY`, `GEMINI_API_KEY`. `WORKSHEET_LLM_ADAPT=1` currently opt-in gates LLM adaptation. `WORKSHEET_SKIP_ASSET_GEN=1` disables image generation (tests/CI rely on it).
- **Commands:** `make lint` (ruff), `make typecheck` (mypy strict, 145 files), `make test` (pytest, 557+ tests, must pass offline with no keys). Use `.venv/bin/...` binaries.
- **Commits:** a pre-commit hook BLOCKS `Co-Authored-By: Claude` trailers — do not add them. Never `git add -A`; stage exact paths. Commit per task.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `.claude/worksheet-project-context.md` | Modify | Decision rows D30–D32; session handoff entries |
| `adapt/rules.py` | Modify | `MAX_SECTIONS_PER_WORKSHEET` table; `AccommodationRules.max_sections_per_worksheet` |
| `validate/adhd_compliance.py` | Modify | Hard-error sections-per-worksheet check |
| `adapt/section_cap.py` | Create | `enforce_section_cap()` — content-preserving worksheet splitting |
| `adapt/llm_adapt.py` | Modify | `PlannedItem`, `ActivityPlan.items`, authored-item translation, `_call_gemini(model=...)` |
| `adapt/llm_planner.py` | Create | Single-call planner: prompt (full source + corpus), provider chain, judge gate + one regen, logging |
| `adapt/llm_judge.py` | Modify | Full-item-text judge prompt; structural criteria folded in |
| `adapt/engine.py` | Modify | `WORKSHEET_PLANNER_V2` routing; section-cap wrap; finale removes old loop + direct compiler |
| `transform.py` | Modify | Skip `ai_review` for planner-v2 output; skip chunk asset gen under `image_gen` |
| `adapt_battery.py` | Create | A/B CLI: old loop vs new planner scorecard |
| `adapt/llm_orchestrator.py` | Delete (Task 14) | Superseded retry/takeover loop |
| `adapt/direct_compiler.py` | Delete (Task 14) | Superseded inert experiment |
| `pyproject.toml` | Modify (Task 14) | Drop `llm_orchestrator.py` E501 exemption if present |
| `AGENTS.md` | Modify (Task 15) | Document planner env vars + default-on semantics |
| `tests/test_adapt.py` | Modify | Section-cap rules test |
| `tests/test_validate.py` | Modify | adhd sections-check tests |
| `tests/test_section_cap.py` | Create | Split/renumber/preserve tests |
| `tests/test_llm_adapt.py` | Create | Widened schema + translation tests; receives relocated orchestrator-file tests in Task 14 |
| `tests/test_llm_planner.py` | Create | Prompt, provider chain, orchestration tests |
| `tests/test_llm_judge.py` | Create | Full-text judge prompt tests |
| `tests/test_planner_pipeline.py` | Create | `transform.py` helper tests (ai_review skip, asset skip) |
| `tests/test_adapt_battery.py` | Create | Scorecard builder test |
| `tests/conftest.py` | Create (Task 13) | Autouse `WORKSHEET_LLM_ADAPT=0` for tests |
| `tests/test_llm_orchestrator.py` | Delete (Task 14) | Tests of deleted loop (two helper-test classes relocated first) |
| `tests/test_direct_compiler.py` | Delete (Task 14) | Tests of deleted module |

**Call-count budget (per lesson, LLM path):** old worst case = 2 Gemini plans + 2 judge calls + 1 GPT takeover + up to 9 `ai_review` calls ≈ 14. New worst case = 2 planning + 2 judge = 4; typical = 2.

---

### Task 0: Decision log entries (docs only)

**Files:**
- Modify: `.claude/worksheet-project-context.md` (Key Decisions Log table, after the last row)

- [ ] **Step 1: Append decision rows**

The parallel image_gen-promotion session may have claimed D29. Use the next free numbers (shown here as D30–D32; renumber if needed):

```markdown
| D30 | Planner simplification: one strong planning call replaces the Gemini→judge→retry→GPT-takeover loop | Provider chain gpt-5.4 → gemini-3.5-flash (`WORKSHEET_PLANNER_PROVIDERS`, default `openai,gemini`). Prompt carries FULL source items + canonical corpus lesson content (`lookup_lesson`); the model authors item content/options/answers directly; deterministic clamps from adapt/rules.py run after the call, including a grade-scaled hard cap on sections per mini-worksheet (K:2, 1:3, 2:4, 3:4) enforced by splitting, never dropping. Evidence: every live run (Sessions 41–43) ended `gpt_takeover_unjudged` after two wasted Gemini calls; a live page shipped with 9 sections. | 2026-06-12 |
| D31 | Judge gates everything that ships: approve → ship; reject → ONE regeneration with feedback; reject again → deterministic engine | Closes the unjudged-takeover hole. Judge reads full item text (no truncation) with ai_review's structural criteria folded in; the ai_review mutation loop is skipped on the LLM path (kept for deterministic output). Deterministic-path output gets an advisory verdict. LLM adaptation flips default-on (opt-out `WORKSHEET_LLM_ADAPT=0`) only after the owner-reviewed A/B battery gate. | 2026-06-12 |
| D32 | Per-chunk scene/word-picture asset generation skipped when render mode is image_gen | The full-page renderer never consumes those assets; they only served pdf_classic layouts. If image_gen falls back to pdf_classic mid-run, that worksheet renders with deterministic local art (same as asset-gen failure today). Saves several image generations per lesson. | 2026-06-12 |
```

- [ ] **Step 2: Commit**

```bash
git add .claude/worksheet-project-context.md
git commit -m "docs: record D30-D32 (single-call planner, judge gate, asset-gen skip)"
```

---

### Task 1: Grade-scaled section cap in accommodation rules

**Files:**
- Modify: `adapt/rules.py`
- Test: `tests/test_adapt.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_adapt.py`:

```python
def test_rules_include_grade_scaled_section_cap() -> None:
    from adapt.rules import MAX_SECTIONS_PER_WORKSHEET, build_rules
    from companion.schema import Accommodations, LearnerProfile

    assert MAX_SECTIONS_PER_WORKSHEET == {"K": 2, "1": 3, "2": 4, "3": 4}
    for grade, cap in MAX_SECTIONS_PER_WORKSHEET.items():
        profile = LearnerProfile(
            name="t", grade_level=grade, accommodations=Accommodations()
        )
        assert build_rules(profile).max_sections_per_worksheet == cap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_adapt.py::test_rules_include_grade_scaled_section_cap -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_SECTIONS_PER_WORKSHEET'`

- [ ] **Step 3: Implement**

In `adapt/rules.py`, add after the `TIME_ESTIMATE_MINUTES` table (~line 68):

```python
# Hard cap on activity sections (chunks) per mini-worksheet by grade.
# "One main task per page" is the design rule; a page with 9 sections is an
# ADHD anti-pattern. Over-cap packages are SPLIT into more mini-worksheets,
# never trimmed (see adapt/section_cap.py).
MAX_SECTIONS_PER_WORKSHEET: dict[str, int] = {"K": 2, "1": 3, "2": 4, "3": 4}
```

Add a field to `AccommodationRules` after `max_items_per_chunk`:

```python
    max_sections_per_worksheet: int = 4
```

In `build_rules()`, add after the chunking block (~line 106):

```python
    # Section cap
    max_sections = MAX_SECTIONS_PER_WORKSHEET.get(grade, 4)
```

and pass it in the constructor call after `max_items_per_chunk=max_items,`:

```python
        max_sections_per_worksheet=max_sections,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_adapt.py::test_rules_include_grade_scaled_section_cap -v`
Expected: PASS

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && .venv/bin/pytest tests/test_adapt.py -v
git add adapt/rules.py tests/test_adapt.py
git commit -m "feat: grade-scaled max sections per mini-worksheet in accommodation rules"
```

---

### Task 2: Hard sections-per-worksheet check in ADHD compliance

**Files:**
- Modify: `validate/adhd_compliance.py`
- Test: `tests/test_validate.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_validate.py`. Merge these imports into the import block at the TOP of the file (mypy strict needs the annotation resolvable at module level; appending imports mid-file trips ruff E402):

```python
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
```

(Skip any of those names the file already imports.) Then append the tests:

```python
def _worksheet_with_n_chunks(count: int, grade: str = "1") -> AdaptedActivityModel:
    chunks = [
        ActivityChunk(
            chunk_id=i + 1,
            micro_goal=f"Goal {i + 1}",
            instructions=[Step(number=1, text="Do the task.")],
            items=[ActivityItem(item_id=i + 1, content="cat", response_format="write")],
            response_format="write",
            time_estimate="About 2 minutes",
        )
        for i in range(count)
    ]
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level=grade,
        domain="phonics",
        specific_skill="cvc",
        chunks=chunks,
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        self_assessment=["I can read CVC words"],
    )


def test_sections_per_worksheet_cap_violated() -> None:
    from validate.adhd_compliance import validate_adhd_compliance

    result = validate_adhd_compliance(_worksheet_with_n_chunks(9, grade="1"))

    assert result.passed is False
    checks = [v.check for v in result.violations if v.severity == "error"]
    assert "sections_per_worksheet" in checks


def test_sections_per_worksheet_cap_respected() -> None:
    from validate.adhd_compliance import validate_adhd_compliance

    result = validate_adhd_compliance(_worksheet_with_n_chunks(3, grade="1"))

    checks = [v.check for v in result.violations]
    assert "sections_per_worksheet" not in checks


def test_sections_per_worksheet_uses_rules_when_provided() -> None:
    from adapt.rules import build_rules
    from companion.schema import Accommodations, LearnerProfile
    from validate.adhd_compliance import validate_adhd_compliance

    profile = LearnerProfile(name="t", grade_level="K", accommodations=Accommodations())
    result = validate_adhd_compliance(
        _worksheet_with_n_chunks(3, grade="K"), rules=build_rules(profile)
    )

    assert result.passed is False
    checks = [v.check for v in result.violations if v.severity == "error"]
    assert "sections_per_worksheet" in checks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_validate.py -k sections_per_worksheet -v`
Expected: FAIL — `"sections_per_worksheet" in checks` assertions fail (check does not exist yet)

- [ ] **Step 3: Implement**

In `validate/adhd_compliance.py`, change the import at the top to include the new table:

```python
from adapt.rules import (
    CHUNKING_RULES,
    INSTRUCTION_LIMITS,
    MAX_SECTIONS_PER_WORKSHEET,
    AccommodationRules,
)
```

Add a new check at the end of `validate_adhd_compliance()`, after Check 12 and before `return result`:

```python
    # Check 13: Sections per worksheet (grade-scaled hard cap)
    result.checks_run += 1
    if rules is not None:
        max_sections = rules.max_sections_per_worksheet
    else:
        max_sections = MAX_SECTIONS_PER_WORKSHEET.get(grade, 4)
    if len(adapted.chunks) > max_sections:
        result.add_violation(
            check="sections_per_worksheet",
            message=(
                f"Worksheet has {len(adapted.chunks)} sections, "
                f"max for grade {grade} is {max_sections}"
            ),
            details={"sections": len(adapted.chunks), "max": max_sections},
        )
```

(Default severity is `"error"` — this is a hard constraint, not a warning.)

Also update the docstring checklist in `validate_adhd_compliance()` to add `13. Sections per worksheet within grade cap`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_validate.py -v`
Expected: PASS (all — if any pre-existing test constructs a worksheet with more chunks than its grade cap, update that fixture to stay within the cap and note it in the commit message)

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add validate/adhd_compliance.py tests/test_validate.py
git commit -m "feat: hard-error ADHD check for sections per mini-worksheet"
```

---

### Task 3: Content-preserving section-cap enforcement

**Files:**
- Create: `adapt/section_cap.py`
- Modify: `adapt/engine.py` (the three `adapt_lesson` returns)
- Test: `tests/test_section_cap.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_section_cap.py`:

```python
"""Tests for adapt/section_cap.py — split over-cap worksheets, never drop content."""

from __future__ import annotations

from adapt.rules import AccommodationRules, build_rules
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    ScaffoldConfig,
    Step,
)
from adapt.section_cap import enforce_section_cap
from companion.schema import Accommodations, LearnerProfile


def _rules(grade: str = "1") -> AccommodationRules:
    profile = LearnerProfile(name="t", grade_level=grade, accommodations=Accommodations())
    return build_rules(profile)


def _chunk(chunk_id: int) -> ActivityChunk:
    return ActivityChunk(
        chunk_id=chunk_id,
        micro_goal=f"Goal {chunk_id}",
        instructions=[Step(number=1, text="Do the task.")],
        items=[
            ActivityItem(
                item_id=chunk_id * 10,
                content=f"word{chunk_id}",
                response_format="write",
            )
        ],
        response_format="write",
        time_estimate="About 2 minutes",
    )


def _worksheet(
    chunk_count: int,
    *,
    number: int = 1,
    count: int = 1,
    title: str | None = "Word Work",
    break_prompt: str | None = None,
    self_assessment: list[str] | None = None,
) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvc",
        chunks=[_chunk(i + 1) for i in range(chunk_count)],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=number,
        worksheet_count=count,
        worksheet_title=title,
        break_prompt=break_prompt,
        self_assessment=self_assessment,
    )


def test_compliant_package_unchanged() -> None:
    package = [
        _worksheet(2, number=1, count=2, break_prompt="Stretch!"),
        _worksheet(3, number=2, count=2, self_assessment=["I can read"]),
    ]
    result = enforce_section_cap(package, _rules("1"))

    assert len(result) == 2
    assert [ws.worksheet_number for ws in result] == [1, 2]
    assert all(ws.worksheet_count == 2 for ws in result)
    assert result[0].break_prompt == "Stretch!"
    assert result[1].break_prompt is None
    assert result[1].self_assessment == ["I can read"]


def test_nine_section_worksheet_splits_without_dropping_content() -> None:
    package = [_worksheet(9, self_assessment=["I can read"])]
    result = enforce_section_cap(package, _rules("1"))

    # Grade 1 cap is 3: 9 sections -> 3 worksheets of 3.
    assert len(result) == 3
    assert all(len(ws.chunks) <= 3 for ws in result)
    contents = [item.content for ws in result for ch in ws.chunks for item in ch.items]
    assert sorted(contents) == sorted(f"word{i + 1}" for i in range(9))
    # Renumbered package
    assert [ws.worksheet_number for ws in result] == [1, 2, 3]
    assert all(ws.worksheet_count == 3 for ws in result)
    # Chunk ids restart at 1 within each part
    assert [ch.chunk_id for ch in result[1].chunks] == [1, 2, 3]
    # Titles disambiguated
    assert result[0].worksheet_title == "Word Work (Part 1)"
    assert result[2].worksheet_title == "Word Work (Part 3)"
    # Self-assessment only on the final part; breaks on non-final parts
    assert result[0].self_assessment is None
    assert result[2].self_assessment == ["I can read"]
    assert result[0].break_prompt is not None
    assert result[1].break_prompt is not None
    assert result[2].break_prompt is None


def test_split_uses_grade_cap() -> None:
    result = enforce_section_cap([_worksheet(4)], _rules("K"))

    assert len(result) == 2
    assert all(len(ws.chunks) <= 2 for ws in result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_section_cap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapt.section_cap'`

- [ ] **Step 3: Implement the module**

Create `adapt/section_cap.py`:

```python
"""Hard cap on sections per mini-worksheet — splits over-cap worksheets.

Content-preserving by construction: every chunk survives, redistributed into
more mini-worksheets. Idempotent on compliant input. Applied to BOTH the LLM
and deterministic adaptation outputs (the single choke point is
adapt/engine.py:adapt_lesson()).
"""

from __future__ import annotations

from adapt.rules import BRAIN_BREAK_PROMPTS, AccommodationRules
from adapt.schema import AdaptedActivityModel


def enforce_section_cap(
    worksheets: list[AdaptedActivityModel],
    rules: AccommodationRules,
) -> list[AdaptedActivityModel]:
    """Split any worksheet whose chunk count exceeds the grade cap."""
    cap = rules.max_sections_per_worksheet
    parts: list[AdaptedActivityModel] = []

    for ws in worksheets:
        if len(ws.chunks) <= cap:
            parts.append(ws)
            continue
        groups = [ws.chunks[i : i + cap] for i in range(0, len(ws.chunks), cap)]
        for g_idx, group in enumerate(groups):
            renumbered = [
                chunk.model_copy(update={"chunk_id": c_idx + 1})
                for c_idx, chunk in enumerate(group)
            ]
            is_last_part = g_idx == len(groups) - 1
            title = ws.worksheet_title
            if title:
                title = f"{title} (Part {g_idx + 1})"
            parts.append(
                ws.model_copy(
                    update={
                        "chunks": renumbered,
                        "worksheet_title": title,
                        "self_assessment": ws.self_assessment if is_last_part else None,
                        "break_prompt": ws.break_prompt if is_last_part else None,
                    }
                )
            )

    # Renumber the package and refresh brain breaks between worksheets.
    total = len(parts)
    final: list[AdaptedActivityModel] = []
    for idx, ws in enumerate(parts):
        is_last = idx == total - 1
        break_prompt = ws.break_prompt
        if is_last:
            break_prompt = None
        elif break_prompt is None:
            break_prompt = BRAIN_BREAK_PROMPTS[idx % len(BRAIN_BREAK_PROMPTS)]
        final.append(
            ws.model_copy(
                update={
                    "worksheet_number": idx + 1,
                    "worksheet_count": total,
                    "break_prompt": break_prompt,
                }
            )
        )
    return final
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_section_cap.py -v`
Expected: PASS

- [ ] **Step 5: Wire into the deterministic path**

In `adapt/engine.py`, add the import near the other `adapt.` imports at the top:

```python
from adapt.section_cap import enforce_section_cap
```

Then wrap the three exits of `adapt_lesson()`:

1. The LLM-orchestrator return (~line 156–157), change:

```python
        if llm_result:
            return llm_result
```

to:

```python
        if llm_result:
            return enforce_section_cap(llm_result, rules)
```

2. The single-worksheet fallback (~line 414), change `return [single]` to:

```python
        return enforce_section_cap([single], rules)
```

3. The final return (~line 416), change `return worksheets` to:

```python
    return enforce_section_cap(worksheets, rules)
```

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: PASS. If any test pinned an exact worksheet/chunk count that the split now changes (most assert `>= 1` and survive), update the assertion to match the capped output and say so in the commit message. Candidates: `tests/test_adapt.py` multi-worksheet tests, `tests/test_rag_adapt.py`.

- [ ] **Step 7: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/section_cap.py adapt/engine.py tests/test_section_cap.py
git commit -m "feat: enforce grade-scaled section cap by splitting worksheets"
```

(Include `tests/test_adapt.py` etc. in `git add` only if Step 6 required updates.)

---

### Task 4: Widened plan schema — the model authors items

**Files:**
- Modify: `adapt/llm_adapt.py`
- Test: `tests/test_llm_adapt.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_adapt.py`:

```python
"""Tests for adapt/llm_adapt.py — widened plan schema and authored-item translation."""

from __future__ import annotations

import json

from adapt.llm_adapt import (
    ActivityPlan,
    LessonPlan,
    PlannedItem,
    _parse_lesson_plan,
    _translate_plan,
)
from adapt.rules import build_rules
from companion.schema import Accommodations, LearnerProfile
from skill.schema import LiteracySkillModel, SourceItem


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="cake, ride, home",
                source_region_index=0,
            )
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="t", grade_level="1", accommodations=Accommodations())


def test_lesson_plan_parses_authored_items() -> None:
    payload = {
        "concept_focus": "CVCe magic-e",
        "pedagogical_rationale": "Practice the pattern",
        "worksheets": [
            {
                "title": "Magic E",
                "activities": [
                    {
                        "activity_type": "fill_blank",
                        "micro_goal": "Complete each CVCe word",
                        "items": [
                            {
                                "content": "The dog wants to r__de in the car.",
                                "response_format": "fill_blank",
                                "options": ["i", "o", "a"],
                                "answer": "i",
                            }
                        ],
                        "instructions": ["Fill in the missing letter."],
                        "worked_example": "c__ke -> cake (the magic e!)",
                        "response_format": "fill_blank",
                        "time_estimate_minutes": 2,
                        "rationale": "Targets the vowel in the CVCe unit",
                    }
                ],
            }
        ],
    }
    plan = _parse_lesson_plan(json.dumps(payload))

    assert plan is not None
    item = plan.worksheets[0].activities[0].items[0]
    assert item.content == "The dog wants to r__de in the car."
    assert item.options == ["i", "o", "a"]
    assert item.answer == "i"


def test_translate_prefers_authored_items() -> None:
    plan = LessonPlan(
        worksheets=[
            {
                "title": "Magic E",
                "activities": [
                    ActivityPlan(
                        activity_type="fill_blank",
                        micro_goal="Complete each word",
                        items=[
                            PlannedItem(
                                content="r__de",
                                response_format="fill_blank",
                                options=["i", "o"],
                                answer="i",
                            ),
                            PlannedItem(content="h__me", answer="o"),
                        ],
                        words=["ignored"],
                        instructions=["Fill in the blank."],
                        response_format="fill_blank",
                    )
                ],
            }
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    assert [i.content for i in items] == ["r__de", "h__me"]
    assert items[0].options == ["i", "o"]
    assert items[0].answer == "i"
    # Unspecified per-item format inherits the activity format
    assert items[1].response_format == "fill_blank"


def test_translate_clamps_authored_items_to_chunk_cap() -> None:
    rules = build_rules(_profile())  # grade 1 medium -> 4 items max
    plan = LessonPlan(
        worksheets=[
            {
                "title": "Too Many",
                "activities": [
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write words",
                        items=[PlannedItem(content=f"word{i}") for i in range(10)],
                        instructions=["Write each word."],
                        response_format="write",
                    )
                ],
            }
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", rules)

    assert len(worksheets[0].chunks[0].items) == rules.max_items_per_chunk


def test_translate_degrades_to_template_expansion_without_items() -> None:
    plan = LessonPlan(
        worksheets=[
            {
                "title": "Plain",
                "activities": [
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write words",
                        words=["cake", "ride"],
                        instructions=["Write each word."],
                        response_format="write",
                    )
                ],
            }
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    assert [i.content for i in worksheets[0].chunks[0].items] == ["cake", "ride"]


def test_match_activities_use_mechanical_builder_even_with_items() -> None:
    plan = LessonPlan(
        worksheets=[
            {
                "title": "Match",
                "activities": [
                    ActivityPlan(
                        activity_type="match",
                        micro_goal="Match words to pictures",
                        items=[
                            PlannedItem(content="cake"),
                            PlannedItem(content="ride"),
                        ],
                        instructions=["Draw a line."],
                        response_format="match",
                    )
                ],
            }
        ]
    )
    worksheets = _translate_plan(plan, _skill(), _profile(), "default", build_rules(_profile()))

    items = worksheets[0].chunks[0].items
    # Mechanical builder ran: picture prompts + shuffled options contract intact
    assert all(i.picture_prompt for i in items)
    assert all(i.options for i in items)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_adapt.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlannedItem'`

- [ ] **Step 3: Implement the schema widening**

In `adapt/llm_adapt.py`, add before `ActivityPlan` (~line 41):

```python
class PlannedItem(BaseModel):
    """A single practice item authored directly by the LLM."""

    content: str
    response_format: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    picture_prompt: str | None = None
```

Add a field to `ActivityPlan` after `words`:

```python
    items: list[PlannedItem] = Field(default_factory=list)
```

- [ ] **Step 4: Implement authored-item translation**

In `adapt/llm_adapt.py`, in `_translate_plan()` (~line 263), change:

```python
            # Build items based on activity type
            items = _build_items_from_activity(
                activity,
                skill,
                rules,
                item_counter,
            )
```

to:

```python
            # Build items: prefer model-authored items, degrade to template expansion
            items = _items_for_activity(
                activity,
                skill,
                rules,
                item_counter,
            )
```

Add the new functions directly above `_build_items_from_activity()`:

```python
# Formats whose renderer contracts (shuffled picture options, phoneme boxes)
# must stay mechanically constructed even when the model authors items.
_MECHANICAL_FORMATS = {"match", "sound_box"}


def _items_for_activity(
    activity: ActivityPlan,
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    item_start: int,
) -> list[ActivityItem]:
    """Prefer model-authored items; degrade to template expansion."""
    if activity.items and activity.activity_type not in _MECHANICAL_FORMATS:
        authored = _items_from_planned(activity, rules, item_start)
        if authored:
            return authored
    if activity.items and not activity.words:
        # Salvage authored content as inputs for the mechanical builders.
        activity = activity.model_copy(
            update={"words": [planned.content for planned in activity.items]}
        )
    return _build_items_from_activity(activity, skill, rules, item_start)


def _items_from_planned(
    activity: ActivityPlan,
    rules: AccommodationRules,
    item_start: int,
) -> list[ActivityItem]:
    """Clamp model-authored items to ADHD rules; mechanics stay deterministic."""
    from adapt.engine import _limit_options

    items: list[ActivityItem] = []
    item_id = item_start
    for planned in activity.items[: rules.max_items_per_chunk]:
        content = planned.content.strip()
        if not content:
            continue
        options = [opt.strip() for opt in planned.options if opt.strip()]
        if options and planned.answer:
            options = _limit_options(
                options,
                required=planned.answer,
                max_items=rules.max_items_per_chunk,
            )
        else:
            options = options[: rules.max_items_per_chunk]
        item_id += 1
        items.append(
            ActivityItem(
                item_id=item_id,
                content=content,
                response_format=planned.response_format or activity.response_format,
                options=options or None,
                answer=planned.answer,
                picture_prompt=planned.picture_prompt,
            )
        )
    return items
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_adapt.py tests/test_llm_orchestrator.py -v`
Expected: PASS (the old loop is unaffected — its prompt never emits `items`, so `_items_for_activity` degrades to the existing builder)

- [ ] **Step 6: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_adapt.py tests/test_llm_adapt.py
git commit -m "feat: model-authored plan items with deterministic ADHD clamping"
```

---

### Task 5: Planner prompt — full source items + corpus ground truth

**Files:**
- Create: `adapt/llm_planner.py` (prompt builder only; orchestration arrives in Task 8)
- Test: `tests/test_llm_planner.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_planner.py`:

```python
"""Tests for adapt/llm_planner.py — single-call planner."""

from __future__ import annotations

import pytest

from adapt.llm_planner import _build_planner_prompt, _corpus_block
from adapt.rules import build_rules
from companion.schema import Accommodations, LearnerProfile
from corpus.ufli.lookup import CorpusLookupResult
from skill.schema import LiteracySkillModel, SourceItem

LONG_SENTENCE = (
    "The little dog likes to ride home in the big red wagon while the cat "
    "naps on the warm stone step beside the gate and dreams of cake."
)


def _skill(lesson_number: int | None = None) -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[
            SourceItem(
                item_type="word_chain",
                content="1. tune -> tone -> cone -> cane",
                source_region_index=0,
            ),
            SourceItem(
                item_type="sentence",
                content=LONG_SENTENCE,
                source_region_index=1,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
        lesson_number=lesson_number,
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Ian", grade_level="1", accommodations=Accommodations())


def test_prompt_carries_full_source_items_untruncated() -> None:
    prompt = _build_planner_prompt(_skill(), _profile(), build_rules(_profile()), "default", None)

    assert "1. tune -> tone -> cone -> cane" in prompt
    assert LONG_SENTENCE in prompt  # no summarization, no truncation


def test_prompt_states_section_cap_and_item_authoring() -> None:
    rules = build_rules(_profile())
    prompt = _build_planner_prompt(_skill(), _profile(), rules, "default", None)

    assert f"Maximum {rules.max_sections_per_worksheet} sections" in prompt
    assert '"items"' in prompt  # output schema asks for authored items
    assert '"answer"' in prompt


def test_corpus_block_injects_lesson_ground_truth(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_lookup(lesson_number: int) -> CorpusLookupResult:
        assert lesson_number == 84
        return CorpusLookupResult(
            lesson_id="84",
            concept="CVCe a_e",
            decodable_text="A Cake for Tess. Tess had a cake.",
            additional_text="cake lake make take",
            home_practice_text="Read each word: cake, lake, make.",
        )

    monkeypatch.setattr("adapt.llm_planner.lookup_lesson", _fake_lookup)

    block = _corpus_block(_skill(lesson_number=84))

    assert "CVCe a_e" in block
    assert "Read each word: cake, lake, make." in block
    assert "cake lake make take" in block


def test_corpus_block_empty_without_lesson_number() -> None:
    assert _corpus_block(_skill(lesson_number=None)) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapt.llm_planner'`

- [ ] **Step 3: Implement the prompt builder**

Create `adapt/llm_planner.py`:

```python
"""Single-call LLM lesson planner — replaces the retry/takeover orchestration loop.

One strong planning call (provider chain: gpt-5.4 → gemini-3.5-flash) receives
the FULL source items plus canonical corpus lesson content and authors
worksheet items directly. Deterministic code clamps the result to ADHD rules
(adapt/rules.py) and the section cap (adapt/section_cap.py). The GPT judge
evaluates the full item text: approve → ship; reject → ONE regeneration with
feedback; reject again → deterministic engine. Everything that ships carries
a judge verdict.
"""

from __future__ import annotations

import logging
import os

from adapt.rules import AccommodationRules
from companion.schema import LearnerProfile
from corpus.ufli.lookup import lookup_lesson
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)

DEFAULT_PLANNER_PROVIDERS = "openai,gemini"
DEFAULT_PLANNER_GEMINI_MODEL = "gemini-3.5-flash"
PLANNER_MAX_COMPLETION_TOKENS = 8192
_CORPUS_FIELD_CHAR_CAP = 2000


def _corpus_block(skill: LiteracySkillModel) -> str:
    """Canonical UFLI lesson content via the deterministic corpus lookup."""
    if skill.lesson_number is None:
        return ""
    result = lookup_lesson(skill.lesson_number)
    if result is None:
        return ""
    parts = [f"## Canonical UFLI Lesson {result.lesson_id} Content (ground truth)"]
    if result.concept.strip():
        parts.append(f"Concept: {result.concept.strip()}")
    for label, text in (
        ("Home practice text", result.home_practice_text),
        ("Decodable text", result.decodable_text),
        ("Additional practice (Roll and Read)", result.additional_text),
    ):
        cleaned = text.strip()
        if cleaned:
            parts.append(f"{label}:\n{cleaned[:_CORPUS_FIELD_CHAR_CAP]}")
    return "\n\n".join(parts)


def _build_planner_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    theme_id: str,
    rag_curriculum_references: list[dict[str, object]] | None,
) -> str:
    """Build the single planning prompt: full source, corpus truth, ADHD limits."""
    source_sections: list[str] = []
    for si in skill.source_items:
        source_sections.append(f"- [{si.item_type}]: {si.content}")
    source_text = "\n".join(source_sections) if source_sections else "(no source items)"

    corpus_text = _corpus_block(skill)

    curriculum_text = ""
    if rag_curriculum_references:
        refs = []
        for ref in rag_curriculum_references[:3]:
            lesson = ref.get("lesson_id", "?")
            concept = ref.get("concept", "?")
            refs.append(f"- Lesson {lesson}: {concept}")
        curriculum_text = "\nCurriculum references:\n" + "\n".join(refs)

    return f"""You are an expert literacy curriculum designer specializing in ADHD-optimized worksheets for children ages 5-8.

## Source Worksheet Content (COMPLETE — preserve everything below)

Template: {skill.template_type}
Domain: {skill.domain}
Concept: {skill.specific_skill}
Grade level: {skill.grade_level}
Target words: {", ".join(skill.target_words)}

Source sections:
{source_text}

{corpus_text}
{curriculum_text}

## Learner Profile

Name: {profile.name}
Grade: {profile.grade_level}
Response format preferences: {profile.accommodations.response_format_prefs}

## ADHD Design Constraints (hard limits — deterministic validators reject violations)

- Maximum {rules.max_sections_per_worksheet} sections (activities) per mini-worksheet
- Maximum {rules.max_items_per_chunk} items per section
- Maximum {rules.instruction_max_steps} instruction steps per section
- Maximum {rules.instruction_max_words} words per instruction step
- Time estimate per section: about {rules.time_estimate_minutes} minutes
- Allowed response formats: {rules.allowed_response_formats}
- The FIRST section of the first worksheet MUST have a worked example
- One main task per section; keep each mini-worksheet to one page of focus

## Your Task

Design 2-3 mini-worksheets that teach "{skill.specific_skill}" effectively.

CRITICAL RULES:
1. Preserve ALL source content — every word chain, sample word, sight word,
   and sentence from the source MUST appear somewhere in your output items.
2. YOU author the actual practice items: write the exact student-facing text,
   the answer options, and the correct answer for each item. Use real,
   correctly spelled, grade-appropriate words. Never truncate a sentence.
3. Choose activity types that REINFORCE the specific concept (e.g., do NOT
   break "-le" units apart with sound boxes; word chains from the source are
   PRIMARY activities).
4. Order worksheets so the most concept-focused activity comes FIRST.
5. For "match" and "sound_box" activities, list the words in "words" and leave
   "items" empty — the rendering system constructs those mechanically.
6. Each activity needs a rationale for WHY it teaches this concept.

## Output Format

Respond with ONLY this JSON (no markdown fences):
{{
  "concept_focus": "What this lesson teaches",
  "pedagogical_rationale": "Why you structured the worksheets this way",
  "worksheets": [
    {{
      "title": "Worksheet title",
      "activities": [
        {{
          "activity_type": "word_chain|match|write|fill_blank|circle|read_aloud|sound_box|sentence_completion",
          "micro_goal": "Short goal description",
          "words": ["only for match/sound_box or as backup"],
          "items": [
            {{
              "content": "Exact student-facing item text",
              "response_format": "write|circle|fill_blank|read_aloud|trace",
              "options": ["choice1", "choice2"],
              "answer": "correct answer or null"
            }}
          ],
          "instructions": ["Step 1 text", "Step 2 text"],
          "worked_example": "Example text or null",
          "response_format": "write|match|circle|fill_blank|read_aloud|trace|sound_box",
          "time_estimate_minutes": 2,
          "rationale": "Why this activity for this concept"
        }}
      ]
    }}
  ]
}}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_planner.py -v`
Expected: PASS

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_planner.py tests/test_llm_planner.py
git commit -m "feat: planner prompt with full source items and corpus ground truth"
```

---

### Task 6: Planner provider chain (gpt-5.4 → gemini-3.5-flash)

**Files:**
- Modify: `adapt/llm_adapt.py` (`_call_gemini` gains a `model` parameter)
- Modify: `adapt/llm_planner.py`
- Test: `tests/test_llm_planner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_planner.py`:

```python
def test_planner_chain_prefers_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)
    calls: list[str] = []

    def _fake_openai(prompt: str, max_completion_tokens: int = 1024) -> str:
        calls.append(f"openai:{max_completion_tokens}")
        return "{}"

    monkeypatch.setattr(llm_planner, "_call_openai", _fake_openai)

    text, model = llm_planner._call_planner("prompt")

    assert text == "{}"
    assert model == "gpt-5.4"
    assert calls == ["openai:8192"]


def test_planner_chain_falls_back_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_GEMINI_MODEL", raising=False)
    seen: list[str] = []

    def _fake_gemini(prompt: str, model: str = "gemini-3-flash-preview") -> str:
        seen.append(model)
        return "{}"

    monkeypatch.setattr(llm_planner, "_call_gemini", _fake_gemini)

    text, model = llm_planner._call_planner("prompt")

    assert text == "{}"
    assert model == "gemini-3.5-flash"
    assert seen == ["gemini-3.5-flash"]


def test_planner_chain_respects_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("WORKSHEET_PLANNER_PROVIDERS", "gemini,openai")

    monkeypatch.setattr(llm_planner, "_call_gemini", lambda p, model="": "from-gemini")

    text, model = llm_planner._call_planner("prompt")

    assert text == "from-gemini"
    assert model == "gemini-3.5-flash"


def test_planner_chain_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    text, model = llm_planner._call_planner("prompt")

    assert text is None
    assert model == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_planner.py -k chain -v`
Expected: FAIL — `AttributeError: module 'adapt.llm_planner' has no attribute '_call_planner'`

- [ ] **Step 3: Give `_call_gemini` a model parameter**

In `adapt/llm_adapt.py`, change the `_call_gemini` signature and call (~line 170):

```python
def _call_gemini(prompt: str, model: str = "gemini-3-flash-preview") -> str | None:
    """Call Gemini and return the response text."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        return str(response.text)
    except Exception as e:
        logger.warning("Gemini adaptation call failed: %s", e)
        return None
```

(The default keeps the old loop's behavior unchanged.)

- [ ] **Step 4: Implement the chain in `adapt/llm_planner.py`**

Add to the imports:

```python
from adapt.llm_adapt import _call_gemini
from adapt.llm_judge import _call_openai
```

Add after `_corpus_block`:

```python
def _planner_providers() -> list[str]:
    order = os.environ.get("WORKSHEET_PLANNER_PROVIDERS", DEFAULT_PLANNER_PROVIDERS)
    return [p.strip() for p in order.split(",") if p.strip()]


def _call_planner(prompt: str) -> tuple[str | None, str]:
    """Walk the provider chain; return (response_text, model_label)."""
    for provider in _planner_providers():
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            text = _call_openai(prompt, max_completion_tokens=PLANNER_MAX_COMPLETION_TOKENS)
            if text:
                return text, "gpt-5.4"
        elif provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
            model = os.environ.get(
                "WORKSHEET_PLANNER_GEMINI_MODEL", DEFAULT_PLANNER_GEMINI_MODEL
            )
            text = _call_gemini(prompt, model=model)
            if text:
                return text, model
    return None, "none"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_planner.py tests/test_llm_orchestrator.py -v`
Expected: PASS

- [ ] **Step 6: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_adapt.py adapt/llm_planner.py tests/test_llm_planner.py
git commit -m "feat: planner provider chain gpt-5.4 then gemini-3.5-flash"
```

---

### Task 7: Judge reads full item text + structural criteria

**Files:**
- Modify: `adapt/llm_judge.py`
- Test: `tests/test_llm_judge.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_judge.py`:

```python
"""Tests for adapt/llm_judge.py — full-text pedagogical judge prompt."""

from __future__ import annotations

from adapt.llm_judge import _build_judge_prompt
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from skill.schema import LiteracySkillModel, SourceItem

LONG_ITEM = (
    "The little dog likes to ride home in the big red wagon while the cat "
    "naps on the warm stone step."
)


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["cake", "ride", "home"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="sentence", content=LONG_ITEM, source_region_index=0)
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _worksheet() -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="s",
        skill_model_hash="k",
        learner_profile_hash="p",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Read the sentence",
                instructions=[Step(number=1, text="Read it aloud.")],
                worked_example=Example(
                    instruction="Try this first:", content="cake has a magic e"
                ),
                items=[
                    ActivityItem(
                        item_id=1,
                        content=LONG_ITEM,
                        response_format="fill_blank",
                        options=["i", "o", "a"],
                        answer="i",
                    )
                ],
                response_format="fill_blank",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(),
        theme_id="default",
        decoration_zones=[(0.85, 0.0, 1.0, 0.12)],
        worksheet_number=1,
        worksheet_count=1,
        worksheet_title="Magic E",
    )


def test_judge_prompt_carries_full_item_text() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert LONG_ITEM in prompt  # not truncated to 60 chars


def test_judge_prompt_includes_options_answers_instructions_examples() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert "options=['i', 'o', 'a']" in prompt
    assert "answer='i'" in prompt
    assert "Read it aloud." in prompt
    assert "cake has a magic e" in prompt


def test_judge_prompt_includes_structural_criteria() -> None:
    prompt = _build_judge_prompt(_skill(), [_worksheet()])

    assert "truncated" in prompt
    assert "garbled" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_judge.py -v`
Expected: FAIL — `LONG_ITEM in prompt` fails (60-char truncation) and structural-criteria assertions fail

- [ ] **Step 3: Implement the full-text prompt**

In `adapt/llm_judge.py`, replace the worksheet-summary section of `_build_judge_prompt()` (the `ws_sections` loop, ~lines 51–64) with:

```python
    # Adapted worksheets — FULL text, the judge gates what ships
    ws_sections = []
    for ws in worksheets:
        chunks_desc = []
        for chunk in ws.chunks:
            lines = [f"    Section {chunk.chunk_id}: {chunk.micro_goal}"]
            lines.append(
                "      Instructions: " + " | ".join(s.text for s in chunk.instructions)
            )
            if chunk.worked_example is not None:
                lines.append(f"      Worked example: {chunk.worked_example.content}")
            for item in chunk.items:
                item_line = f'      - "{item.content}" ({item.response_format})'
                if item.options:
                    item_line += f" options={item.options}"
                if item.answer is not None:
                    item_line += f" answer={item.answer!r}"
                lines.append(item_line)
            chunks_desc.append("\n".join(lines))
        ws_sections.append(
            f"  Worksheet {ws.worksheet_number}: {ws.worksheet_title}\n"
            + "\n".join(chunks_desc)
        )
    adapted_text = "\n\n".join(ws_sections)
```

Then extend the evaluation-criteria section: after criterion 4 (`adhd_compliance`), add:

```
5. **Structural quality (fold into your scores and approval)**: Every item must be real, correctly spelled, complete text. If any item is truncated (e.g., ends mid-sentence or in "..."), garbled, misspelled, or a formatting artifact (raw markup, teacher-only instructions), set approved=false and name the exact item in feedback.
```

(Keep the `JudgeVerdict` schema unchanged — four score fields; structural failures express through `approved`/`feedback`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_judge.py tests/test_llm_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_judge.py tests/test_llm_judge.py
git commit -m "feat: judge evaluates full item text with structural criteria"
```

---

### Task 8: `plan_lesson_llm` — single call, judge gate, one regen, clean logging

**Files:**
- Modify: `adapt/llm_planner.py`
- Test: `tests/test_llm_planner.py`

- [ ] **Step 1: Write the failing tests**

Merge these imports into the import block at the TOP of `tests/test_llm_planner.py` (mid-file imports trip ruff E402):

```python
import json
from pathlib import Path

from adapt.llm_judge import JudgeVerdict
```

Then append to `tests/test_llm_planner.py`:

```python
_PLAN_JSON = json.dumps(
    {
        "concept_focus": "CVCe magic-e",
        "pedagogical_rationale": "Practice the pattern",
        "worksheets": [
            {
                "title": "Magic E",
                "activities": [
                    {
                        "activity_type": "write",
                        "micro_goal": "Write CVCe words",
                        "words": [],
                        "items": [
                            {"content": "cake", "response_format": "write"},
                            {"content": "ride", "response_format": "write"},
                        ],
                        "instructions": ["Write each word."],
                        "worked_example": "cake -> the e is silent",
                        "response_format": "write",
                        "time_estimate_minutes": 2,
                        "rationale": "Practice writing the pattern",
                    }
                ],
            }
        ],
    }
)


def _verdict(approved: bool, score: float) -> JudgeVerdict:
    return JudgeVerdict(
        approved=approved,
        overall_score=score,
        concept_alignment=score,
        content_coverage=score,
        lesson_flow=score,
        adhd_compliance=score,
        feedback=["ok" if approved else "missing chains"],
        rationale="r",
    )


def _planner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_PROVIDERS", raising=False)


def test_planner_ships_approved_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation", lambda s, w: _verdict(True, 0.9)
    )

    result = llm_planner.plan_lesson_llm(
        _skill(), _profile(), artifacts_dir=str(tmp_path)
    )

    assert result is not None
    assert [i.content for i in result[0].chunks[0].items] == ["cake", "ride"]
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["approved"] is True
    assert verdict["planner_version"] == 2
    assert verdict["outcome"] == "planned_approved"
    log_lines = (tmp_path / "llm_adaptation_log.jsonl").read_text().splitlines()
    assert json.loads(log_lines[-1])["outcome"] == "planned_approved"


def test_planner_regenerates_once_with_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    prompts: list[str] = []

    def _fake_call(prompt: str) -> tuple[str, str]:
        prompts.append(prompt)
        return _PLAN_JSON, "gpt-5.4"

    verdicts = iter([_verdict(False, 0.4), _verdict(True, 0.85)])
    monkeypatch.setattr(llm_planner, "_call_planner", _fake_call)
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: next(verdicts))

    result = llm_planner.plan_lesson_llm(
        _skill(), _profile(), artifacts_dir=str(tmp_path)
    )

    assert result is not None
    assert len(prompts) == 2
    assert "missing chains" in prompts[1]  # feedback fed back
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["outcome"] == "planned_regen_approved"


def test_planner_falls_back_after_two_rejections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation", lambda s, w: _verdict(False, 0.4)
    )

    result = llm_planner.plan_lesson_llm(
        _skill(), _profile(), artifacts_dir=str(tmp_path)
    )

    assert result is None
    # No judge_verdict.json: transform must judge what actually ships
    assert not (tmp_path / "judge_verdict.json").exists()
    attempts = json.loads((tmp_path / "planner_attempts.json").read_text())
    assert attempts["outcome"] == "planned_rejected_fallback"
    assert len(attempts["verdicts"]) == 2


def test_planner_ships_unjudged_when_judge_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(llm_planner, "judge_adaptation", lambda s, w: None)

    result = llm_planner.plan_lesson_llm(
        _skill(), _profile(), artifacts_dir=str(tmp_path)
    )

    assert result is not None
    verdict = json.loads((tmp_path / "judge_verdict.json").read_text())
    assert verdict["unjudged"] is True
    assert verdict["outcome"] == "planned_unjudged"


def test_planner_returns_none_without_env_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)

    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None


def test_planner_returns_none_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None


def test_planner_never_writes_global_log_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adapt import llm_planner

    _planner_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation", lambda s, w: _verdict(True, 0.9)
    )

    llm_planner.plan_lesson_llm(
        _skill(), _profile(), artifacts_dir=str(tmp_path / "artifacts")
    )

    # PYTEST_CURRENT_TEST is set by pytest itself; the global log must not appear
    assert not (tmp_path / "logs").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_planner.py -v`
Expected: new tests FAIL — `AttributeError: module 'adapt.llm_planner' has no attribute 'plan_lesson_llm'`

- [ ] **Step 3: Implement the orchestration**

In `adapt/llm_planner.py`, extend the imports:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from adapt.llm_adapt import _call_gemini, _parse_lesson_plan, _translate_plan
from adapt.llm_judge import JudgeVerdict, _call_openai, judge_adaptation
from adapt.rules import AccommodationRules, build_rules
from adapt.schema import AdaptedActivityModel
from adapt.section_cap import enforce_section_cap
```

(Merge with the existing imports; keep one import block.)

Add after `_call_planner`:

```python
class PlannerLogEntry(BaseModel):
    """One row in llm_adaptation_log.jsonl (planner-v2 schema)."""

    timestamp: str
    skill_domain: str
    specific_skill: str
    template_type: str
    outcome: str
    planning_model: str
    judge_verdicts: list[dict[str, object]] = Field(default_factory=list)
    final_score: float | None = None
    final_output_judged: bool = True
    planner_version: int = 2


def plan_lesson_llm(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
    artifacts_dir: str | None = None,
) -> list[AdaptedActivityModel] | None:
    """One planning call → clamp → judge → one regen → deterministic fallback.

    Returns worksheets on success, or None when the deterministic engine
    should take over (no keys, parse failure, or judge rejected twice).
    """
    if not os.environ.get("WORKSHEET_LLM_ADAPT"):
        return None

    if rules is None:
        rules = build_rules(profile)

    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        logger.info("  LLM planner: no API keys, falling back to deterministic")
        return None

    base_prompt = _build_planner_prompt(
        skill, profile, rules, theme_id, rag_curriculum_references
    )

    verdicts: list[JudgeVerdict] = []
    model_label = "none"
    prompt = base_prompt

    for attempt in range(2):  # one call + one regeneration with feedback
        if attempt == 1:
            prompt = base_prompt + "\n\n" + _feedback_suffix(verdicts[-1])
            logger.info("  LLM planner: regenerating once with judge feedback")

        response_text, model_label = _call_planner(prompt)
        if response_text is None:
            break
        plan = _parse_lesson_plan(response_text)
        if plan is None:
            logger.warning("  LLM planner: failed to parse plan (attempt %d)", attempt + 1)
            break
        worksheets = enforce_section_cap(
            _translate_plan(plan, skill, profile, theme_id, rules), rules
        )
        if not worksheets:
            logger.warning("  LLM planner: translation produced no worksheets")
            break

        verdict = judge_adaptation(skill, worksheets)
        if verdict is None:
            outcome = "planned_unjudged"
            _write_verdict_artifact(_unjudged_payload(outcome), artifacts_dir)
            _log_performance(
                _entry(skill, outcome, verdicts, None, model_label, judged=False),
                artifacts_dir,
            )
            logger.warning("  LLM planner: judge unavailable, shipping unjudged")
            return worksheets

        verdicts.append(verdict)
        if verdict.approved:
            outcome = "planned_approved" if attempt == 0 else "planned_regen_approved"
            _write_verdict_artifact(_verdict_payload(verdict, outcome), artifacts_dir)
            _log_performance(
                _entry(skill, outcome, verdicts, verdict.overall_score, model_label),
                artifacts_dir,
            )
            logger.info("  LLM planner: %s (score=%.2f)", outcome, verdict.overall_score)
            return worksheets

        logger.warning(
            "  LLM planner: judge rejected attempt %d (score=%.2f)",
            attempt + 1,
            verdict.overall_score,
        )

    if verdicts:
        outcome = "planned_rejected_fallback"
    elif model_label != "none":
        outcome = "parse_failure_fallback"
    else:
        outcome = "llm_unavailable"
    _write_planner_attempts(outcome, verdicts, artifacts_dir)
    _log_performance(
        _entry(skill, outcome, verdicts, None, model_label, judged=False),
        artifacts_dir,
    )
    logger.info("  LLM planner: %s — deterministic engine takes over", outcome)
    return None


def _feedback_suffix(verdict: JudgeVerdict) -> str:
    """Judge feedback appended to the prompt for the single regeneration."""
    feedback_lines = "\n".join(f"- {fb}" for fb in verdict.feedback)
    return f"""## Previous Attempt Feedback

Your previous plan was REJECTED by the pedagogical reviewer. You MUST fix all issues below.

Scores:
- Concept alignment: {verdict.concept_alignment:.2f}
- Content coverage: {verdict.content_coverage:.2f}
- Lesson flow: {verdict.lesson_flow:.2f}
- ADHD compliance: {verdict.adhd_compliance:.2f}
- Overall: {verdict.overall_score:.2f}

Specific feedback:
{feedback_lines}

Rationale: {verdict.rationale}

IMPORTANT: Address ALL feedback items above. Ensure EVERY source word, chain, and sentence appears in your revised plan. Do not drop any content."""


def _verdict_payload(verdict: JudgeVerdict, outcome: str) -> dict[str, object]:
    payload: dict[str, object] = dict(verdict.model_dump())
    payload["outcome"] = outcome
    payload["planner_version"] = 2
    return payload


def _unjudged_payload(outcome: str) -> dict[str, object]:
    return {
        "approved": None,
        "overall_score": None,
        "outcome": outcome,
        "unjudged": True,
        "pedagogical_judge_ran": False,
        "planner_version": 2,
        "rationale": "Judge unavailable; planner output shipped without a verdict.",
    }


def _write_verdict_artifact(payload: dict[str, object], artifacts_dir: str | None) -> None:
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "judge_verdict.json").write_text(json.dumps(payload, indent=2))


def _write_planner_attempts(
    outcome: str,
    verdicts: list[JudgeVerdict],
    artifacts_dir: str | None,
) -> None:
    """Record rejected attempts WITHOUT claiming a verdict for what ships.

    Deliberately not judge_verdict.json: when the planner falls back, the
    deterministic output is what ships, and transform.py runs the advisory
    judge on it (judge-everything policy).
    """
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "planner_attempts.json").write_text(
        json.dumps(
            {
                "outcome": outcome,
                "planner_version": 2,
                "verdicts": [v.model_dump() for v in verdicts],
            },
            indent=2,
        )
    )


def _entry(
    skill: LiteracySkillModel,
    outcome: str,
    verdicts: list[JudgeVerdict],
    final_score: float | None,
    planning_model: str,
    judged: bool = True,
) -> PlannerLogEntry:
    return PlannerLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        skill_domain=skill.domain,
        specific_skill=skill.specific_skill,
        template_type=skill.template_type,
        outcome=outcome,
        planning_model=planning_model,
        judge_verdicts=[v.model_dump() for v in verdicts],
        final_score=final_score,
        final_output_judged=judged,
    )


def _log_performance(entry: PlannerLogEntry, artifacts_dir: str | None) -> None:
    line = entry.model_dump_json() + "\n"
    if artifacts_dir:
        path = Path(artifacts_dir)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)
    # The global cross-run log is live telemetry — never write it from tests.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        global_log = Path("logs")
        global_log.mkdir(parents=True, exist_ok=True)
        with open(global_log / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)
    logger.info(
        "  LLM planner log: outcome=%s model=%s score=%s",
        entry.outcome,
        entry.planning_model,
        f"{entry.final_score:.2f}" if entry.final_score is not None else "N/A",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_planner.py -v`
Expected: PASS

- [ ] **Step 5: Write a failing test for the OLD loop's log pollution**

The legacy orchestrator stays alive through the A/B window (Tasks 9–12) and its `_log_performance` is THE source of the 311 polluted entries — it needs the same guard now, not at deletion time. Append to `tests/test_llm_orchestrator.py` (merge `from pathlib import Path` into the top imports if missing; `json` and the patch targets are already imported there):

```python
def test_orchestrator_never_writes_global_log_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.chdir(tmp_path)

    with (
        patch(_PATCH_GEMINI, return_value=_GEMINI_PLAN_JSON),
        patch(_PATCH_JUDGE, return_value=_approved_verdict()),
    ):
        orchestrate_llm_adaptation(_skill(), _profile())

    # PYTEST_CURRENT_TEST is set by pytest itself; the global log must not appear
    assert not (tmp_path / "logs").exists()
```

Run: `.venv/bin/pytest tests/test_llm_orchestrator.py::test_orchestrator_never_writes_global_log_under_pytest -v`
Expected: FAIL — `logs/` directory created by the global write

- [ ] **Step 6: Guard the old loop's global write**

In `adapt/llm_orchestrator.py:_log_performance()` (~line 441), wrap the global-log block:

```python
    # Write to global log (cross-run visibility) — never from tests
    if "PYTEST_CURRENT_TEST" not in os.environ:
        global_log = Path("logs")
        global_log.mkdir(parents=True, exist_ok=True)
        with open(global_log / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)
```

Run: `.venv/bin/pytest tests/test_llm_orchestrator.py -v`
Expected: PASS

- [ ] **Step 7: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_planner.py adapt/llm_orchestrator.py tests/test_llm_planner.py tests/test_llm_orchestrator.py
git commit -m "feat: single-call planner with judge gate, one regen, pytest-safe logging"
```

---

### Task 9: Route through the new planner behind a flag; skip ai_review for judged output

**Files:**
- Modify: `adapt/engine.py` (`adapt_lesson`, ~lines 144–160)
- Modify: `transform.py` (`_run_multi_worksheet_pipeline`, ~lines 509–588)
- Test: `tests/test_planner_pipeline.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner_pipeline.py`:

```python
"""Tests for transform/engine wiring of the planner-v2 path."""

from __future__ import annotations

import pytest

from transform import _skip_ai_review


def test_skip_ai_review_for_planner_v2_output() -> None:
    assert _skip_ai_review({"planner_version": 2, "approved": True}) is True


def test_run_ai_review_for_legacy_and_deterministic_output() -> None:
    assert _skip_ai_review({"approved": True}) is False
    assert _skip_ai_review({"enabled": False}) is False


def test_engine_routes_to_planner_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import engine
    from adapt.llm_adapt import ActivityPlan, LessonPlan, _translate_plan
    from adapt.rules import build_rules
    from companion.schema import Accommodations, LearnerProfile
    from skill.schema import LiteracySkillModel, SourceItem

    skill = LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc",
        learning_objectives=["Read CVC words"],
        target_words=["cat"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="cat", source_region_index=0)
        ],
        extraction_confidence=0.9,
        template_type="ufli_word_work",
    )
    profile = LearnerProfile(name="t", grade_level="1", accommodations=Accommodations())
    plan = LessonPlan(
        worksheets=[
            {
                "title": "CVC",
                "activities": [
                    ActivityPlan(
                        activity_type="write",
                        micro_goal="Write CVC words",
                        words=["cat"],
                        instructions=["Write the word."],
                        response_format="write",
                    )
                ],
            }
        ]
    )
    canned = _translate_plan(plan, skill, profile, "default", build_rules(profile))

    monkeypatch.setenv("WORKSHEET_PLANNER_V2", "1")
    called: list[str] = []

    def _fake_planner(*args: object, **kwargs: object) -> list[object]:
        called.append("planner")
        return list(canned)

    monkeypatch.setattr("adapt.llm_planner.plan_lesson_llm", _fake_planner)

    result = engine.adapt_lesson(skill, profile)

    assert called == ["planner"]
    assert result[0].chunks[0].items[0].content == "cat"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_planner_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name '_skip_ai_review'`

- [ ] **Step 3: Add the engine routing**

In `adapt/engine.py`, inside `adapt_lesson()`, replace the orchestrator block (~lines 144–159):

```python
    # Try orchestrated LLM adaptation (Gemini → Judge → retry → GPT takeover)
    try:
        from adapt.llm_orchestrator import orchestrate_llm_adaptation

        llm_result = orchestrate_llm_adaptation(
            skill,
            profile,
            theme_id=theme_id,
            rules=rules,
            rag_curriculum_references=rag_curriculum_references,
            artifacts_dir=artifacts_dir,
        )
        if llm_result:
            return enforce_section_cap(llm_result, rules)
    except Exception as exc:
        logger.warning("LLM orchestration failed, using deterministic engine: %s", exc)
```

with:

```python
    if os.environ.get("WORKSHEET_PLANNER_V2") == "1":
        # New single-call planner (A/B flag; becomes the only LLM path after
        # the battery gate — see plans/2026-06-12-planner-simplification-plan.md)
        try:
            from adapt.llm_planner import plan_lesson_llm

            planned = plan_lesson_llm(
                skill,
                profile,
                theme_id=theme_id,
                rules=rules,
                rag_curriculum_references=rag_curriculum_references,
                artifacts_dir=artifacts_dir,
            )
            if planned:
                return enforce_section_cap(planned, rules)
        except Exception as exc:
            logger.warning("LLM planner failed, using deterministic engine: %s", exc)
    else:
        # Legacy loop (Gemini → Judge → retry → GPT takeover)
        try:
            from adapt.llm_orchestrator import orchestrate_llm_adaptation

            llm_result = orchestrate_llm_adaptation(
                skill,
                profile,
                theme_id=theme_id,
                rules=rules,
                rag_curriculum_references=rag_curriculum_references,
                artifacts_dir=artifacts_dir,
            )
            if llm_result:
                return enforce_section_cap(llm_result, rules)
        except Exception as exc:
            logger.warning("LLM orchestration failed, using deterministic engine: %s", exc)
```

- [ ] **Step 4: Add the ai_review skip in `transform.py`**

Add a module-level helper near `_validate_and_report`:

```python
def _skip_ai_review(judge_result: dict[str, object]) -> bool:
    """Planner-v2 output was already judged on full item text.

    The legacy ai_review loop (up to 3 LLM calls per worksheet) only adds
    value for deterministic/legacy output, where OCR artifacts are real and
    no full-text judge gated the content.
    """
    return judge_result.get("planner_version") == 2
```

In `_run_multi_worksheet_pipeline()`, after the judge read-back block (after `judge_json.write_text(...)`, ~line 549), add:

```python
    skip_review = _skip_ai_review(judge_result)
```

Then wrap the existing AI-review block inside the worksheet loop (~lines 571–588):

```python
        if skip_review:
            logger.info(
                "  AI quality review skipped for worksheet %s/%s (planner-v2 output already judged)",
                i,
                len(worksheets),
            )
        else:
            logger.info("  AI quality review for worksheet %s/%s...", i, len(worksheets))
            adapted, reviews = review_adapted_worksheet(adapted)
            review_json = artifacts / f"ai_review_{i}.json"
            review_json.write_text(
                json.dumps([review.to_dict() for review in reviews], indent=2)
            )
            if reviews:
                latest_review = reviews[-1]
                ai_review_passed = ai_review_passed and latest_review.passed
                if latest_review.passed:
                    logger.info("  AI quality review_%s: PASSED", i)
                else:
                    logger.warning(
                        "  AI quality review_%s: %s issues remaining after %s iterations",
                        i,
                        len(latest_review.issues),
                        len(reviews),
                    )
            adapted_json.write_text(adapted.model_dump_json(indent=2))
            worksheets[i - 1] = adapted
```

(Indent the existing statements under the `else:`; the `adapted_json.write_text` + `worksheets[i - 1] = adapted` lines move inside it since nothing mutated when the review is skipped.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner_pipeline.py -v && make test`
Expected: PASS

- [ ] **Step 6: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/engine.py transform.py tests/test_planner_pipeline.py
git commit -m "feat: WORKSHEET_PLANNER_V2 routing; skip ai_review for judged planner output"
```

---

### Task 10: Skip per-chunk asset generation under image_gen

**Files:**
- Modify: `transform.py` (`_run_multi_worksheet_pipeline`, asset block ~lines 598–628)
- Test: `tests/test_planner_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_planner_pipeline.py`:

```python
def test_chunk_assets_skipped_for_image_gen() -> None:
    from transform import _should_generate_chunk_assets

    assert _should_generate_chunk_assets("pdf_classic") is True
    assert _should_generate_chunk_assets("image_prompt") is True
    assert _should_generate_chunk_assets("image_gen") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_planner_pipeline.py::test_chunk_assets_skipped_for_image_gen -v`
Expected: FAIL — `ImportError: cannot import name '_should_generate_chunk_assets'`

- [ ] **Step 3: Implement**

In `transform.py`, add near `_skip_ai_review`:

```python
def _should_generate_chunk_assets(render_mode: str) -> bool:
    """Per-chunk scene/word images only serve pdf_classic-style layouts.

    The image_gen renderer generates full pages and never reads the asset
    manifest; if it falls back to pdf_classic mid-run, that worksheet renders
    with the deterministic local art (same degradation as asset-gen failure).
    """
    return render_mode != "image_gen"
```

In `_run_multi_worksheet_pipeline()`, wrap the asset-generation block (the `try:` from `scenes = plan_scenes(...)` through the `except Exception as exc:` handler, keeping `asset_manifest = None` above it):

```python
        asset_manifest = None
        if _should_generate_chunk_assets(render_mode):
            try:
                scenes = plan_scenes(adapted, character_spec=char_spec)
                word_prompts = plan_word_pictures(adapted)
                ws_hash = compute_worksheet_hash(
                    adapted.source_hash,
                    i,
                    theme_id,
                    identity_version=identity.identity_version,
                )

                # Pass style sheet for theme-accurate character rendering
                style_sheet = None
                if profile.avatar and profile.avatar.style_sheet:
                    style_sheet = profile.avatar.style_sheet

                asset_manifest = generate_worksheet_assets(
                    scenes,
                    word_prompts,
                    ws_hash,
                    character_name=(
                        profile.avatar.base_character if profile.avatar else "rainbow_roblox"
                    ),
                    style_sheet=style_sheet,
                    character_spec=char_spec,
                    profile=profile,
                    theme_id=theme_id,
                    identity=identity,
                )
            except Exception as exc:
                logger.warning("  Asset generation skipped: %s", exc)
        else:
            logger.info("  Asset generation skipped (image_gen renders full pages)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner_pipeline.py -v && make test`
Expected: PASS

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add transform.py tests/test_planner_pipeline.py
git commit -m "feat: skip per-chunk asset generation when render mode is image_gen"
```

---

### Task 11: A/B adaptation battery CLI

**Files:**
- Create: `adapt_battery.py`
- Test: `tests/test_adapt_battery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_adapt_battery.py`:

```python
"""Tests for adapt_battery.py — old-loop vs new-planner scorecard."""

from __future__ import annotations

from adapt_battery import AdaptBatteryRow, build_scorecard


def test_scorecard_lists_both_variants() -> None:
    rows = [
        AdaptBatteryRow(
            input_name="IMG_0004",
            variant="loop",
            outcome="gpt_takeover_unjudged",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[9],
            content_coverage_passed=False,
            adhd_compliance_passed=False,
        ),
        AdaptBatteryRow(
            input_name="IMG_0004",
            variant="planner",
            outcome="planned_approved",
            judge_approved=True,
            judge_score=0.86,
            sections_per_worksheet=[3, 3, 2],
            content_coverage_passed=True,
            adhd_compliance_passed=True,
        ),
    ]
    card = build_scorecard(rows)

    assert "IMG_0004" in card
    assert "loop" in card and "planner" in card
    assert "gpt_takeover_unjudged" in card
    assert "planned_approved" in card
    assert "0.86" in card
    assert "3/3/2" in card


def test_scorecard_shows_errors() -> None:
    rows = [
        AdaptBatteryRow(
            input_name="IMG_0003",
            variant="planner",
            outcome="error",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[],
            content_coverage_passed=None,
            adhd_compliance_passed=None,
            error="boom",
        )
    ]
    card = build_scorecard(rows)

    assert "error" in card
    assert "boom" in card
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_adapt_battery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapt_battery'`

- [ ] **Step 3: Implement the CLI**

Create `adapt_battery.py`:

```python
"""A/B adaptation battery — legacy retry/takeover loop vs single-call planner.

Runs each input through both adaptation paths with render mode pdf_classic
and asset generation skipped (adaptation is the variable under test), then
writes <output>/<timestamp>/scorecard.md comparing judge verdicts, sections
per worksheet, content coverage, and outcomes.

Usage (requires API keys; see Session 42 notes re SSL_CERT_FILE on macOS):
    WORKSHEET_LLM_ADAPT=1 .venv/bin/python adapt_battery.py \
        --input samples/input/IMG_0004.JPG \
        --profile profiles/ian.yaml \
        --theme roblox_obby
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

VARIANTS = ("loop", "planner")
_VARIANT_ENV = ("WORKSHEET_PLANNER_V2", "WORKSHEET_SKIP_ASSET_GEN", "WORKSHEET_LLM_ADAPT")


class AdaptBatteryRow(BaseModel):
    """One battery cell: a single input run through one adaptation variant."""

    input_name: str
    variant: str  # "loop" | "planner"
    outcome: str
    judge_approved: bool | None
    judge_score: float | None
    sections_per_worksheet: list[int]
    content_coverage_passed: bool | None
    adhd_compliance_passed: bool | None
    error: str | None = None


def build_scorecard(rows: list[AdaptBatteryRow]) -> str:
    lines = [
        "# Adaptation battery scorecard",
        "",
        "| input | variant | outcome | judge | score | sections/ws | coverage | adhd |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        judge = {True: "PASS", False: "FAIL", None: "—"}[row.judge_approved]
        score = f"{row.judge_score:.2f}" if row.judge_score is not None else "—"
        sections = "/".join(str(n) for n in row.sections_per_worksheet) or "—"
        coverage = {True: "PASS", False: "FAIL", None: "—"}[row.content_coverage_passed]
        adhd = {True: "PASS", False: "FAIL", None: "—"}[row.adhd_compliance_passed]
        lines.append(
            f"| {row.input_name} | {row.variant} | {row.outcome} | {judge} "
            f"| {score} | {sections} | {coverage} | {adhd} |"
        )
    errors = [row for row in rows if row.error]
    if errors:
        lines.append("")
        lines.append("## Errors")
        for row in errors:
            lines.append(f"- {row.input_name} ({row.variant}): {row.error}")
    lines.append("")
    return "\n".join(lines)


def _collect_row(
    input_name: str,
    variant: str,
    artifacts: Path,
    validation_results: dict[str, bool],
) -> AdaptBatteryRow:
    judge_approved: bool | None = None
    judge_score: float | None = None
    outcome = "unknown"

    judge_json = artifacts / "judge_verdict.json"
    if judge_json.exists():
        verdict = json.loads(judge_json.read_text())
        approved = verdict.get("approved")
        if isinstance(approved, bool):
            judge_approved = approved
        score = verdict.get("overall_score")
        if isinstance(score, (int, float)):
            judge_score = float(score)
        if isinstance(verdict.get("outcome"), str):
            outcome = str(verdict["outcome"])

    log_path = artifacts / "llm_adaptation_log.jsonl"
    if log_path.exists():
        log_lines = log_path.read_text().splitlines()
        if log_lines:
            outcome = str(json.loads(log_lines[-1]).get("outcome", outcome))

    sections: list[int] = []
    for model_path in sorted(artifacts.glob("adapted_model_*.json")):
        data = json.loads(model_path.read_text())
        sections.append(len(data.get("chunks", [])))

    return AdaptBatteryRow(
        input_name=input_name,
        variant=variant,
        outcome=outcome,
        judge_approved=judge_approved,
        judge_score=judge_score,
        sections_per_worksheet=sections,
        content_coverage_passed=validation_results.get("content_coverage_passed"),
        adhd_compliance_passed=validation_results.get("adhd_compliance_passed"),
    )


def _run_variant(
    input_path: str,
    profile_path: str,
    theme_id: str,
    out_root: Path,
    variant: str,
) -> AdaptBatteryRow:
    from transform import run_pipeline_collect_artifacts

    input_name = Path(input_path).stem
    out_dir = out_root / f"{input_name}_{variant}"
    artifacts = out_dir / "artifacts"

    backup = {key: os.environ.get(key) for key in _VARIANT_ENV}
    os.environ["WORKSHEET_LLM_ADAPT"] = "1"
    os.environ["WORKSHEET_SKIP_ASSET_GEN"] = "1"
    if variant == "planner":
        os.environ["WORKSHEET_PLANNER_V2"] = "1"
    else:
        os.environ.pop("WORKSHEET_PLANNER_V2", None)
    try:
        run = run_pipeline_collect_artifacts(
            input_path=input_path,
            profile_path=profile_path,
            theme_id=theme_id,
            output_dir=str(out_dir),
            artifacts_dir=str(artifacts),
            index_results=False,
            render_mode="pdf_classic",
        )
    except Exception as exc:  # battery must keep going past a failed cell
        logger.exception("Battery cell failed: %s %s", input_name, variant)
        return AdaptBatteryRow(
            input_name=input_name,
            variant=variant,
            outcome="error",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[],
            content_coverage_passed=None,
            adhd_compliance_passed=None,
            error=str(exc),
        )
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    flags = {
        key: value for key, value in run.validation_results.items() if isinstance(value, bool)
    }
    return _collect_row(input_name, variant, artifacts, flags)


def battery(
    inputs: list[str],
    profile_path: str,
    theme_id: str,
    output_dir: str,
) -> Path:
    """Run every input through both variants; write and return the scorecard path."""
    root = Path(output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)

    rows: list[AdaptBatteryRow] = []
    for input_path in inputs:
        for variant in VARIANTS:
            logger.info("Battery cell: %s × %s", Path(input_path).stem, variant)
            rows.append(_run_variant(input_path, profile_path, theme_id, root, variant))

    scorecard_path = root / "scorecard.md"
    scorecard_path.write_text(build_scorecard(rows))
    (root / "scorecard.json").write_text(
        json.dumps([row.model_dump() for row in rows], indent=2)
    )
    logger.info("Scorecard: %s", scorecard_path)
    return scorecard_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, dest="inputs")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--theme", default="default")
    parser.add_argument("--output", default="samples/output/adapt_battery")
    args = parser.parse_args()
    battery(args.inputs, args.profile, args.theme, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_adapt_battery.py -v`
Expected: PASS

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt_battery.py tests/test_adapt_battery.py
git commit -m "feat: A/B adaptation battery CLI with promotion scorecard"
```

---

### Task 12: Live A/B run + owner review gate (manual; requires API keys)

> **GATE: Tasks 13–15 MUST NOT start until the owner reviews this battery and approves.** The old loop stays the default until then.

**Files:**
- Modify: `.claude/worksheet-project-context.md` (session handoff entry)

- [ ] **Step 1: Run the battery on 2–3 lessons**

Live calls need the sandbox disabled and, on macOS/Python 3.13, `SSL_CERT_FILE` pointed at the venv certifi bundle (Session 42 notes):

```bash
SSL_CERT_FILE=$(.venv/bin/python -c "import certifi; print(certifi.where())") \
WORKSHEET_LLM_ADAPT=1 .venv/bin/python adapt_battery.py \
  --input samples/input/IMG_0003.JPG \
  --input samples/input/IMG_0004.JPG \
  --input samples/input/IMG_0005.JPG \
  --profile profiles/ian.yaml \
  --theme roblox_obby
```

- [ ] **Step 2: Inspect the scorecard and artifacts**

In `samples/output/adapt_battery/<timestamp>/`:
- `scorecard.md` — compare per input: judge approval/score, outcome, sections per worksheet (planner cells must all be ≤ grade cap), content coverage, ADHD compliance.
- Per-cell `artifacts/adapted_model_*.json` — read the planner-authored items for quality (real words, complete sentences, sensible options/answers).
- Per-cell `artifacts/llm_adaptation_log.jsonl` — confirm planner outcomes (`planned_approved` / `planned_regen_approved`) and count calls: the loop cells log `gemini_attempts`; planner cells log at most 2 attempts.
- The per-input `*_planner/` output PDFs (pdf_classic render) — quick visual read.
- If a planner cell hit `planned_rejected_fallback`, read both verdicts in `artifacts/planner_attempts.json` before tuning anything (systematic-debugging: identify the failing criterion first; likely candidates are judge harshness vs genuine content drops).

- [ ] **Step 3: Owner review**

Present the scorecard and 2–3 adapted-model comparisons to the owner. The owner decides:
- **Promote** → proceed to Tasks 13–15.
- **Iterate** → fix what the comparison exposed (prompt emphasis, judge threshold), rerun this task.

- [ ] **Step 4: Record the handoff entry**

Add a dated session entry to `.claude/worksheet-project-context.md` covering: battery scorecard numbers (judge scores, outcomes, section counts, call counts old vs new), the owner's verdict, and any planner weaknesses found.

```bash
git add .claude/worksheet-project-context.md
git commit -m "docs: record adaptation A/B battery results and owner verdict"
```

---

### Task 13: Default-on semantics (GATED on Task 12 owner approval)

**Files:**
- Modify: `adapt/llm_planner.py` (gate line)
- Create: `tests/conftest.py`
- Test: `tests/test_llm_planner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_planner.py`:

```python
def test_planner_default_on_with_explicit_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt import llm_planner

    # Default-on: unset env + keys present should NOT return None at the gate
    monkeypatch.delenv("WORKSHEET_LLM_ADAPT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setattr(llm_planner, "_call_planner", lambda p: (_PLAN_JSON, "gpt-5.4"))
    monkeypatch.setattr(
        llm_planner, "judge_adaptation", lambda s, w: _verdict(True, 0.9)
    )
    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is not None

    # Explicit opt-out
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_llm_planner.py::test_planner_default_on_with_explicit_opt_out -v`
Expected: FAIL — first assertion (unset env currently returns None)

- [ ] **Step 3: Flip the gate + pin tests offline**

In `adapt/llm_planner.py`, change the gate at the top of `plan_lesson_llm()`:

```python
    if os.environ.get("WORKSHEET_LLM_ADAPT", "1") == "0":
        return None
```

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _llm_adapt_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM adaptation is default-on in production; tests must opt in explicitly.

    Without this pin, any test with API-key env vars set (real or fake) would
    hit the planner gate and attempt network calls. Tests that exercise the
    LLM path override with monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "1").
    """
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
```

Note: tests that previously relied on `monkeypatch.delenv("WORKSHEET_LLM_ADAPT")` to mean "disabled" (e.g., `test_planner_returns_none_without_env_gate` from Task 8) now need `monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")` instead — update that test to match the new semantics:

```python
def test_planner_returns_none_without_env_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt import llm_planner

    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")

    assert llm_planner.plan_lesson_llm(_skill(), _profile()) is None
```

- [ ] **Step 4: Run the full suite**

Run: `make test`
Expected: PASS. Any failure here means a test was implicitly depending on LLM adaptation being off by absence — fix it to opt out explicitly (the conftest pin should cover almost all).

- [ ] **Step 5: Full check + commit**

```bash
make lint && make typecheck && make test
git add adapt/llm_planner.py tests/conftest.py tests/test_llm_planner.py
git commit -m "feat: LLM adaptation default-on with WORKSHEET_LLM_ADAPT=0 opt-out"
```

---

### Task 14: Delete the old loop, direct compiler, and the V2 flag (GATED on Task 12)

**Files:**
- Modify: `adapt/engine.py`, `transform.py`, `tests/test_llm_adapt.py`, `pyproject.toml`
- Delete: `adapt/llm_orchestrator.py`, `adapt/direct_compiler.py`, `tests/test_llm_orchestrator.py`, `tests/test_direct_compiler.py`

- [ ] **Step 1: Relocate the still-valuable helper tests**

`tests/test_llm_orchestrator.py` contains test classes that exercise `adapt/llm_adapt.py` helpers (not the loop): the chunk-cap test (`test_helper_respects_small_chunk_cap_for_items_and_options`, ~line 300) and the circle-distractor test (`test_circle_distractors_do_not_reintroduce_omitted_targets`, ~line 381). Copy those test functions (with the fixtures they use) into `tests/test_llm_adapt.py` verbatim, dropping any `llm_orchestrator` imports (they import from `adapt.llm_adapt`).

Run: `.venv/bin/pytest tests/test_llm_adapt.py -v`
Expected: PASS

- [ ] **Step 2: Make engine route only through the planner**

In `adapt/engine.py:adapt_lesson()`:

1. Delete the `WORKSHEET_DIRECT_COMPILER` block (~lines 129–142).
2. Replace the entire V2-flag `if/else` from Task 9 with the unconditional planner path:

```python
    # LLM adaptation: single-call planner (judge-gated; see D30/D31)
    try:
        from adapt.llm_planner import plan_lesson_llm

        planned = plan_lesson_llm(
            skill,
            profile,
            theme_id=theme_id,
            rules=rules,
            rag_curriculum_references=rag_curriculum_references,
            artifacts_dir=artifacts_dir,
        )
        if planned:
            return enforce_section_cap(planned, rules)
    except Exception as exc:
        logger.warning("LLM planner failed, using deterministic engine: %s", exc)
```

3. Remove the now-unused `character_identity` parameter from `adapt_lesson()` (it only served the direct compiler) and the `if TYPE_CHECKING:` import of `CharacterIdentity` if nothing else in the module uses it.
4. Update the `adapt_lesson()` docstring: the LLM path is the single-call planner; deterministic engine is the fallback.

In `transform.py:_run_multi_worksheet_pipeline()`, remove `character_identity=character_identity,` from the `adapt_lesson(...)` call (~line 505). Keep `resolve_character_identity` — it is still used for assets and rendering.

In `tests/test_planner_pipeline.py::test_engine_routes_to_planner_v2`, delete the `monkeypatch.setenv("WORKSHEET_PLANNER_V2", "1")` line and rename the test to `test_engine_routes_to_planner` (the flag no longer exists).

- [ ] **Step 3: Delete the superseded modules and their tests**

```bash
git rm adapt/llm_orchestrator.py tests/test_llm_orchestrator.py
git rm adapt/direct_compiler.py tests/test_direct_compiler.py
```

Then sweep for dangling references:

```bash
grep -rn "llm_orchestrator\|direct_compiler\|WORKSHEET_DIRECT_COMPILER\|WORKSHEET_PLANNER_V2" \
  --include="*.py" --include="*.toml" --include="*.md" . | grep -v plans/ | grep -v .claude/
```

Expected hits to fix: `pyproject.toml` E501 exemption for `llm_orchestrator.py` (remove the entry), any stale comment in `transform.py` (~line 510 mentions "the LLM orchestrator" — reword to "the LLM planner"). The grep must come back clean (excluding plans/ and context docs) before committing.

- [ ] **Step 4: Run the full suite**

Run: `make lint && make typecheck && make test`
Expected: PASS — `make test` count drops by the deleted test files' counts but everything green.

- [ ] **Step 5: Commit**

```bash
git add adapt/engine.py transform.py tests/test_llm_adapt.py tests/test_planner_pipeline.py pyproject.toml
git commit -m "refactor: single-call planner replaces retry/takeover loop and direct compiler"
```

(`git rm` already staged the deletions.)

---

### Task 15: Archive polluted telemetry + docs (GATED on Task 12)

**Files:**
- Modify: `AGENTS.md`, `.claude/worksheet-project-context.md`
- Local file move (gitignored): `logs/llm_adaptation_log.jsonl`

- [ ] **Step 1: Archive the polluted global log**

`logs/` is gitignored — this is a local hygiene move so real telemetry accumulates from a clean slate:

```bash
mkdir -p logs/archive
mv logs/llm_adaptation_log.jsonl logs/archive/llm_adaptation_log.pytest-polluted.jsonl
```

- [ ] **Step 2: Document the planner env vars in AGENTS.md**

In the `## Conventions` section of `AGENTS.md`, after the image-renderer env bullet, add:

```markdown
- LLM adaptation (single-call planner, default-on): `WORKSHEET_LLM_ADAPT=0` opts out (no-key runs auto-fall back to the deterministic engine). `WORKSHEET_PLANNER_PROVIDERS` (comma-ordered chain, default `openai,gemini`), `WORKSHEET_PLANNER_GEMINI_MODEL` (default `gemini-3.5-flash`). Judge gate: approve → ship; reject → one regeneration; reject again → deterministic engine. Every shipped package carries a judge verdict (`judge_verdict.json`).
```

Also update the stale `WORKSHEET_LLM_ADAPT=1` mentions if any remain in `AGENTS.md` command examples (default-on no longer needs the prefix).

- [ ] **Step 3: Session handoff entry**

Add a dated entry to `.claude/worksheet-project-context.md` Current State covering: what shipped (Tasks 0–15), the A/B battery numbers, the default-on flip, deletions (`llm_orchestrator`, `direct_compiler`), the log archive, and the new outcome taxonomy (`planned_approved | planned_regen_approved | planned_unjudged | planned_rejected_fallback | parse_failure_fallback | llm_unavailable`). Mark the D31 default-on clause as effective.

- [ ] **Step 4: Final verification + commit**

```bash
make lint && make typecheck && make test
git add AGENTS.md .claude/worksheet-project-context.md
git commit -m "docs: planner env vars, default-on flip, telemetry log archive"
```

---

## Follow-up plans (separate documents, after this ships)

1. **Provider tuning for the image renderer** — cumulative live data says gemini third attempts recover 0-for-4 while gpt-image-2 rescues 4-for-4 on attempt 1; consider dropping gemini's budget to 2 or reordering `WORKSHEET_IMAGE_PROVIDERS` for text-dense lessons. (Out of scope here: render/ just shipped.)
2. **Multi-theme rotation** — `--theme auto` from `profile.preferences.favorite_themes`.
3. **Judge telemetry review** — once the clean global log accumulates ~20 live lessons, review score distributions to tune the 0.7 approval threshold and decide whether the regeneration is earning its cost.
4. **Decodable-passage planning** — extend the planner prompt to author fluency worksheets from `ufli_decodable_story` templates.

## Known risks

- **Self-judging:** gpt-5.4 judges gpt-5.4's plans (the old loop deliberately avoided this). Mitigations: the judge runs a different role prompt on full text; deterministic validators (`content_coverage`, `adhd_compliance`, `skill_parity`) backstop independently; the A/B battery exposes leniency before the default flips. If scores look inflated, switch `WORKSHEET_PLANNER_PROVIDERS=gemini,openai` for cross-vendor judging and compare.
- **Judge harshness:** the live judge rejected 100% of Gemini's plans. If it also rejects the new planner's output, everything silently degrades to deterministic (`planned_rejected_fallback` in the log). The battery makes this visible before promotion; the fix is prompt/threshold tuning, not removing the gate.
- **`gemini-3.5-flash` model id:** owner-specified "latest Gemini"; verify the exact id against the `google-genai` SDK at execution time and adjust `DEFAULT_PLANNER_GEMINI_MODEL` if it differs.
- **Token budget:** full source + corpus + authored items is a much larger response than the old word-list plans. `PLANNER_MAX_COMPLETION_TOKENS = 8192` should suffice for 2–3 worksheets; truncated JSON shows up as `parse_failure_fallback` in the log — raise the budget if that outcome appears.
- **Section-cap ripple:** the split pass changes deterministic outputs for content-heavy lessons (e.g., warmup + 3 trace batches). Most pinned tests assert `>= 1` and survive; Task 3 Step 6 names the candidates. `test_e2e.py` golden runs (excluded from `make test`) may need regeneration.
- **Env mutation in `adapt_battery.py`:** variants toggle process-global env vars; the battery must stay serial (it is). Don't parallelize cells without reworking that.
- **Deletion ordering:** `tests/test_llm_orchestrator.py` pins helper behavior that lives in `llm_adapt.py`; Task 14 Step 1 relocates those tests BEFORE the file is deleted — do not skip it.
- **Parallel-session drift:** a parallel session is landing cover-consistency + image_gen promotion (D29). This plan touches `transform.py` (`_run_multi_worksheet_pipeline`) — rebase carefully if that session also edited it; the asset-skip conditional (Task 10) must wrap whatever the asset block looks like after their merge.
