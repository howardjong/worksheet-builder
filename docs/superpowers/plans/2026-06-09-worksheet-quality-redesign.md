# Worksheet Quality Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve worksheet quality, learner personalization, Learning Buddy consistency, and merge safety while keeping `main` stable.

**Architecture:** Build this on a new feature branch with small, testable checkpoints. Start with quality gates that expose current failures, then fix live pipeline gaps, then simplify RAG, then route all buddy art through one identity path, then add a direct-context worksheet compiler behind a feature flag, then keep future image-model pivots behind a renderer strategy boundary.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy, ReportLab, ChromaDB/RAG retained as optional experiment tooling, Gemini/OpenAI calls behind existing adapters and environment flags.

---

## Branch and merge strategy

Work must happen on `feature/worksheet-quality-redesign`, not directly on `main`.

Preferred isolation:

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
git status --short --branch
git fetch --prune origin
git switch main
git pull --ff-only origin main
git switch -c feature/worksheet-quality-redesign
```

If implementation should avoid touching the current checkout entirely, create a linked worktree instead:

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
git status --short --branch
git fetch --prune origin
git worktree add .worktrees/worksheet-quality-redesign -b feature/worksheet-quality-redesign origin/main
cd .worktrees/worksheet-quality-redesign
```

Before using `.worktrees/`, verify it is ignored:

```bash
git check-ignore -q .worktrees || printf "\n.worktrees/\n" >> .gitignore
```

Baseline verification before edits:

```bash
make lint
make typecheck
make test
make test-golden
```

Expected baseline:

- `make lint`: passes.
- `make typecheck`: passes.
- `make test`: passes.
- `make test-golden`: may skip if no golden E2E fixtures exist; record the exact output.

Merge criteria:

- All tasks below are complete.
- `make lint`, `make typecheck`, `make test`, and `make test-golden` pass on the feature branch.
- At least one real or fixture-backed UFLI lesson run produces a quality report showing no blocking skill coverage, ADHD, buddy identity, or print issues.
- RAG is not required for the default MVP path.
- Learning Buddy art in integrated scenes uses the same identity inputs as corner/avatar output.
- `.claude/worksheet-project-context.md` is updated with decisions, test results, and remaining risks before merge.

---

## File map

### Quality gates and validators

- Modify: `validate/skill_parity.py`
  - Tighten skill parity or delegate content coverage to a new validator.
- Create: `validate/content_coverage.py`
  - Deterministic target word, source item, word chain, and objective coverage checks.
- Modify: `validate/adhd_compliance.py`
  - Add profile-aware chunk caps and wire lesson time budget into live validation.
- Modify: `transform.py`
  - Stop hardcoding multi-worksheet `ai_review_passed=True`.
  - Run content coverage, lesson time budget, and multi-worksheet AI review/quality gates.
- Test: `tests/test_content_coverage.py`
- Test: `tests/test_validate.py`
- Test: `tests/test_time_budget.py`
- Test: `tests/test_transform_quality_gates.py`

### Adaptation quality

- Modify: `adapt/engine.py`
  - Respect `rules.max_items_per_chunk` in all `adapt_lesson()` chunk builders.
  - Replace generic fill-blank selection with pattern-aware target grapheme blanking.
  - Soften speed framing in Roll and Read instructions.
- Test: `tests/test_adapt.py`
- Test: `tests/test_rag_adapt.py`

### RAG simplification

- Modify: `transform.py`
  - Make live RAG adaptation explicitly opt-in through a flag or env var.
- Modify: `rag/eval.py`
  - Keep eval tooling working after live-path changes.
- Modify: `README.md`
  - Document RAG as experiment/memory tooling, not lesson understanding.
- Test: `tests/test_transform_rag_context.py`
- Test: `tests/test_rag_eval.py`

### Learning Buddy identity

- Create: `companion/character_identity.py`
  - Resolve canonical character inputs from profile, style sheet, reference pack, equipped items, theme, and identity version.
- Modify: `companion/schema.py`
  - Add optional identity fields without breaking existing profiles.
- Modify: `companion/avatar.py`
  - Use the unified resolver.
- Modify: `companion/generate_overlays.py`
  - Fix generation/judge reference mismatch.
- Modify: `render/asset_gen.py`
  - Pass equipped items, scene guidelines, pose-specific references, and identity version into scene and cover generation.
- Modify: `render/pose_planner.py`
  - Return pose keys that can map to existing reference pack images.
