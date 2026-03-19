# Pilot-First UFLI Audio Companion Rollout

## Summary
Implement a staged, evidence-informed audio companion pipeline for UFLI numeric lessons `1–128` that treats audio as a support for explicit reading instruction, not a replacement for it. The rollout must minimize ElevenLabs spend by validating voice, clip taxonomy, pronunciation, pacing, and retrieval on a small pilot before any large-scale generation.

Success criteria for scaling:
- No critical pronunciation or instructional-meaning errors in pilot clips
- Human review median `>= 4/5` for `pronunciation`, `pacing`, `focus`, and `helpfulness`
- Pilot retrieval/indexing passes on generated audio manifests and Chroma records
- User signoff is required before moving from pilot to broader generation

Evidence base used for defaults:
- [Ontario Effective Early Reading Instruction, 2022](https://assets-us-01.kc-usercontent.com/fbd574c4-da36-0066-a0c5-849ffb2de96e/6827ed32-baf6-48a1-afe8-6e53f8c5eda8/EN%20Effective%20Early%20Reading-19-04-2022-AODA.pdf)
- [BC Early Literacy Screening FAQ](https://www2.gov.bc.ca/assets/gov/education/kindergarten-to-grade-12/support/diverse-student-needs/learning-supports/early-literacy-screening-faq.pdf)
- [CDC ADHD classroom guidance, updated October 22, 2024](https://www.cdc.gov/adhd/treatment/classroom.html)
- [Canadian Paediatric Society ADHD treatment statement, reaffirmed January 11, 2024](https://cps.ca/documents/position/adhd-2-treatment)
- [Wood et al. TTS meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC5494021/)
- [ElevenLabs TTS docs](https://elevenlabs.io/docs/capabilities/text-to-speech) and [voice settings docs](https://elevenlabs.io/docs/speech-synthesis/voice-settings)

## Staged Rollout
### Stage 0: Refine the current scaffold before any live generation
- Keep all work under the existing `corpus/ufli` audio companion path and `corpus/ufli/ingest.py` CLI; do not add a separate standalone project.
- Replace the current "generate many generic lesson clips" approach with a fixed instructional taxonomy:
  - `lesson_instruction`
  - `phoneme_model`
  - `word_model`
  - `passage_sentence`
  - `passage_full`
  - `review`
- Remove `encouragement` from indexed content and make global encouragement/transitions shared assets only, not per-lesson indexed clips.
- Add a committed pronunciation/normalization contract:
  - `pronunciation_lexicon.yaml` for phonemes, graphemes, affixes, special words, and approved TTS text
  - `voice_profiles.yaml` for model, voice id, and settings
  - `pilot_lessons.yaml` for fixed pilot lesson sets
- Keep `normalized.jsonl` unchanged.

### Stage 1: Micro-pilot for voice and taxonomy validation
- Pilot lessons: `1`, `14`, `95`
  - `1`: early lesson with no decodable passage
  - `14`: early passage lesson
  - `95`: later vowel-team lesson
- Compare exactly two voice profiles:
  - `dorothy` using the existing voice id
  - `neutral_na_pilot` using a neutral North American child-friendly voice id supplied in config before generation
- Generate only these clip families in the micro-pilot:
  - `lesson_instruction`
  - `phoneme_model`
  - `word_model`
  - `passage_sentence` and `passage_full` when present
  - `review`
- Use `eleven_multilingual_v2` as the default pilot model and `eleven_flash_v2_5` as the fallback cost/speed profile; do not use `eleven_turbo_v2_5` as the default.
- Default voice settings:
  - `passage_*`: stability `0.65`, similarity `0.75`, style `0`, speed `0.92`
  - `word_model`: stability `0.70`, similarity `0.78`, style `0`, speed `0.84`
  - `phoneme_model`: stability `0.72`, similarity `0.78`, style `0`, speed `0.76`
  - `lesson_instruction` and `review`: stability `0.68`, similarity `0.76`, style `0`, speed `0.90`
- Add a dry-run estimator that reports per-voice clip count, total characters, and projected cost before any API call.
- Output a timestamped pilot review packet under `data/ufli/companion/pilots/<timestamp>/` containing:
  - `review.md`
  - `review.csv`
  - `clips.json`
  - `playlist.m3u`
  - generated audio files
- Gate: scale only after human review selects one voice profile and approves the taxonomy.

### Stage 2: Representative pilot with the winning voice
- Pilot lessons: `1`, `14`, `34`, `64`, `95`, `128`
- Use the single winning voice profile from Stage 1.
- Build sentence-level passage clips for all passage lessons; keep full-passage audio as a separate artifact.
- Add lesson-level aggregate documents in addition to clip-level documents.
- Index into two Chroma collections:
  - `audio_companion_clips`
  - `audio_companion_lessons`
- Embed with Gemini Embeddings 2 using transcript-first documents augmented with structured context:
  - lesson id
  - concept
  - clip type
  - target grapheme/phoneme/word
  - transcript text
- Gate: require user signoff plus retrieval/audit success before batch production.

### Stage 3: Controlled production rollout by lesson bands
- Generate and validate in four batches:
  - `1–34`
  - `35–64`
  - `65–94`
  - `95–128`
- After each batch:
  - run audio companion indexing
  - run the existing corpus audit with audio enabled
  - write a batch report with clip counts, cost, errors, skipped lessons, and review flags
- Do not start the next batch if the current batch produces:
  - any systematic pronunciation issue in a pattern family
  - retrieval regressions
  - repeated human-review critical failures

### Stage 4: Full corpus completion and operational hardening
- Regenerate only missing or failed clips by manifest status; keep the pipeline idempotent.
- Add a "quality retry" path that allows exact-text free regeneration when ElevenLabs output has a distortion but the script is otherwise accepted.
- Freeze the approved voice profile, lexicon, and script templates before full-corpus regeneration.
- Produce final artifacts:
  - `data/ufli/companion/audio.jsonl`
  - lesson bundle JSON files
  - pilot/batch review reports
  - clip-level and lesson-level Chroma records
  - updated context documentation with counts, validation, and chosen defaults

## Key Implementation Changes
### CLI and workflow
- Refine the existing `build-audio`, `generate-audio`, and `index-audio` subcommands instead of replacing them.
- Add these required flags/behaviors:
  - `--lesson-set pilot_micro|pilot_rep|all|range`
  - `--voice-profile <name>`
  - `--dry-run` cost/character estimation
  - `--review-packet` to emit Markdown/CSV review artifacts
  - `--granularity clips|lessons|both` for indexing
- `generate-audio` must stay explicit-live only; no runtime/session-time TTS calls anywhere in the app.

### Data contracts and content rules
- Lesson bundle schema must include:
  - lesson metadata
  - clip list with deterministic ids
  - clip type
  - transcript text
  - tts text
  - pronunciation targets
  - source fields used to derive the clip
  - review status
- Add a `PilotReviewRecord` schema for reviewer scores and blockers.
- Sentence splitting must be deterministic and preserve lesson order.
- No-passage lessons must still emit instruction, phoneme, word, and review clips.

### Pedagogical defaults
- Use short, predictable language and low-stimulation delivery.
- Instructional clips must be child-directed, one task at a time, with simple wording.
- Passage clips must read the written text neutrally; they must not inject extra coaching into the passage itself.
- Pronunciation lexicon must explicitly define all short vowels, digraphs, r-controlled vowels, inflectional endings, and affix-review targets so TTS never guesses from raw symbols alone.
- Default localization is neutral North American English suitable for Ontario and BC elementary learners.

## Test Plan
- Unit tests for lesson derivation across:
  - no-passage lessons
  - passage lessons
  - suffix/affix lessons
  - sentence-level passage segmentation
  - pronunciation lexicon overrides
- Generation tests with stubbed ElevenLabs responses for:
  - dry-run estimation
  - idempotent caching
  - voice-profile selection
  - exact-text retry behavior
- Indexing tests for:
  - clip-level metadata
  - lesson-level aggregate metadata
  - Gemini embedding calls
  - skipped indexing when audio files are absent
- Review/audit tests for:
  - review packet generation
  - critical fail handling
  - batch gating behavior
  - existing multimodal audit consuming `audio.jsonl`
- Acceptance review for pilot:
  - at least two human reviewers
  - median `>= 4/5` in all four rubric areas
  - no critical fail in phoneme accuracy, word accuracy, or misleading prosody

## Assumptions and Defaults
- Scope is numeric UFLI lessons `1–128` only in this phase.
- The repo's existing normalized corpus remains the single source of truth; no shape changes to `normalized.jsonl`.
- The second pilot voice is an external prerequisite and must be configured before Stage 1 generation; if not available, implementation stops before live generation rather than silently falling back to Dorothy-only.
- Transcript-first retrieval is the primary retrieval path; raw audio embeddings are out of scope for this rollout.
- Image companion work is unchanged in this plan.
