# Profile-Driven Visual Intensity, Lesson-Number Entry Point, Hybrid Renderer

Approved 2026-07-07. Executed as two /goal runs: **Goal 1 = Phases 0+A+B**, **Goal 2 = Phases C+D+E+F** (submit Goal 2 only after Goal 1's UAT passes).

## Context

The owner is dissatisfied with worksheet quality. Root cause: the codebase hard-enforces "calm/minimal" ADHD design (≤2 decorations, ≤4 colors) while the owner's validated gold standard (`samples/output/*.png` — busy Roblox-quest style pages his son reliably completes) violates those caps. The fix: keep structural ADHD rules universal (chunking, worked examples, micro-goals, predictable rewards, no leaderboards/loot/streaks), but make **decoration/visual intensity a per-student profile dial**. Additionally: the MVP ask — "make me a worksheet from UFLI lesson 74" — has **no entry point today** (pipeline is photo-driven only), and phonics text accuracy demands a **hybrid renderer** (vector text + themed art) rather than full-page AI images.

**Environment facts:** the goals run locally on the owner's machine, where `.env` (API keys) and the real `data/ufli/normalized.jsonl` corpus exist. `transform.py` and `batch.py` already call `load_dotenv()` at startup — the new lesson CLI inherits it, and `tools/uat_compare.py` must also call `load_dotenv()` and must NOT force `WORKSHEET_SKIP_ASSET_GEN=1` (UAT PDFs should exercise the full AI planner + art path, degrading gracefully offline). Tests and CI stay offline-deterministic regardless: every test sets `WORKSHEET_SKIP_ASSET_GEN=1` itself and monkeypatches LLM calls. `data/ufli/normalized.jsonl` and `profiles/ian.yaml` are gitignored → commit a small original fixture corpus so tests/CI and fresh clones work; the real corpus wins via loading precedence.

## Phases (each ends with `make lint && make typecheck && make test` green + a commit)

### Phase 0 — Branch setup (S) [Goal 1]
Worktree on new branch `feature/intensity-dial-lesson-entry` from `claude/review-recent-refactoring-rma786`; `git merge origin/refactor/separate-experiments` (verified clean fast-forward — the session branch sits at the fork point; 687 tests green on that base). Venv + full gate baseline. Known pre-existing: 3 mypy mutagen errors under `experiments/` (also on main) — ignore if they surface.

### Phase A — Profile-driven intensity dial (M) [Goal 1]
- `companion/schema.py` `Preferences`: add `visual_intensity: str | None = None` (validator: None|"low"|"medium"|"high"). `None` = exact legacy behavior everywhere.
- `adapt/rules.py`: add `IntensityVisuals` model + `INTENSITY_VISUALS` table — low: 1 decoration/3 colors/0.75 art scale/chrome "none"; **medium: 2/4/1.0/"basic" (bit-identical to today's hardcodes)**; high: 6/6/1.3/"full". `AccommodationRules` gains `visual_intensity: str = "medium"`; `build_rules()` derives both from the profile (replaces hardcoded `max_decorative_elements=2` at adapt/rules.py:141). Already threaded everywhere — no new plumbing.
- `validate/adhd_compliance.py` Check 4 (lines 101-109): `limit = rules.max_decorative_elements if rules else 2` (mirrors the Check 1/13 rules-branch pattern).
- `render/design_spec.py`: widen `VisualBudget` field validators to outer bounds (0-8 decorations, 1-6 colors) + `model_validator` enforcing per-intensity caps from `INTENSITY_VISUALS`. `compile_worksheet_design_spec` (line 146): new `_resolve_visual_budget(theme, profile)` — dial unset → legacy (theme `max_per_page`, 4 colors, `_intensity_for_style`); dial set → table values.
- `render/benchmark.py:43-46`: gate compares against the table, not hardcoded 2/4.
- Tests: new — `build_rules` high→6 / low→1; validator honors high rules (copy `test_chunk_size_uses_supplied_small_profile_rules` pattern at tests/test_validate.py:232); design-spec compile with high profile → 6/6/high; profile YAML round-trip. Existing tests at tests/test_worksheet_design_spec.py:95-96,108, tests/test_validate.py:255, tests/test_adapt.py:219 must pass UNCHANGED (backward-compat proof).

### Phase B — `--lesson N` entry point + fixture corpus (M) [Goal 1]
- `transform.py` CLI: `--input` becomes optional; new `--lesson` (int); UsageError unless exactly one given. Usage: `python transform.py --lesson 74 --profile profiles/ian.yaml --theme roblox_obby --output ./output/`.
- New `skill/lesson_loader.py`: `skill_model_from_lesson(n)` → `LiteracySkillModel` from `corpus.ufli.lookup.lookup_lesson(n)`; source_items mirror what `_enrich_from_corpus` (skill/extractor.py:395) injects (roll_and_read, word_list, passage, sentences); promote needed private extractor helpers to public names (keep aliases); `template_type="ufli_word_work"`, `extraction_confidence=1.0`, grade via `_grade_from_lesson(n)`.
- `transform.py`: factor post-extraction pipeline into `_run_from_skill_model(...)`; add `run_lesson_pipeline_collect_artifacts(...)` skipping capture/OCR. Idempotency: `source_image_hash = sha256(f"ufli_lesson:{n}")[:16]` feeding the existing content-hash (transform.py:427).
- Fixture corpus at `corpus/ufli/fixtures/normalized_fixture.jsonl`: 4 hand-authored ORIGINAL lessons (31 "sh", 49 a_e, **74 "ay"**, 90 "oa/ow") — never copy UFLI copyrighted text; size lesson 74 under grade-2 section caps (≤8 roll-and-read words, 1 short decodable passage, ≤4 sentences). `corpus/ufli/lookup.py`: fall back to fixture when `data/ufli/normalized.jsonl` absent (real file always wins); cache keyed by resolved path + `reset_lookup_cache()`.
- Tests: lesson_loader from fixture 74; fixture fallback/precedence/cache reset; offline lesson-mode transform (stable `lesson_<hash>.pdf` across runs); CLI arg validation via CliRunner. Audit full suite for tests that assumed "no corpus" (skill/extractor concept cache) — fix by pointing their `data_dir` at an empty tmp dir.

### Phase C — Hybrid renderer (L — highest risk) [Goal 2]
- Fix the dead end: transform.py:415,635 currently DISCARD `apply_theme()`'s returned `ThemedModel` — keep it, pass `decoration_placements` via new optional `RenderContext` field (render/strategies.py:29). `theme/engine._plan_decorations`: add `max_elements` override + cycle assets. `adapt/engine._define_decoration_zones` (engine.py:1967): accept rules — medium/None → current 2 corner zones (unchanged output, hashes stable), high → 6 margin-safe non-overlapping normalized zones, low → 1.
- New `render/hybrid.py` `render_hybrid_worksheet(...)`: REUSE render/pdf.py primitives (`_register_fonts`, `_draw_chunk`, `_draw_chunk_with_scene`, item widgets, estimators) — never reimplement phonics-accurate text widgets. Draw order: (1) background + high-only double-stroke "pixel" border just inside 54pt margins (stroke-only); (2) game chrome band when `INTENSITY_VISUALS[intensity].game_chrome != "none"` — quest banner (Fredoka title), segmented progress bar (`worksheet_count` segments, filled below `worksheet_number`, "Part n of m"), "LEVEL {chunk_id}" micro-goal badges (extract pill at render/pdf.py:553-564 into `_draw_micro_goal_pill(..., chrome_label: str | None)`; classic passes None → byte-identical classic output); (3) chunk loop identical to classic incl. AI scenes when `asset_manifest` present; (4) decorations LAST with content-overlap guard — normalized top-down → PDF points (`y_pdf = PAGE_HEIGHT*(1-y_norm)`), scale by `art_scale`, skip zones intersecting tracked content rects (complements `validate/print_checks._check_text_image_overlap`).
- Asset degradation chain: curated PNG via `resolve_decoration` → deterministic ReportLab vector motifs keyed by theme (coin/platform/star) → none. Zero-asset env still gets themed output.
- Invariants at every intensity: white/near-white behind all text and answer areas, WCAG AA, 54pt margins, chunk structure, worked examples, NO leaderboards/streaks/loot ever.
- Wire `HybridShellRenderer.render` (render/strategies.py:72-87, currently a stub). Keep `image_gen` default; keep hybrid `experimental=True`.
- Tests (`tests/test_hybrid_renderer.py`, offline): coord conversion; chrome present at high / absent at low (fitz text extraction); decoration image count ≤ budget; zero-asset render OK; `validate_print_quality` passes with zero overlap violations at high; `required_text` extractable.

### Phase D — roblox_obby assets (S) [Goal 2]
Committed `tools/generate_obby_assets.py` (Pillow) draws 6 transparent 256×256 PNGs (coin, platform, checkpoint, star, jump_pad, flag) per the theme's `character_spec.scene_elements`, flat bold-outline style, theme palette; run once, commit outputs to `assets/themes/roblox_obby/`; update theme config `assets:` list but **KEEP `max_per_page: 2`** (the legacy no-dial path reads it; raising it would break `VisualBudget` compile for dial-less profiles — the dial, not the theme, unlocks >2). Tests: `resolve_decoration` finds all 6, RGBA, ≥64px.

### Phase E — Gold set, UAT harness, golden e2e (M) [Goal 2]
- `docs/gold-standard.md`: declare `samples/output/*.png` as the gold set; target attributes (pixel borders, level chrome, progress bar, dense themed art) vs untradeable structural rules; note the samples' AI-text garbling and doll/roll rhyme error as anti-goals for text accuracy.
- UAT profiles in `samples/profiles/` (`profiles/` is gitignored): `uat_grade1_low.yaml`, `uat_grade1_high.yaml` (grade "1", `favorite_themes: [roblox_obby]`, `visual_style: pixel_art`, generic child name, low/high dial). Owner later adds `visual_intensity: high` under `preferences:` in local `profiles/ian.yaml`.
- `tools/uat_compare.py` + `make uat`: lesson 74 through the 2×2 matrix (pdf_classic|hybrid_shell × low|high) → `output/uat/<cell>/lesson_*.pdf` + `output/uat/index.md` summary. Calls `load_dotenv()` (same try/except pattern as transform.py:19-21); never sets `WORKSHEET_SKIP_ASSET_GEN` itself — full-AI locally, deterministic offline.
- Golden e2e in the currently-empty `tests/test_e2e.py` (offline: set `WORKSHEET_SKIP_ASSET_GEN=1` inside the test): lesson 74 high-intensity, both renderers — stable hash across runs, print + ADHD validation pass, fixture words extractable from the text layer, hybrid decoration count ≤ 6. Add `make test-golden` to `.github/workflows/ci.yml`.

### Phase F — Docs + handoff (S) [Goal 2]
Update `.agents/skills/adhd-design/SKILL.md` (decoration budget = profile dial per `INTENSITY_VISUALS`; structural rules + ABSOLUTE ANTI-PATTERNS are intensity-independent), `AGENTS.md` (ADHD-safe constraint wording, `--lesson` + `hybrid_shell` examples, fixture fallback), `.claude/worksheet-project-context.md` (session handoff: what shipped, `max_per_page` gotcha, fixture precedence, next steps).

### Finish (each goal)
Merge the worktree branch back to `claude/review-recent-refactoring-rma786` only after ALL gates green (Goal 2 additionally `make test-golden` + `make uat`), `git push -u origin claude/review-recent-refactoring-rma786` (retry with backoff on network errors), remove the worktree. No PR unless asked.

## Top risks + mitigations
1. **VisualBudget validator ripple** into image_prompt_builder/benchmark/strategies/image_gen tests → medium == today's values; every existing construction (≤2/≤4) stays valid; run those 5 test files right after Phase A.
2. **mypy strict** on new code (Pillow/fitz/click) → copy existing typed idioms (asset_gen `Any` draw handles, strategies `cast`); run `mypy .` per module.
3. **Sparse decoration_zones from LLM planner paths** → hybrid falls back to `_define_decoration_zones(rules)` when empty; overlap guard skips conflicts.
4. **Fixture corpus changes "no corpus" assumptions** in extractor concept-cache tests → path-keyed cache + reset hook; full-suite audit right after Phase B.
5. **Golden brittleness from section_cap splits** → fixture sized under caps; golden asserts stability + ranges, not exact counts.

## Verification (UAT)
- **UAT #1 (after Goal 1):** gates green; `python transform.py --lesson 74 --profile profiles/ian.yaml --theme roblox_obby --output ./output/` produces a lesson PDF from the real local corpus with the AI planner; low- vs high-dial profiles change validation budgets; dial-off profiles behave identically to today.
- **UAT #2 (after Goal 2):** gates + `make test-golden` green; `make uat` 2×2 matrix — compare `hybrid_shell × high` against the gold set, `pdf_classic × low` as the regression anchor.

## Model recommendation
Goal 1: Opus 4.8 is sufficient. Goal 2: Fable 5 (renderer layout math + visual judgment); Opus 4.8 fallback.