- Modify: `theme/themes/roblox_obby/config.yaml`
  - Move Ian-specific identity text out of theme-level defaults where practical.
- Test: `tests/test_companion.py`
- Test: `tests/test_character_research.py`
- Test: `tests/test_render.py`
- Create: `tests/test_character_identity.py`

### Direct-context worksheet compiler

- Create: `adapt/direct_compiler.py`
  - Feature-flagged planner that receives full lesson context, learner profile, buddy identity, and strict output schema.
- Modify: `adapt/engine.py`
  - Add opt-in route before deterministic fallback.
- Modify: `adapt/schema.py`
  - Add minimal fields needed for richer quality reports only if existing schema cannot carry them.
- Test: `tests/test_direct_compiler.py`
- Test: `tests/test_llm_orchestrator.py`

### Documentation and handoff

- Modify: `README.md`
  - Clarify default MVP path, RAG role, quality gates, and character asset model.
- Modify: `.claude/worksheet-project-context.md`
  - Record decisions, exact verification commands, and known follow-ups.

### Renderer strategy and image-model readiness addendum

- Create: `render/design_spec.py`
  - Compile adapted worksheets into `WorksheetDesignSpec` with exact required text, answer zones, print geometry, learner/theme metadata, and ADHD visual budget.
- Create: `render/strategies.py`
  - Keep `pdf_classic` as the default deterministic ReportLab renderer.
  - Add opt-in `hybrid_shell` for future deterministic-text visual shell experiments.
  - Add opt-in `image_prompt` for offline full-page image-model prompt artifacts.
- Create: `render/benchmark.py`
  - Gate experimental renderer promotion on required text, answer zones, ADHD visual budget, and print-ready output.
- Modify: `transform.py` and `batch.py`
  - Add `--render-mode` while preserving `pdf_classic` defaults.
- Modify: `README.md`, `AGENTS.md`, and `.claude/worksheet-project-context.md`
  - Document renderer modes, prompt-only trials, promotion gates, and handoff decisions.

---

## Task 0: Create the feature branch and verify baseline

**Files:**
- Modify only if needed: `.gitignore`

- [ ] **Step 0.1: Confirm repo state**

Run:

```bash
cd /Users/hjong/Documents/Projects/worksheet-builder
git status --short --branch
git branch --show-current
git rev-parse --show-toplevel
```

Expected:

- Top level is `/Users/hjong/Documents/Projects/worksheet-builder`.
- Branch is `main`.
- Working tree is clean, or only unrelated user changes are present and recorded.

- [ ] **Step 0.2: Create isolated branch**

Run:

```bash
git fetch --prune origin
git switch main
git pull --ff-only origin main
git switch -c feature/worksheet-quality-redesign
```

Expected:

- Branch is `feature/worksheet-quality-redesign`.

- [ ] **Step 0.3: Run baseline checks**

Run:

```bash
make lint
make typecheck
make test
make test-golden
```

Expected:

- All pass, or `make test-golden` skips because no golden E2E tests exist.
- If any fail, stop and decide whether to fix baseline or postpone the branch.

- [ ] **Step 0.4: Commit only branch setup changes if `.gitignore` changed**

Run only if `.gitignore` was modified:

```bash
git add .gitignore
git commit -m "$(cat <<'EOF'
Ignore local worktree directories.

EOF
)"
```

---

## Task 1: Add deterministic content coverage gates

**Files:**
- Create: `validate/content_coverage.py`
- Modify: `validate/skill_parity.py`
- Modify: `transform.py`
- Test: `tests/test_content_coverage.py`
- Test: `tests/test_transform_quality_gates.py`

- [ ] **Step 1.1: Write coverage validator tests**

Create `tests/test_content_coverage.py` with tests for:

- All target words present passes.
- Missing target words fails.
- Missing source sentence fails for UFLI word work when sentence source items exist.
- Word chain coverage checks each chain target word, not only the raw chain string.
- Decodable passage can pass with partial coverage when the task is read-aloud fluency and the passage is present.

Minimum test skeleton:

```python
from __future__ import annotations

from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel, ScaffoldConfig, Step
from skill.schema import LiteracySkillModel, SourceItem
from validate.content_coverage import validate_content_coverage


def _skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read and spell CVCe words"],
        target_words=["grade", "slide", "quite"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="grade, slide, quite", source_region_index=0),
            SourceItem(item_type="word_chain", content="tune -> tone -> cone -> cane", source_region_index=1),
            SourceItem(item_type="sentence", content="The slide is quite tall.", source_region_index=2),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _adapted(contents: list[str]) -> AdaptedActivityModel:
    return AdaptedActivityModel(
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        chunks=[
            ActivityChunk(
                chunk_id=1,
                micro_goal="Practice target words",
                instructions=[Step(number=1, text="Read each word.")],
                worked_example=None,
                items=[
                    ActivityItem(item_id=i + 1, content=text, response_format="write")
                    for i, text in enumerate(contents)
                ],
                response_format="write",
                time_estimate="About 2 minutes",
            )
        ],
        scaffolding=ScaffoldConfig(show_worked_example=True, fade_after_chunk=1, hint_level="full"),
        theme_id="roblox_obby",
        decoration_zones=[],
    )


def test_content_coverage_passes_when_targets_and_sentence_present() -> None:
    result = validate_content_coverage(
        _skill(),
        _adapted(["grade", "slide", "quite", "tune tone cone cane", "The slide is quite tall."]),
    )
    assert result.passed


def test_content_coverage_fails_when_target_words_missing() -> None:
    result = validate_content_coverage(_skill(), _adapted(["grade"]))
    assert not result.passed
    assert any(v.check == "target_word_coverage" for v in result.violations)
```

- [ ] **Step 1.2: Run tests and verify failure**

Run:

```bash
pytest tests/test_content_coverage.py -v
```

Expected:

- Fails because `validate.content_coverage` does not exist.

- [ ] **Step 1.3: Implement `validate/content_coverage.py`**

Implement:

- `_adapted_text(adapted) -> str`
- `_words_from_text(text) -> set[str]`
- `_target_word_coverage(source_skill, adapted_text) -> missing words`
- `_chain_words(source_item.content) -> set[str]`
- `validate_content_coverage(source_skill, adapted, min_target_coverage=0.8) -> ValidationResult`

Rules:

- For `ufli_word_work`, target word coverage below `80%` is an error.
- If fewer than four target words exist, require all target words.
- For word chains, require all chain words that appear as alphabetic tokens.
- For source sentences, require at least one exact or normalized sentence match if the sentence is short enough to be student-facing.
- For decodable passage worksheets, require a read-aloud item containing the passage title or a substantial passage excerpt when passage source items exist.

- [ ] **Step 1.4: Run focused validator tests**

Run:

```bash
pytest tests/test_content_coverage.py -v
```

Expected:

- Passes.

- [ ] **Step 1.5: Wire content coverage into transform validation**

Modify `transform._validate_and_report()` so each worksheet runs:

```python
from validate.content_coverage import validate_content_coverage
```

Add the result to the same validation aggregate used by skill parity, age band, ADHD, and print checks.

Expected behavior:

- Content coverage errors affect `all_validators_passed`.
- Warnings still appear in artifact JSON.

- [ ] **Step 1.6: Add transform quality gate test**

Create `tests/test_transform_quality_gates.py` with a unit-level test that monkeypatches validators or calls `_aggregate_validation_results()` and proves a failed content coverage result makes `all_validators_passed=False`.

- [ ] **Step 1.7: Run focused tests**

Run:

```bash
pytest tests/test_content_coverage.py tests/test_transform_quality_gates.py tests/test_validate.py -v
```

Expected:

- Passes.

- [ ] **Step 1.8: Commit Task 1**

Run:

```bash
git add validate/content_coverage.py validate/skill_parity.py transform.py tests/test_content_coverage.py tests/test_transform_quality_gates.py tests/test_validate.py
git commit -m "$(cat <<'EOF'
Add content coverage quality gates.

EOF
)"
```

---

## Task 2: Make ADHD gates profile-aware and live in the multi-worksheet path

**Files:**
- Modify: `adapt/engine.py`
- Modify: `validate/adhd_compliance.py`
- Modify: `transform.py`
- Test: `tests/test_adapt.py`
- Test: `tests/test_time_budget.py`
- Test: `tests/test_validate.py`

- [ ] **Step 2.1: Add failing adapt lesson chunking tests**

Add tests proving `adapt_lesson()` respects `Accommodations(chunking_level="small")`.

Test behavior:

- Discovery match/write/trace/fill chunks do not exceed `rules.max_items_per_chunk`.
- Builder fill-blank and sight-word chunks do not exceed `rules.max_items_per_chunk`.
- Story chunks do not exceed `rules.max_items_per_chunk` unless a single passage item must remain intact.

