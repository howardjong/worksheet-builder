# Worksheet Builder — Running Context

> This is the running context document for session-to-session handoffs and multi-agent coordination.
> **Read this first** when starting a new session or picking up work.
> **Update this** at the end of every session with current state, decisions, and next steps.

---

## Current State

**Status:** Core product milestones remain complete. Gemini Embedding 2 RAG Phase 7 is implemented and the curriculum-aware adaptation follow-up is now wired through `adapt/engine.py`. UFLI corpus pipeline is fully executed: crawl complete (148 lessons), acquire complete (539 files), extract complete (148 normalized), index complete (148 curriculum records in `vector_store/`). UFLI multimodal corpus audit is now implemented too: `corpus/ufli/ingest.py` has a new offline `audit` subcommand, `corpus/ufli/audit.py` + `corpus/ufli/audit_schema.py` produce timestamped Markdown/JSON/CSV reports, optional companion manifests (`data/ufli/companion/images.jsonl`, `data/ufli/companion/audio.jsonl`) are audited without requiring companion indexes, and missing companion retrieval sections are marked `skipped`. UFLI audio companion Stage 0 and Stage 1 are now implemented in a pilot-first shape: `corpus/ufli/audio_companion.py` + `corpus/ufli/audio_companion_schema.py` now build voice-neutral lesson bundles, enforce numeric lessons `1-128`, enforce Stage 1 live generation/indexing to pilot lessons `1`, `14`, and `95`, load committed companion configs from `data/ufli/companion/pronunciation_lexicon.yaml`, `voice_profiles.yaml`, and `pilot_lessons.yaml`, use the refined clip taxonomy (`lesson_instruction`, `phoneme_model`, `word_model`, `passage_sentence`, `passage_full`, `review`), keep `encouragement` out of indexed lesson clips, support `dorothy` and `neutral_na_pilot` voice profiles, default offline generation to dry-run, and emit timestamped review packets under `data/ufli/companion/pilots/<timestamp>/`. Pilot-remediation hardening is now implemented in the source/build path too: `corpus/ufli/audio_companion_schema.py` now defines `BundleValidationIssue`/`BundleValidationReport` plus explicit pronunciation anchor fields, validates ElevenLabs voice settings against provider limits (including `speed` between `0.7` and `1.2`), `corpus/ufli/audio_companion.py` now sanitizes `word_targets` from student-facing lists only, denies teacher-metadata targets, rewrites instruction/review prompts to decoding-first process prompts, resolves phoneme exemplars from exact lexicon anchors instead of loose first-match fallbacks, applies pause-shaped `tts_text` separately from clean `transcript_text` for instruction/review/passage clips, wires lexicon `modeling_tts_text` into phoneme modeling, persists a typed `generation_log.json`, and validates bundles both during `build-audio` and in the new `validate-audio` CLI before any TTS generation. `data/ufli/companion/pronunciation_lexicon.yaml` now carries exact anchor words for `a`, `c`, `oi`, and `oy`; the short-`a` modeling override has been updated from `the a in cat` to `the short a sound`, which the canary and the later full rerun both showed is materially better for Dorothy. `corpus/ufli/audio_companion.py` also now uses a safer `clause_pause_only` path for `passage_full` clips, no longer recursively rewrites its own inserted ellipses, uses safer review wording for the hard `/k/` case (`Focus on c in cat.` instead of relying on raw phoneme notation in review text), and adds a true mid-sentence pause to long passage-sentence clips when punctuation alone is not enough. A narrower follow-up landed on 2026-03-16 to make this pause shaping more generalizable without broad retuning: `_clause_pause_only_tts()` now uses a temporary pause marker so comma and quote handling no longer duplicates its own inserted ellipses, and quoted dialogue such as `“This kitten is cute,” said Boyd.` now becomes `“This kitten is cute,” ... said Boyd. ...` instead of splitting the clause mid-phrase. This looks like a safe source-side fix rather than pilot-only tuning because it corrects malformed TTS input generation for ordinary commas and quote-adjacent clause breaks. These changes matter beyond the pilot because they live at the source-build stage and reduce bad generation inputs before TTS cost is incurred, but the exact passage pacing heuristics are still partly pilot/provider-tuned and should not yet be treated as globally validated defaults. `data/ufli/companion/voice_profiles.yaml` still slows Dorothy’s `lesson_instruction`, `review`, `phoneme_model`, `passage_sentence`, and `passage_full` clip families to the lowest practical provider-supported settings, with `phoneme_model.speed` corrected to the slowest valid ElevenLabs value (`0.7`) after a live provider rejection at `0.58`. `corpus/ufli/ingest.py` now exposes pilot-aware `build-audio`, `validate-audio`, `generate-audio`, `index-audio`, `judge-audio`, and `diagnose-audio` flags for lesson-set selection, voice-profile selection, dry-run estimation, review-packet generation, Stage-1-only clip indexing, transcript/script LLM judging, and controlled canary probes. `corpus/ufli/audio_judge.py` now runs a `gemini-3-flash-preview` judge over generated clips and writes timestamped `judge_summary.json`, `judge_results.csv`, and `judge_report.md` artifacts under `data/ufli/companion/evals/<timestamp>/`. The judge is no longer transcript-only: it now reads the actual generated audio file, asks Gemini for a best-effort heard transcript, scores audio clarity from the real clip, measures actual clip duration from the MP3/WAV, computes actual WPM, scores pacing suitability/consistency against conservative child-directed clip-family bands, and now also scores model-based acoustic pronunciation accuracy for the actual spoken phoneme/grapheme/word targets. It also now reports family-level pacing summaries, explicit pilot gate failures, required manual-review segments, and relaxes WPM false positives for single-word `word_model` clips and one-word `passage_sentence` interjections without widening the fast-clip guardrails for instructional families. Those pace bands are an inference, not a hard clinical standard: they were set conservatively below the `150 WPM` TTS rate reported in older-student reading-difficulty studies and informed by synthetic-speech intelligibility literature showing slower rate and simpler prosody can improve intelligibility, plus child-listener findings that synthetic speech is less intelligible than live speech and benefits from context. The earlier full live Dorothy judge run on 2026-03-16 wrote `data/ufli/companion/evals/20260316_121249`: `57` clips judged across lessons `1`, `14`, and `95`, with `47 use`, `3 revise`, `7 block`, and `9` blocker-marked clips. After the audio-based clarity/pacing update, a live three-clip sample run at `data/ufli/companion/evals/20260316_122938` confirmed that the judge could now catch timing problems from the actual Dorothy MP3 files: `lesson_001_phoneme_01_a` was clear but too fast for a phoneme-model clip (`100.6 WPM` vs target band `35-75 WPM`), while `lesson_001_word_cat` remained clear and appropriately paced (`71.9 WPM`). After the acoustic-pronunciation upgrade, the new full live rerun at `data/ufli/companion/evals/20260316_124158` became much stricter: `57` clips judged, `10 use`, `40 revise`, `7 block`, and `31` blocker-marked clips. The first remediation rerun was `data/ufli/companion/evals/20260316_145837`, generated from fresh Dorothy audio rebuilt with `build-audio` + `validate-audio` clean and a review packet at `data/ufli/companion/pilots/20260316_144854`: `53` clips judged, `23 use`, `30 revise`, `0 block`, `12 blocker-marked clips`, and `pilot_ready=False`. The second remediation rerun at `data/ufli/companion/evals/20260316_152838`, generated from fresh Dorothy audio rebuilt with the first pause-shaped TTS pass and a review packet at `data/ufli/companion/pilots/20260316_151233`, reached `53` clips judged, `30 use`, `21 revise`, `2 block`, `8 blocker-marked clips`, and `pilot_ready=False`. The first full rerun after the short-`a` source change but before the punctuation-recursion bug fix was `data/ufli/companion/evals/20260316_160656`: blockers improved slightly from `8` to `7`, but the intended `passage_full` improvement did not show up because the malformed pause script still reached generation, and the run remained `pilot_ready=False`. A controlled root-cause probe harness is now implemented in `corpus/ufli/audio_diagnostics.py` and exercised through `python -m corpus.ufli.ingest diagnose-audio`. The first full canary run at `data/ufli/companion/diagnostics/20260316_154844` showed the remaining issues were mixed rather than purely provider-caused: `lesson_001_phoneme_01_a` was a pipeline-input problem, `lesson_095_passage_full` was a pipeline-input problem, `lesson_014_review` was unstable, and `lesson_014_passage_sentence_03` still failed across all tested text/model variants, which remains the strongest current evidence of a real Dorothy/ElevenLabs limitation under the exact-text constraint. After the short-`a` and passage-full source fixes landed, a follow-up canary at `data/ufli/companion/diagnostics/20260316_161215` (see `probe_report_corrected.md`) showed that `lesson_001_phoneme_01_a` is now clean on both ElevenLabs models (`use` at `61.8 WPM` on `eleven_multilingual_v2`, `use` at `50.6 WPM` on `eleven_flash_v2_5`), and `lesson_095_passage_full` is now clean on Dorothy’s preferred `eleven_multilingual_v2` path (`use` at `124.7 WPM` with no added fillers). After the review-wording and sentence-pause source fixes landed, a narrower canary at `data/ufli/companion/diagnostics/20260316_174257` showed that `lesson_014_review` is now fixed on both ElevenLabs models (`use` at `97.1 WPM` on `eleven_multilingual_v2`, `use` at `78.8 WPM` on `eleven_flash_v2_5`), while `lesson_014_passage_sentence_03` improved substantially (`178.6` -> `135.1 WPM`) but still remained outside the target band, which further strengthens the view that the remaining passage-sentence issue is largely a Dorothy/ElevenLabs limitation rather than a bad pipeline input. The latest full official rerun is now `data/ufli/companion/evals/20260316_175300`, generated from fresh Dorothy audio with the review-wording and sentence-pause fixes plus a review packet at `data/ufli/companion/pilots/20260316_174419`: `53` clips judged, `35 use`, `18 revise`, `0 block`, `0 blocker-marked clips`, and `pilot_ready=False`. This is the first run with zero blocker-marked clips. It also confirms that the remaining failures are almost entirely pacing-band misses rather than instructional-content defects: `review` family blockers dropped from `1` to `0`, `passage_sentence` blockers dropped from `5` to `0`, `passage_full` blockers dropped from `1` to `0`, but the pilot gate still fails because too many required instructional passage clips remain `revise`, and `passage_sentence`/`passage_full` family medians are still below the pilot-ready threshold. A focused live follow-up canary after the punctuation cleanup now lives at `data/ufli/companion/diagnostics/20260316_181439`. It probed the four Lesson 95 passage sentences most directly affected by malformed comma/quote shaping (`lesson_095_passage_sentence_01`, `_06`, `_08`, `_16`). All four now judged `use` on Dorothy’s preferred `eleven_multilingual_v2` current-pipeline path, and the diagnostics labeled the cleaned current pipeline as the preferred controlled variant for each clip. The direct gain is that these particular pacing/supportiveness misses should no longer be treated as active pipeline defects; the remaining higher-risk passage failures still concentrate in other segments, especially Lesson 14 sentence/full passage pacing. A Google TTS canary path is now implemented only inside the diagnostics harness, not the main generation flow. `corpus/ufli/audio_diagnostics.py` can now run `diagnose-audio` with `--provider-scope google|both`, use official Cloud Text-to-Speech ADC auth via `google.auth`, hit a supported Chirp 3 endpoint, translate the current pause-shaped pipeline text into provider-appropriate Google markup (`[pause]` / `[pause long]`), and judge the result with the existing Gemini audio judge. `corpus/ufli/audio_companion_schema.py` now adds diagnostics-only `GoogleCloudTtsSettings` plus provider/input-format fields on `AudioProbeVariant`; the main `VoiceProfile` and `generate-audio` path remain ElevenLabs-specific on purpose. Context7 on the Google Gen AI SDK confirmed the current Vertex env-variable pattern (`GOOGLE_GENAI_USE_VERTEXAI`, project, location), but the concrete official Chirp 3 / Leda synthesis path was clearer in Google’s Cloud Text-to-Speech docs than in the Gen AI SDK docs: `en-US-Chirp3-HD-Leda` is a supported voice, current docs describe Chirp 3 pace/pause controls via `speaking_rate` and `markup`, and the regional endpoint docs indicate Chirp 3 should use `global`, `us`, `eu`, `asia-southeast1`, `europe-west2`, or `asia-northeast1` rather than `us-central1`. A small live Google-only canary was run at `data/ufli/companion/diagnostics/20260316_203756` against four hard passage clips (`lesson_014_passage_sentence_03`, `lesson_014_passage_full`, `lesson_095_passage_sentence_02`, `lesson_095_passage_sentence_11`) using `GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/adc-personal.json`, project `ws-builder-rag`, `GOOGLE_CLOUD_LOCATION=us-central1`, `GOOGLE_TTS_LOCATION=us`, `SSL_CERT_FILE` pointed at the venv `certifi` bundle, and `en-US-Chirp3-HD-Leda`. The result was mixed but informative: the provider-appropriate current-pipeline Google markup variant beat raw exact transcript text for all four clips, which supports preserving the recent source-side pause-shaping gains, but only `lesson_014_passage_full` reached `use` (`111.5 WPM`, versus Dorothy baseline `166.3 WPM` on the official full rerun). The tested Google passage sentences remained `revise` and were generally as fast or faster than Dorothy (`lesson_014_passage_sentence_03` `147.1` vs Dorothy `143.6`, `lesson_095_passage_sentence_02` `182.0` vs Dorothy `139.4`, `lesson_095_passage_sentence_11` `143.2` vs Dorothy `138.9`). This suggests the remaining sentence-family failures are still more likely provider/voice pacing limits than active pipeline bugs, while full-passage pacing may benefit from provider-specific pause controls. One caveat from the live logs: even with `personal-on` and Vertex env vars set, the judge path still initialized its RAG client on the existing API-key backend rather than the repo’s Vertex backend, although the judge requests themselves still went to `aiplatform.googleapis.com`; this did not affect the Google TTS synthesis evidence but is worth keeping in mind if the repo later standardizes all live calls on Vertex. The numeric lesson scope for companion audio remains explicitly corrected to lessons `1-128` rather than `1-34`, while alpha lessons remain excluded from this path. RAG client now supports API-key or Vertex backends plus embedding-model fallback (`gemini-embedding-exp-03-07` -> `gemini-embedding-2-preview` -> `text-embedding-005`). Curriculum retrieval now flows through `transform.py` and `ab_eval.py` into adaptation so word choices can be steered toward exact UFLI lesson content when overlap is strong enough. Validation for the audit follow-up passed: focused `ruff`/`mypy` on touched files, focused audit/ingest tests green (`9 passed`), and today’s offline repo audit wrote reports to `data/ufli/audit/20260315_204339` with text benchmark `Hit@1=0.78`, `Hit@3=0.93`, `Hit@5=0.96`, `MRR=0.85`, `grade correctness=0.96`, plus image/audio retrieval cleanly skipped because companion manifests are not present yet. Validation for the Stage 0/1 audio rollout is also green: focused `ruff`, `mypy`, and `pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audit.py tests/test_corpus_ingest.py` all passed on 2026-03-15 (`16 passed`). Validation for the new remediation gate is also green on 2026-03-16: focused `ruff check corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py corpus/ufli/audio_judge.py corpus/ufli/ingest.py tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py`, focused `mypy` on the same files, and `pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py` all passed (`15 passed`) before the provider-limit patch, and the targeted follow-up after the pause-shaping pass also passed with `.venv/bin/ruff check corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py`, `.venv/bin/mypy corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py`, and `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py` (`17 passed`). The new diagnostics harness also now passes focused verification with `.venv/bin/ruff check corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py corpus/ufli/audio_diagnostics.py corpus/ufli/ingest.py tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py tests/test_corpus_audio_diagnostics.py`, `.venv/bin/mypy` on the same files, and `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py tests/test_corpus_audio_diagnostics.py` (`20 passed`). After the punctuation-recursion fix, the narrower follow-up verification also passed with `.venv/bin/ruff check corpus/ufli/audio_companion.py tests/test_corpus_audio_companion.py`, `.venv/bin/mypy corpus/ufli/audio_companion.py tests/test_corpus_audio_companion.py`, and `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_diagnostics.py` (`16 passed`). After the review-wording and sentence-pause changes, the next narrow pass also passed with the same focused `ruff`, `mypy`, and `pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_diagnostics.py` (`17 passed`). The punctuation-cleanup follow-up also passed with `.venv/bin/ruff check corpus/ufli/audio_companion.py tests/test_corpus_audio_companion.py`, `.venv/bin/mypy corpus/ufli/audio_companion.py tests/test_corpus_audio_companion.py`, and `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audio_diagnostics.py` (`19 passed`). The Google canary implementation also passed focused verification with `.venv/bin/ruff check corpus/ufli/audio_diagnostics.py corpus/ufli/audio_companion_schema.py corpus/ufli/ingest.py tests/test_corpus_audio_diagnostics.py`, `.venv/bin/mypy corpus/ufli/audio_diagnostics.py corpus/ufli/audio_companion_schema.py corpus/ufli/ingest.py tests/test_corpus_audio_diagnostics.py`, and `.venv/bin/pytest -q tests/test_corpus_audio_diagnostics.py tests/test_corpus_audio_companion.py tests/test_corpus_audio_judge.py` (`26 passed`). `.venv/bin/python -m corpus.ufli.ingest build-audio --data-dir data/ufli --lesson-set pilot_rep` now succeeds and `.venv/bin/python -m corpus.ufli.ingest validate-audio --data-dir data/ufli --lesson-set pilot_rep` now reports `bundles=6 issues=0 passed=True`. The live remediation loop also now runs successfully end-to-end with `SSL_CERT_FILE` pointed at the venv `certifi` bundle, which was required on this macOS/Python 3.13 environment to avoid TLS trust-store failures during ElevenLabs, Google TTS, and Gemini calls. CI failure investigation on 2026-03-15 found a strict-mypy regression in `tests/test_vision.py`: three pytest fixture parameters lacked annotations, so repo-wide `mypy .` failed even though runtime behavior was unchanged; adding `MonkeyPatch` and `LogCaptureFixture` annotations fixed the issue, and local verification now passes with `.venv/bin/ruff check .`, `.venv/bin/mypy .`, and `.venv/bin/pytest tests/ -v --ignore=tests/test_e2e.py` (`308 passed`). Gemini access investigation on 2026-03-15 confirmed `.env` config is present and direct Gemini API access works outside the sandbox; prior live eval failures were caused by sandbox DNS/network restrictions, not missing credentials. OCR crash investigation on 2026-03-15 found the remaining stability risk is local PaddleOCR fallback on macOS/Python 3.13, not the RAG code itself: one `PaddleOCR(lang="en")` init raised RSS from ~163 MB to ~862 MB, and one real OCR pass on `samples/input/IMG_0004.JPG` peaked at `ru_maxrss=10432413696` (~10.4 GB on macOS) while processing only the first image. Eval hardening is now implemented enough for safe live runs: `ab_eval.py` and `rag/eval.py` default to `--extract-mode vision_only` so live evals fail fast instead of silently falling back to Paddle, `ab_eval.py` now requires explicit `--seed --extract-mode auto` for the old seed-and-fallback flow, and `extract/ocr.py` reuses a single PaddleOCR instance per process. Phase 14 batch indexing is now implemented too: batch workers return `RunArtifacts` payloads and the main thread performs sequential RAG indexing after worker completion. Harness split is now explicit: `rag/eval.py` is the primary experiment harness with retrieval-health and efficiency metrics, while `ab_eval.py` is the narrower causal check for whether retrieval beats no-RAG and an intentionally weak retrieval control.
**Branch:** `codex/feature-gemini-embedding-2-rag`
**Plan version:** 1.5.0 + `plans/gemini-embedding-2-rag-plan.md` (v2)
**Last Updated:** 2026-03-18 (PDF layout, scene coverage, and format preference fixes)

