"""Build, estimate, generate, review, and index UFLI audio companion pilots."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from corpus.ufli.audio_companion_schema import (
    AudioClipDefinition,
    AudioClipKind,
    AudioVoiceSettings,
    ClipSourceField,
    DryRunEstimate,
    LessonAudioBundle,
    PilotLessonCatalog,
    PilotReviewRecord,
    PronunciationLexicon,
    PronunciationLexiconEntry,
    VoiceProfile,
    VoiceProfileCatalog,
)
from corpus.ufli.extract import LessonContent
from corpus.ufli.grade_levels import derive_grade
from rag.embeddings import embed_text
from rag.store import AUDIO_COMPANION, add_document, get_or_create_collection, get_store

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
_GENERATE_DELAY_SECONDS = 0.5
_BUNDLE_DIR = "lessons"
_AUDIO_MANIFEST = "audio.jsonl"
_GENERATION_LOG = "generation_log.json"
_PILOT_DIR = "pilots"
_PRONUNCIATION_LEXICON = "pronunciation_lexicon.yaml"
_VOICE_PROFILES = "voice_profiles.yaml"
_PILOT_LESSONS = "pilot_lessons.yaml"
_NUMERIC_LESSONS = range(1, 129)
_STAGE1_PILOT_SET = "pilot_micro"
_COMMON_WORDS = {
    "a",
    "and",
    "are",
    "as",
    "at",
    "brief",
    "block",
    "boys",
    "could",
    "get",
    "had",
    "heads",
    "here",
    "illustrate",
    "insert",
    "is",
    "it",
    "lesson",
    "made",
    "mother",
    "new",
    "next",
    "not",
    "of",
    "on",
    "part",
    "pet",
    "pets",
    "practice",
    "read",
    "reading",
    "reinforcement",
    "review",
    "said",
    "sample",
    "script",
    "teach",
    "the",
    "their",
    "them",
    "then",
    "they",
    "this",
    "today",
    "to",
    "transition",
    "try",
    "we",
    "will",
    "with",
    "word",
    "words",
    "you",
}


@dataclass(frozen=True)
class _ConceptTarget:
    grapheme_key: str
    grapheme_display: str
    grapheme_tts: str
    phoneme_key: str
    phoneme_display: str
    phoneme_tts: str


def build_audio_companion_manifests(
    data_dir: str = "data/ufli",
    lesson_set: str = _STAGE1_PILOT_SET,
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
) -> list[LessonAudioBundle]:
    """Derive voice-neutral lesson bundles from normalized.jsonl."""
    base = Path(data_dir)
    companion_dir = base / "companion"
    bundle_dir = companion_dir / _BUNDLE_DIR
    bundle_dir.mkdir(parents=True, exist_ok=True)

    lexicon = load_pronunciation_lexicon(companion_dir / _PRONUNCIATION_LEXICON)
    pilot_lessons = load_pilot_lessons(companion_dir / _PILOT_LESSONS)
    selected_lessons = _resolve_selected_lessons(
        pilot_lessons=pilot_lessons,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
    )

    lesson_records = _load_lessons(base / "normalized.jsonl")
    bundles: list[LessonAudioBundle] = []

    for lesson in lesson_records:
        lesson_number = _lesson_number(lesson.lesson_id)
        if lesson_number is None or lesson_number not in selected_lessons:
            continue
        bundles.append(_derive_lesson_bundle(lesson, lesson_number, lexicon))

    bundles.sort(key=lambda bundle: bundle.lesson_number)
    for bundle in bundles:
        _write_bundle(bundle_dir, bundle)

    logger.info("Built %s audio lesson bundles for lessons %s", len(bundles), selected_lessons)
    return bundles


def generate_audio_companion(
    data_dir: str = "data/ufli",
    lesson_set: str = _STAGE1_PILOT_SET,
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
    voice_profile: str | None = None,
    dry_run: bool = True,
    force: bool = False,
    review_packet: bool = False,
) -> dict[str, Any]:
    """Estimate or generate Stage 1 pilot audio for selected lesson bundles."""
    base = Path(data_dir)
    companion_dir = base / "companion"
    bundle_dir = companion_dir / _BUNDLE_DIR
    if not bundle_dir.exists():
        build_audio_companion_manifests(
            data_dir=data_dir,
            lesson_set=lesson_set,
            lesson_id=lesson_id,
            lesson_min=lesson_min,
            lesson_max=lesson_max,
        )

    pilot_lessons = load_pilot_lessons(companion_dir / _PILOT_LESSONS)
    selected_lessons = _resolve_selected_lessons(
        pilot_lessons=pilot_lessons,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
    )
    _enforce_stage1_pilot_scope(selected_lessons, pilot_lessons)

    bundles = load_audio_bundles(bundle_dir, selected_lessons=selected_lessons)
    voice_catalog = load_voice_profiles(companion_dir / _VOICE_PROFILES)
    voice_names = _selected_voice_profiles(
        voice_catalog=voice_catalog,
        voice_profile=voice_profile,
        dry_run=dry_run,
    )

    if review_packet and len(voice_names) != 1:
        raise RuntimeError("review packets require exactly one selected voice profile")

    if dry_run:
        estimates = [
            _estimate_voice_profile(voice_catalog.profiles[name], bundles)
            for name in voice_names
        ]
        review_packet_dir = ""
        if review_packet:
            review_packet_dir = str(
                _write_review_packet(
                    companion_dir=companion_dir,
                    bundle_copies=_bundle_copies_for_voice(bundles, voice_names[0]),
                    voice_profile=voice_names[0],
                    estimates=estimates,
                    generated_at=_timestamp(),
                    include_audio=False,
                )
            )
        return {
            "planned": sum(estimate.clip_count for estimate in estimates),
            "generated": 0,
            "skipped": 0,
            "voice_profiles": {
                estimate.voice_profile: estimate.model_dump() for estimate in estimates
            },
            "review_packet_dir": review_packet_dir,
            "dry_run": True,
        }

    selected_voice = voice_catalog.profiles[voice_names[0]]
    _validate_live_voice_profile(selected_voice)
    api_key = _elevenlabs_api_key()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required for live generation")

    generated_at = _timestamp()
    log_entries = _read_generation_log(companion_dir / _GENERATION_LOG)
    bundle_copies = _bundle_copies_for_voice(bundles, selected_voice.name)
    generated = 0
    skipped = 0
    planned = 0

    for bundle in bundle_copies:
        for clip in bundle.clips:
            clip.duration_ms = _estimate_duration_ms(clip.tts_text, clip.segment_type)
            clip.voice_profile = selected_voice.name
            clip.speaker = selected_voice.name
            clip.audio_path = _resolved_audio_path(
                lesson_key=bundle.lesson_key,
                voice_profile=selected_voice.name,
                audio_file_name=clip.audio_file_name,
            )
            target_path = companion_dir / clip.audio_path
            if target_path.exists() and not force:
                clip.duration_ms = _measured_or_estimated_duration_ms(
                    target_path,
                    clip.tts_text,
                    clip.segment_type,
                )
                clip.status = "generated"
                skipped += 1
                continue

            planned += 1
            _ensure_parent(target_path)
            audio_bytes, model_id = _synthesize_elevenlabs(
                text=clip.tts_text,
                audio_type=clip.segment_type,
                voice_profile=selected_voice,
                api_key=api_key,
                seed=_stable_seed(clip.segment_id),
            )
            target_path.write_bytes(audio_bytes)
            clip.duration_ms = _measured_or_estimated_duration_ms(
                target_path,
                clip.tts_text,
                clip.segment_type,
            )
            clip.status = "generated"
            generated += 1
            log_entries.append(
                {
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "voice_profile": selected_voice.name,
                    "model_id": model_id,
                    "lesson_id": clip.lesson_id,
                    "segment_id": clip.segment_id,
                    "audio_path": clip.audio_path,
                    "character_count": len(clip.tts_text),
                }
            )
            time.sleep(_GENERATE_DELAY_SECONDS)

        _write_bundle(bundle_dir, bundle)

    _write_generation_log(companion_dir / _GENERATION_LOG, log_entries)
    _write_audio_manifest(companion_dir / _AUDIO_MANIFEST, bundle_copies)

    review_packet_dir = ""
    estimates = [_estimate_voice_profile(selected_voice, bundle_copies)]
    if review_packet:
        review_packet_dir = str(
            _write_review_packet(
                companion_dir=companion_dir,
                bundle_copies=bundle_copies,
                voice_profile=selected_voice.name,
                estimates=estimates,
                generated_at=generated_at,
                include_audio=True,
            )
        )

    return {
        "planned": planned,
        "generated": generated,
        "skipped": skipped,
        "voice_profiles": {
            estimate.voice_profile: estimate.model_dump() for estimate in estimates
        },
        "review_packet_dir": review_packet_dir,
        "dry_run": False,
    }


def index_audio_companion(
    data_dir: str = "data/ufli",
    db_path: str = "vector_store",
    lesson_set: str = _STAGE1_PILOT_SET,
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
    voice_profile: str | None = None,
    granularity: str = "clips",
) -> int:
    """Index generated audio companion transcripts into ChromaDB."""
    if granularity != "clips":
        raise RuntimeError("lesson-level indexing is Stage 2 work; use --granularity clips")

    base = Path(data_dir)
    companion_dir = base / "companion"
    pilot_lessons = load_pilot_lessons(companion_dir / _PILOT_LESSONS)
    selected_lessons = _resolve_selected_lessons(
        pilot_lessons=pilot_lessons,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
    )
    _enforce_stage1_pilot_scope(selected_lessons, pilot_lessons)

    bundles = load_audio_bundles(companion_dir / _BUNDLE_DIR, selected_lessons=selected_lessons)
    store = get_store(db_path)
    collection = get_or_create_collection(store, AUDIO_COMPANION)

    indexed = 0
    for bundle in bundles:
        for clip in bundle.clips:
            if voice_profile and clip.voice_profile != voice_profile:
                continue
            if clip.status != "generated" or not clip.audio_path:
                continue
            if not (companion_dir / clip.audio_path).exists():
                continue

            document = "\n".join(
                part
                for part in [
                    clip.transcript_text,
                    bundle.concept,
                    " ".join(bundle.word_targets),
                    " ".join(clip.pronunciation_targets),
                ]
                if part
            )
            if not document.strip():
                continue

            result = embed_text(document[:2000], task_type="RETRIEVAL_DOCUMENT")
            metadata = {
                "lesson_id": clip.lesson_id,
                "lesson_number": clip.lesson_number,
                "title": bundle.title,
                "concept": bundle.concept,
                "grade_level": bundle.grade_level,
                "segment_type": clip.segment_type,
                "voice_profile": clip.voice_profile,
                "speaker": clip.speaker,
                "audio_path": clip.audio_path,
                "duration_ms": clip.duration_ms,
                "pronunciation_targets": ",".join(clip.pronunciation_targets),
                "word_targets": ",".join(bundle.word_targets),
                "phoneme_targets": ",".join(bundle.phoneme_targets),
                "source_fields": ",".join(clip.source_fields),
                "review_status": clip.review_status,
            }
            add_document(
                collection,
                doc_id=clip.segment_id,
                embedding=result.values,
                metadata=metadata,
                document=document[:1000],
            )
            indexed += 1

    logger.info("Indexed %s audio companion clips into %s", indexed, AUDIO_COMPANION)
    return indexed


def load_audio_bundles(
    bundle_dir: Path,
    selected_lessons: set[int] | None = None,
) -> list[LessonAudioBundle]:
    """Load lesson bundles from disk."""
    if not bundle_dir.exists():
        return []
    bundles: list[LessonAudioBundle] = []
    for path in sorted(bundle_dir.glob("lesson_*.json")):
        bundle = LessonAudioBundle.model_validate_json(path.read_text())
        if selected_lessons is not None and bundle.lesson_number not in selected_lessons:
            continue
        bundles.append(bundle)
    return bundles


def load_pronunciation_lexicon(path: Path) -> PronunciationLexicon:
    """Load the committed pronunciation lexicon."""
    payload = _load_yaml(path)
    return PronunciationLexicon.model_validate(payload)


def load_voice_profiles(path: Path) -> VoiceProfileCatalog:
    """Load committed pilot voice profiles."""
    payload = _load_yaml(path)
    catalog = VoiceProfileCatalog.model_validate(payload)
    for name, profile in catalog.profiles.items():
        if profile.name != name:
            raise ValueError(f"voice profile key/name mismatch for {name}")
    if catalog.default_profile not in catalog.profiles:
        raise ValueError("default_profile must exist in voice_profiles.yaml")
    return catalog


def load_pilot_lessons(path: Path) -> PilotLessonCatalog:
    """Load committed pilot lesson sets."""
    payload = _load_yaml(path)
    catalog = PilotLessonCatalog.model_validate(payload)
    if _STAGE1_PILOT_SET not in catalog.lesson_sets:
        raise ValueError(f"{_STAGE1_PILOT_SET} must exist in pilot_lessons.yaml")
    return catalog


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing companion config: {path}")
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping")
    return payload


def _load_lessons(path: Path) -> list[LessonContent]:
    lessons: list[LessonContent] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        lessons.append(LessonContent(**json.loads(line)))
    return lessons


def _derive_lesson_bundle(
    lesson: LessonContent,
    lesson_number: int,
    lexicon: PronunciationLexicon,
) -> LessonAudioBundle:
    lesson_key = f"lesson_{lesson_number:03d}"
    concept = _clean_text(lesson.concept)
    title = f"Lesson {lesson_number}: {concept or 'UFLI practice'}"
    word_targets = _extract_word_targets(lesson)
    concept_targets = _extract_concept_targets(concept, word_targets, lexicon)
    passage_text = _extract_passage_text(lesson.decodable_text)

    clips: list[AudioClipDefinition] = []
    sequence_index = 0

    clips.append(
        _clip(
            lesson_id=lesson.lesson_id,
            lesson_number=lesson_number,
            segment_id=f"{lesson_key}_lesson_instruction",
            segment_type="lesson_instruction",
            sequence_index=sequence_index,
            audio_file_name="lesson_instruction.mp3",
            transcript_text=_lesson_instruction_text(concept_targets, word_targets),
            tts_text=_lesson_instruction_text(concept_targets, word_targets),
            pronunciation_targets=_bundle_pronunciation_targets(concept_targets),
            source_fields=["concept", "slide_text", "home_practice_text"],
        )
    )
    sequence_index += 1

    for target_index, target in enumerate(concept_targets, start=1):
        example_word = _first_matching_example_word(target, word_targets)
        transcript_text, tts_text = _phoneme_clip_text(target, example_word)
        clips.append(
            _clip(
                lesson_id=lesson.lesson_id,
                lesson_number=lesson_number,
                segment_id=f"{lesson_key}_phoneme_{target_index:02d}_{_slugify(target.grapheme_key)}",
                segment_type="phoneme_model",
                sequence_index=sequence_index,
                audio_file_name=f"phoneme_{target_index:02d}_{_slugify(target.grapheme_key)}.mp3",
                transcript_text=transcript_text,
                tts_text=tts_text,
                pronunciation_targets=[
                    f"grapheme:{target.grapheme_key}",
                    f"phoneme:{target.phoneme_key}",
                ],
                source_fields=["concept", "home_practice_text"],
            )
        )
        sequence_index += 1

    for word in word_targets:
        clips.append(
            _clip(
                lesson_id=lesson.lesson_id,
                lesson_number=lesson_number,
                segment_id=f"{lesson_key}_word_{_slugify(word)}",
                segment_type="word_model",
                sequence_index=sequence_index,
                audio_file_name=f"word_{_slugify(word)}.mp3",
                transcript_text=word,
                tts_text=_apply_special_word_overrides(word, lexicon),
                pronunciation_targets=[f"word:{_slugify(word)}"],
                source_fields=["home_practice_text", "slide_text", "decodable_text"],
            )
        )
        sequence_index += 1

    if passage_text:
        for sentence_index, sentence in enumerate(_split_passage_sentences(passage_text), start=1):
            clips.append(
                _clip(
                    lesson_id=lesson.lesson_id,
                    lesson_number=lesson_number,
                    segment_id=f"{lesson_key}_passage_sentence_{sentence_index:02d}",
                    segment_type="passage_sentence",
                    sequence_index=sequence_index,
                    audio_file_name=f"passage_sentence_{sentence_index:02d}.mp3",
                    transcript_text=sentence,
                    tts_text=sentence,
                    pronunciation_targets=[],
                    source_fields=["decodable_text"],
                )
            )
            sequence_index += 1
        clips.append(
            _clip(
                lesson_id=lesson.lesson_id,
                lesson_number=lesson_number,
                segment_id=f"{lesson_key}_passage_full",
                segment_type="passage_full",
                sequence_index=sequence_index,
                audio_file_name="passage_full.mp3",
                transcript_text=passage_text,
                tts_text=passage_text,
                pronunciation_targets=[],
                source_fields=["decodable_text"],
            )
        )
        sequence_index += 1

    clips.append(
        _clip(
            lesson_id=lesson.lesson_id,
            lesson_number=lesson_number,
            segment_id=f"{lesson_key}_review",
            segment_type="review",
            sequence_index=sequence_index,
            audio_file_name="review.mp3",
            transcript_text=_review_text(concept_targets, word_targets),
            tts_text=_review_text(concept_targets, word_targets),
            pronunciation_targets=_bundle_pronunciation_targets(concept_targets),
            source_fields=["concept", "home_practice_text", "decodable_text", "additional_text"],
        )
    )

    return LessonAudioBundle(
        lesson_id=lesson.lesson_id,
        lesson_number=lesson_number,
        lesson_key=lesson_key,
        title=title,
        concept=concept,
        grade_level=derive_grade(str(lesson_number)),
        phoneme_targets=[target.phoneme_key for target in concept_targets],
        word_targets=word_targets,
        passage_text=passage_text,
        clips=clips,
    )


def _clip(
    lesson_id: str,
    lesson_number: int,
    segment_id: str,
    segment_type: AudioClipKind,
    sequence_index: int,
    audio_file_name: str,
    transcript_text: str,
    tts_text: str,
    pronunciation_targets: list[str],
    source_fields: list[ClipSourceField],
) -> AudioClipDefinition:
    clip = AudioClipDefinition(
        lesson_id=lesson_id,
        lesson_number=lesson_number,
        segment_id=segment_id,
        segment_type=segment_type,
        sequence_index=sequence_index,
        audio_file_name=audio_file_name,
        transcript_text=_clean_text(transcript_text),
        tts_text=_clean_text(tts_text),
        pronunciation_targets=pronunciation_targets,
        source_fields=source_fields,
    )
    clip.duration_ms = _estimate_duration_ms(clip.tts_text, clip.segment_type)
    return clip


def _resolve_selected_lessons(
    pilot_lessons: PilotLessonCatalog,
    lesson_set: str,
    lesson_id: str | None,
    lesson_min: int,
    lesson_max: int,
) -> set[int]:
    if lesson_id:
        lesson_number = _parse_numeric_lesson(lesson_id)
        return {lesson_number}
    if lesson_set in pilot_lessons.lesson_sets:
        return set(pilot_lessons.lesson_sets[lesson_set])
    if lesson_set == "all":
        return set(_NUMERIC_LESSONS)
    if lesson_set == "range":
        if lesson_min < 1 or lesson_max > 128 or lesson_min > lesson_max:
            raise ValueError("range lessons must stay within numeric lessons 1-128")
        return set(range(lesson_min, lesson_max + 1))
    raise ValueError(f"Unsupported lesson set: {lesson_set}")


def _enforce_stage1_pilot_scope(
    selected_lessons: set[int],
    pilot_lessons: PilotLessonCatalog,
) -> None:
    allowed_lessons = set(pilot_lessons.lesson_sets[_STAGE1_PILOT_SET])
    if not selected_lessons.issubset(allowed_lessons):
        raise RuntimeError(
            "Stage 1 generation/indexing is pilot-only; select lessons 1, 14, and/or 95"
        )


def _selected_voice_profiles(
    voice_catalog: VoiceProfileCatalog,
    voice_profile: str | None,
    dry_run: bool,
) -> list[str]:
    if voice_profile:
        if voice_profile not in voice_catalog.profiles:
            raise ValueError(f"Unknown voice profile: {voice_profile}")
        return [voice_profile]
    if dry_run:
        preferred = ["dorothy", "neutral_na_pilot"]
        return [name for name in preferred if name in voice_catalog.profiles]
    return [voice_catalog.default_profile]


def _validate_live_voice_profile(voice_profile: VoiceProfile) -> None:
    if not voice_profile.voice_id or voice_profile.voice_id.startswith("TODO_"):
        raise RuntimeError(
            f"Voice profile {voice_profile.name} is not fully configured for live generation"
        )


def _estimate_voice_profile(
    voice_profile: VoiceProfile,
    bundles: list[LessonAudioBundle],
) -> DryRunEstimate:
    clip_count = 0
    character_count = 0
    clip_counts_by_type: dict[str, int] = {}

    for bundle in bundles:
        for clip in bundle.clips:
            clip_count += 1
            character_count += len(clip.tts_text)
            clip_counts_by_type[clip.segment_type] = (
                clip_counts_by_type.get(clip.segment_type, 0) + 1
            )

    projected_costs: dict[str, float] = {}
    for model_id in (voice_profile.default_model, voice_profile.fallback_model):
        rate = voice_profile.estimated_cost_per_1k_chars_usd.get(model_id, 0.0)
        projected_costs[model_id] = round((character_count / 1000.0) * rate, 4)

    return DryRunEstimate(
        voice_profile=voice_profile.name,
        lesson_count=len(bundles),
        clip_count=clip_count,
        character_count=character_count,
        clip_counts_by_type=clip_counts_by_type,
        projected_costs_usd=projected_costs,
    )


def _bundle_copies_for_voice(
    bundles: list[LessonAudioBundle],
    voice_profile: str,
) -> list[LessonAudioBundle]:
    bundle_copies: list[LessonAudioBundle] = []
    for bundle in bundles:
        bundle_copy = bundle.model_copy(deep=True)
        for clip in bundle_copy.clips:
            clip.voice_profile = voice_profile
            clip.speaker = voice_profile
            clip.audio_path = _resolved_audio_path(
                lesson_key=bundle_copy.lesson_key,
                voice_profile=voice_profile,
                audio_file_name=clip.audio_file_name,
            )
            clip.duration_ms = _estimate_duration_ms(clip.tts_text, clip.segment_type)
        bundle_copies.append(bundle_copy)
    return bundle_copies


def _extract_word_targets(lesson: LessonContent) -> list[str]:
    candidates: list[str] = []
    candidates.extend(_extract_chain_words(lesson.home_practice_text))
    candidates.extend(_extract_sample_words(lesson.home_practice_text))
    candidates.extend(_extract_sample_words(lesson.additional_text))
    candidates.extend(_extract_sample_words(lesson.slide_text))
    if lesson.decodable_text:
        candidates.extend(_frequent_content_words(_extract_passage_text(lesson.decodable_text)))
    candidates.extend(_frequent_content_words(lesson.slide_text))
    deduped = _dedupe_casefold(candidates)
    return deduped[:8]


def _extract_sample_words(text: str) -> list[str]:
    words: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z'-]{1,14}", text):
        cleaned = token.strip("'")
        if cleaned.lower() in _COMMON_WORDS:
            continue
        words.append(cleaned)
    return words


def _extract_chain_words(text: str) -> list[str]:
    words: list[str] = []
    for line in text.splitlines():
        if "→" not in line and "->" not in line:
            continue
        cleaned = re.sub(r"^\d+\.\s*", "", line)
        for part in re.split(r"(?:→|->)", cleaned):
            token = re.sub(r"[^A-Za-z]", "", part).strip()
            if token:
                words.append(token)
    return words


def _extract_concept_targets(
    concept: str,
    word_targets: list[str],
    lexicon: PronunciationLexicon,
) -> list[_ConceptTarget]:
    targets: list[_ConceptTarget] = []
    for part in [chunk.strip() for chunk in concept.split(",") if chunk.strip()]:
        match = re.match(r"(?P<grapheme>[-A-Za-z]+)\s*/(?P<phoneme>[^/]+)/", part)
        if not match:
            continue
        grapheme_key = _normalize_grapheme_label(match.group("grapheme"))
        phoneme_key = _normalize_phoneme_label(match.group("phoneme"))
        grapheme_raw = match.group("grapheme")
        phoneme_raw = match.group("phoneme")
        grapheme_entry = _lookup_lexicon_entry(lexicon.graphemes, grapheme_key, grapheme_raw)
        affix_entry = _lookup_lexicon_entry(lexicon.affixes, grapheme_key, grapheme_raw)
        phoneme_entry = _lookup_lexicon_entry(lexicon.phonemes, phoneme_key, phoneme_raw)
        grapheme_target = affix_entry if match.group("grapheme").startswith("-") else grapheme_entry
        targets.append(
            _ConceptTarget(
                grapheme_key=grapheme_key,
                grapheme_display=grapheme_target.transcript_text,
                grapheme_tts=grapheme_target.approved_tts_text,
                phoneme_key=phoneme_key,
                phoneme_display=phoneme_entry.transcript_text,
                phoneme_tts=phoneme_entry.approved_tts_text,
            )
        )

    if targets:
        return _dedupe_targets(targets)

    fallback_word = word_targets[0] if word_targets else "map"
    fallback_grapheme = _normalize_grapheme_label(fallback_word[:1])
    grapheme_entry = _lookup_lexicon_entry(lexicon.graphemes, fallback_grapheme, fallback_grapheme)
    phoneme_entry = _lookup_lexicon_entry(lexicon.phonemes, fallback_grapheme, fallback_grapheme)
    return [
        _ConceptTarget(
            grapheme_key=fallback_grapheme,
            grapheme_display=grapheme_entry.transcript_text,
            grapheme_tts=grapheme_entry.approved_tts_text,
            phoneme_key=fallback_grapheme,
            phoneme_display=phoneme_entry.transcript_text,
            phoneme_tts=phoneme_entry.approved_tts_text,
        )
    ]


def _dedupe_targets(targets: list[_ConceptTarget]) -> list[_ConceptTarget]:
    seen: set[tuple[str, str]] = set()
    deduped: list[_ConceptTarget] = []
    for target in targets:
        key = (target.grapheme_key, target.phoneme_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _lookup_lexicon_entry(
    entries: dict[str, PronunciationLexiconEntry],
    key: str,
    fallback: str,
) -> PronunciationLexiconEntry:
    return entries.get(
        key,
        PronunciationLexiconEntry(
            transcript_text=fallback,
            approved_tts_text=fallback,
        ),
    )


def _lesson_instruction_text(
    concept_targets: list[_ConceptTarget],
    word_targets: list[str],
) -> str:
    focus = _concept_focus_text(concept_targets)
    sample_words = ", ".join(word_targets[:4])
    if sample_words:
        return (
            f"Listen first. Tap the sounds and read these words: {sample_words}. "
            f"Focus on {focus}."
        )
    return f"Listen first. Tap the sounds and read the words. Focus on {focus}."


def _review_text(concept_targets: list[_ConceptTarget], word_targets: list[str]) -> str:
    focus = _concept_focus_text(concept_targets)
    sample_words = ", ".join(word_targets[:4])
    if sample_words:
        return f"Review {focus} with these words: {sample_words}. Read each word slowly."
    return f"Review {focus}. Read each word slowly."


def _concept_focus_text(concept_targets: list[_ConceptTarget]) -> str:
    parts = [
        f"{target.grapheme_display} saying {target.phoneme_display}"
        for target in concept_targets
    ]
    if not parts:
        return "the target sound"
    if len(parts) == 1:
        return parts[0]
    return ", then ".join(parts)


def _phoneme_clip_text(target: _ConceptTarget, example_word: str) -> tuple[str, str]:
    example_text = f" As in {example_word}." if example_word else ""
    transcript = f"{target.grapheme_display} says {target.phoneme_display}.{example_text}"
    tts = f"{target.grapheme_tts} says {target.phoneme_tts}.{example_text}"
    return transcript.strip(), tts.strip()


def _first_matching_example_word(target: _ConceptTarget, word_targets: list[str]) -> str:
    grapheme = target.grapheme_key.replace("_", "")
    for word in word_targets:
        if grapheme and grapheme in word.casefold():
            return word
    return word_targets[0] if word_targets else ""


def _bundle_pronunciation_targets(concept_targets: list[_ConceptTarget]) -> list[str]:
    targets: list[str] = []
    for target in concept_targets:
        targets.append(f"grapheme:{target.grapheme_key}")
        targets.append(f"phoneme:{target.phoneme_key}")
    return targets


def _apply_special_word_overrides(word: str, lexicon: PronunciationLexicon) -> str:
    normalized = _normalize_special_word(word)
    entry = lexicon.special_words.get(normalized)
    if entry is None:
        return word
    return entry.approved_tts_text


def _extract_passage_text(text: str) -> str:
    if not text.strip():
        return ""
    filtered_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_text(raw_line)
        if not line:
            continue
        line = re.sub(r"^Lesson \d+:\s*", "", line)
        line = re.sub(r"^[A-Za-z,\- ]+ /[^/]+/\s*", "", line)
        line = line.replace("Illustrate the story here:", " ")
        line = _clean_text(line)
        if not line:
            continue
        if line.startswith("© "):
            continue
        filtered_lines.append(line)

    if filtered_lines and len(filtered_lines[0].split()) <= 6 and filtered_lines[0][-1].isalnum():
        filtered_lines = filtered_lines[1:]
    return _clean_text(" ".join(filtered_lines))


def _split_passage_sentences(text: str) -> list[str]:
    if not text:
        return []
    sentences = [
        _clean_text(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if _clean_text(sentence)
    ]
    return sentences


def _frequent_content_words(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    filtered = [
        token
        for token in tokens
        if token.casefold() not in _COMMON_WORDS and 2 <= len(token) <= 12
    ]
    counts = Counter(token.casefold() for token in filtered)
    ordered: list[str] = []
    for token in filtered:
        if counts[token.casefold()] >= 1:
            ordered.append(token)
    return ordered


def _dedupe_casefold(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _lesson_number(lesson_id: str) -> int | None:
    try:
        value = int(lesson_id)
    except ValueError:
        return None
    if value not in _NUMERIC_LESSONS:
        return None
    return value


def _parse_numeric_lesson(lesson_id: str) -> int:
    match = re.search(r"(\d+)", lesson_id)
    if not match:
        raise ValueError("lesson ids must be numeric 1-128")
    lesson_number = int(match.group(1))
    if lesson_number < 1 or lesson_number > 128:
        raise ValueError("lesson ids must be numeric 1-128")
    return lesson_number


def _normalize_phoneme_label(text: str) -> str:
    cleaned = text.strip().lower()
    replacements = {
        "ă": "a_short",
        "ĕ": "e_short",
        "ĭ": "i_short",
        "ŏ": "o_short",
        "ŭ": "u_short",
        "oi": "oi_diphthong",
        "ou": "ou_diphthong",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = cleaned.replace("/", "")
    cleaned = cleaned.replace(" ", "_")
    cleaned = cleaned.strip("-_")
    return cleaned or "target_sound"


def _normalize_grapheme_label(text: str) -> str:
    cleaned = text.strip().lower().replace(" ", "_")
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.strip("_")
    return cleaned or "target_grapheme"


def _normalize_special_word(text: str) -> str:
    return re.sub(r"[^a-z]+", "", text.casefold())


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
    return slug or "clip"


def _estimate_duration_ms(text: str, audio_type: AudioClipKind) -> int:
    word_count = max(len(re.findall(r"[A-Za-z0-9']+", text)), 1)
    if audio_type == "passage_full":
        wpm = 115
    elif audio_type == "passage_sentence":
        wpm = 108
    elif audio_type == "phoneme_model":
        wpm = 58
    elif audio_type == "word_model":
        wpm = 78
    else:
        wpm = 92
    return max(int((word_count / wpm) * 60000) + 500, 900)


def _measured_or_estimated_duration_ms(
    audio_path: Path,
    text: str,
    audio_type: AudioClipKind,
) -> int:
    measured_duration = _measure_audio_duration_ms(audio_path)
    if measured_duration is not None:
        return measured_duration
    return _estimate_duration_ms(text, audio_type)


def _measure_audio_duration_ms(audio_path: Path) -> int | None:
    if not audio_path.exists():
        return None

    suffix = audio_path.suffix.lower()
    try:
        if suffix == ".wav":
            with wave.open(str(audio_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                framerate = wav_file.getframerate()
                if frames > 0 and framerate > 0:
                    return max(int((frames / framerate) * 1000), 1)
            return None
        if suffix == ".mp3":
            try:
                from mutagen.mp3 import MP3
            except ImportError:
                logger.debug("mutagen is unavailable; falling back to estimated duration")
                return None
            audio = MP3(str(audio_path))
            if audio.info.length > 0:
                return max(int(audio.info.length * 1000), 1)
    except Exception as exc:
        logger.warning("Failed to measure audio duration for %s: %s", audio_path, exc)
    return None


def _audio_settings(voice_profile: VoiceProfile, audio_type: AudioClipKind) -> AudioVoiceSettings:
    return voice_profile.clip_settings[audio_type]


def _elevenlabs_api_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY", "")


def _synthesize_elevenlabs(
    text: str,
    audio_type: AudioClipKind,
    voice_profile: VoiceProfile,
    api_key: str,
    seed: int,
) -> tuple[bytes, str]:
    models = [voice_profile.default_model]
    if voice_profile.fallback_model != voice_profile.default_model:
        models.append(voice_profile.fallback_model)

    last_error: Exception | None = None
    for model_id in models:
        try:
            return _request_elevenlabs_audio(
                text=text,
                audio_type=audio_type,
                voice_profile=voice_profile,
                api_key=api_key,
                seed=seed,
                model_id=model_id,
            ), model_id
        except RuntimeError as exc:  # pragma: no cover - exercised live only
            last_error = exc
            logger.warning(
                "ElevenLabs synthesis failed for %s with model %s; trying fallback",
                voice_profile.name,
                model_id,
            )

    raise RuntimeError("ElevenLabs synthesis failed for all configured models") from last_error


def _request_elevenlabs_audio(
    text: str,
    audio_type: AudioClipKind,
    voice_profile: VoiceProfile,
    api_key: str,
    seed: int,
    model_id: str,
) -> bytes:
    settings = _audio_settings(voice_profile, audio_type)
    payload = {
        "text": text,
        "model_id": model_id,
        "language_code": voice_profile.language_code,
        "seed": seed,
        "voice_settings": settings.model_dump(),
    }
    query = urllib.parse.urlencode({"output_format": ELEVENLABS_OUTPUT_FORMAT})
    url = f"{ELEVENLABS_API_BASE}/v1/text-to-speech/{voice_profile.voice_id}?{query}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            return cast(bytes, response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - exercised live only
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"ElevenLabs TTS failed ({exc.code}): {body}") from exc


def _resolved_audio_path(
    lesson_key: str,
    voice_profile: str,
    audio_file_name: str,
) -> str:
    return f"audio/{voice_profile}/lessons/{lesson_key}/{audio_file_name}"


def _stable_seed(text: str) -> int:
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) % (2**32)
    return value


def _read_generation_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _write_generation_log(path: Path, entries: list[dict[str, Any]]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True))


def _write_audio_manifest(path: Path, bundles: list[LessonAudioBundle]) -> None:
    _ensure_parent(path)
    with path.open("w") as handle:
        for bundle in bundles:
            for clip in bundle.clips:
                handle.write(
                    json.dumps(
                        {
                            "lesson_id": clip.lesson_id,
                            "segment_id": clip.segment_id,
                            "segment_type": clip.segment_type,
                            "sequence_index": clip.sequence_index,
                            "audio_path": clip.audio_path,
                            "duration_ms": clip.duration_ms,
                            "transcript_text": clip.transcript_text,
                            "speaker": clip.speaker,
                            "voice_profile": clip.voice_profile,
                            "source_modality": "audio_companion",
                            "status": clip.status,
                            "review_status": clip.review_status,
                            "pronunciation_targets": clip.pronunciation_targets,
                            "source_fields": clip.source_fields,
                        }
                    )
                    + "\n"
                )


def _write_bundle(bundle_dir: Path, bundle: LessonAudioBundle) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_dir / f"{bundle.lesson_key}.json"
    path.write_text(bundle.model_dump_json(indent=2))


def _write_review_packet(
    companion_dir: Path,
    bundle_copies: list[LessonAudioBundle],
    voice_profile: str,
    estimates: list[DryRunEstimate],
    generated_at: str,
    include_audio: bool,
) -> Path:
    packet_dir = companion_dir / _PILOT_DIR / generated_at
    packet_dir.mkdir(parents=True, exist_ok=True)
    _write_review_markdown(packet_dir / "review.md", voice_profile, bundle_copies, estimates)
    _write_review_csv(packet_dir / "review.csv", voice_profile, bundle_copies)
    _write_clips_json(packet_dir / "clips.json", bundle_copies)
    _write_playlist(packet_dir / "playlist.m3u", bundle_copies)
    if include_audio:
        _copy_packet_audio(packet_dir, companion_dir, bundle_copies)
    return packet_dir


def _write_review_markdown(
    path: Path,
    voice_profile: str,
    bundles: list[LessonAudioBundle],
    estimates: list[DryRunEstimate],
) -> None:
    lesson_ids = ", ".join(bundle.lesson_id for bundle in bundles)
    estimate = estimates[0]
    lines = [
        "# UFLI Audio Pilot Review",
        "",
        f"- Voice profile: `{voice_profile}`",
        f"- Lessons: `{lesson_ids}`",
        f"- Clips: `{estimate.clip_count}`",
        f"- Characters: `{estimate.character_count}`",
        f"- Cost estimates: `{json.dumps(estimate.projected_costs_usd, sort_keys=True)}`",
        "",
        "## Review Rubric",
        "",
        "- `pronunciation`: 1-5",
        "- `pacing`: 1-5",
        "- `focus`: 1-5",
        "- `helpfulness`: 1-5",
        "- Mark `blocker=true` for any instructional-meaning or pronunciation failure.",
    ]
    path.write_text("\n".join(lines) + "\n")


def _write_review_csv(path: Path, voice_profile: str, bundles: list[LessonAudioBundle]) -> None:
    rows = _review_rows(voice_profile, bundles)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PilotReviewRecord.model_fields))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: "" if value is None else value
                    for key, value in row.model_dump().items()
                }
            )


def _review_rows(voice_profile: str, bundles: list[LessonAudioBundle]) -> list[PilotReviewRecord]:
    rows: list[PilotReviewRecord] = []
    for bundle in bundles:
        for clip in bundle.clips:
            rows.append(
                PilotReviewRecord(
                    voice_profile=voice_profile,
                    lesson_id=clip.lesson_id,
                    lesson_number=clip.lesson_number,
                    segment_id=clip.segment_id,
                    segment_type=clip.segment_type,
                    sequence_index=clip.sequence_index,
                    audio_path=clip.audio_path,
                    transcript_text=clip.transcript_text,
                )
            )
    return rows


def _write_clips_json(path: Path, bundles: list[LessonAudioBundle]) -> None:
    payload = [
        clip.model_dump()
        for bundle in bundles
        for clip in bundle.clips
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_playlist(path: Path, bundles: list[LessonAudioBundle]) -> None:
    lines = ["#EXTM3U"]
    for bundle in bundles:
        for clip in bundle.clips:
            lines.append(f"#EXTINF:{max(clip.duration_ms // 1000, 1)},{clip.segment_id}")
            lines.append(clip.audio_path or clip.audio_file_name)
    path.write_text("\n".join(lines) + "\n")


def _copy_packet_audio(
    packet_dir: Path,
    companion_dir: Path,
    bundles: list[LessonAudioBundle],
) -> None:
    for bundle in bundles:
        for clip in bundle.clips:
            if not clip.audio_path:
                continue
            source = companion_dir / clip.audio_path
            if not source.exists():
                continue
            destination = packet_dir / clip.audio_path
            _ensure_parent(destination)
            shutil.copy2(source, destination)


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