- [ ] **Step 2.2: Run adapt tests and verify failure**

Run:

```bash
pytest tests/test_adapt.py -k "chunking or adapt_lesson" -v
```

Expected:

- New tests fail on hardcoded `words[:4]`, `words[:5]`, or similar caps.

- [ ] **Step 2.3: Replace hardcoded chunk caps with `rules.max_items_per_chunk`**

Modify these areas in `adapt/engine.py`:

- `_build_discovery_chunks()`
- `_build_builder_chunks()`
- `_build_roll_and_read_chunk()`
- `_build_story_chunks()`
- LLM translation helper caps in `adapt/llm_adapt.py` if needed for parity.

Use local variables:

```python
max_items = rules.max_items_per_chunk
match_words = words[:max_items]
write_words = words[:max_items]
fill_words = words[:max_items]
```

For match layout, if renderer cannot support more than four items cleanly, use:

```python
match_limit = min(rules.max_items_per_chunk, 4)
```

Document that renderer limit in a comment and test it.

- [ ] **Step 2.4: Make ADHD validator use profile rules**

Change `validate_adhd_compliance()` signature to accept optional profile/rules:

```python
def validate_adhd_compliance(
    adapted: AdaptedActivityModel,
    rules: AccommodationRules | None = None,
) -> ValidationResult:
```

When `rules` is supplied, use `rules.max_items_per_chunk`; otherwise keep the current grade-large fallback for backward compatibility.

- [ ] **Step 2.5: Wire profile-aware ADHD validation in `transform.py`**

Pass `build_rules(profile)` or existing rules into `validate_adhd_compliance()` from `_validate_and_report()`.

- [ ] **Step 2.6: Wire lesson time budget into live multi-worksheet validation**

In `_run_multi_worksheet_pipeline()`, after per-worksheet validations:

```python
from validate.adhd_compliance import validate_lesson_time_budget

time_budget = validate_lesson_time_budget(worksheets)
```

Persist the result in artifacts and aggregate warnings/errors into `validation_results`.

- [ ] **Step 2.7: Soften speed framing**

Change Roll and Read instructions from speed-focused language such as `Try to read them faster each time!` to:

```text
Read each word smoothly.
Try the list three times.
Point to each word as you read.
```

Add a test that no generated instruction contains `faster`.

- [ ] **Step 2.8: Run focused tests**

Run:

```bash
pytest tests/test_adapt.py tests/test_validate.py tests/test_time_budget.py -v
```

Expected:

- Passes.

- [ ] **Step 2.9: Commit Task 2**

Run:

```bash
git add adapt/engine.py adapt/llm_adapt.py validate/adhd_compliance.py transform.py tests/test_adapt.py tests/test_validate.py tests/test_time_budget.py
git commit -m "$(cat <<'EOF'
Make ADHD validation profile-aware.

EOF
)"
```

---

## Task 3: Stop shipping unchecked multi-worksheet outputs

**Files:**
- Modify: `transform.py`
- Modify: `validate/ai_review.py`
- Modify: `adapt/llm_judge.py`
- Test: `tests/test_transform_quality_gates.py`
- Test: `tests/test_llm_orchestrator.py`
- Test: `tests/test_validate.py`

- [ ] **Step 3.1: Add failing test for multi-worksheet AI review**

In `tests/test_transform_quality_gates.py`, assert multi-worksheet validation does not set `ai_review_passed=True` without review evidence.

Use monkeypatching to make `review_adapted_worksheet()` return one failing `ReviewResult`, then assert aggregate `all_validators_passed=False`.

- [ ] **Step 3.2: Run test and verify failure**

Run:

```bash
pytest tests/test_transform_quality_gates.py -v
```

Expected:

- Fails because current multi path hardcodes AI review as passed.

- [ ] **Step 3.3: Run AI review on each multi-worksheet adapted model**

In `_run_multi_worksheet_pipeline()`, before render:

- Write `adapted_model_{i}.json`.
- Run `review_adapted_worksheet(adapted)`.
- Persist `ai_review_{i}.json`.
- Use the reviewed model for theme/render/validate.
- Set `ai_review_passed` from actual review result.

If no API key is available, current `validate/ai_review.py` returns passed. Preserve that behavior but record `"skipped_no_api_key": true` in artifacts if feasible.

- [ ] **Step 3.4: Make pedagogical judge actionable**

Keep the judge as a gate only when it ran. Behavior:

