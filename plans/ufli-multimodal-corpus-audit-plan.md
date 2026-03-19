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

## Assumptions and Defaults
- Offline audit remains the default.
- Optional AI judge mode is advisory only and used for sampled retrieval relevance, not as the primary score.
- Image companion content is audited now as multimodal-ready, because image embeddings are already supported.
- Audio companion content is transcript-first until a true audio embedding/indexing path is added.
- Companion asset manifests are optional and may arrive before companion indexing exists.
- No CI gating by default; malformed records, empty required text, and missing companion transcripts for declared audio assets are the only default fail-level conditions.