### 2026-03-18 PDF Layout, Scene Coverage & Learner Format Preferences

**Status:** Implemented and verified. All 360 tests pass.

Three rendering/adaptation quality issues were identified during visual review of lesson 72 worksheets and fixed:

**1. Avatar scenes now render on all chunks (`render/pdf.py`)**

Previously, chunks with ≤2 items skipped scene layout ("scene isn't worth the column narrowing"). This meant Word Builder chain-step chunks and single-item circle chunks had no avatar image. The threshold was removed — all chunks now get scene images showing the avatar doing activity-relevant actions. The avatar-in-context association (avatar doing things related to the worksheet task) was confirmed still working via `render/pose_planner.py` theme-specific poses and content-word prompts.

**2. Blank page elimination (`render/pdf.py`)**

Two changes to prevent blank/sparse pages:
- **Chunk-level page break** now only triggers when the chunk header + first item won't fit (not the entire chunk). Previously a tall chunk like Word Builder (5 chain-step items + worked example) would push everything to page 2, stranding the header on a blank page 1.
- **Per-item page breaks** added inside `_draw_chunk()` via a `page_break_fn` callback. Items flow naturally across pages instead of forcing entire chunks to new pages. Added `_estimate_chunk_header_height()` helper.
- Result: Home practice Word Builder went from 4 pages (blank first page) to 3 well-packed pages.

**3. Trace→Write format substitution (`adapt/engine.py`)**

`_build_discovery_chunks()` hardcoded `["match", "trace", "circle"]` regardless of learner preferences. Ian's profile has `response_format_prefs: [write, circle]` (no "trace"), but got dotted tracing anyway. Fix:
- Discovery format selection now checks `rules.allowed_response_formats` — when "trace" isn't in the learner's prefs, "write" is substituted.
- Added "write" format handler in `_build_discovery_chunks()` (micro_goal "Write N words", instructions "Say each word out loud / Write the word on the line").
- Backfill guard prevents "trace" from re-appearing when "write" already substitutes for it.
- Tests updated: `test_format_mix_rotation_from_rag`, `test_render_trace_items`, `test_chunk_starts_on_new_page_before_bottom_clip`.

**Files changed:** `render/pdf.py`, `adapt/engine.py`, `tests/test_render.py`, `tests/test_rag_adapt.py`

### 2026-03-18 Theme-Aware Avatar Creation & Consistency Pipeline

**Plan file:** `plans/theme-aware-avatar-pipeline.md`
**Status:** Implemented and verified. All 360 tests pass (16 new).

**Problem:** Worksheet characters looked generically "cartoon blocky" instead of matching Ian's Roblox theme. The `_CHARACTER_DESC` was hardcoded in two files, scene prompts were theme-agnostic, and the Gemini judge didn't evaluate theme fidelity.

**Architecture: "Research Once, Enforce Cheap"**

Phase 1 (expensive, one-time): When a profile is created or theme changes, MCP research (perplexity-ask) fetches the theme's authentic visual language, Gemini generates a reference image pack, and a frozen `CharacterStyleSheet` is persisted on the profile.

Phase 2 (cheap, per-image): Every worksheet render reads the style sheet's `character_block` instead of hardcoded `_CHARACTER_DESC`. Scene prompts include theme environment context. The judge evaluates theme fidelity criteria. Zero MCP calls.

**Changes implemented:**

1. **`theme/schema.py`**: Added `CharacterSpec` model (art_style, style_description, body/face/scene descriptions, color_palette, reference_keywords, judge_criteria). Added to `ThemeConfig`.

2. **`theme/engine.py`**: `_parse_theme_config()` now loads `character_spec` from YAML.

3. **`theme/themes/roblox_obby/config.yaml`**: Populated with researched Roblox visual DNA — R15 rig proportions, 2D decal face, flat cell-shading, obby environment elements, 8 judge criteria. Based on perplexity/exa research of Roblox character specs and obby design.

4. **`companion/schema.py`**: Added `CharacterStyleSheet` model (frozen character_block prompt, reference_image_dir, scene_guidelines, item_style_notes). Linked to `AvatarConfig` via `style_sheet` field.

5. **`companion/character_research.py`** (new): One-time research module. `research_character_style()` loads theme's `CharacterSpec`, optionally enriches via Perplexity API, composes a frozen `character_block` prompt, generates reference image pack via Gemini. CLI: `python -m companion.character_research --profile profiles/ian.yaml --theme roblox_obby`. Works without API keys (falls back to static spec). Caches results.

6. **`render/asset_gen.py`**: Replaced hardcoded `_CHARACTER_DESC` with `_FALLBACK_CHARACTER_DESC`. `generate_worksheet_assets()` accepts `style_sheet` and `character_spec`. `_generate_scene()` uses style sheet's `character_block` + theme's `scene_environment`. Loads reference images from style sheet pack when available.

7. **`render/pose_planner.py`**: `plan_scenes()` accepts optional `CharacterSpec`. Added `_THEMED_POSES` dict with theme-aware pose variants (e.g., Roblox: "standing on a floating platform pointing at word signs" vs generic "pointing at word signs on a wall").

8. **`companion/generate_overlays.py`**: Replaced hardcoded `_CHARACTER_DESC`. `_build_variant_prompt()`, `_generate_single_variant()`, `generate_variant()` accept `CharacterStyleSheet`. `_build_judge_prompt()`, `_judge_with_gemini()`, `_judge_with_openai()`, `_judge_variant()` accept `CharacterSpec` for theme fidelity criteria.

9. **`companion/avatar.py`**: `_get_or_generate_variant()` loads theme and passes `style_sheet` + `character_spec` to `generate_variant()`.

10. **`transform.py`**: Multi-worksheet pipeline passes `character_spec` to `plan_scenes()` and `style_sheet` + `character_spec` to `generate_worksheet_assets()`.

### 2026-03-18 PDF Layout & Rendering Quality Pass

After implementing the missing literacy activities, a visual review of all generated PDF pages identified and fixed several layout, rendering, and data quality issues:

**`render/pdf.py` layout fixes:**
- **Blank first page elimination**: Scene-column fallback logic now checks whether content fits in the *remaining* page space (not just absolute max page height). If scene layout doesn't fit below the header but full-width does, it drops to full-width instead of pushing content to a new page. This was causing blank title-only pages on Word Builder and Story Time.
- **Passage full-width rendering**: Read-aloud passage chunks (decodable stories) always render full-width, bypassing scene-column layout. Dense passage text wraps badly in narrow columns and becomes hard for a child to read.
- **Small chunk optimization**: Chunks with ≤2 items skip scene layout. The decorative scene image isn't worth the column narrowing and vertical waste for small content blocks.
- **Fluency word renderer**: New `_draw_fluency_word_item()` renders Roll and Read words as large, clean text instead of individual blue "Read Aloud" boxes. Each word gets `heading + 4` pt font for rapid reading practice.
- **Combined tail elements**: Break prompt + self-assessment are treated as a single block for page-break decisions. Previously each independently checked for space and could end up on separate mostly-blank pages. Now they share a page.

**`adapt/engine.py` data quality fixes:**
- **Sentence deduplication**: Home practice PDFs often contain duplicated content (same sentences appear twice in OCR regions). Sentences are now deduplicated by normalized lowercase text before adaptation, eliminating repeated fill-in-the-blank items.
- **Roll and Read artifact filter**: `_parse_roll_and_read()` now filters known OCR extraction artifacts (`la`, `le`, `re`, `de`, `el`, `al`) that appear in corpus word lists but aren't real target-pattern words.

**Page count improvements for lesson 73:**
- Word Builder: 4 pages → 2 pages
- Story Time: 3 pages → 2 pages
- Word Discovery: 3 pages (unchanged — match section genuinely needs its own page due to picture tiles)

All 344 tests pass. `ruff` and `mypy` clean on all changed files. All PDF validations (skill parity, age band, ADHD compliance, print quality) pass.

### 2026-03-18 Missing Literacy Activities — Implemented

**Plan file:** `plans/add-missing-literacy-activities.md`
**Status:** Implemented and verified. All 344 tests pass. Lesson 73 pipeline produces all 3 new activity types.

Lesson 73 worksheets were missing reading/passage sections. Root cause: `_extract_word_work()` never created `passage` source items because the home practice PDF doesn't contain the decodable story, and `lesson_number` was extracted but discarded before corpus lookup could happen.

**Changes implemented:**

1. **`skill/schema.py`**: Added `lesson_number: int | None = None` field to `LiteracySkillModel`

2. **`corpus/ufli/lookup.py`** (new): Deterministic corpus lookup module. `lookup_lesson(N)` reads `normalized.jsonl` and returns `CorpusLookupResult` with `decodable_text`, `additional_text`, `concept`. Module-level caching for batch mode.

3. **`skill/extractor.py`**:
   - `_extract_word_work()` and `_extract_decodable_story()` now pass `lesson_number` to `LiteracySkillModel`
   - `_infer_lesson_from_concept()`: Fallback for when OCR doesn't find a "Lesson N" title — matches concept text ("y as long i") to corpus concepts ("y /ī/") via IPA-to-descriptive normalization
   - `_enrich_from_corpus()`: After skill extraction, looks up corpus and injects `passage` and `roll_and_read` source items if missing
   - `_clean_corpus_passage()`: Strips copyright, lesson headers, "Illustrate the story here:" boilerplate

4. **`adapt/engine.py`**:
   - Categorization loop handles new `roll_and_read` item type via `_parse_roll_and_read()`
   - `_build_warmup_chunk()`: Phonemic awareness sound boxes (Elkonin boxes) for grades K-1 only. 3 target words, phoneme segmentation via `_segment_phonemes()`. Prepended to Word Discovery chunks.
   - `_segment_phonemes()`: Grapheme-to-phoneme segmentation handling common digraphs/trigraphs (sh, ch, th, ck, ai, ay, ee, igh, ar, er, etc.) and silent e
   - `_build_roll_and_read_chunk()`: Fluency practice with 5 words (mix of base + inflected forms). Appended to Word Builder chunks. Reuses existing `read_aloud` renderer.