- If judge result exists and `approved=False`, mark `pedagogical_judge_passed=False`.
- Add that value to aggregate validation.
- Do not block when no judge API is available unless strict mode is enabled.

- [ ] **Step 3.5: Re-judge GPT takeover or mark it unverified**

In `adapt/llm_orchestrator.py`, after GPT takeover planning:

- If a separate judge is unavailable, set outcome metadata to `gpt_takeover_unjudged`.
- If a judge is available and can judge GPT output without self-judging, use Gemini as judge; otherwise mark unverified and let `transform.py` treat it as warning or failure based on strictness.

Do not let unjudged takeover look the same as approved output.

- [ ] **Step 3.6: Run focused tests**

Run:

```bash
pytest tests/test_transform_quality_gates.py tests/test_llm_orchestrator.py tests/test_validate.py -v
```

Expected:

- Passes.

- [ ] **Step 3.7: Commit Task 3**

Run:

```bash
git add transform.py validate/ai_review.py adapt/llm_judge.py adapt/llm_orchestrator.py tests/test_transform_quality_gates.py tests/test_llm_orchestrator.py tests/test_validate.py
git commit -m "$(cat <<'EOF'
Gate multi-worksheet quality review.

EOF
)"
```

---

## Task 4: Simplify live RAG and preserve eval tooling

**Files:**
- Modify: `transform.py`
- Modify: `rag/eval.py`
- Modify: `ab_eval.py`
- Modify: `README.md`
- Test: `tests/test_transform_rag_context.py`
- Test: `tests/test_rag_eval.py`
- Test: `tests/test_ab_eval.py`

- [ ] **Step 4.1: Add failing tests for RAG default-off behavior**

In `tests/test_transform_rag_context.py`, assert:

- Live pipeline does not call `retrieve_context()` unless an explicit opt-in is set.
- Existing eval harness can still call retrieval.

Use an env var name:

```text
WORKSHEET_USE_RAG=1
```

- [ ] **Step 4.2: Run tests and verify failure**

Run:

```bash
pytest tests/test_transform_rag_context.py -v
```

Expected:

- Fails because current live path uses RAG whenever `rag_available()` is true.

- [ ] **Step 4.3: Add live RAG gate**

In `transform.py`, replace:

```python
if rag_available():
```

with:

```python
use_live_rag = os.environ.get("WORKSHEET_USE_RAG") == "1"
if use_live_rag and rag_available():
```

Keep writing `rag_context.json`, but record:

```json
{"enabled": false, "reason": "WORKSHEET_USE_RAG not set"}
```

- [ ] **Step 4.4: Remove curriculum RAG from default adaptation semantics**

When `WORKSHEET_USE_RAG` is not set:

- Do not retrieve curriculum references.
- Rely on `skill/extractor.py` direct `lookup_lesson()` enrichment.

When `WORKSHEET_USE_RAG=1`:

- Keep current behavior for experiments.

- [ ] **Step 4.5: Keep `rag/eval.py` and `ab_eval.py` independent**

Ensure eval harnesses call `retrieve_context()` directly and do not depend on `WORKSHEET_USE_RAG`.

- [ ] **Step 4.6: Update README**

Change RAG language:

- Default MVP path uses direct lesson extraction and corpus lookup.
- RAG is optional memory/eval tooling.
- Live RAG requires `WORKSHEET_USE_RAG=1`.

- [ ] **Step 4.7: Run focused tests**

Run:

```bash
pytest tests/test_transform_rag_context.py tests/test_rag_eval.py tests/test_ab_eval.py -v
```

Expected:

- Passes.

- [ ] **Step 4.8: Commit Task 4**

Run:

```bash
git add transform.py rag/eval.py ab_eval.py README.md tests/test_transform_rag_context.py tests/test_rag_eval.py tests/test_ab_eval.py
git commit -m "$(cat <<'EOF'
Make live RAG opt-in.

EOF
)"
```

---

## Task 5: Unify Learning Buddy identity inputs

**Files:**
- Create: `companion/character_identity.py`
- Modify: `companion/schema.py`
- Modify: `companion/avatar.py`
- Modify: `companion/generate_overlays.py`
- Modify: `render/asset_gen.py`
- Modify: `render/pose_planner.py`
- Test: `tests/test_character_identity.py`
- Test: `tests/test_companion.py`
- Test: `tests/test_character_research.py`
- Test: `tests/test_render.py`

