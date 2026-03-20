# Multimodal Corpus Audit Plan

## Summary
Add a repeatable corpus audit command that evaluates three corpus families per lesson: core curriculum text, image companion content, and audio companion content. The audit will run fully offline by default and write timestamped Markdown/JSON/CSV reports. It will work now for text-only corpora and automatically expand its checks when image/audio companion manifests appear.

The key design choice is:
- image companion content is audited as true multimodal content now, because the repo already supports image and fused text+image embeddings in `rag/embeddings.py`
- audio companion content is audited transcript-first for retrieval and quality, with audio asset sanity checks alongside it
- raw audio is not the retrieval primitive in this phase; transcript text plus audio metadata is

## Key Changes
### 1. Add modality-aware corpus manifests and audit inputs
The audit should expect these optional inputs under `data/ufli/companion/`:
- `images.jsonl`
- `audio.jsonl`

Use these normalized shapes:

For image companion records:
- `lesson_id`
- `asset_id`
- `asset_type`
  default enum: `scene`, `character`, `word_picture`, `diagram`, `cover`
- `sequence_index`
- `image_path`
- `caption_text`
- `alt_text`
- `prompt_text` optional
- `source_modality = "image_companion"`
- `status`

For audio companion records:
- `lesson_id`
- `segment_id`
- `segment_type`
  default enum: `intro`, `instruction`, `worked_example`, `encouragement`, `review`
- `sequence_index`
- `audio_path`
- `duration_ms`
- `transcript_text`
- `speaker`
- `source_modality = "audio_companion"`
- `status`

Defaults:
- These manifests are optional.
- If absent, the audit reports the modality as `not_present`.
- The core text audit must still pass independently.

### 2. Add a single audit CLI that handles text, image, and audio
Expose one command:
`python -m corpus.ufli.ingest audit --data-dir data/ufli --db-path vector_store --output-dir data/ufli/audit --sample-size 20 --benchmark-size 50 --seed 42 --use-ai-judge/--no-ai-judge`

Outputs:
- `report.md`
- `summary.json`
- `record_metrics.csv`
- `flags.csv`
- `manual_review_sample.csv`
- `retrieval_benchmark.json`

The report should be organized by:
1. Executive summary
2. Corpus inventory and modality coverage
3. Text curriculum quality
4. Image companion quality
5. Audio companion quality
6. Retrieval benchmark
7. Manual review pack
8. Action items

### 3. Audit core text curriculum quality
Keep the original text audit and make it the baseline:
- inventory parity across:
  - `manifest.jsonl`
  - `raw/`
  - `normalized.jsonl`
  - indexed `curriculum` docs
- hard failures:
  - duplicate `lesson_id`
  - malformed JSONL
  - missing required fields
  - empty combined extracted text
- warnings:
  - very short extracted records
  - missing concept text where concept should exist
  - stale or missing index rows
  - near-duplicate lesson documents
- retrieval benchmark:
  - deterministic concept queries and lexical queries
  - metrics: Hit@1, Hit@3, Hit@5, MRR, grade-filter correctness

### 4. Audit image companion corpus quality
Automate these checks for each image asset:
- file integrity:
  - path exists
  - readable image
  - width/height present
  - file size > 0
- metadata quality:
  - non-empty `caption_text`
  - non-empty `alt_text`
  - valid `asset_type`
  - valid `lesson_id`
- caption heuristics:
  - flag captions under 8 words
  - flag placeholder/generic captions like filename-only text
  - flag captions with no lexical overlap with lesson concept/curriculum tokens
- duplicate detection:
  - exact duplicate by file hash
  - near-duplicate by perceptual hash or image embedding similarity
  - flag cross-lesson near-duplicates above threshold
- modality coverage:
  - lesson has expected image companion count by `asset_type`
  - report missing image companions per lesson
- multimodal retrieval benchmark:
  - when indexed companion image embeddings exist, test:
    - caption query -> expected lesson image in top-k
    - concept query -> expected lesson image in top-k
  - if no image companion index exists yet, mark retrieval section `skipped`

Default heuristics:
- caption under 8 words => warn
- exact duplicate across lessons => fail unless explicitly allowlisted
- near-duplicate image similarity >= 0.98 => warn
- missing caption or alt text => fail