5. **`render/pdf.py`**:
   - `_draw_sound_box_item()`: Target word in large type + row of centered empty rounded-rect boxes (one per phoneme, ~0.8" square)
   - Height estimator added for `sound_box` format

**Lesson 73 results (grade 2, so no warmup):**
- Word Discovery: match + trace + circle (unchanged)
- Word Builder: chain steps + sight words + **Roll and Read** (5 fluency words)
- Story Time: sentence fill-blank + **"Plane Race" decodable passage** + **comprehension questions**

Sound box warmup activates for K-1 lessons (verified in test suite).

### 2026-03-17 Worksheet Rendering & Adaptation Quality Fixes

Lesson 73 UFLI worksheets generated from `data/ufli/raw/73/` (decodable passage + home practice PDFs). Six worksheets output to `output/lesson73_decodable/` and `output/lesson73_home_practice/`. During review, several rendering and adaptation quality issues were identified and fixed:

**adapt/engine.py changes:**
- **Word Builder chain-step redesign:** `_build_builder_chunks()` no longer creates items identical to the worked example. Added `_parse_chain_steps()` and `_find_letter_change()` helpers that decompose word chains into individual letter-substitution steps. The worked example shows the first step (e.g., `cry → try (change the "c" to "t")`), and activity items are interactive — each gives a starting word, the letter to change, and a writing line for the answer. Duplicate steps from repeated source chains are deduplicated.
- **Match picture shuffling:** `_build_discovery_chunks()` now uses `_shuffled_mismatch()` (deterministic derangement) to shuffle picture order so no picture aligns with its word in the match activity. Each item stores the shuffled picture word in `options[0]` and the correct answer in `answer`.
- **Research-based distractors:** `_generate_distractors()` replaced generic common-word list with graduated phonetic near-miss distractors (per PMC8862114/PMC5902514). ~Half near-miss words sharing features with targets (e.g., "funny"/"happy" for y-as-long-i targets), ~half clearly different CVC words.

**render/pdf.py changes:**
- **Match picture lookup fix:** `_draw_match_item()` now uses `item.options[0]` (shuffled picture word) for asset cache lookup instead of `item.content`, so pictures actually render in shuffled order.
- **Dotted trace letters:** `_draw_trace_item()` now uses `setTextRenderMode(1)` (stroke-only outline) with `setDash(1, 2)` for dotted letter outlines instead of solid light-gray fill.
- **Circle items de-bubbled:** `_draw_circle_item()` no longer draws `roundRect` bubbles around words. Words render as plain text with 28pt spacing between them, giving children room to draw their own circles.
- **Fill-in-the-blank spacing:** `_draw_fill_blank_item()` now uses larger display text (`body + 4`pt), adds a dedicated writing line with `write_line_height = max(body * 2, 32)` (~0.45" for grade 1).
- **Write item spacing:** All write-format items (regular, chain, chain_step) now use proper ruled writing lines with the same generous `write_line_height` instead of inline underscore characters. Added `_draw_chain_step_item()` dedicated renderer.
- **Scene layout overflow fix:** Chunks that exceed `max_page_height` when estimated with scene columns now fall back to full-width layout instead of creating blank pages. This prevented the Word Builder and Story Time worksheets from rendering as blank first pages.
- **Height estimators updated:** All item height estimators updated to account for larger writing areas and new renderers, ensuring correct page breaks.

All 344 tests pass. PDF validation (skill parity, age band, ADHD compliance, print quality) passes on all generated worksheets.

### 2026-03-16 Audio Canary Update
- A diagnostics-only Google provider path now exists in `corpus/ufli/audio_diagnostics.py` and `corpus/ufli/ingest.py` without changing the main ElevenLabs generation path. The canary path now supports both Chirp 3 HD voices and Google Cloud TTS Gemini-TTS model experiments, while keeping our existing source-side `tts_text` shaping and judge flow intact.
- The first Google canary used `en-US-Chirp3-HD-Leda` against four focused passage-family clips and wrote `data/ufli/companion/diagnostics/20260316_203756`. Result: mixed but informative. `lesson_014_passage_full` improved materially versus Dorothy (`111.5 WPM`, `use`, versus Dorothy official rerun `166.3 WPM`, `revise`), but the tested `passage_sentence` clips stayed `revise` and were usually as fast or faster than Dorothy. This still points to remaining sentence-family failures being more provider/voice limited than pipeline-bug driven.
- A second canary used Google Cloud TTS Gemini-TTS with `model_name=gemini-2.5-pro-tts`, voice `Leda`, `speaking_rate=0.85`, `sample_rate_hz=44100`, `volume_gain_db=0`, and the style prompt `Speak slowly, clearly, and warmly like you were speaking to a young child. Enunciate every sound distinctly. Pause slightly between words. Use a calm, encouraging teacher voice.` The results are under `data/ufli/companion/diagnostics/20260316_230309`.
- Important implementation caveat: these exact knobs were available on the official Google Cloud TTS Gemini-TTS surface, not clearly on the installed Vertex `google.genai` SDK path. To avoid guessing, the live Gemini-TTS canary was run through the official Cloud TTS API using the same personal ADC / `ws-builder-rag` project and Google auth setup, not via a separate new auth stack. Even so, Vertex-oriented env setup was still reused (`personal-on`, ADC, project, `GOOGLE_CLOUD_LOCATION=us-central1`, plus `GOOGLE_TTS_LOCATION=us` for the supported TTS endpoint).
- The Gemini-TTS canary was consistently clear and accurate but overshot heavily into under-speeding. All four clips remained `revise`; measured WPM ranged from `45.4` to `75.8` on the current-pipeline variants and `54.3` to `72.9` on the exact-transcript variants. This is far slower than both Dorothy’s remaining-pain-point range and the judge target bands for passage clips, so the requested style + `0.85` speaking rate should be treated as too aggressive for pilot use.
- The Gemini-TTS canary also showed a provider-specific shaping mismatch: unlike the Chirp 3 run, the current-pipeline pause-shaped text did not consistently beat exact transcript text. `lesson_014_passage_full` and `lesson_095_passage_sentence_02` were both classified as `pipeline_input_problem`, with exact transcript outperforming the current pause-shaped variant on the same voice/model. That suggests our current pause-shaping heuristics are not one-to-one portable from ElevenLabs/Chirp 3 to Gemini-TTS and should be retuned conservatively if this branch continues.
- A follow-up recalibration canary on 2026-03-17 kept the same `gemini-2.5-pro-tts` / `Leda` setup and output controls but raised `speaking_rate` from `0.85` to `1.0` and slightly softened the style wording (`would` instead of `were`). The run wrote `data/ufli/companion/diagnostics/20260317_141548`. This helped meaningfully but not enough: current-pipeline WPM improved from `55.4 -> 63.5` on `lesson_014_passage_sentence_03`, `45.4 -> 57.0` on `lesson_014_passage_full`, `65.0 -> 74.5` on `lesson_095_passage_sentence_02`, and `75.8 -> 81.1` on `lesson_095_passage_sentence_11`; exact-transcript WPM improved even more strongly, especially `61.1 -> 82.0` on `lesson_014_passage_full` and `72.9 -> 90.5` on `lesson_095_passage_sentence_02`. All variants still remained `revise`, but only one blocker remained (`lesson_014_passage_sentence_03` current/exact and `lesson_014_passage_full` current). This strengthens the case that Gemini-TTS is highly sensitive to prompt-plus-pause shaping, and that exact transcript or much lighter pause shaping is a better next probe than simply increasing rate again.
- A second 2026-03-17 wording-only canary kept the same `gemini-2.5-pro-tts` / `Leda` setup and `speaking_rate=1.0` but removed the word `slowly` from the style prompt (`Speak clearly and warmly like you would to a young child...`). The run wrote `data/ufli/companion/diagnostics/20260317_142555`. The result was mixed in a more nonlinear way than a simple rate change: `lesson_095_passage_sentence_11` current-pipeline improved from `81.1 -> 96.0 WPM` and flipped from `revise` to `use`, while `lesson_014_passage_sentence_03` current-pipeline regressed sharply from `63.5 -> 49.2 WPM` and remained blocker-marked. `lesson_014_passage_full` exact-transcript improved slightly (`82.0 -> 85.3 WPM`), and `lesson_095_passage_sentence_02` current-pipeline improved slightly (`74.5 -> 78.1 WPM`), but both still remained `revise`. The strongest takeaway is that Gemini-TTS prompt wording interacts unpredictably with our current pause-shaped inputs; exact transcript again outperformed current-pipeline shaping on the harder Lesson 14 clips, while current-pipeline finally won cleanly on one Lesson 95 clip. This makes a broad Gemini rollout less safe than a very narrow, clip-family-specific canary strategy.
- A third 2026-03-17 canary kept `gemini-2.5-pro-tts` / `Leda` and `speaking_rate=1.0` but replaced qualitative pacing words with explicit target pacing guidance in the style prompt (`Aim for a natural reading pace around 108 words per minute for sentence reads and around 115 words per minute for full-passage reads...`). After one transient Google `499 CANCELLED` response during synthesis, the clean rerun wrote `data/ufli/companion/diagnostics/20260317_143834`. This was the best Gemini sentence-family result so far, but only when pause shaping was removed: exact-transcript variants reached `use` on `lesson_014_passage_sentence_03` (`93.5 WPM`), `lesson_095_passage_sentence_02` (`99.2 WPM`), and `lesson_095_passage_sentence_11` (`107.4 WPM`), while current-pipeline also reached `use` on `lesson_095_passage_sentence_02` (`119.9 WPM`). The hard remaining failure is still `lesson_014_passage_full`, where current-pipeline remained blocker-marked (`56.7 WPM`) and even exact transcript stayed below band (`87.5 WPM`). The main implication is now clearer than before: Gemini `gemini-2.5-pro-tts` appears materially more promising when given explicit WPM-style guidance and much lighter input shaping, especially for `passage_sentence`; our current ElevenLabs-oriented pause-shaped source text still transfers poorly to Gemini on the harder clips, particularly `passage_full`.
- A narrow diagnostics-only code change landed locally on 2026-03-17 to support Experiment 2 cleanly: `corpus/ufli/audio_diagnostics.py` and `corpus/ufli/ingest.py` now accept a Google variant filter (`google_variant_scope=both|current_pipeline|exact_transcript` / `--google-variant-scope ...`) so rate sweeps can target the winning Gemini input condition without paying for the known-bad branch. Focused validation passed with `.venv/bin/ruff check corpus/ufli/audio_diagnostics.py corpus/ufli/ingest.py tests/test_corpus_audio_diagnostics.py`, `.venv/bin/mypy` on the same files, and `.venv/bin/pytest -q tests/test_corpus_audio_diagnostics.py` (`9 passed`).
- Experiment 2 (exact-transcript-only speaking-rate response curve) is now complete for `gemini-2.5-pro-tts` / `Leda` using the explicit-WPM prompt. The clean runs are `data/ufli/companion/diagnostics/20260317_143834` at `1.0`, `data/ufli/companion/diagnostics/20260317_152720` at `1.05`, and `data/ufli/companion/diagnostics/20260317_153239` at `1.1`. Result: `1.0` is the best overall sentence-family setting, `1.05` overshoots the hard Lesson 14 sentence clip while still helping the Lesson 95 sentences, and `1.1` finally fixes `lesson_014_passage_full` (`118.0 WPM`, `use`) but pushes all three sentence clips too fast. In exact-transcript terms: `lesson_014_passage_sentence_03` was `93.5/use` at `1.0`, `135.1/revise` at `1.05`, and `129.7/revise` at `1.1`; `lesson_014_passage_full` was `87.5/revise`, `88.9/revise`, then `118.0/use`; `lesson_095_passage_sentence_02` was `99.2/use`, `112.5/use`, then `139.9/revise`; `lesson_095_passage_sentence_11` was `107.4/use`, `121.9/use`, then `134.5/revise`. This points toward clip-family-specific rate or prompt handling as the next DOE lever rather than one global rate.
- Experiment 3 started on 2026-03-17 as a holdout-focused confirmation test to reduce overfitting. The untouched holdout sentence baseline with the global `1.0` explicit-WPM policy wrote `data/ufli/companion/diagnostics/20260317_155027` and generalized poorly: `lesson_014_passage_sentence_01` `77.4/revise`, `lesson_014_passage_sentence_05` `88.8/revise`, `lesson_095_passage_sentence_06` `63.8/revise blocker`, and `lesson_095_passage_sentence_13` `91.1/revise`. A sentence-specific prompt at the same `1.0` rate wrote `data/ufli/companion/diagnostics/20260317_160626` and was mixed rather than uniformly better: it improved `lesson_095_passage_sentence_13` to `110.5/use` and removed the blocker on `lesson_095_passage_sentence_06` (`78.3/revise`), but it also slowed `lesson_014_passage_sentence_01` and `lesson_014_passage_sentence_05` further (`66.3` and `83.7 WPM`). The holdout full-passage branch was partially completed but noisy because Google returned repeated transient `502` failures on the single-clip baseline path. The targeted full-specific `1.1` run did complete at `data/ufli/companion/diagnostics/20260317_161406`, but landed slightly too fast at `128.1 WPM` (`revise`) on `lesson_095_passage_full`. The current practical lesson is that family-specific prompting may help particular sentence subtypes, but prompt-only splitting is not yet a robust generalization fix; Gemini still looks sensitive to clip content and provider instability, so any broader policy should be treated as provisional until the full-passage holdout cells are rerun cleanly.
- Practical conclusion after the Gemini DOE work: keep ElevenLabs/Dorothy as the main production path for now; treat Google as diagnostics-only except for narrowly targeted fallback candidates. Gemini `gemini-2.5-pro-tts` is not yet a better broad provider candidate than ElevenLabs because the wins did not generalize cleanly across untouched holdout clips and the Google path showed repeated transient `499/502` instability. It does remain promising as a targeted fallback candidate for some hard pacing-only passage clips, especially when using exact transcript, explicit WPM guidance, and clip-family-specific handling. That policy step is now implemented locally in `corpus/ufli/audio_fallback_policy.py` plus the new `classify-audio-fallback` CLI in `corpus/ufli/ingest.py`: it is heuristic-first, keeps ElevenLabs as the default pass, limits Gemini eligibility to fast-side `passage_sentence` / `passage_full` misses with measured audio pacing, and explicitly buckets clips into `auto_accept`, `gemini_fallback_eligible`, and `needs_llm_or_manual_review` without auto-switching providers.
- The first live deterministic fallback-policy run on the current Dorothy data wrote `data/ufli/companion/fallbacks/20260317_170923`. It classified `23` generated clips across Lessons `1` and `14`: `17 auto_accept`, `4 gemini_fallback_eligible`, and `2 needs_llm_or_manual_review`. The initial Gemini-eligible set is exactly the narrow passage cluster we expected: `lesson_014_passage_sentence_02`, `lesson_014_passage_sentence_03`, `lesson_014_passage_sentence_05`, and `lesson_014_passage_full`. The non-passage misses (`lesson_001_lesson_instruction`, `lesson_001_review`) correctly stayed in manual review instead of being routed to Gemini. The policy report also carries family-specific Gemini fallback guidance (exact transcript + WPM-targeted prompt text) but leaves execution mode at `manual_opt_in`.
- Google retry hardening is now implemented for the diagnostics path via a shared helper module, `corpus/ufli/google_tts_client.py`. The helper preflights ADC once per live run, retries transient Google synthesis failures with bounded exponential backoff and jitter (`429`, `499`, `500`, `502`, `503`, `504`, plus `URLError` transport failures), honors `Retry-After` when present, and raises typed failures with attempt/status metadata. `corpus/ufli/audio_diagnostics.py` now uses that helper and soft-fails exhausted Google variants into probe artifacts instead of aborting the whole run, while still hard-failing true preflight auth/config problems. `corpus/ufli/audio_companion_schema.py` now records per-variant retry metadata (`attempt_count`, `failure_status_code`, `failure_category`, `failure_message`, `retry_exhausted`) so the Markdown/JSON probe reports capture which variants failed after retries.
- Focused validation for the Google hardening passed on 2026-03-17: `.venv/bin/ruff check corpus/ufli/google_tts_client.py corpus/ufli/audio_diagnostics.py corpus/ufli/audio_companion_schema.py tests/test_corpus_google_tts_client.py tests/test_corpus_audio_diagnostics.py tests/test_corpus_audio_fallback_policy.py`, `.venv/bin/mypy corpus/ufli/google_tts_client.py corpus/ufli/audio_diagnostics.py corpus/ufli/audio_companion_schema.py`, and `.venv/bin/pytest -q tests/test_corpus_google_tts_client.py tests/test_corpus_audio_diagnostics.py tests/test_corpus_audio_fallback_policy.py` (`23 passed`, one unrelated `requests` dependency warning from the local venv).

### Milestone Progress

| Milestone | Status | Checkpoints | Notes |
|-----------|--------|-------------|-------|
| M1: Foundation + Source Extraction | **Complete** | ~~1.1~~, ~~1.2~~, ~~1.3~~, ~~1.4~~ | All done |
| M2: Skill Extraction + ADHD Adaptation | **Complete** | ~~2.1~~, ~~2.2~~, ~~2.3~~, ~~2.4~~ | All done (2.2 merged into 2.1) |
| M3: Theme + Render + Validate + E2E | **Complete** | ~~3.1~~, ~~3.2~~, ~~3.3~~, ~~4.4~~ | All done |
| M4: Companion + Avatar | **Complete** | ~~4.1~~, ~~4.2~~, ~~4.3~~ | All done |
| M5: AI Assist + Generative | **Complete** | ~~5.1~~, ~~5.2~~, ~~5.3~~ | OpenAI + Gemini + Claude |

### Active Workstream: Gemini Embedding 2 RAG + UFLI Corpus (2026-03-14)
- **Plan files:**
  - `plans/gemini-embedding-2-rag-plan.md` — RAG architecture and phases (Phases 1-7 code implemented; curriculum-aware adaptation follow-up now complete)
  - `plans/vertex-ai-gemini-migration-plan.md` — future repo-wide Gemini-to-Vertex migration plan; not yet implemented
  - `plans/worksheet-builder-consolidated-plan.md` — original product plan (v1.4.0, all 15 checkpoints complete)
- **Completed in branch**:
  - RAG package created: `rag/client.py`, `rag/embeddings.py`, `rag/store.py`, `rag/retrieval.py`, `rag/indexer.py`
  - RAG backend hardening: `rag/client.py` now supports `RAG_GEMINI_BACKEND=auto|api_key|vertex`, `rag/embeddings.py` retries across fallback embedding models, `corpus/ufli/ingest.py` loads `.env` for direct CLI runs
  - Phase 7 modules added: `rag/backfill.py` (artifact-to-index CLI) and `rag/eval.py` (retrieval/adaptation evaluation harness with JSON + Markdown reports)
  - Adaptation consumption path added in `adapt/engine.py` (`rag_prior_adaptations`, distractor blacklist, format mix rotation)
  - Curriculum-aware adaptation added in `adapt/engine.py`: optional `rag_curriculum_references` flows into both `adapt_activity()` and `adapt_lesson()`, builds a deterministic curriculum word bank from retrieved UFLI lesson text, prefers curriculum-backed target words when at least two exact matches are present, and annotates supported items with `curriculum_supported` metadata for auditability
  - Transform pipeline integration in `transform.py` (`RunArtifacts`, optional retrieval before adapt, optional indexing after run)
  - `transform.py` + `ab_eval.py` now preserve curriculum retrieval documents via `_select_rag_curriculum_context()` and pass them into the adaptation stage alongside exemplar/prior-adaptation metadata
  - Gemini access hardening (2026-03-15): `ab_eval.py` now loads `.env` directly instead of relying on `transform.py` import side effects; `extract/vision.py` now accepts either `GEMINI_API_KEY` or `GOOGLE_API_KEY`, matching the RAG client
  - Eval/runtime hardening (2026-03-15): `ab_eval.py` and `rag/eval.py` gained `--extract-mode vision_only|auto|paddle|tesseract` with safe default `vision_only`; `ab_eval.py` now defaults `--no-seed` and refuses `--seed` unless `--extract-mode auto`; `extract/ocr.py` now caches one PaddleOCR instance per process to avoid repeated model loads
  - Phase 14 batch indexing strategy implemented (2026-03-15): `transform.py` now exposes `run_pipeline_collect_artifacts(..., index_results=...)`; `batch.py` workers call it with `index_results=False`, collect `RunArtifacts` payloads, and then index sequentially from the main thread after `ThreadPoolExecutor` completes
  - Harness split implemented (2026-03-15):
    - `rag/eval.py` is now the primary experiment harness and reports retrieval latency, retrieval-context rate, curriculum-reference hit rate, selected-context average score, curriculum-support deltas, and mean RAG runtime overhead in addition to the existing retrieval/validator metrics
    - `ab_eval.py` is now explicitly the causal harness and adds curriculum-support metrics plus an optional `C_bad_rag` negative-control arm (`--negative-control/--no-negative-control`) that routes intentionally weaker retrieval context through adaptation
    - `transform._build_adapted_summary()` now records `curriculum_supported_items` and `curriculum_lesson_ids`, so both harnesses can score curriculum-backed adaptation behavior from run artifacts
  - Multimodal corpus audit implemented (2026-03-15):
    - New modules: `corpus/ufli/audit.py` and `corpus/ufli/audit_schema.py`
    - New CLI: `python -m corpus.ufli.ingest audit --data-dir data/ufli --db-path vector_store --output-dir data/ufli/audit --sample-size 20 --benchmark-size 50 --seed 42 --no-ai-judge`
    - Outputs per run: `report.md`, `summary.json`, `record_metrics.csv`, `flags.csv`, `manual_review_sample.csv`, `retrieval_benchmark.json`
    - Current behavior: text corpus audits always run; image/audio companion manifests are optional; companion retrieval benchmarks are skipped cleanly when companion indexes are absent
    - Heuristics covered: inventory parity, empty/short text detection, concept coverage, image caption/alt/file integrity, image duplicate detection, audio transcript/duration/WPM checks, transcript duplicate/boilerplate checks, cross-modality lexical consistency, per-lesson modality coverage
    - New tests: `tests/test_corpus_audit.py` covering image/audio manifest parsing, modality coverage, cross-modality mismatch, duplicate heuristics, skipped companion retrieval, and CLI artifact generation
  - UFLI audio companion Stage 0 + Stage 1 rollout implemented (2026-03-15):
    - `corpus/ufli/audio_companion_schema.py` now defines committed config/data contracts for pronunciation lexicon, voice profiles, pilot lesson sets, dry-run estimates, and pilot review rows
    - `corpus/ufli/audio_companion.py` now builds voice-neutral lesson bundles keyed to raw numeric lesson ids, derives deterministic `passage_sentence` and `passage_full` clips from passage text when present, removes `encouragement` from indexed lesson clips, applies pronunciation lexicon overrides, supports dry-run cost estimation across pilot voices, keeps generation offline by default, validates live generation voice ids, and writes review packets (`review.md`, `review.csv`, `clips.json`, `playlist.m3u`, copied audio) to `data/ufli/companion/pilots/<timestamp>/`
    - `data/ufli/companion/pronunciation_lexicon.yaml` captures phoneme/grapheme/affix/special-word overrides; `voice_profiles.yaml` captures `dorothy` and `neutral_na_pilot` with `eleven_multilingual_v2` default + `eleven_flash_v2_5` fallback and clip-family settings; `pilot_lessons.yaml` captures `pilot_micro` (`1`, `14`, `95`) and `pilot_rep`
    - `corpus/ufli/ingest.py` audio subcommands now accept `--lesson-set`, `--voice-profile`, `--dry-run/--live`, `--review-packet`, and `--granularity`, with live generation/indexing explicitly gated to Stage 1 pilot lessons only and lesson-level indexing left for Stage 2
    - `corpus/ufli/audit_schema.py` and `corpus/ufli/audit.py` now understand the refined audio taxonomy and no longer treat `encouragement` as boilerplate because it is no longer indexed
    - New/updated tests: `tests/test_corpus_audio_companion.py` now covers taxonomy, pilot lesson selection, lexicon overrides, dry-run estimation, review packet generation, and voice-profile-aware indexing; `tests/test_corpus_audit.py` now uses `lesson_instruction`
    - MVP evaluation packet now lives under `data/ufli/companion/mvp_test/` with `facilitator_script.md`, `child_score_sheet.csv`, `adult_observation_rubric.md`, and `summary_template.md` for the smallest no-TTS vs TTS crossover test
  - UFLI audio companion Gemini judge implemented (2026-03-16):
    - New module: `corpus/ufli/audio_judge.py`
    - New CLI: `python -m corpus.ufli.ingest judge-audio --lesson-set pilot_micro --voice-profile dorothy --judge-model gemini-3-flash-preview --output-dir data/ufli/companion/evals`
    - Judge scope now includes transcript/script alignment, pedagogical fit, actual audio clarity, actual audio pacing from the generated file, and model-based acoustic pronunciation accuracy; it still is not a forced-alignment or lab-grade phonetic measurement
    - Outputs per run: `judge_summary.json`, `judge_results.csv`, `judge_report.md`
    - First live sample run: `data/ufli/companion/evals/20260316_121159` (`12` clips, `5` blockers)
    - First full live run: `data/ufli/companion/evals/20260316_121249` (`57` clips, `47 use`, `3 revise`, `7 block`, `9` blocker-marked clips)
    - Pacing/clarity upgrade: actual clip duration is now measured from MP3/WAV, actual WPM is scored against conservative child-directed clip-family pace bands, and Gemini now returns a best-effort heard transcript so clarity can be checked against the intended transcript
    - Pronunciation upgrade: Gemini now explicitly scores acoustic target pronunciation from the generated file via `pronunciation_accuracy_score`, and low pronunciation scores now trigger revise/block guardrails
    - External evidence check used Perplexity + Exa on 2026-03-16; direct age-5-8 ADHD-specific WPM evidence is sparse, but useful anchors were: older-student TTS studies often used `150 WPM`, synthetic-speech intelligibility can improve when rate is reduced, and child-listener studies show synthesized speech is less intelligible than live speech and benefits from context
    - First live audio-file sample after the upgrade: `data/ufli/companion/evals/20260316_122938` (`3` clips, `2` blockers), which confirmed Dorothy Lesson 1 phoneme modeling is clear but paced too quickly for the intended phoneme-model band
    - Full live rerun after the pronunciation upgrade: `data/ufli/companion/evals/20260316_124158` (`57` clips, `10 use`, `40 revise`, `7 block`, `31` blocker-marked clips)
    - Main judge findings: filter teacher-facing headings/metadata out of word targets, keep lesson/review prompts decoding-first instead of answer-giving, slow the phoneme-model delivery, substantially slow passage clips, and fix Lesson 95 `oy` anchor selection
    - New tests: `tests/test_corpus_audio_judge.py` covering judge response parsing and report artifact generation
  - Config/deps updates: `requirements.txt` (`chromadb>=0.5`, `python-pptx>=0.6.21`, `playwright>=1.40`), `.gitignore` (`vector_store/`, `data/ufli/raw/`, `data/ufli/normalized.jsonl`), `pyproject.toml` mypy override for `chromadb.*`, `playwright.*`, `pptx.*`
  - New RAG tests: `tests/test_rag_embeddings.py`, `tests/test_rag_store.py`, `tests/test_rag_retrieval.py`, `tests/test_rag_indexer.py`, `tests/test_rag_adapt.py`
  - New curriculum steering tests: `tests/test_rag_adapt.py` covers curriculum-backed target-word prioritization and the minimum-match guardrail; `tests/test_transform_rag_context.py` covers curriculum document preservation in transform-side RAG selection
  - **UFLI corpus ingestion pipeline** (new):
    - `corpus/__init__.py`, `corpus/ufli/__init__.py` — package structure
    - `corpus/ufli/crawl.py` — Playwright crawler for UFLI Toolbox (15 lesson group pages, ~148 lessons). Verified against live site. Features: retries with exponential backoff, incremental writes, malformed manifest recovery, browser cleanup via try/finally, realistic User-Agent/headers, rate limiting with jitter, SafeLinks URL unwrapping, A-J vs 1-128 page structure handling
    - `corpus/ufli/acquire.py` — Download PPTX/PDF resources from manifest. Features: retries with backoff, 60s socket timeout, partial file cleanup, resumable, prefers direct PPTX over Google Slides export
    - `corpus/ufli/extract.py` — Text extraction from PPTX (python-pptx) and PDF (PyMuPDF). Outputs `normalized.jsonl`
    - `corpus/ufli/ingest.py` — Embed with Gemini, index into ChromaDB `curriculum` collection. Click CLI with commands: `crawl`, `acquire`, `extract`, `index`, `run-all`
    - `rag/store.py` — Added `CURRICULUM = "curriculum"` collection constant
    - `rag/retrieval.py` — Added `curriculum_references` field to `RAGContext`, curriculum collection query in `retrieve_context()` (reuses existing skill embedding, no extra API call)
    - `transform.py` — Added `curriculum_references` count to RAG diagnostics
    - New tests: `tests/test_corpus_extract.py` (3), `tests/test_corpus_ingest.py` (4), `tests/test_retrieval_curriculum.py` (3) — 10 total
- **Validated locally**:
  - `.venv/bin/ruff check adapt/engine.py transform.py ab_eval.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` — clean
  - `.venv/bin/mypy adapt/engine.py transform.py ab_eval.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` — clean
  - `.venv/bin/pytest -q tests/test_rag_adapt.py tests/test_transform_rag_context.py` → `8 passed`
  - `.venv/bin/pytest -q tests/test_adapt.py tests/test_rag_adapt.py tests/test_transform_rag_context.py` → `48 passed`
  - `.venv/bin/pytest -q tests` → `285 passed`
  - `.venv/bin/pytest -q tests/test_vision.py tests/test_rag_client.py` → `6 passed`
  - `.venv/bin/ruff check extract/ocr.py ab_eval.py rag/eval.py tests/test_ab_eval.py tests/test_ocr_runtime.py` — clean
  - `.venv/bin/mypy extract/ocr.py ab_eval.py rag/eval.py tests/test_ab_eval.py tests/test_ocr_runtime.py tests/test_rag_eval.py` — clean
  - `.venv/bin/pytest -q tests/test_ab_eval.py tests/test_ocr_runtime.py tests/test_rag_eval.py tests/test_extract.py` → `18 passed`
  - `.venv/bin/ruff check transform.py batch.py batch_utils.py tests/test_batch.py` — clean
  - `.venv/bin/mypy transform.py batch.py batch_utils.py tests/test_batch.py` — clean
  - `.venv/bin/pytest -q tests/test_batch.py` → `27 passed`
  - `.venv/bin/pytest tests/ -v` → `294 passed`
  - `.venv/bin/ruff check ab_eval.py rag/eval.py transform.py tests/test_ab_eval.py tests/test_rag_eval.py` — clean
  - `.venv/bin/mypy ab_eval.py rag/eval.py transform.py tests/test_ab_eval.py tests/test_rag_eval.py` — clean
  - `.venv/bin/pytest -q tests/test_ab_eval.py tests/test_rag_eval.py tests/test_transform_rag_context.py tests/test_rag_adapt.py` → `14 passed`
  - `.venv/bin/ruff check corpus/ufli/audit.py corpus/ufli/audit_schema.py corpus/ufli/ingest.py tests/test_corpus_audit.py` — clean
  - `.venv/bin/mypy corpus/ufli/audit.py corpus/ufli/audit_schema.py corpus/ufli/ingest.py tests/test_corpus_audit.py` — clean
  - `.venv/bin/pytest -q tests/test_corpus_audit.py tests/test_corpus_ingest.py` → `9 passed`
  - `.venv/bin/ruff check corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py corpus/ufli/audit.py corpus/ufli/audit_schema.py corpus/ufli/ingest.py tests/test_corpus_audio_companion.py tests/test_corpus_audit.py` — clean
  - `.venv/bin/mypy corpus/ufli/audio_companion.py corpus/ufli/audio_companion_schema.py corpus/ufli/audit.py corpus/ufli/audit_schema.py corpus/ufli/ingest.py tests/test_corpus_audio_companion.py tests/test_corpus_audit.py` — clean
  - `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audit.py tests/test_corpus_ingest.py` → `16 passed`
  - `.venv/bin/python -m corpus.ufli.ingest audit --data-dir data/ufli --db-path vector_store --output-dir data/ufli/audit --sample-size 20 --benchmark-size 50 --seed 42 --no-ai-judge`
    - Output root: `data/ufli/audit/20260315_204339`
    - Result: text benchmark complete (`Hit@1=0.78`, `Hit@3=0.93`, `Hit@5=0.96`, `MRR=0.85`, `grade correctness=0.96`); image/audio sections `not_present` and retrieval skipped; action-item leaders were `missing_concept` (10), `very_short_record` (4), and `near_duplicate_lesson_text` (1)
  - Live eval: `source ~/.zshrc && personal-on && export RAG_GEMINI_BACKEND=vertex && PYTHONPATH=. .venv/bin/python -m rag.eval --test-dir samples/input --profile profiles/ian.yaml --db-path vector_store --theme roblox_obby --include 'IMG_0004.JPG' --output-root ./samples/output/rag_eval_live --extract-mode vision_only --no-images`
    - Output root: `samples/output/rag_eval_live/20260315_185306`
    - Result: `retrieval@3 mean=0.67`, `baseline_validator_pass_rate=1.0`, `rag_validator_pass_rate=1.0`, `rag_selected_source=curated_exemplars`, `rag_selected_count=2`
- **Executed** (2026-03-14):
  - `playwright install chromium` — done
  - **Crawl**: 148 lessons across 15 pages, zero errors, manifest at `data/ufli/manifest.jsonl`
  - **Acquire**: 539 files downloaded (148 PPTX + 131 decodable PDFs + 134 home practice PDFs + 126 additional PDFs). Required SSL fix: added `certifi` + `ssl.create_default_context(cafile=certifi.where())` to `acquire.py` (macOS Python 3.13 has no default CA bundle). All 148 lessons status: `acquired`
  - **Extract**: 148 lessons extracted to `data/ufli/normalized.jsonl` via python-pptx + PyMuPDF
  - **Index**: Completed after backend hardening. Live run used API-key backend auto-selection and `gemini-embedding-2-preview`; 148 lessons indexed into `vector_store/`
- **Pending from RAG plan**:
  - Run broader live eval coverage now that `rag/eval.py` is the primary harness and `ab_eval.py` is narrowed to causal checks
  - Optional docs updates (`README.md`, `CLAUDE.md`)
- **OCR eval crash investigation (2026-03-15)**:
  - Partial run artifacts confirm both live evals died in the first OCR fallback case:
    - `samples/output/ab_eval_live/20260314_215613/seed_runs/IMG_0003/artifacts/preprocessed_ocr_resized.png`
    - `samples/output/rag_eval_live/20260315_015613/IMG_0003/frozen/artifacts/preprocessed_ocr_resized.png`
    - Neither run reached `source_model.json` or a final report, so the failure occurred during Paddle OCR, not later in adaptation/render/RAG scoring.
  - Root-cause factors:
    - `extract/vision.py` returns `None` on sandbox DNS/network failures, which silently forces OCR fallback.
    - `extract/ocr.py` constructs a fresh `PaddleOCR(lang="en")` instance for every OCR call.
    - `ab_eval.py` seeds multiple non-target inputs before evaluating targets, so one invocation can trigger repeated OCR initializations when Gemini is unavailable.
    - Running `rag/eval.py` and `ab_eval.py` concurrently duplicates that memory-heavy OCR path in separate processes.
    - Local fallback safety is weak: `extract_text_with_fallback()` only catches `ImportError`, and local Tesseract is not installed in the current macOS dev environment.
  - Prevention plan:
    - Add an explicit OCR backend switch for evals (`auto|vision_only|paddle|tesseract`) and fail fast instead of silently falling back to Paddle when the intended live Gemini path is unavailable.
    - Cache/reuse a single PaddleOCR instance per process, or isolate OCR in a subprocess with a hard timeout/memory budget so an eval can fall back or abort cleanly instead of crashing the host app.
    - Default eval harnesses to sequential, low-footprint execution (`--no-seed`, single target, no parallel runs) unless live Gemini access is confirmed.
    - Add an OCR smoke/benchmark command that records elapsed time and peak RSS on one sample image before launching long evals.
    - Align the local OCR runtime with the supported matrix before depending on Paddle locally; current dev env is Python 3.13.1 while CI remains Python 3.11.
- **Future follow-up plan**:
  - `plans/vertex-ai-gemini-migration-plan.md` captures the repo-wide Gemini auth/client migration to Vertex AI as a separate workstream after current evals and RAG hardening

### What Exists Now
- `plans/worksheet-builder-consolidated-plan.md` — full implementation plan (v1.4.0, 15 checkpoints)
- `CLAUDE.md` — project guidance for Claude Code
- `.gitignore` — excludes data dirs, python artifacts, IDE files, samples/input/
- `.claude/` — context doc, commands, skills
- `samples/input/` — 6 UFLI phone photos (gitignored, local only)
- `samples/output/` — 3 manually-created adapted worksheet examples (committed)
- `pyproject.toml` — ruff, mypy (strict), pytest config
- `requirements.txt` — all pipeline dependencies pinned
- `Makefile` — lint, typecheck, test, test-golden, test-all, format, clean, batch
- `.github/workflows/ci.yml` — CI with Python 3.11, Tesseract, lint+typecheck+test
- 8 pipeline packages with `__init__.py`: capture, extract, skill, adapt, theme, companion, render, validate
- `capture/preprocess.py` — OpenCV preprocessing (deskew, dewarp, denoise, CLAHE)
- `capture/store.py` — hash-based master storage + archival PDF
- `capture/schema.py` — PreprocessResult, MasterRecord models
- `extract/ocr.py` — PaddleOCR v3/v2 + Tesseract fallback
- `extract/heuristics.py` — UFLI template detection + region classification
- `extract/schema.py` — SourceWorksheetModel, SourceRegion, OCRBlock, OCRResult
- `skill/taxonomy.py` — K-3 literacy taxonomy (6 domains), phonics pattern matcher
- `skill/extractor.py` — rule-based skill extraction dispatched by template_type
- `skill/schema.py` — LiteracySkillModel, SourceItem models
- `tests/test_capture.py` — 11 tests (preprocessing, storage, archival PDF)
- `tests/test_extract.py` — 13 tests (template detection, region classification, confidence)
- `tests/test_skill.py` — 31 tests (taxonomy, word work/story/generic extraction, schema)
- `companion/schema.py` — LearnerProfile + Accommodations (MVP fields, companion Optional)
- `adapt/schema.py` — AdaptedActivityModel, ActivityChunk, ScaffoldConfig, Step, Example, ActivityItem (with options, answer, picture_prompt, worksheet_number/count/title, break_prompt)
- `adapt/rules.py` — AccommodationRules, chunking tables, response format substitutions, FORMAT_RENDERING metadata, BRAIN_BREAK_PROMPTS, color system
- `adapt/engine.py` — ADHD activity adaptation: single-worksheet `adapt_activity()` + multi-worksheet `adapt_lesson()` producing 2-3 mini-worksheets with varied response types (match, trace, circle, fill_blank, write, read_aloud); helpers for distractors, fill-blank generation, comprehension questions, word-picture prompts
- `tests/test_adapt.py` — 40 tests (profile, rules, adaptation engine, multi-worksheet, format variety, schema)
- `validate/schema.py` — ValidationResult, ValidationViolation models
- `validate/skill_parity.py` — skill-parity + age-band validation (domain, skill, grade, format checks)
- `validate/adhd_compliance.py` — 12 ADHD design rule checks (chunk size, instructions, decoration, scoring, format variety, worksheet time limit, etc.)
- `tests/test_validate.py` — 25 tests (skill parity, age band, ADHD compliance, schema)
- `theme/schema.py` — ThemeConfig (with multi_worksheet flag), ThemeColors, ThemeFonts, AssetManifest, ThemedModel models
- `theme/engine.py` — theme loading (YAML) + application; 4 built-in themes
- `theme/themes/space/config.yaml` — Space Adventure theme
- `theme/themes/underwater/config.yaml` — Ocean Explorer theme
- `theme/themes/dinosaur/config.yaml` — Dino Discovery theme
- `theme/themes/roblox_obby/config.yaml` — Roblox Obby Quest (multi_worksheet: true, avatar_position: integrated)
- `tests/test_theme.py` — 11 tests (theme loading, application, round-trip)
- `render/pdf.py` — ReportLab PDF renderer: letter size, margins, vector text, chunks, self-assessment + new format renderers (_draw_match_item, _draw_trace_item, _draw_circle_item, _draw_fill_blank_item, _draw_read_aloud_item, _draw_break_prompt, _draw_chunk_with_scene)
- `render/pose_planner.py` — content-driven scene planning: analyzes chunk content to generate character scene descriptions and word picture prompts
- `render/asset_gen.py` — AI asset generation with hash-based caching; generates character scenes + word pictures via Gemini; graceful fallback when no API key
- `validate/print_checks.py` — PDF print quality validation (dimensions, text, pages)
- `tests/test_render.py` — 20 tests (PDF rendering, multi-format rendering, print quality validation)
- `transform.py` — CLI entry point: single-worksheet (backward-compatible) and multi-worksheet pipelines with format variety validation
- `tests/test_smoke.py` — verifies all packages importable

- `companion/profile.py` — profile CRUD (create, update accommodations, ensure companion fields)
- `companion/catalog.py` — 15-item avatar catalog across 3 themes + universal
- `companion/rewards.py` — token economy (effort-based, milestone bonuses, purchase, equip/unequip)
- `companion/caregiver.py` — progress reports, accommodation adjustments
- `complete.py` — CLI entry point for completion, rewards, progress, accommodations
- `tests/test_companion.py` — 28 tests (profile, catalog, rewards, caregiver)

- `extract/adapter.py` — ModelAdapter protocol; OpenAI (GPT-5.4), Gemini (3.1 Flash Lite), Claude adapters; NoOpAdapter baseline; image generation (Gemini 3.1 Flash Image Preview primary, OpenAI gpt-image-1.5 fallback); auto-detection: OpenAI > Gemini > Claude > NoOp
- `tests/test_adapter.py` — 27 tests (schema contracts, adapters, factory, image gen, AI assist runner)
- `extract/vision.py` — Gemini vision fallback: sends image to Gemini when OCR quality is poor (>80 fragments or <0.5 avg confidence)
- `.env` — API keys (gitignored): OPENAI_API_KEY, GEMINI_API_KEY
- `README.md` — project documentation
- `plans/gemini-embedding-2-rag-plan.md` — Gemini Embedding 2 RAG architecture and implementation plan (v2)
- `rag/` — new RAG package (Vertex AI client, embedding service, vector store, retrieval, indexer)
- `batch.py` — batch processing CLI: multi-threaded orchestration with rate limiting, retry, graceful shutdown, manifest-based skip detection
- `batch_utils.py` — batch utilities: FileResult, RateLimiter (token-bucket), ProgressTracker, file collection, manifest I/O, report generation
- `tests/test_batch.py` — 25 tests (file collection, rate limiter, progress tracker, manifest, process_single_file, CLI dry-run)
- `tests/test_rag_*.py` + `tests/test_rag_adapt.py` — RAG unit tests and retrieval-to-adaptation tests
- `corpus/ufli/crawl.py` — Playwright crawler for UFLI Toolbox (15 page groups, ~148 lessons)
- `corpus/ufli/acquire.py` — Resource downloader (PPTX + PDF) with retries
- `corpus/ufli/extract.py` — Text extraction from PPTX (python-pptx) and PDF (PyMuPDF)
- `corpus/ufli/ingest.py` — Embed + index into ChromaDB curriculum collection; Click CLI
- `corpus/ufli/audio_judge.py` — Gemini transcript/script judge for generated audio companion clips
- `tests/test_corpus_extract.py` — 3 tests (PPTX/PDF extraction with fixtures)
- `tests/test_corpus_ingest.py` — 4 tests (ingestion, idempotency, grade derivation)
- `tests/test_retrieval_curriculum.py` — 3 tests (curriculum retrieval, grade filtering, empty collection)
- `tests/test_corpus_audio_judge.py` — judge response parsing + artifact generation

### What's Next
**All original milestones remain complete. UFLI crawl/acquire/extract/index are done. Active remaining work is now experiment-harness consolidation/docs and broader production hardening.**

### Handoff Start Here
- **Current ready state**: `vector_store/` contains 148 indexed UFLI curriculum records, transform/eval code now passes curriculum hits into adaptation, and curriculum-backed word steering is covered by tests.
- **Current code state**: `rag/backfill.py` and `rag/eval.py` are implemented; curriculum-aware adaptation is now complete in `adapt/engine.py`; multimodal corpus audit is implemented in `corpus/ufli/audit.py` + `corpus/ufli/audit_schema.py`; `corpus/ufli/audio_judge.py` is implemented and live-verified against `gemini-3-flash-preview`; source/build-stage audio remediation is now implemented in `corpus/ufli/audio_companion.py`, `corpus/ufli/audio_companion_schema.py`, `corpus/ufli/ingest.py`, `data/ufli/companion/pronunciation_lexicon.yaml`, and `data/ufli/companion/voice_profiles.yaml`; `build-audio` + `validate-audio` now pass on both `pilot_micro` and `pilot_rep`; live Dorothy regeneration succeeded at `data/ufli/companion/pilots/20260316_144854` and `data/ufli/companion/pilots/20260316_151233`; live Dorothy judging succeeded at `data/ufli/companion/evals/20260316_145837` and `data/ufli/companion/evals/20260316_152838`; deterministic fallback classification is now implemented in `corpus/ufli/audio_fallback_policy.py` with new `AudioFallbackClipDecision` / `AudioFallbackPolicySummary` schemas and the `classify-audio-fallback` CLI; Google diagnostics hardening now lives in the shared `corpus/ufli/google_tts_client.py` helper and soft-failing probe integration in `corpus/ufli/audio_diagnostics.py`.
- **First task next session**: decide whether to keep the policy in manual-only mode for one more validation pass or wire a semi-automatic opt-in Gemini retry path for only the currently eligible passage clips. Preserve the current scope guardrails: eligible families are only `passage_sentence` and `passage_full`, pacing-only fast misses only, exact transcript first, no automatic Google switching.
- **Second task after that**: if execution work starts, implement a narrow opt-in Gemini retry path that consumes the policy report instead of re-judging every clip. Best shape: ElevenLabs first, classify deterministically, optionally retry only `gemini_fallback_eligible` clips with family-specific prompt guidance, then re-judge only the retried clips.
- **Third task after that**: rerun a small live fallback execution trial on the currently eligible Lesson 14 passage set and compare the retried clips against both the existing Dorothy outputs and the current policy buckets before widening scope.
- **Fourth task after that**: only if the fallback execution trial is stable, revisit additional Gemini family-specific prompt/rate exploration for the remaining gaps. Avoid broad new canaries unless they answer a concrete policy question.
- **Primary files to open first**: `corpus/ufli/audio_fallback_policy.py`, `corpus/ufli/audio_companion.py`, `corpus/ufli/audio_diagnostics.py`, `corpus/ufli/audio_companion_schema.py`, `corpus/ufli/ingest.py`
- **Useful verification commands**:
  - `.venv/bin/pytest -q tests/test_rag_backfill.py tests/test_rag_eval.py tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_rag_retrieval.py tests/test_corpus_ingest.py tests/test_retrieval_curriculum.py`
  - `.venv/bin/pytest -q tests/test_corpus_audit.py tests/test_corpus_ingest.py`
  - `.venv/bin/pytest -q tests/test_corpus_audio_companion.py tests/test_corpus_audit.py tests/test_corpus_ingest.py`
  - `.venv/bin/pytest -q tests/test_corpus_audio_judge.py tests/test_corpus_audio_companion.py tests/test_corpus_ingest.py`
  - `.venv/bin/python -m corpus.ufli.ingest build-audio --data-dir data/ufli --lesson-set pilot_rep`
  - `.venv/bin/python -m corpus.ufli.ingest validate-audio --data-dir data/ufli --lesson-set pilot_rep`
  - `.venv/bin/python -m corpus.ufli.ingest audit --data-dir data/ufli --db-path vector_store --output-dir data/ufli/audit --sample-size 20 --benchmark-size 50 --seed 42 --no-ai-judge`
  - `.venv/bin/python -m corpus.ufli.ingest judge-audio --lesson-set pilot_micro --voice-profile dorothy --judge-model gemini-3-flash-preview --output-dir data/ufli/companion/evals`
  - `.venv/bin/python -m corpus.ufli.ingest judge-audio --lesson-set pilot_micro --voice-profile dorothy --judge-model gemini-3-flash-preview --clip-limit 3 --output-dir data/ufli/companion/evals`
  - `.venv/bin/python -c 'from rag.store import CURRICULUM, get_or_create_collection, get_store; print(get_or_create_collection(get_store("vector_store"), CURRICULUM).count())'`
- **Environment note**: live Gemini embedding currently works via API-key auto-selection from `.env`. Vertex fallback remains supported in code but was not needed after backend hardening.
- **Sandbox note (2026-03-15)**: a minimal direct Gemini probe failed inside Codex sandbox with `httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known`, then succeeded immediately when rerun with escalation (`pong`). Use escalated commands for live Gemini evals from Codex, or expect OCR-only fallback behavior.
- **OCR note (2026-03-15)**: the local macOS dev env currently has PaddleOCR 3.4.0 / Paddle 3.3.0 on Python 3.13.1 and no `tesseract` binary in `PATH`. Treat local Paddle fallback as memory-unsafe until the eval harness is hardened or the runtime is aligned.
- **Vertex auth note (2026-03-15)**: personal ADC now works for Vertex on `ws-builder-rag` when using `personal-on` (`GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/adc-personal.json`, `GOOGLE_CLOUD_PROJECT=ws-builder-rag`, `GOOGLE_CLOUD_LOCATION=us-central1`). Live repo verification succeeded with `RAG_GEMINI_BACKEND=vertex`; prior failures were caused by ADC authenticating as `hjong@verily.health` instead of `howiejong@gmail.com`.

**Priority 1: Remaining RAG work** (see `plans/gemini-embedding-2-rag-plan.md`)
- Decide how `rag/eval.py` and `ab_eval.py` should coexist or converge
- Expand live eval coverage beyond the verified single-image run if broader evidence is needed

**Priority 2: Testing and polish**
- Test batch processing on full folder of UFLI lessons
- Test multi-worksheet output on more UFLI lessons
- AI asset generation end-to-end (requires Gemini API key with image gen capability)
- Custom font embedding (Nunito TTF files)
- Two-column scene layout refinement (content-column-width-constrained rendering)
- Web/mobile companion app (beyond CLI)

---

## Key Decisions Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| D1 | PaperBanana dropped | It generates academic illustrations, not worksheet adaptations | 2026-03-07 |
| D2 | Deterministic core, AI as optional assist | Pipeline must work offline without API calls | 2026-03-07 |
| D3 | Physical paper as image-native input | Master images are the authoritative artifact | 2026-03-07 |
| D4 | Skill-preserving, not page-faithful | Preserve instructional intent, not exact layout/wording/word lists | 2026-03-07 |
| D5 | ReportLab for vector-first PDF rendering | Text stays vector (searchable, sharp), raster only for illustrations | 2026-03-07 |
| D6 | PaddleOCR primary, Tesseract fallback | PaddleOCR better on camera photos; Tesseract requires native binary | 2026-03-07 |
| D7 | Pydantic for all data contracts | Single contract layer for schema validation, serialization, type enforcement | 2026-03-07 |
| D8 | Curated theme assets for MVP | No on-demand image generation; pre-made asset packs per theme | 2026-03-07 |
| D9 | ADHD anti-patterns are hard constraints | No loot boxes, streak punishment, leaderboards, variable-ratio rewards — ever | 2026-03-07 |
| D10 | UFLI Foundations as primary input family | Two known templates: word work + decodable story. Private input only, not repo fixtures | 2026-03-07 |
| D11 | MVP = core engine only (M1-M3) | Companion layer (avatar, tokens, caregiver) is post-core, pre-launch | 2026-03-07 |
| D12 | Game-themed structure, visually calm execution | Evidence-consistent ADHD design: game labels are motivational scaffolding but visually subordinate to literacy content | 2026-03-07 |
| D13 | Effort-based rewards, never accuracy-based | XP/points for completing and trying, not for getting answers right | 2026-03-07 |
| D14 | Skill-parity validates instructional intent | Adapted activities may use different words as long as they exercise the same skill pattern | 2026-03-07 |
| D15 | AI output may differ from no-AI output | Both paths produce valid results; AI is bounded, schema-validated, and auditable | 2026-03-07 |
| D16 | Golden test fixtures must be synthetic | Original content mimicking UFLI layout — no copyrighted material in repo | 2026-03-07 |
| D17 | Companion fields are Optional in data contracts | MVP builds and runs without companion layer; reward_event, avatar_prompts, avatar_image all Optional | 2026-03-07 |
| D18 | Ontario curriculum primary, BC at high level | Ontario Language 2023 Strand B/C is specific; BC ELA K-3 is high-level alignment only | 2026-03-07 |
| D19 | GPT-5.4 primary for text, Gemini for images | OpenAI best for structured JSON text tasks; Gemini 3.1 Flash Image Preview for asset generation with OpenAI gpt-image-1.5 fallback | 2026-03-07 |
| D20 | google.genai SDK, not google.generativeai | Old SDK deprecated; new google.genai has different API (Client-based) | 2026-03-07 |
| D21 | Auto-detection: OpenAI > Gemini > Claude | Priority based on available API keys; NoOp baseline when no keys | 2026-03-07 |
| D22 | Gemini vision as OCR fallback, not replacement | OCR runs first; if >80 fragments or <0.5 avg confidence, send image to Gemini for structured extraction. Keeps deterministic path working without API keys | 2026-03-07 |
| D23 | UFLI corpus as 5th ChromaDB collection (`curriculum`) | Gives RAG system canonical lesson content (concepts, target words, teaching sequences) for retrieval during worksheet generation | 2026-03-13 |
| D24 | Playwright for UFLI crawl, not HTTP fetch | UFLI Toolbox is JS-rendered (Divi/WordPress); static fetch returns only framework code | 2026-03-13 |
| D25 | Incremental manifest writes in crawler | Write after each page, not batched at end — crash on page 14 preserves pages 1-13 | 2026-03-13 |

---

## Architecture Quick Reference

### Pipeline Stages & Data Flow
```
[1] Capture    → master page image (PNG)
[2] Normalize  → preprocessed image (OpenCV)
[3] Extract    → SourceWorksheetModel (Pydantic) — OCR + heuristics, Gemini vision fallback
[4] Skill      → LiteracySkillModel (Pydantic) — dispatches by template_type
[5] Adapt      → AdaptedActivityModel (single) or list[AdaptedActivityModel] (multi-worksheet)
[5b] AI Review → iterative quality review
[6] Theme      → themed model with decoration zones; multi_worksheet themes → 2-3 mini-worksheets
[6c] Assets    → AI-generated character scenes + word pictures (optional, cached)
[7] Render     → PDF (ReportLab, vector text, match/trace/circle/fill_blank/read_aloud renderers)
[8] Validate   → skill-parity, age-band, print, ADHD compliance, format variety
```

### UFLI Template Types
```
ufli_word_work:        concept_label, sample_words, word_chain, chain_script,
                       sight_word_list, practice_sentences
ufli_decodable_story:  story_title, illustration_box, decodable_passage
unknown:               falls back to generic heuristics
```

### Module → Checkpoint Mapping
```
capture/    → Checkpoint 1.2
extract/    → Checkpoint 1.3
skill/      → Checkpoint 1.4
adapt/      → Checkpoints 2.1, 2.2
validate/   → Checkpoints 2.3, 2.4, 3.3
theme/      → Checkpoint 3.1
render/     → Checkpoint 3.2
transform.py + tests/test_e2e.py → Checkpoint 4.4 (in Milestone 3)
companion/  → Checkpoints 4.1, 4.2, 4.3 (post-core)
extract/adapter.py → Checkpoint 5.1 (post-launch)
rag/        → RAG Phases 1-6 (embeddings, store, retrieval, indexer)
corpus/     → UFLI corpus pipeline (crawl, acquire, extract, ingest)
```

### UFLI Corpus Pipeline
```
CLI: python -m corpus.ufli.ingest <command> --data-dir ./data/ufli

crawl    → Playwright crawl → data/ufli/manifest.jsonl    ✅ DONE (148 lessons)
acquire  → Download PPTX/PDF → data/ufli/raw/{lesson_id}/ ✅ DONE (539 files)
extract  → python-pptx + PyMuPDF → data/ufli/normalized.jsonl ✅ DONE (148 records)
index    → Gemini embed + ChromaDB → vector_store/         ❌ BLOCKED (Vertex AI 403)
run-all  → All 4 steps in sequence

ChromaDB collections: worksheets, skills, adaptations, exemplars, curriculum

Note: acquire.py was patched to use certifi SSL context (macOS Python 3.13 fix).
Note: index step requires GOOGLE_CLOUD_PROJECT=ws-builder-rag env var.
```

### Key Files (once created)
| File | Purpose |
|------|---------|
| `transform.py` | CLI: transform worksheets (full pipeline) |
| `complete.py` | CLI: mark completion, award tokens (post-core) |
| `extract/heuristics.py` | UFLI template detection + region classification |
| `extract/adapter.py` | Model adapter interface (swap AI providers by config) |
| `adapt/rules.py` | ADHD accommodation rules (chunking tables, substitutions) |
| `skill/taxonomy.py` | K-3 literacy skill taxonomy |
| `skill/extractor.py` | Skill extraction dispatched by template_type |
| `validate/skill_parity.py` | Instructional-intent preservation validation |
| `validate/adhd_compliance.py` | ADHD design rules enforcement |

---

## ADHD Design Summary (for quick reference)

**Core principle:** Game-themed structure, visually calm execution.

- **Decoration budget:** 0-2 decorative + unlimited functional visuals per page
- **Color system:** Blue (directions), Green (examples), Gold (rewards), Black (content), White (background)
- **Avatar:** 1-2 instances per page in fixed zones, one consistent character, visually subordinate
- **Chunking:** ~3-7 min per chunk, grade-scaled item counts (K: 2-3, Grade 3: 5-8)
- **Game labels:** "Level 1" / "Challenge" are fine but must be visually subordinate — child focuses on literacy, not mechanics
- **Rewards:** Effort-based stars/checkmarks per section. No complex XP totals, no accuracy scoring
- **Self-assessment:** "I can... / I'm still learning..." checklist at end of each worksheet
- **Time estimates:** Soft cues only ("About 3 minutes"), configurable off for anxious children

---

## Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| Q1 | PaddleOCR vs Tesseract cross-platform install | PaddleOCR has heavier dependencies; may affect dev setup | Open |
| Q2 | Nunito font licensing for embedded PDF | Listed as primary theme font | Open |
| Q3 | How to create synthetic golden test images | Need to mimic UFLI layout without using UFLI content | Open — solve during Checkpoint 1.3 |

---

## Gotchas Discovered

| # | Gotcha | Impact | Resolution |
|---|--------|--------|------------|
| G1 | pytesseract is only a Python wrapper | CI needs `apt-get install tesseract-ocr` | Added to CI workflow |
| G2 | PDF/A is not a simple ReportLab toggle | Requires ocrmypdf or equivalent | Deferred to post-MVP |
| G3 | OpenDyslexic not evidence-backed for ADHD | Was listed as font option | Removed, replaced with Nunito |
| G4 | "All source target words must appear" is too strict | Blocks valid adaptations for phonics, morphology, fluency | Changed to instructional-intent preservation |
| G5 | GitHub PAT needs `workflow` scope to push CI files | `.github/workflows/ci.yml` push rejected without it | User needs to update PAT or push CI file via web UI |
| G6 | google.generativeai deprecated | FutureWarning on import | Migrated to google.genai SDK |
| G7 | UFLI Toolbox A-J page has different table structure | 2 columns (Lesson + Slide Deck) vs 6 columns (1-128 pages); row headers say "Getting Ready A" not "A" | Structural detection (link presence in first cell) + `_normalize_lesson_id()` |
| G8 | Some UFLI Google Slides URLs wrapped in Outlook SafeLinks | `nam10.safelinks.protection.outlook.com` URL wrapping on A-J page | `_extract_gslides_id()` unwraps via `urllib.parse.parse_qs` |
| G9 | UFLI Toolbox has 15 lesson group pages, not 5 | Original assumption was 5 slugs; actual site has 15 slug pages | Verified via Playwright MCP, hardcoded all 15 slugs |
| G10 | macOS Python 3.13 has no default SSL CA bundle | `urllib.request.urlretrieve` fails with `SSL: CERTIFICATE_VERIFY_FAILED` | Added `certifi` package + `ssl.create_default_context(cafile=certifi.where())` to `acquire.py`; replaced `urlretrieve` with `urlopen` + chunked write (urlretrieve doesn't accept SSL context) |
| G11 | Vertex AI ADC permissions for embedding model | `gemini-embedding-exp-03-07` returns 403 `PERMISSION_DENIED` even with `GOOGLE_CLOUD_PROJECT` set and quota project configured. ADC user needs `aiplatform.endpoints.predict` permission | Re-authenticated ADC with quota project (`gcloud auth application-default login --project=ws-builder-rag`); still blocked. May need service account key or different auth approach |
| G7 | GPT-5.4 uses max_completion_tokens not max_tokens | 400 error with max_tokens param | Changed to max_completion_tokens |
| G8 | gpt-image-1.5 doesn't support response_format param | 400 error; returns b64_json by default | Removed response_format param |

---

## Session Log

### Session 1 — 2026-03-07 (Planning)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built initial plan through 7 versions (0.1.0 → 1.0.0)
- Key pivots: dropped PaperBanana, added physical paper input, ADHD design, avatar progression, skill-preserving adaptation, companion layer

### Session 2 — 2026-03-07 (Plan Review + Refinement)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Applied 4 rounds of review feedback (v1.0.0 → v1.4.0):
  - **v1.1.0:** Narrowed MVP to core engine; fixed skill-parity validator; resolved AI-assist contradiction; fixed CI Tesseract + PDF/A issues; softened curriculum claims; corrected ADHD evidence; clarified Pydantic as single contract layer
  - **v1.2.0:** Evidence-consistent ADHD design overhaul using Perplexity research (PMC10453933, PMC5280087, Longwood/BCH tools); established "game-themed structure, visually calm execution"; added decoration budget, chunking targets, effort-based rewards, self-assessment, avatar placement rules
  - **v1.3.0:** Split UFLI into two templates (word work + decodable story); restrained game framing; added UFLI rights boundary; softened research language to "evidence-consistent"
  - **v1.4.0:** Accuracy pass for clean build: threaded template_type through data model; added UFLI-specific region types; made companion fields Optional; separated LearnerProfile MVP vs companion fields; noted golden fixtures must be synthetic; added self_assessment to AdaptedActivityModel
- Reviewed all 6 input samples (UFLI phone photos) and 3 output samples (manually-created adapted worksheets)
- Identified key tension: output samples are more visually dense than ADHD evidence supports → resolved with "game structure, calm execution" principle

**What's next:** Checkpoint 1.1 — Repository scaffold + CI

### Session 3 — 2026-03-07 (Checkpoint 1.1 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.1: repo scaffold, dependencies, CI, Makefile, package structure
- Created pyproject.toml (ruff, mypy strict, pytest config)
- Created requirements.txt with all pinned deps (PaddleOCR, OpenCV, ReportLab, Pydantic, etc.)
- Created Makefile with 7 targets
- Created CI workflow with Tesseract install
- Created 8 pipeline packages with __init__.py
- Created smoke test verifying all packages importable
- All acceptance criteria pass: `make lint`, `make typecheck`, `make test`
- Hit G5: GitHub PAT missing `workflow` scope, blocking push of ci.yml

**What's next:** Checkpoint 1.2 — Image Capture + Preprocessing

### Session 4 — 2026-03-07 (Checkpoint 1.2 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.2: image capture, preprocessing, master storage
- `capture/schema.py` — PreprocessResult and MasterRecord Pydantic models
- `capture/preprocess.py` — full OpenCV pipeline: page detection, perspective warp, deskew (Hough), denoise, CLAHE contrast normalization, border trimming
- `capture/store.py` — hash-based master storage (idempotent) + archival PDF via ReportLab
- `tests/test_capture.py` — 11 tests with synthetic worksheet image generator (skew, perspective, noise, desk background variants)
- Tested against real UFLI sample: perspective correction detected and applied correctly
- Resolved numpy/OpenCV typing issues with mypy strict mode (used `np.ndarray[Any, Any]` alias)

**What's next:** Checkpoint 1.3 — OCR + Source Extraction

### Session 5 — 2026-03-07 (Checkpoint 1.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.3: OCR extraction, UFLI template detection, region classification
- `extract/schema.py` — SourceWorksheetModel, SourceRegion, OCRBlock, OCRResult Pydantic models with template_type and UFLI-specific region types
- `extract/ocr.py` — PaddleOCR v3 (dict output format) + v2 (list format) + Tesseract fallback; polygon-to-bbox conversion; sorted output
- `extract/heuristics.py` — detect_ufli_template (keyword matching + story structure detection); map_to_source_model with template-specific classifiers for word work, decodable story, and generic fallback
- `tests/test_extract.py` — 13 tests: template detection (4), source model mapping (6), confidence gating (3)
- Discovered PaddleOCR v3 requires paddlepaddle and has new API (dict output with rec_texts/rec_scores/rec_polys instead of list-of-lists)
- PaddleOCR v3 is slow on CPU (~2-3 min per image); added PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK env var
- Added pytesseract to mypy ignore list in pyproject.toml
- G5 resolved: PAT updated with workflow scope, CI file pushed

**What's next:** Checkpoint 1.4 — Skill Taxonomy + Extraction

### Session 6 — 2026-03-07 (Checkpoint 1.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 1.4: Skill Taxonomy + Extraction — completes Milestone 1
- `skill/schema.py` — LiteracySkillModel and SourceItem Pydantic models
- `skill/taxonomy.py` — K-3 literacy taxonomy with 6 domains, phonics pattern matcher with word-boundary-aware matching for short patterns
- `skill/extractor.py` — rule-based extraction dispatched by template_type: word work → phonics domain with concept label pattern matching, chain/sight word extraction; decodable story → fluency domain with CVCe passage analysis; generic fallback with reduced confidence
- `tests/test_skill.py` — 31 tests: taxonomy (8), word work extraction (10), decodable story extraction (7), generic extraction (3), schema validation (3)
- Fixed false positive in phonics pattern matcher: 2-char patterns (sh, ch, st, etc.) were matching inside words like "just" → added word boundary requirement for short patterns
- All 56 tests pass, lint clean, types clean

**What's next:** Checkpoint 2.1 — LearnerProfile + Accommodation Rules

### Session 7 — 2026-03-07 (Checkpoint 2.1 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoint 2.1: ADHD Activity Adapter + Accommodation Rules + LearnerProfile
- `companion/schema.py` — LearnerProfile with MVP fields (name, grade_level, accommodations) and Optional companion fields (avatar, preferences, progress); YAML load/save
- `adapt/schema.py` — AdaptedActivityModel, ActivityChunk, ScaffoldConfig, Step, Example, ActivityItem Pydantic models
- `adapt/rules.py` — AccommodationRules derived from grade+profile; chunking tables (K:2-3, G1:3-5, G2:4-6, G3:5-8); response format substitutions; instruction limits by grade; font size minimums; color system; time estimates
- `adapt/engine.py` — Full adaptation pipeline: source items → chunked activity items with worked examples (fading scaffolding), numbered instructions, time estimates, self-assessment checklist, decoration zones; handles phonics, fluency, and generic domains
- `tests/test_adapt.py` — 28 tests: profile (4), rules (7), adaptation engine (17)
- All 84 tests pass, lint clean, types clean

**What's next:** Checkpoint 2.2/2.3 — Accommodation Rules Engine + Skill-Parity Validation

### Session 8 — 2026-03-07 (Checkpoints 2.3 + 2.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 2.3 + 2.4: Skill-Parity Validation + ADHD Compliance — completes Milestone 2
- `validate/schema.py` — ValidationResult and ValidationViolation Pydantic models with add_violation helper (errors set passed=False, warnings don't)
- `validate/skill_parity.py` — 5 checks: domain preserved, specific skill preserved (warning), grade band (±1 grade allowed), response types compatible, non-empty adaptation; plus age_band validator
- `validate/adhd_compliance.py` — 10 checks: chunk size limits, numbered instructions, instruction word/step limits, decoration budget (≤2), no dense text, worked example in first chunk, self-assessment present, no accuracy-based scoring, decoration zone coords valid, time estimates reasonable
- `tests/test_validate.py` — 25 tests: skill parity (8), age band (3), ADHD compliance (11), schema (3)
- All 109 tests pass, lint clean, types clean

**What's next:** Checkpoint 3.1 — Theme Engine

### Session 9 — 2026-03-07 (Checkpoints 3.1 + 3.2 + 3.3 + 4.4 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 3.1-3.3 + 4.4: Theme Engine + PDF Renderer + Print Validation + E2E Pipeline — completes Milestone 3 and all MVP milestones
- `theme/schema.py` — ThemeConfig, ThemeColors, ThemeFonts, DecorativeConfig, ThemedModel
- `theme/engine.py` — load themes from YAML, apply theme to adapted model, plan decoration placements within zones
- 3 built-in themes: space (Space Adventure), underwater (Ocean Explorer), dinosaur (Dino Discovery)
- `render/pdf.py` — ReportLab PDF renderer: letter size (8.5x11"), 0.75" margins, vector text, grade-scaled font sizes, chunk headers, numbered instructions, worked examples in green-tinted boxes, activity items with response format indicators, self-assessment checklists, themed footer
- `validate/print_checks.py` — PDF validation: readable, letter dimensions, has pages, non-empty pages, vector text present
- `transform.py` — Full CLI pipeline: preprocess → store master → OCR → source model → skill extraction → ADHD adaptation → theme → render PDF → validate (skill parity + age band + ADHD compliance + print quality) → persist all artifacts
- `tests/test_theme.py` — 11 tests: theme loading (6), theme application (5)
- `tests/test_render.py` — 12 tests: PDF rendering (7), print quality validation (5)
- All 132 tests pass, lint clean, types clean

**What's next:** MVP complete. Post-core milestones: M4 (Companion + Avatar) and M5 (AI Assist)

### Session 10 — 2026-03-07 (Checkpoints 4.1 + 4.2 + 4.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 4.1-4.3: Companion + Avatar layer — completes Milestone 4
- `companion/schema.py` — expanded with structured models: AvatarConfig, Preferences, Progress, CompletionRecord, OperationalSignals (replacing generic dict[str, Any] fields)
- `companion/profile.py` — create_profile (saves to YAML), update_accommodations, ensure_companion_fields
- `companion/catalog.py` — 15 avatar items across universal + 3 themes; get_item, get_affordable_items, get_milestone_items
- `companion/rewards.py` — predictable effort-based token economy: 10 tokens/worksheet, milestone every 5 (25 bonus), purchase/equip/unequip items; enforces ADHD-safe rules (no accuracy scoring, milestone items auto-unlock)
- `companion/caregiver.py` — view_progress report, adjust_accommodations
- `complete.py` — CLI: --lesson (award), --progress (report), --buy (purchase), --set-chunking (adjust)
- `tests/test_companion.py` — 28 tests: profile (5), catalog (6), rewards (13), caregiver (4)
- All 160 tests pass, lint clean, types clean

**What's next:** M5 (AI Assist + Generative) — post-launch milestone

### Session 11 — 2026-03-07 (Checkpoint 5.1-5.3 Implementation)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Built Checkpoints 5.1-5.3: AI Assist layer — completes Milestone 5 and all milestones
- `extract/adapter.py` — ModelAdapter Protocol with 4 methods (tag_regions, infer_skill, review_ocr, suggest_adaptations); NoOpAdapter (deterministic baseline); ClaudeAdapter (Anthropic API); adapter factory with auto-detection (uses Claude if ANTHROPIC_API_KEY set, else NoOp); run_ai_assist runner with schema-validated outputs
- AI schema contracts: RegionTag, SkillInference, OCRCorrection, AdaptationSuggestion, AIResult — all Pydantic models
- No API keys needed — pipeline works fully without them; AI is optional assist
- Added anthropic to mypy ignore list
- `tests/test_adapter.py` — 17 tests: schema contracts (5), NoOp adapter (5), factory (5), AI assist runner (2)
- All 177 tests pass, lint clean, types clean

**Status:** All 15 checkpoints across 5 milestones implemented

### Session 12 — 2026-03-07 (AI Provider Integration + Testing)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Added OpenAI (GPT-5.4) and Gemini (3.1 Flash Lite) adapters for text tasks
- Added image generation: Gemini 3.1 Flash Image Preview (primary) + OpenAI gpt-image-1.5 (fallback)
- Set auto-detection priority: OpenAI > Gemini > Claude > NoOp
- Migrated from deprecated google.generativeai to google.genai SDK
- Fixed GPT-5.4 requiring max_completion_tokens instead of max_tokens
- Fixed gpt-image-1.5 not supporting response_format param (returns b64 by default)
- Added .env to .gitignore to protect API keys
- Integration tested all providers end-to-end: text and image generation confirmed working for both Gemini and OpenAI
- Added generate_image() top-level function with Gemini-first, OpenAI-fallback chain
- Added README.md with full project documentation
- Updated requirements.txt with openai, google-genai, python-dotenv
- All 189 tests pass, lint clean, types clean

### Session 13 — 2026-03-07 (Gemini Vision Fallback + E2E Real-World Test)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Added `extract/vision.py` — Gemini vision fallback for poor OCR results
- Quality gate: if OCR produces >80 fragments or avg confidence <0.5, send image to Gemini
- Gemini receives the actual worksheet image and returns structured JSON (template_type + regions)
- E2E tested on real UFLI Lesson 59 phone photo (two-page spread: word work + decodable story):
  - OCR-only: 113 fragments, wrong template (decodable_story), wrong domain (fluency), 8-page PDF
  - With Gemini fallback: 8 clean regions, correct template (word_work), correct skill (CVCe phonics), 2-page PDF
- Wired into transform.py pipeline automatically — no user intervention needed
- Gemini correctly identified both pages, prioritized word work page as planned
- All 189 tests pass, lint clean, types clean

### Session 14 — 2026-03-09 (Multi-Sensory Activities + Content-Driven Illustrations)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Implemented multi-worksheet adaptation engine and multi-format PDF rendering
- **Problem addressed:** UFLI Lesson 59 produced 15 items across 4 chunks, ALL "write" format. Decodable story dropped entirely. No variety.
- **Solution:** `adapt_lesson()` splits one lesson into 2-3 focused mini-worksheets:
  - Worksheet 1 "Word Discovery": match (word-picture), trace (dotted letters), circle (pattern recognition)
  - Worksheet 2 "Word Builder": word chains (write), fill-blank (missing vowels), sight words (write)
  - Worksheet 3 "Story Time": sentence completion (fill-blank with word bank), read-aloud passage, comprehension (circle)
- `adapt/schema.py` — Added `options`, `answer`, `picture_prompt` to ActivityItem; `worksheet_number/count/title`, `break_prompt` to AdaptedActivityModel
- `adapt/engine.py` — Added `adapt_lesson()` + 8 helper functions (discovery/builder/story chunk builders, distractor generation, fill-blank, sentence-to-blank, comprehension questions, word-to-picture prompts)
- `adapt/rules.py` — Added FORMAT_RENDERING metadata, BRAIN_BREAK_PROMPTS
- `render/pdf.py` — Added 7 new drawing functions: match tiles, trace letters, circle bubbles, fill-blank with word bank, read-aloud styled box, break prompts, two-column scene layout
- `render/pose_planner.py` — NEW: content-driven scene planning from chunk content
- `render/asset_gen.py` — NEW: AI asset generation with hash-based caching (Gemini Flash), graceful fallback
- `theme/schema.py` — Added AssetManifest model, multi_worksheet flag on ThemeConfig
- `theme/themes/roblox_obby/config.yaml` — NEW: multi_worksheet theme with integrated avatar
- `transform.py` — Split into single-worksheet (backward-compatible) and multi-worksheet pipeline branches
- `validate/adhd_compliance.py` — Added format variety check (Check 11) and worksheet time limit (Check 12)
- 20 new tests (12 adapt + 8 render), all 214 pass, lint clean, types clean
- **Fully backward compatible** — `adapt_activity()` and single-worksheet themes work unchanged

### Session 15 — 2026-03-09 (Rendering Quality Fixes + Word Picture Embedding)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Fixed `render/asset_gen.py` — migrated from deprecated `google.generativeai` SDK with unsupported `response_mime_type="image/png"` to `google.genai` SDK with `response_modalities=["TEXT", "IMAGE"]`, matching the working pattern in `companion/generate_overlays.py`. Uses reference character (`rainbow_roblox.png`) for scene consistency.
- Fixed text-image overlap in `render/pdf.py` — `_draw_chunk_with_scene()` now constrains text to a 60% content column via `content_left`/`content_right` parameters passed through `_draw_chunk()` and all item renderers. Scene images occupy 32% column on alternating sides with a gap. Text never enters the scene column.
- Embedded word pictures in match items — `_draw_match_item()` now accepts `asset_manifest` and renders actual AI-generated images (e.g., running dog for "chase", playground slide for "slide") instead of placeholder dashed boxes. Falls back to dashed placeholder when no manifest.
- All item renderers (`_draw_trace_item`, `_draw_circle_item`, `_draw_fill_blank_item`, `_draw_read_aloud_item`) now accept column bounds for constrained rendering.
- Added rendering quality check — `validate/print_checks.py` Check 6 uses PyMuPDF to detect text blocks overlapping with image bounding boxes (flags when >20% of text block area intersects an image). Runs automatically in pipeline.
- E2E tested: 11 AI images generated (7 character scenes + 4 word pictures), 0 text-image overlaps across all 3 worksheets, all validations pass
- All 214 tests pass, lint clean

### Session 16 — 2026-03-09 (ADHD-Optimized Typography)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Researched ADHD-friendly typography via Perplexity (sources: audioeye.com, neurodivergent.blog, reciteme.com, forbrain.com)
- Selected two free Google Fonts (OFL license, embedded in PDF):
  - **Fredoka** (headings) — rounded, fun, kid-friendly, clear letter differentiation
  - **Lexend** (body) — ADHD-optimized spacing, designed to reduce visual stress, clear b/d p/q I/l/1 differentiation
- Downloaded variable TTF files from `google/fonts` repo, stored in `assets/fonts/`
- `render/pdf.py` — registered fonts via `pdfmetrics.registerFont(TTFont(...))` with graceful fallback to Helvetica if TTFs not found
- Applied evidence-based ADHD spacing:
  - Line height: 1.7x font size (research shows 1.5x insufficient for ADHD)
  - Character spacing: 0.4pt body, 0.7pt headings (reduces visual crowding)
  - Word spacing: 1.5pt extra (aids tracking)
- Increased font sizes for K-1 (heading 20-22pt, body 16-18pt vs previous 16-18pt, 14-16pt)
- `theme/themes/roblox_obby/config.yaml` — updated to use Lexend/Fredoka
- Spacing applied via Canvas._charSpace/_wordSpace (setCharSpace/setWordSpace only on TextObject)
- All 214 tests pass, lint clean

### Session 17 — 2026-03-09 (Batch Processing with Rate-Limited API Orchestration)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Implemented batch processing CLI for bulk worksheet transformation
- `batch.py` — click CLI with `--input-dir`, `--profile`, `--theme`, `--output`, `--workers`, `--max-retries`, `--force`, `--dry-run`, `--no-images`, `--no-recursive`, `--rpm` options
- `batch_utils.py` — FileResult dataclass, RateLimiter (sliding-window token bucket, thread-safe via threading.Condition), ProgressTracker (thread-safe with ETA), collect_input_files, load/save manifest, generate_report
- Rate limiting: default 4 RPM to stay under Gemini's 5 RPM hard limit (Tier 1)
- Retry: exponential backoff (5s → 10s → 20s) + random jitter, configurable max retries
- Graceful shutdown: SIGINT handler lets running workers finish, cancels pending, writes partial report
- Skip detection: `batch_manifest.json` tracks completed files; re-runs skip automatically unless `--force`
- `--no-images` flag: sets `WORKSHEET_SKIP_ASSET_GEN=1` env var; 1-line check added to `render/asset_gen.py` returns None immediately. Enables bulk text-only processing (avoids 35 RPD image gen limit)
- `pipeline_fn` parameter on `_process_single_file` for testability (avoids pymupdf segfault from heavy transform module import under pytest)
- `tests/test_batch.py` — 25 tests covering all utilities and orchestration
- Updated Makefile (batch target), CLAUDE.md (batch CLI usage), README.md (batch processing section)
- All 239 tests pass (214 existing + 25 new), lint clean

### Session 18 — 2026-03-09 (CI Fixes — Lint + Type Errors)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Fixed all CI failures (lint + typecheck were failing, tests passing)
- **Ruff lint fixes (16 errors → 0):**
  - Removed unused imports across `batch_utils.py`, `companion/generate_overlays.py`, `tests/test_batch.py`, `tests/test_companion.py`
  - Fixed `UP017` — `timezone.utc` → `datetime.UTC` in `batch.py`
  - Fixed `I001` — sorted import blocks in `tests/test_batch.py`, `batch.py`
  - Fixed `E501` — line-length violations in `generate_overlays.py`, `complete.py`, `validate/ai_review.py`
  - Fixed `N806` — `MAX_OCR_SIDE` → `max_ocr_side` (local var in function) in `extract/ocr.py`
- **Mypy type fixes (39 errors → 0):**
  - Added type parameters to bare `dict` annotations in `batch_utils.py`, `validate/ai_review.py`, `companion/generate_overlays.py`
  - Fixed type conflict in `complete.py` — `equip_item`/`unequip_item` results shadowed `RewardResult`-typed variable
  - Changed `_display_catalog(profile: object)` → `_display_catalog(profile: LearnerProfile)`
  - Added `Callable` type alias for `pipeline_fn` in `batch.py` (was untyped `object`)
  - Changed `_validate_format_variety(list[object])` → `Sequence[AdaptedActivityModel]` in `transform.py`
  - Added `# type: ignore` for Gemini SDK incomplete type stubs (`generate_content` arg-type, `putdata` arg-type)
- All 239 tests still pass, lint clean, typecheck clean

### Session 19 — 2026-03-11 (Gemini Embedding 2 RAG Phases 1-6)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Created feature branch `codex/feature-gemini-embedding-2-rag` before implementation.
- Implemented RAG core package:
  - `rag/client.py` — Vertex AI client (`vertexai=True`) + `rag_available()` + model availability startup check.
  - `rag/embeddings.py` — `embed_text`, `embed_image`, `embed_pdf`, `embed_multimodal` with configurable dimensionality and task type.
  - `rag/store.py` — ChromaDB persistent store wrapper + collection helpers + query helper.
  - `rag/retrieval.py` — staged hybrid retrieval (skill-primary, content-secondary), grade filtering, dedup by `source_hash`.
  - `rag/indexer.py` — run artifact indexing for worksheets, skills, adaptations, exemplars; learner-name redaction before indexing text.
- Integrated retrieval-to-adaptation path in `adapt/engine.py`:
  - Added optional `rag_prior_adaptations` parameter to `adapt_activity()` and `adapt_lesson()` (backward-compatible defaults).
  - `_generate_distractors()` now supports blacklist from prior adaptations.
  - Added `_suggest_format_mix()` and `_extract_distractor_blacklist()` helpers.
  - Word Discovery format order can rotate when prior runs used same format mix.
- Integrated RAG in `transform.py` with non-blocking behavior:
  - Added `RunArtifacts` model for branch-agnostic indexing payload.
  - Added optional retrieval step before adaptation.
  - Added optional indexing step after single/multi branch completion.
  - Preserved `run_pipeline()` return type (`str` PDF path) for caller compatibility.
- Added tests:
  - `tests/test_rag_embeddings.py`
  - `tests/test_rag_store.py`
  - `tests/test_rag_retrieval.py`
  - `tests/test_rag_indexer.py`
  - `tests/test_rag_adapt.py`
- Updated config/deps:
  - `requirements.txt` adds `chromadb>=0.5`
  - `.gitignore` adds `vector_store/`
  - `pyproject.toml` adds mypy ignore for `chromadb.*`
- Validation status:
  - `ruff check .` ✅
  - `mypy .` ✅
  - `pytest tests -v --ignore=tests/test_e2e.py` ✅ (`247 passed, 3 skipped`)

**What's next:**
- Implement RAG Phase 7 modules: `rag/backfill.py` and `rag/eval.py`.
- Decide and implement batch main-thread indexing strategy from RAG plan phase 14.
- Optional docs pass for RAG usage/setup in `README.md` and `CLAUDE.md`.

### Session 20 — 2026-03-11 (GCP Project + Vertex Auth Setup for RAG)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Switched gcloud auth context to `howiejong@gmail.com` (user-provided account for project access).
- Verified target project exists and is active:
  - `ws-builder-rag` (`projectNumber: 715442045755`)
- Confirmed billing is linked (`billingEnabled: true`).
- Enabled required APIs on `ws-builder-rag`:
  - `aiplatform.googleapis.com`
  - `serviceusage.googleapis.com`
  - `iam.googleapis.com`
  - `iamcredentials.googleapis.com`
- Created runtime service account:
  - `worksheet-rag-runtime@ws-builder-rag.iam.gserviceaccount.com`
- Granted IAM bindings:
  - Service account → `roles/aiplatform.user`
  - Service account → `roles/serviceusage.serviceUsageConsumer`
  - User `howiejong@gmail.com` → `roles/serviceusage.serviceUsageConsumer` (for ADC quota project usage)
  - User `howiejong@gmail.com` on SA → `roles/iam.serviceAccountTokenCreator`
- Re-authenticated ADC as `howiejong@gmail.com` and set ADC quota project to `ws-builder-rag`.
- Updated local `.env` GCP setting:
  - `GOOGLE_CLOUD_PROJECT=ws-builder-rag`
- Verified live Vertex model availability check succeeded for:
  - `GEMINI_EMBEDDING_MODEL=gemini-embedding-2-preview`

**Current status:**
- Local machine is configured for Vertex-backed RAG embeddings against `ws-builder-rag`.
- Existing non-RAG Gemini paths in repo remain API-key based (auth migration still separate from RAG workstream).

### Session 21 — 2026-03-11 (A/B Evaluation Harness + RAG Context Quality Gating)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Implemented quality-first RAG context selection in `transform.py`:
  - Added `_select_rag_adaptation_context()` helper.
  - Adaptation now prefers `curated_exemplars` over generic `prior_adaptations`.
  - Curated exemplar retrieval is now deduped by `source_hash` (to avoid over-weighting one source).
  - Selected RAG metadata now includes `_rag_score` and `_rag_doc_id`.
  - Added `artifacts/rag_context.json` output for every run (selected source/count/avg score or retrieval error).
- Improved exemplar indexing in `rag/indexer.py`:
  - Exemplar metadata now includes primitive adaptation summary fields (e.g. `response_formats`, `estimated_minutes`, `distractor_words`) when available.
  - This allows curated exemplar retrieval to influence adaptation heuristics directly.
- Added deterministic paired A/B runner `ab_eval.py`:
  - Freezes Stage 1-4 per holdout target (`source_model.json` + `skill_model.json`).
  - Seeds vector store from non-target inputs.
  - Runs `A_no_rag` and `B_with_rag` from identical frozen artifacts.
  - Produces `scorecard.md` + `scorecard.json` and per-variant `rag_context.json`.
  - Supports `--clean-db`, `--seed`, and `--images/--no-images`.
- Updated docs:
  - `README.md` now includes A/B evaluation usage for `ab_eval.py`.
- Added/updated tests:
  - New `tests/test_transform_rag_context.py` for curated-vs-prior context selection behavior.
  - Updated `tests/test_rag_indexer.py` to assert exemplar metadata carries adaptation summary fields.
  - Updated `tests/test_rag_retrieval.py` to assert curated exemplar deduplication by `source_hash`.
- Validation run:
  - `.venv/bin/ruff check ...` on touched files ✅
  - `.venv/bin/mypy ...` on touched files ✅
  - `.venv/bin/pytest -q tests/test_transform_rag_context.py tests/test_rag_indexer.py tests/test_rag_retrieval.py` ✅ (13 passed)

**What's next:**
- Run `ab_eval.py` on a multi-target holdout set (not just `IMG_0004.JPG`) and review `scorecard.md`.
- Consider tightening retrieval filters further (domain/skill match in addition to grade) if B quality remains flat.
- Add learner-facing effectiveness rubric scoring (manual or evaluator-assisted) to complement validator flags.

### Session 22 — 2026-03-11 (A/B Harness Smoke Validation + Current Working State)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Ran end-to-end smoke test of `ab_eval.py`:
  - Command used (no seed): holdout `IMG_0004.JPG`, theme `roblox_obby`, `--no-images`.
  - Output root: `samples/output/ab_eval_smoke/20260311_170208`
  - Scorecard generated successfully:
    - `B selected source`: `curated_exemplars`
    - `B selected count`: `3`
    - Aggregate result: tie (`Delta score = 0`) for this single holdout.
- Verified run provenance files are emitted as designed:
  - Per variant `artifacts/rag_context.json`
  - Frozen artifacts under `frozen/artifacts/` (`source_model.json`, `skill_model.json`)
- Additional retrieval quality fix validated:
  - Curated exemplar retrieval deduplicates by `source_hash`.
  - Test coverage updated and passing.

**Current status (ready to run):**
- `ab_eval.py` is operational for deterministic paired A/B.
- RAG adaptation context now quality-gated (curated-first + deduped).
- Recommended next run is multi-target holdouts with seeding enabled to produce aggregate evidence.

### Session 23 — 2026-03-14 (UFLI Corpus Pipeline Execution)
**Participants:** User + Claude Opus 4.6
**What happened:**
- Executed the UFLI corpus pipeline (crawl → acquire → extract → index):
  - **Crawl**: Successfully crawled all 15 UFLI Toolbox lesson group pages, captured 148 lessons into `data/ufli/manifest.jsonl`. Zero errors, ~60 seconds total with polite rate limiting.
  - **Acquire**: Downloaded 539 resource files across all 148 lesson directories. Hit macOS Python 3.13 SSL issue — `urllib.request.urlretrieve` fails because Python 3.13 ships without a default CA bundle. Fixed by adding `certifi` package and replacing `urlretrieve` with `urlopen(req, context=ssl_ctx)` + chunked file write. All 148 lessons marked `acquired`.
    - Resource breakdown: 148 PPTX slide decks, 131 decodable passage PDFs, 134 home practice PDFs, 126 additional activity PDFs
  - **Extract**: Successfully extracted text from all 148 lessons into `data/ufli/normalized.jsonl` using python-pptx (PPTX) and PyMuPDF (PDF).
  - **Index**: BLOCKED by Vertex AI permissions. The ADC user account gets 403 `PERMISSION_DENIED` on `aiplatform.endpoints.predict` for model `gemini-embedding-exp-03-07`. Re-authenticated ADC with `--project=ws-builder-rag` and quota project was accepted, but embedding calls still fail. Possible causes: (1) user IAM role missing `aiplatform.user`, (2) experimental model may need allowlist, (3) need service account key instead of user ADC.
- **Code changes**:
  - `corpus/ufli/acquire.py` — Added `certifi`, `ssl` imports; created `_SSL_CTX` with certifi CA bundle; replaced `urlretrieve` with `urlopen` + chunked write for SSL compatibility
- **Data on disk**:
  - `data/ufli/manifest.jsonl` — 148 records, all status `acquired`
  - `data/ufli/raw/` — 148 directories, 539 files (PPTX + PDF)
  - `data/ufli/normalized.jsonl` — 148 extracted lesson records
  - `vector_store/` — empty (indexing not yet completed)

**What's next:**
- Fix Vertex AI auth to unblock `ingest index` step. Options: (1) grant `roles/aiplatform.user` to `howiejong@gmail.com` on `ws-builder-rag`, (2) use service account key file, (3) try `GEMINI_EMBEDDING_MODEL=text-embedding-005` (GA model, not experimental), (4) switch to API key auth (`GOOGLE_API_KEY`) with non-Vertex client
- Once indexing works: `GOOGLE_CLOUD_PROJECT=ws-builder-rag python -m corpus.ufli.ingest index --data-dir ./data/ufli`
- The ingestion is idempotent — re-running is safe

### Session 24 — 2026-03-14 (RAG Backend Fallback Hardening + Successful Corpus Index)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Hardened the RAG embedding path to reduce dependence on the failing Vertex ADC setup:
  - `rag/client.py` now supports `RAG_GEMINI_BACKEND=auto|api_key|vertex`
  - Auto mode prefers `GOOGLE_API_KEY` / `GEMINI_API_KEY` when present, otherwise falls back to Vertex via `GOOGLE_CLOUD_PROJECT`
  - `rag/embeddings.py` now retries embedding requests across model candidates in order: configured model, `gemini-embedding-2-preview`, `text-embedding-005`
  - `corpus/ufli/ingest.py` now loads `.env`, so `python -m corpus.ufli.ingest ...` sees the same key/project config as `transform.py`
- Added regression coverage:
  - `tests/test_rag_client.py` — backend selection for api-key and Vertex modes
  - `tests/test_rag_embeddings.py` — fallback-to-next-model behavior
- Re-ran the live corpus index outside the sandbox after a sandbox DNS failure:
  - `python -m corpus.ufli.ingest index --data-dir ./data/ufli`
  - Auto-selected API-key backend from `.env`
  - Successfully embedded against `gemini-embedding-2-preview`
  - Indexed all 148 lessons into the `curriculum` collection in `vector_store/`
  - Verified local Chroma count: `148`
- Validation run:
  - `.venv/bin/pytest -q tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_corpus_ingest.py` → `14 passed`
  - `.venv/bin/ruff check rag/client.py rag/embeddings.py corpus/ufli/ingest.py tests/test_rag_client.py tests/test_rag_embeddings.py` → clean
  - `.venv/bin/mypy rag/client.py rag/embeddings.py corpus/ufli/ingest.py tests/test_rag_client.py tests/test_rag_embeddings.py` → clean

**What's next:**
- Completed in Session 25: RAG Phase 7 module implementation (`rag/backfill.py`, `rag/eval.py`)
- Next remaining follow-up: consume `curriculum_references` in `adapt/engine.py` for curriculum-aware target-word validation

### Session 25 — 2026-03-14 (Phase 7 Modules: Backfill + Eval)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Implemented `rag/backfill.py`:
  - Scans artifact directories for `source_model.json`, `skill_model.json`, `adapted_model*.json`, `validation*.json`, and matching PDFs
  - Reconstructs `index_run()` payloads from saved artifacts rather than requiring a fresh pipeline run
  - Aggregates per-worksheet validation files for multi-worksheet runs
  - Resolves nested `artifacts/` directories back to their corresponding PDF output directories
- Implemented `rag/eval.py`:
  - Freezes extraction + skill per input using the existing A/B helper path
  - Computes retrieval@3 using current `RAGContext`
  - Runs baseline vs RAG variants and reports validator pass rate, format-change rate, unique RAG format sets, and distractor novelty
  - Writes both `report.json` and `report.md`
- Added focused tests:
  - `tests/test_rag_backfill.py`
  - `tests/test_rag_eval.py`
- Validation run:
  - `.venv/bin/pytest -q tests/test_rag_backfill.py tests/test_rag_eval.py tests/test_rag_client.py tests/test_rag_embeddings.py tests/test_rag_retrieval.py tests/test_corpus_ingest.py tests/test_retrieval_curriculum.py` → `25 passed`
  - `.venv/bin/ruff check rag/backfill.py rag/eval.py rag/__init__.py tests/test_rag_backfill.py tests/test_rag_eval.py` → clean
  - `.venv/bin/mypy rag/backfill.py rag/eval.py rag/__init__.py tests/test_rag_backfill.py tests/test_rag_eval.py` → clean

**What's next:**
- Integrate `curriculum_references` into `adapt/engine.py`
- Decide whether `rag/eval.py` should replace or complement `ab_eval.py`
- Run a real evaluation pass and, if useful, a live `rag.backfill` smoke run against saved outputs

### Session 29 — 2026-03-15 (UFLI Audio Companion Research + Rollout Plan)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Completed a research pass using Perplexity, Exa, and Jina on:
  - evidence-based early reading instruction for Ontario and BC primary learners
  - ADHD-supportive classroom/audio design for ages 5–8
  - ElevenLabs model and voice-setting guidance
- Confirmed the audio companion path should be transcript-first, pilot-first, and treated as support for explicit reading instruction rather than as a replacement for decoding instruction.
- Confirmed rollout scope is numeric UFLI lessons `1–128`, not `1–34`.
- Wrote a staged rollout plan for a pilot-first UFLI audio companion pipeline:
  - Stage 0 scaffold refinement
  - Stage 1 micro-pilot (`1`, `14`, `95`) with two voice profiles
  - Stage 2 representative pilot (`1`, `14`, `34`, `64`, `95`, `128`)
  - Stage 3 controlled batch rollout by lesson band
  - Stage 4 full corpus completion and hardening
- Plan file created at `plans/ufli-audio-companion-rollout-plan.md`.

**Key decisions locked:**
- Human signoff is required before scaling beyond the pilot.
- Pilot set should be representative, not random.
- Voice selection is part of the pilot; compare two voice profiles before committing.
- Default TTS model for pilot should be `eleven_multilingual_v2`, with `eleven_flash_v2_5` as fallback.
- Indexed clip taxonomy should focus on:
  - `lesson_instruction`
  - `phoneme_model`
  - `word_model`
  - `passage_sentence`
  - `passage_full`
  - `review`
- `encouragement` should not be part of indexed lesson content.
- Add committed config/data contracts for:
  - pronunciation lexicon
  - voice profiles
  - pilot lesson sets

**What’s next:**
- Implement Stage 0 and Stage 1 only.
- Do not run full-corpus generation until pilot review passes and user signs off.
- Start by refining the existing `corpus/ufli/audio_companion.py` scaffold and CLI commands to match the rollout plan.

**Primary files to open first next session:**
- `plans/ufli-audio-companion-rollout-plan.md`
- `.claude/worksheet-project-context.md`
- `corpus/ufli/audio_companion.py`
- `corpus/ufli/audio_companion_schema.py`
- `corpus/ufli/ingest.py`

### Session 30 — 2026-03-16 (UFLI Child MVP Audio Remediation Report Consolidation)
**Participants:** User + Codex (GPT-5.2-Codex)
**What happened:**
- Continued UFLI audio companion handoff work with Stage 1 pilot-only scope (`1`, `14`, `95`) and explicit-reading-support framing.
- Produced consolidated remediation report at:
  - `data/ufli/companion/evals/20260316_mvp_child_audio_remediation_report.md`
- Report groups required findings into:
  - extraction/target-selection errors
  - decoding-first instructional violations
  - pacing by clip family
  - pronunciation
  - clarity/intelligibility
  - lesson-specific issues (`1`, `14`, `95`)
- Report includes per-pattern dispositions (`fix content`, `fix prompt/template`, `fix pacing/voice settings`, `remove`, `regenerate`) and likely code locations to edit next.

**Environment/verification notes:**
- Requested path `/Users/hjong/Documents/Projects/worksheet-builder/.claude/worksheet-project-context.md` is not available in this container checkout.
- Requested historical eval directories are referenced in context but not present on disk in this checkout:
  - `data/ufli/companion/evals/20260316_124158`
  - `data/ufli/companion/evals/20260316_121249`
  - `data/ufli/companion/evals/20260316_122938`
- Due missing local eval artifacts and unavailable dependency installation in this environment, this pass consolidated remediation using latest documented judge outcomes plus current code-path inspection.

**Commands run:**
- `sed -n '1,80p' .claude/worksheet-project-context.md`
- `git log -n 5 --date=iso --pretty=format:'%h %ad %an %s' -- .claude/worksheet-project-context.md`
- `rg --files | rg 'ufli/companion|audio_judge|audio_companion|worksheet-project-context'`
- `find data/ufli/companion -maxdepth 3 -type d | sort`
- `rg -n '20260316_124158|20260316_121249|20260316_122938|blocker|pacing_suitability' .claude/worksheet-project-context.md corpus tests data`
- `nl -ba corpus/ufli/audio_companion.py | sed -n '660,1160p'`
- `nl -ba corpus/ufli/audio_judge.py | sed -n '520,700p'`
- `nl -ba data/ufli/companion/voice_profiles.yaml | sed -n '1,220p'`

**What’s next:**
1. Implement target-sanitization hardening in `_extract_word_targets` path.
2. Rewrite decoding-first instruction/review templates in `_lesson_instruction_text` + `_review_text`.
3. Reduce pacing in `data/ufli/companion/voice_profiles.yaml` for high-risk clip families.
4. Tighten pronunciation anchor handling (`pronunciation_lexicon.yaml`, target-selection helpers).
5. Regenerate pilot clips and rerun `judge-audio` for lessons `1`, `14`, and `95`.

### Session 31 — 2026-03-16 (CI workflow dependency fix)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Investigated likely CI failure path and confirmed OpenCV imports require system GL runtime.
- Updated GitHub Actions CI apt install step to include `libgl1` and `libglib2.0-0` alongside `tesseract-ocr` so `cv2` imports succeed in Ubuntu runners.
- Local lint check still passes after workflow update.

**What’s next:**
- Re-run CI on GitHub to confirm the missing shared-library failure is resolved.
- If CI still fails, share the exact failing job log so we can address the next blocker directly.

### Session 32 — 2026-03-17 (Lesson 74 Roblox Worksheets + PDF Pagination/Spacing Fix)
**Participants:** User + Codex (GPT-5)
**What happened:**
- Produced ADHD-adapted, Roblox-themed lesson 74 worksheet outputs for:
  - `data/ufli/raw/74/decodable_passage_pdf.pdf`
  - `data/ufli/raw/74/home_practice_pdf.pdf`
- Rendered source PDFs to page PNGs for inspection, but the image-first transform path was unreliable on the decodable source because Gemini vision returned no regions and OCR produced an empty/unknown extraction.
- Switched to a curated lesson-content path using strict `LiteracySkillModel` inputs built from the already-extracted UFLI lesson text so the output preserved the intended lesson 74 targets:
  - decodable passage skill: `decodable_text_y_as_long_e`
  - home practice skill: `y_as_long_e`
- Regenerated final outputs under:
  - `output/pdf/ufli_lesson74_roblox/decodable_passage_curated/`
  - `output/pdf/ufli_lesson74_roblox/home_practice_curated/`
- Confirmed the worksheet asset generation path uses `gemini-3.1-flash-image-preview` in `render/asset_gen.py`. The final `*_with_images.pdf` outputs now embed generated Roblox companion scene art, and the lesson-74 regeneration summary lives at:
  - `output/pdf/ufli_lesson74_roblox/regeneration_summary.json`
- Fixed a real pagination defect in `render/pdf.py`:
  - the renderer previously decided to paginate after drawing a chunk, so content could run off the bottom of the page
  - the fix now estimates chunk height up front and starts a new page before overflow
  - related lesson-74 outputs were rerendered after the fix
- Improved worksheet visual separation in `render/pdf.py`:
  - increased section spacing after instructions and examples
  - increased per-item spacing in match/trace/circle/fill-blank/read-aloud layouts
  - widened chunk divider spacing
  - kept chunk-height estimation in sync so the extra spacing does not reintroduce clipping
- Added render regression coverage in `tests/test_render.py` to ensure integrated-scene layouts move the next chunk onto a fresh page before bottom clipping.

**Validation run:**
- `.venv/bin/ruff check render/pdf.py tests/test_render.py` → clean
- `.venv/bin/mypy render/pdf.py tests/test_render.py` → clean
- `.venv/bin/pytest -q tests/test_render.py` → `21 passed`

**Current output status:**
- Final PDFs to open:
  - `output/pdf/ufli_lesson74_roblox/decodable_passage_curated/decodable_passage_curated_1of2_with_images.pdf`
  - `output/pdf/ufli_lesson74_roblox/decodable_passage_curated/decodable_passage_curated_2of2_with_images.pdf`
  - `output/pdf/ufli_lesson74_roblox/home_practice_curated/home_practice_curated_1of3_with_images.pdf`
  - `output/pdf/ufli_lesson74_roblox/home_practice_curated/home_practice_curated_2of3_with_images.pdf`
  - `output/pdf/ufli_lesson74_roblox/home_practice_curated/home_practice_curated_3of3_with_images.pdf`
- Matching preview PNGs were regenerated in the same directories.
- Page splitting is now explicit where needed (for example, the home-practice `Word Discovery` worksheet now cleanly pushes `Trace 4 words` to page 2 instead of clipping it at the bottom of page 1).

**Gotchas/notes for next session:**
- The original image-first transform path for lesson 74 decodable input (`transform.py` on the rendered page PNG) is still brittle because Gemini vision can return zero regions for some source pages and OCR may not recover enough structure; the curated skill-model path produced the usable outputs for this session.
- Some home-practice picture matches were regenerated from the lesson-specific asset pipeline, but if the user wants even richer word-specific picture coverage for every match tile, the next pass should focus specifically on `plan_word_pictures()` / `generate_worksheet_assets()` outputs for those worksheets rather than on pagination/layout.

**What’s next:**
- If the user wants more polish, continue tuning `render/pdf.py` spacing with side-by-side preview review against the lesson-74 regenerated PNGs.
- If the user wants richer match-tile imagery, explicitly inspect the lesson-74 home-practice asset cache directories from `regeneration_summary.json` and regenerate or backfill any missing word pictures.