- [ ] **Step 5.1: Write character identity resolver tests**

Create `tests/test_character_identity.py` covering:

- Resolver returns `base_character_path` from `profile.avatar.base_character`.
- Resolver loads `reference_image_dir`.
- Resolver chooses pose-specific references such as `pose_pointing.png`.
- Resolver includes equipped items in an `identity_version`.
- Resolver includes `scene_guidelines` from `profile.avatar.style_sheet`.
- Resolver does not fall back to `rainbow_roblox` when `ian_learning_buddy` exists.

- [ ] **Step 5.2: Run tests and verify failure**

Run:

```bash
pytest tests/test_character_identity.py -v
```

Expected:

- Fails because `companion.character_identity` does not exist.

- [ ] **Step 5.3: Implement `companion/character_identity.py`**

Define:

```python
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel

from companion.schema import LearnerProfile
from theme.schema import CharacterSpec


class CharacterIdentity(BaseModel):
    base_character: str
    base_image_path: str | None
    reference_image_dir: str | None
    canonical_reference_path: str | None
    pose_reference_path: str | None
    character_block: str
    scene_guidelines: str
    item_style_notes: str
    equipped_items: dict[str, str]
    identity_version: str


def resolve_character_identity(
    profile: LearnerProfile,
    theme_id: str,
    pose: str | None = None,
    character_spec: CharacterSpec | None = None,
) -> CharacterIdentity:
    ...
```

Identity version must hash:

- `theme_id`
- `base_character`
- `character_block`
- `reference_image_dir`
- sorted `equipped_items`
- pose reference filename when present

- [ ] **Step 5.4: Fix generation/judge reference mismatch**

In `companion/generate_overlays.py`:

- Change `_generate_single_variant()` to accept reference bytes/path from the resolver.
- Stop always reading `_BASE_PATH`.
- Judge and generation must use the same canonical reference source.

- [ ] **Step 5.5: Wire resolver into corner avatar path**

In `companion/avatar.py`:

- Resolve identity once.
- Include `identity_version` in cache key.
- Pass resolver reference into variant generation.

- [ ] **Step 5.6: Wire resolver into integrated scene path**

In `transform.py` / `render/asset_gen.py`:

- Pass profile or resolved identity into `generate_worksheet_assets()`.
- Include equipped items in scene prompts.
- Include `scene_guidelines`.
- Include pose-specific reference bytes when available.
- Include `identity_version` in worksheet asset cache key.

- [ ] **Step 5.7: Fix cover style conflict**

In `render/asset_gen.py`, cover prompt should use:

- `identity.character_block`
- `identity.scene_guidelines`
- `theme_spec.scene_environment`

Remove theme-incompatible terms such as `Pixar-like` from the Roblox path.

- [ ] **Step 5.8: Run focused tests**

Run:

```bash
pytest tests/test_character_identity.py tests/test_companion.py tests/test_character_research.py tests/test_render.py -v
```

Expected:

- Passes.

- [ ] **Step 5.9: Commit Task 5**

Run:

```bash
git add companion/character_identity.py companion/schema.py companion/avatar.py companion/generate_overlays.py render/asset_gen.py render/pose_planner.py tests/test_character_identity.py tests/test_companion.py tests/test_character_research.py tests/test_render.py
git commit -m "$(cat <<'EOF'
Unify Learning Buddy identity inputs.

EOF
)"
```

---

## Task 6: Add scene QA for Learning Buddy consistency

**Files:**
- Modify: `render/asset_gen.py`
- Modify: `companion/generate_overlays.py`
- Test: `tests/test_render.py`
- Test: `tests/test_character_identity.py`

- [ ] **Step 6.1: Add tests for scene judge behavior**

Test:

- Scene generation can call a judge function when API keys exist.
- If judge rejects a scene, generation retries or falls back to approved local pose art.
- If judges are unavailable, canonical local pose fallback is preferred over accepting an unverified identity-changing AI scene.

- [ ] **Step 6.2: Reuse or extract judge helper**

Move shared image judging logic to a helper that both variants and scenes can call.

Suggested file:

```text
companion/character_judge.py
```

Keep public function:

```python
def judge_character_consistency(
    reference_bytes: bytes,
    generated_bytes: bytes,
    criteria: list[str],
) -> CharacterJudgeResult:
    ...
```

- [ ] **Step 6.3: Add scene fallback policy**

In `render/asset_gen.py`:

- If scene judge rejects all attempts, use local pose fallback.
- Do not cache failed AI scene as approved.
- Write rejection diagnostics under the existing asset cache directory.

- [ ] **Step 6.4: Run focused tests**

Run:

```bash
pytest tests/test_render.py tests/test_character_identity.py -v
```

Expected:

- Passes.

- [ ] **Step 6.5: Commit Task 6**

Run:

```bash
git add companion/character_judge.py companion/generate_overlays.py render/asset_gen.py tests/test_render.py tests/test_character_identity.py
git commit -m "$(cat <<'EOF'
Add Learning Buddy scene QA.

EOF
)"
```

---

## Task 7: Add direct-context worksheet compiler behind a flag

**Files:**
- Create: `adapt/direct_compiler.py`
- Modify: `adapt/engine.py`
- Modify: `transform.py`
- Test: `tests/test_direct_compiler.py`
- Test: `tests/test_adapt.py`

- [ ] **Step 7.1: Write direct compiler tests**

Create `tests/test_direct_compiler.py`.

Test:

- Prompt/context builder includes full `skill.source_items`, not only target word summary.
- Learner profile name, grade, accommodations, preferences, and avatar identity summary are included.
- Output parser rejects plans that drop required target words.
- Feature flag disabled means existing deterministic path is unchanged.

Use env var:

```text
WORKSHEET_DIRECT_COMPILER=1
```

- [ ] **Step 7.2: Run tests and verify failure**

Run:

```bash
pytest tests/test_direct_compiler.py -v
```

Expected:

- Fails because `adapt.direct_compiler` does not exist.

- [ ] **Step 7.3: Implement direct compiler skeleton**

Create:

```python
def build_direct_context_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    character_identity: CharacterIdentity | None,
    theme_id: str,
) -> str:
    ...


def compile_lesson_direct(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    character_identity: CharacterIdentity | None = None,
) -> list[AdaptedActivityModel] | None:
    ...
```

Constraints:

- No live API call in tests.
- Parser must validate with Pydantic.
- Output must pass `validate_content_coverage()` before returning.
- On any failure, return `None` so deterministic path remains stable.

- [ ] **Step 7.4: Wire into `adapt_lesson()` behind feature flag**

In `adapt/engine.py`, before LLM orchestrator:

```python
if os.environ.get("WORKSHEET_DIRECT_COMPILER") == "1":
    direct = compile_lesson_direct(...)
    if direct:
        return direct
```

Keep deterministic fallback unchanged.

- [ ] **Step 7.5: Run focused tests**

Run:

```bash
pytest tests/test_direct_compiler.py tests/test_adapt.py -v
```

Expected:

- Passes.

- [ ] **Step 7.6: Commit Task 7**

Run:

```bash
git add adapt/direct_compiler.py adapt/engine.py transform.py tests/test_direct_compiler.py tests/test_adapt.py
git commit -m "$(cat <<'EOF'
Add direct-context worksheet compiler flag.

EOF
)"
```

---

## Task 8: Add a fixture-backed quality eval harness

**Files:**
- Create: `tests/fixtures/quality_cases/lesson_cvce_case.json`
- Create: `validate/quality_report.py`
- Create: `tests/test_quality_report.py`
- Modify: `README.md`

- [ ] **Step 8.1: Create a small quality case fixture**

Create `tests/fixtures/quality_cases/lesson_cvce_case.json`:

```json
{
  "case_id": "lesson_cvce_case",
  "profile": "profiles/ian.yaml",
  "theme_id": "roblox_obby",
  "expected": {
    "domain": "phonics",
    "specific_skill": "cvce_pattern",
    "target_words": ["grade", "slide", "quite"],
    "must_include_activity_types": ["word_chain", "write", "read_aloud"],
    "max_items_per_chunk_small": 3,
    "buddy_required": true
  }
}
```

- [ ] **Step 8.2: Implement quality report**

Create `validate/quality_report.py` with:

```python
class WorksheetQualityReport(BaseModel):
    case_id: str
    content_coverage_passed: bool
    adhd_passed: bool
    skill_parity_passed: bool
    buddy_identity_checked: bool
    print_quality_passed: bool
    blocking_issues: list[str]
```

Add a pure function that combines existing validation results and content coverage into a single report.

- [ ] **Step 8.3: Add report tests**

Create `tests/test_quality_report.py` proving:

- Any failed content coverage result produces a blocking issue.
- Missing buddy identity check produces a blocking issue when expected.
- All pass produces zero blocking issues.