### 5. Audit audio companion corpus quality
Automate these checks for each audio segment:
- file integrity:
  - path exists
  - readable asset
  - `duration_ms > 0`
- transcript quality:
  - non-empty `transcript_text`
  - transcript length above minimum threshold
  - no obvious placeholder text
- transcript-duration sanity:
  - compute words per minute from `transcript_text` and `duration_ms`
  - warn for outliers
- transcript coverage:
  - every expected lesson segment type present
  - segment ordering via `sequence_index`
  - no missing transcript for an existing audio file
- duplicate detection:
  - exact duplicate transcript hash
  - near-duplicate transcript similarity
  - repeated boilerplate across many lessons flagged separately from true duplicates
- retrieval usefulness:
  - transcript-only benchmark now
  - segment-type-aware queries later when enough data exists

Default heuristics:
- transcript under 5 words => fail
- WPM < 80 or > 220 => warn
- missing transcript for present audio asset => fail
- exact duplicate transcript across different lessons => warn unless `segment_type` is known boilerplate like encouragement
- same transcript reused in >20% of lessons for non-boilerplate segment types => fail

### 6. Add modality coverage and cross-modality consistency checks
Per lesson, the audit should compute:
- text corpus present
- image companion present
- audio companion present
- asset counts by modality
- missing required segment/asset types
- cross-modality consistency

Cross-modality consistency checks:
- image caption lexical overlap with lesson concept or normalized text tokens
- audio transcript lexical overlap with lesson concept or normalized text tokens
- optional overlap checks between image captions and audio transcripts for the same lesson
- flag lessons where companion content appears semantically detached from the lesson concept

Default output:
- per-lesson modality coverage score
- counts of lessons with:
  - text only
  - text + image
  - text + audio
  - full multimodal support

### 7. Add a manual review pack for multimodal spot-checking
Produce a deterministic stratified sample across:
- lesson groups
- flagged text records
- flagged image records
- flagged audio records

`manual_review_sample.csv` should include:
- `lesson_id`
- `record_type`
  values: `text`, `image`, `audio`
- `asset_id_or_segment_id`
- `flags`
- `review_extraction_ok`
- `review_metadata_ok`
- `review_relevance_ok`
- `notes`

Manual checklist:
- text: extracted content matches lesson and is not truncated
- image: caption/alt text actually describes the image and fits the lesson
- audio: transcript matches intended segment and fits lesson purpose
- retrieval: top-k results are genuinely useful, not just lexically similar

## Public Interfaces / Types
Add an `audit` subcommand to the existing corpus CLI in `corpus/ufli/ingest.py`.

Add new internal audit result types:
- `CorpusAuditSummary`
- `LessonAuditRecord`
- `RetrievalBenchmarkResult`
- `DuplicateCluster`
- `ManualReviewRow`

Do not change the existing `normalized.jsonl` lesson shape in this phase.

Add optional companion manifest readers for:
- `data/ufli/companion/images.jsonl`
- `data/ufli/companion/audio.jsonl`

Assume companion assets are audited from manifests plus file paths. Do not require they already be indexed into Chroma to run the audit.

## Test Plan
Add tests for:
- manifest parsing for image/audio companion records
- modality coverage scoring per lesson
- image caption quality heuristics
- transcript-duration sanity checks
- duplicate detection:
  - exact duplicate transcript
  - near-duplicate image cluster
- cross-modality consistency:
  - lesson concept mismatch is flagged
- retrieval benchmark behavior:
  - text benchmark works with current curriculum index
  - image/audio retrieval sections are `skipped` cleanly when companion indexes do not exist
- CLI/report generation:
  - audit runs with only text corpus
  - audit runs with text + image manifests
  - audit runs with text + audio manifests
  - output files contain modality-specific sections

### 8. Audit-driven remediation

Add a `remediate` subcommand that reads the most recent audit output and applies automated fixes for actionable flag codes. The user re-audits manually after reviewing the remediation report.

**CLI:**
```bash
python -m corpus.ufli.ingest remediate \
  --data-dir data/ufli \
  --db-path vector_store \
  --audit-dir data/ufli/audit/20260319_123456 \
  --dry-run
```