- [ ] **Step 8.4: Run focused tests**

Run:

```bash
pytest tests/test_quality_report.py tests/test_content_coverage.py -v
```

Expected:

- Passes.

- [ ] **Step 8.5: Document quality gate command**

Update `README.md` with a short section:

```bash
make lint
make typecheck
make test
make test-golden
```

Add the required quality conditions for merge.

- [ ] **Step 8.6: Commit Task 8**

Run:

```bash
git add validate/quality_report.py tests/test_quality_report.py tests/fixtures/quality_cases/lesson_cvce_case.json README.md
git commit -m "$(cat <<'EOF'
Add worksheet quality report harness.

EOF
)"
```

---

## Task 9: Full verification and handoff update

**Files:**
- Modify: `.claude/worksheet-project-context.md`

- [ ] **Step 9.1: Run full verification**

Run:

```bash
make lint
make typecheck
make test
make test-golden
```

Expected:

- All pass.
- Record exact test counts and any skipped golden tests.

- [ ] **Step 9.2: Run one no-network smoke transform**

Use fixture/sample input available in the branch. If no real corpus input exists, run the closest smoke test command already supported by tests and record that no checked-in `data/ufli/raw/75` exists.

Preferred when a sample image is available:

```bash
WORKSHEET_SKIP_ASSET_GEN=1 python transform.py \
  --input samples/input/IMG_0004.JPG \
  --profile profiles/ian.yaml \
  --theme roblox_obby \
  --output output/quality_redesign_smoke
```

Expected:

- Pipeline completes or fails with a known missing-input/API reason.
- Artifacts include content coverage, ADHD validation, AI review status, and RAG disabled reason.

- [ ] **Step 9.3: Update running context**

Append to `.claude/worksheet-project-context.md`:

- Branch name.
- What changed.
- Quality gate decisions.
- Verification commands and outputs.
- Known risks.
- Next steps before merge.

- [ ] **Step 9.4: Commit handoff**

Run:

```bash
git add .claude/worksheet-project-context.md
git commit -m "$(cat <<'EOF'
Update quality redesign handoff.

EOF
)"
```

- [ ] **Step 9.5: Final branch status**

Run:

```bash
git status --short --branch
git log --oneline --decorate -10
```

Expected:

- Working tree clean.
- Branch is ahead of `origin/main` by the task commits.

---

## Implementation order and checkpoints

Checkpoint 1: Quality gates

- Complete Tasks 1-3.
- Run:

```bash
pytest tests/test_content_coverage.py tests/test_transform_quality_gates.py tests/test_validate.py tests/test_time_budget.py -v
```

Checkpoint 2: RAG and buddy identity

- Complete Tasks 4-6.
- Run:

```bash
pytest tests/test_transform_rag_context.py tests/test_character_identity.py tests/test_companion.py tests/test_render.py -v
```

Checkpoint 3: Direct compiler and reporting

- Complete Tasks 7-8.
- Run:

```bash
pytest tests/test_direct_compiler.py tests/test_quality_report.py tests/test_adapt.py -v
```

Final checkpoint:

```bash
make lint
make typecheck
make test
make test-golden
```

---

## Risks and controls

- Risk: Direct compiler introduces nondeterministic output.
  - Control: Feature flag default off, Pydantic parsing, content coverage gate, deterministic fallback.

- Risk: Tight coverage gates reject valid high-adaptation worksheets.
  - Control: Start strict for UFLI word work only; allow lower thresholds for decodable passage fluency with explicit source item rules.

- Risk: Buddy identity changes invalidate cached assets unexpectedly.
  - Control: Add `identity_version` to cache keys and preserve old cache files.

- Risk: RAG simplification breaks experiments.
  - Control: Keep `rag/eval.py` and `ab_eval.py` direct retrieval paths independent from `WORKSHEET_USE_RAG`.

- Risk: Existing tests assume warning-only validators.
  - Control: Adjust aggregate validation only where errors should block; leave warnings non-blocking unless strict mode is enabled.

---

## Self-review

- Spec coverage: The plan covers branch isolation, quality gates, RAG simplification, buddy identity, ADHD validation, direct-context generation, testing, and merge criteria.
- Placeholder scan: No task depends on an undefined “later” step. Each task has concrete files, commands, and expected results.
- Type consistency: New modules are named consistently: `validate.content_coverage`, `validate.quality_report`, `companion.character_identity`, and `adapt.direct_compiler`.