Flags:
- `--audit-dir`: path to a timestamped audit output directory (must contain `summary.json`). Defaults to the most recent directory under `data/ufli/audit/`.
- `--dry-run`: report what would be fixed without changing anything.
- `--severity fail,warn`: filter which severity levels to act on. Default: `fail,warn`.
- `--codes`: comma-separated allowlist of flag codes to remediate. Default: all actionable codes.
- `--skip-reindex`: fix source data but skip ChromaDB re-indexing.

**Remediation strategies by flag code:**

Text corpus flags:

| Flag code | Severity | Strategy | Existing tooling reused |
|-----------|----------|----------|------------------------|
| `very_short_record` | warn | Re-extract lesson from raw files | `extract.extract_lesson()` |
| `empty_extracted_text` | fail | Re-extract lesson from raw files | `extract.extract_lesson()` |
| `missing_concept` | warn | Backfill concept from `manifest.jsonl` if available; skip if manifest also empty (lessons A-J are pre-phonics "Getting Ready" with no concept by design) | `manifest.jsonl` read |
| `missing_curriculum_index` | warn | Embed and upsert lesson into ChromaDB | `embed_text()` + `add_document()` |
| `stale_curriculum_index` | warn | **Delete** the stale entry from ChromaDB (lesson no longer exists in `normalized.jsonl`) | `collection.delete(ids=[doc_id])` |
| `missing_raw_dir` | warn | Log as manual action required (source files need re-downloading) | — |
| `malformed_jsonl` | fail | Log as manual action required (corrupt source data) | — |
| `missing_required_fields` | fail | Re-extract lesson from raw files if `lesson_id` is known; skip if `lesson_id` is empty (can't identify which lesson to re-extract) | `extract.extract_lesson()` |
| `duplicate_lesson_id` | fail | Log as manual action required (data integrity issue) | — |
| `near_duplicate_lesson_text` | warn | Log as manual review required | — |
| `malformed_manifest_jsonl` | fail | Log as manual action required (corrupt manifest) | — |

Image companion flags:

| Flag code | Severity | Strategy | Existing tooling reused |
|-----------|----------|----------|------------------------|
| `missing_image_file` | fail | Log as manual action required | — |
| `empty_image_file` | fail | Log as manual action required | — |
| `unreadable_image` | fail | Log as manual action required | — |
| `missing_caption` | fail | Log as manual action required | — |
| `missing_alt_text` | fail | Log as manual action required | — |
| `short_caption` | warn | Log as manual review required | — |
| `placeholder_caption` | warn | Log as manual review required | — |
| `caption_concept_mismatch` | warn | Log as manual review required | — |
| `exact_duplicate_image` | fail | Log as manual review required | — |
| `near_duplicate_image` | warn | Log as manual review required | — |
| `unknown_lesson_id` | fail | Log as manual action required (image references a lesson not in `normalized.jsonl`) | — |

Audio companion flags (note: `unknown_lesson_id` also appears for audio records):

| Flag code | Severity | Strategy | Existing tooling reused |
|-----------|----------|----------|------------------------|
| `missing_audio_file` | fail | Re-generate via audio companion (pilot lessons only; see constraint below) | `generate_audio_companion(force=True, lesson_id=X)` |
| `empty_audio_file` | fail | Re-generate via audio companion (pilot lessons only) | `generate_audio_companion(force=True, lesson_id=X)` |
| `unreadable_audio` | fail | Re-generate via audio companion (pilot lessons only) | `generate_audio_companion(force=True, lesson_id=X)` |
| `invalid_duration` | fail | Re-generate via audio companion (pilot lessons only) | `generate_audio_companion(force=True, lesson_id=X)` |
| `missing_transcript` | fail | Log as manual action required (transcript is source data, not generated) | — |
| `short_transcript` | fail | Log as manual action required | — |
| `placeholder_transcript` | warn | Log as manual action required | — |
| `wpm_outlier` | warn | Re-generate audio clip (pilot lessons only; ElevenLabs TTS is non-deterministic so a retry may produce better pacing, but is not guaranteed — voice settings are unchanged) | `generate_audio_companion(force=True, lesson_id=X)` |
| `transcript_concept_mismatch` | warn | Log as manual review required | — |
| `duplicate_transcript` | warn | Log as manual review required | — |
| `boilerplate_transcript_overuse` | fail | Log as manual review required | — |
| `duplicate_sequence_index` | warn | Log as manual review required | — |
| `non_contiguous_sequence_index` | warn | Log as manual review required | — |
| `unknown_lesson_id` | fail | Log as manual action required (audio references a lesson not in `normalized.jsonl`) | — |

Codes not listed above are skipped with a log message "no automated fix available".

**Implementation approach:**

**New file:** `corpus/ufli/remediate.py`

- `RemediationAction` Pydantic model: `flag: AuditFlag`, `strategy: str`, `status: Literal["pending", "fixed", "skipped", "manual_review", "failed"]`, `detail: str`
- `RemediationReport` Pydantic model: `actions: list[RemediationAction]`, `fixed_count`, `skipped_count`, `manual_review_count`, `failed_count`, `reindexed_lesson_ids: list[str]`, `deleted_index_ids: list[str]`
- `plan_remediations(summary: CorpusAuditSummary, severity_filter, code_filter) -> list[RemediationAction]`: reads flags, maps each to a strategy, deduplicates by lesson_id per strategy (one re-extract per lesson even if multiple flags trigger it, one audio regen per lesson even if multiple audio flags)
- `execute_remediations(actions, data_dir, db_path, dry_run, skip_reindex) -> RemediationReport`: applies fixes in a specific order to avoid conflicts:
  1. **Re-extract phase**: collect all lesson_ids needing re-extraction. For each lesson, look up `lesson_group` and `concept` from `manifest.jsonl` (required by `extract_lesson()` signature). Call `extract_lesson(lesson_id, lesson_group, concept, data_dir)`. If re-extraction returns `None` (no raw files found), mark the action as `failed` with detail explaining the raw directory is missing. Collect all successful re-extractions, then do a **single** read-modify-write pass on `normalized.jsonl` to patch all of them atomically — do not interleave reads and writes.
  2. **Concept backfill phase**: for `missing_concept` flags, first check if the lesson was already re-extracted in phase 1 — if so, skip (re-extract already used the manifest concept in the `extract_lesson()` call). For remaining lessons, read `manifest.jsonl` to get concept text. If the manifest also has an empty concept for that lesson (true for lessons A-J), mark the action as `skipped` with detail "manifest also has no concept for this lesson (pre-phonics Getting Ready lesson)". Otherwise, read the existing `normalized.jsonl` line for that lesson, parse it to a dict, update the `concept` field, construct a `LessonContent` from the updated dict, and include it in the patches for the next atomic write pass.
  3. **Index cleanup phase**: for `stale_curriculum_index` flags, **delete** the stale doc from ChromaDB via `collection.delete(ids=[f"curriculum_ufli_{lesson_id}"])`. This is a removal, not an upsert — the lesson no longer exists in `normalized.jsonl`.
  4. **Re-index phase**: for `missing_curriculum_index` flags and all lesson_ids touched by re-extract or concept backfill, re-embed and upsert into ChromaDB. Requires a working Gemini API key for `embed_text()`. If embedding is unavailable (`rag_available()` returns False or `embed_text()` raises), mark re-index actions as `skipped` with detail "embedding API not available — re-run with API key configured" rather than failing the entire remediation. Reuse the same embedding + metadata logic from `ingest_curriculum()` to avoid drift.
  5. **Audio re-generation phase**: collect lesson_ids needing audio fixes. **Constraint:** `generate_audio_companion()` enforces `_enforce_stage1_pilot_scope()` which restricts live generation to pilot lessons {1, 14, 95} only (defined in `data/ufli/companion/pilot_lessons.yaml` under `pilot_micro`). For non-pilot lessons, mark the action as `skipped` with detail "lesson N is outside Stage 1 pilot scope — will be available after Stage 2 rollout". For pilot lessons, call `generate_audio_companion()` Python API directly with `force=True`, `dry_run=False`, `lesson_id=str(X)`. This phase also requires a live ElevenLabs API key. If unavailable, mark as `skipped` with detail.
  6. **Manual review phase**: collect remaining flags that require human review, write to `manual_review_needed.csv`.

- `_load_manifest_lookup(data_dir) -> dict[str, dict]`: read `manifest.jsonl` into a `lesson_id`-keyed dict for fast lookup of `lesson_group` and `concept`. No module-level cache — remediation runs once per invocation and manifest should be read fresh each time (unlike `corpus/ufli/lookup.py` which caches for batch worksheet generation within a single process).
- `_patch_normalized_jsonl(data_dir, patches: dict[str, LessonContent])`: read all lines from `normalized.jsonl`, for each line attempt to parse as JSON and match by `lesson_id` — if matched, replace with the patched `LessonContent` serialized via `dataclasses.asdict()` + `json.dumps()`. Malformed lines (unparseable JSON) are preserved as-is. Write back in a single atomic pass. Preserves original line order. Uses a temp file + `os.replace()` for crash safety.

**Error handling:**

- If `--audit-dir` is omitted, find the most recent timestamped directory under `data/ufli/audit/` by filtering for directories matching `YYYYMMDD_HHMMSS` pattern (`re.fullmatch(r"\d{8}_\d{6}", name)`) and sorting lexicographically. If no matching directories exist, exit with "no audit results found — run `python -m corpus.ufli.ingest audit` first".
- If `--audit-dir` doesn't contain `summary.json`, exit with a clear error message.
- If `extract_lesson()` raises (corrupt PPTX/PDF), catch the exception, mark the action as `failed` with the exception message, and continue with other lessons.
- If `embed_text()` raises for one lesson, mark that lesson's re-index as `failed` and continue with others.
- If `generate_audio_companion()` raises, mark all audio actions for that lesson as `failed` and continue.
- `_patch_normalized_jsonl` writes to a temp file first, then does `os.replace()` to avoid leaving a half-written `normalized.jsonl` on crash.
- All mutations are logged at INFO level with lesson_id so failures are traceable.

**Changes to existing files:**

- `corpus/ufli/ingest.py`: add `remediate` CLI subcommand that loads `summary.json`, calls `plan_remediations()` + `execute_remediations()`, writes report.
- `corpus/ufli/extract.py`: no changes needed — `extract_lesson()` already works per-lesson with `(lesson_id, lesson_group, concept, data_dir)` signature.
- `rag/store.py`: add a `delete_document(collection, doc_id)` wrapper around `collection.delete(ids=[doc_id])` for consistency with the existing `add_document()` API. ChromaDB's `Collection.delete(ids=...)` is available natively but not currently wrapped.

**Re-audit cycle:**

After remediation completes, the CLI prints a summary and suggestion:
```
Remediation complete: 5 fixed, 3 skipped, 2 manual review, 0 failed.
Re-indexed: 43, 58, 72. Deleted stale: 99.
Re-run audit to verify: python -m corpus.ufli.ingest audit --data-dir data/ufli
```

The user runs audit again manually. The remediation report includes `reindexed_lesson_ids` and `deleted_index_ids` so the next audit can be compared against the previous one. No automatic re-audit loop — the human decides when to re-audit.

**Output artifacts** (written to `--audit-dir`):
- `remediation_report.json`: full `RemediationReport` as JSON
- `remediation_report.md`: human-readable summary with per-action status table
- `manual_review_needed.csv`: flags requiring human intervention (columns: `lesson_id`, `record_type`, `code`, `severity`, `message`)

**Known limitations:**

- Lessons A-J (`missing_concept`) cannot be auto-fixed because neither the manifest nor the source files contain concept text. These are pre-phonics "Getting Ready" lessons with no concept by design.
- Audio re-generation is restricted to Stage 1 pilot lessons {1, 14, 95} by `_enforce_stage1_pilot_scope()`. Audio flags for non-pilot lessons are marked `skipped` until Stage 2+ broadens the scope. This is a deliberate safety constraint, not a bug.
- Audio re-generation also requires a live ElevenLabs API key. The remediation `--dry-run` flag controls whether remediation *plans* or *executes* fixes. When executing audio fixes, the underlying `generate_audio_companion()` is called with `dry_run=False` (since the point is to actually regenerate). These are two distinct dry-run concepts: remediation-level vs. generation-level.
- Re-indexing requires a Gemini API key for `embed_text()`. Without one, the re-index phase is skipped (not failed) and the user is told to re-run later.
- `missing_raw_dir` cannot be auto-fixed — the raw source files need to be re-downloaded via `python -m corpus.ufli.ingest acquire`.
- Transcript and caption quality flags (`missing_transcript`, `missing_caption`, `short_caption`, etc.) are manual review because these are source data problems, not generation problems.
- Re-extraction can only help if the raw files in `data/ufli/raw/<lesson_id>/` contain better content than what was previously extracted. If the PPTX/PDF source is itself low-quality (OCR artifacts, corrupt file), re-extraction will produce the same result. The action is still worth attempting because extraction code may have been improved since the original run.

**Test plan additions:**

- `test_plan_remediations_filters_by_severity`: only `fail`+`warn` flags produce actions; `info` and `skipped` are ignored
- `test_plan_remediations_deduplicates_by_lesson`: multiple flags for lesson 43 produce one re-extract action, not N
- `test_plan_remediations_deduplicates_audio_by_lesson`: multiple audio flags for the same lesson produce one regen action
- `test_execute_dry_run_changes_nothing`: dry run returns report but `normalized.jsonl` is unchanged (compare file hash before/after)
- `test_patch_normalized_jsonl_preserves_order`: patching one lesson doesn't reorder others; patching multiple lessons in one pass works correctly
- `test_patch_normalized_jsonl_atomic_write`: write failure doesn't leave a half-written file (mock `os.replace` to fail, verify original file is intact)
- `test_concept_backfill_from_manifest`: `missing_concept` flag with non-empty manifest concept patches `normalized.jsonl`
- `test_concept_backfill_skipped_for_empty_manifest`: `missing_concept` for lesson A (manifest concept also empty) produces `skipped` status
- `test_reextract_needs_manifest_metadata`: re-extract looks up `lesson_group` and `concept` from manifest before calling `extract_lesson()`
- `test_reextract_failed_when_raw_dir_missing`: re-extract for a lesson with no `data/ufli/raw/<id>/` directory produces `failed` status
- `test_reindex_uses_upsert`: re-indexed lesson overwrites old ChromaDB entry (mocked `add_document`)
- `test_reindex_skipped_without_api_key`: re-index with unavailable embedding API produces `skipped` status (mocked)
- `test_stale_index_deleted_not_upserted`: `stale_curriculum_index` flag triggers `collection.delete()`, not `add_document()` (mocked)
- `test_manual_review_flags_not_auto_fixed`: `near_duplicate_lesson_text` produces `manual_review` status
- `test_audio_regen_calls_generate_audio_companion`: audio flag for pilot lesson routes to `generate_audio_companion()` with `force=True` (mocked)
- `test_audio_regen_skipped_for_non_pilot_lesson`: audio flag for lesson 43 (not in pilot scope) produces `skipped` status
- `test_audio_regen_skipped_without_api_key`: audio regen without ElevenLabs key produces `skipped` status
- `test_patch_normalized_jsonl_preserves_malformed_lines`: a malformed (non-JSON) line in `normalized.jsonl` is preserved as-is after patching other lessons
- `test_concept_backfill_skipped_when_reextract_handled_lesson`: if phase 1 re-extract already replaced a lesson, phase 2 concept backfill skips it (concept was already set via `extract_lesson()`'s `concept` parameter)
- `test_delete_document_wrapper`: `delete_document()` in `rag/store.py` calls `collection.delete(ids=[doc_id])` (mocked)

## Assumptions and Defaults
- Offline audit remains the default.
- Optional AI judge mode is advisory only and used for sampled retrieval relevance, not as the primary score.
- Image companion content is audited now as multimodal-ready, because image embeddings are already supported.
- Audio companion content is transcript-first until a true audio embedding/indexing path is added.
- Companion asset manifests are optional and may arrive before companion indexing exists.
- No CI gating by default; malformed records, empty required text, and missing companion transcripts for declared audio assets are the only default fail-level conditions.
