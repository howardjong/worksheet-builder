"""Offline multimodal audit for the UFLI curriculum corpus."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import random
import re
import wave
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import ValidationError

from corpus.ufli.audit_schema import (
    AudioCompanionRecord,
    AuditFlag,
    CorpusAuditSummary,
    DuplicateCluster,
    ImageCompanionRecord,
    LessonAuditRecord,
    ManualReviewRow,
    NormalizedLessonRecord,
    RecordType,
    RetrievalBenchmarkResult,
)
from corpus.ufli.ingest import _derive_grade
from rag.store import CURRICULUM, get_store

logger = logging.getLogger(__name__)

CompanionRecord = ImageCompanionRecord | AudioCompanionRecord

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}
_PLACEHOLDER_TOKENS = {"todo", "tbd", "placeholder", "image", "audio", "segment", "caption"}
_IMAGE_COLLECTION_NAMES = ("image_companion", "ufli_image_companion")
_AUDIO_COLLECTION_NAMES = ("audio_companion", "audio_companion_transcripts", "ufli_audio_companion")
_BOILERPLATE_AUDIO_TYPES = {"encouragement"}


def run_audit(
    data_dir: str = "data/ufli",
    db_path: str = "vector_store",
    output_dir: str = "data/ufli/audit",
    sample_size: int = 20,
    benchmark_size: int = 50,
    seed: int = 42,
    use_ai_judge: bool = False,
) -> CorpusAuditSummary:
    """Run the multimodal corpus audit and write timestamped artifacts."""
    base = Path(data_dir)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    flags: list[AuditFlag] = []
    duplicate_clusters: list[DuplicateCluster] = []

    normalized_records = load_normalized_records(base / "normalized.jsonl", flags)
    image_records = load_image_companion_records(base / "companion" / "images.jsonl", flags)
    audio_records = load_audio_companion_records(base / "companion" / "audio.jsonl", flags)

    lesson_by_id = {record.lesson_id: record for record in normalized_records}
    _audit_text_records(normalized_records, flags)
    duplicate_clusters.extend(_find_text_duplicates(normalized_records, flags))

    image_metrics = _audit_image_records(
        image_records=image_records,
        lesson_by_id=lesson_by_id,
        base_dir=base,
        flags=flags,
    )
    duplicate_clusters.extend(image_metrics["duplicate_clusters"])

    audio_metrics = _audit_audio_records(
        audio_records=audio_records,
        lesson_by_id=lesson_by_id,
        base_dir=base,
        flags=flags,
    )
    duplicate_clusters.extend(audio_metrics["duplicate_clusters"])

    inventory_counts = _inventory_counts(base, normalized_records, db_path, flags)
    lesson_records = _build_lesson_records(
        normalized_records=normalized_records,
        image_records=image_records,
        audio_records=audio_records,
        image_alignment=image_metrics["lesson_alignment"],
        audio_alignment=audio_metrics["lesson_alignment"],
        flags=flags,
    )
    retrieval_benchmarks = _build_retrieval_benchmarks(
        normalized_records=normalized_records,
        image_records=image_records,
        audio_records=audio_records,
        db_path=db_path,
        benchmark_size=benchmark_size,
        seed=seed,
    )
    manual_review_rows = _build_manual_review_rows(
        lesson_records=lesson_records,
        flags=flags,
        sample_size=sample_size,
        seed=seed,
    )

    summary = CorpusAuditSummary(
        generated_at=datetime.now(tz=UTC).isoformat(),
        data_dir=str(base),
        db_path=db_path,
        output_dir=str(report_dir),
        use_ai_judge=use_ai_judge,
        text_status="completed",
        image_status="completed" if image_records else "not_present",
        audio_status="completed" if audio_records else "not_present",
        text_lesson_count=len(normalized_records),
        image_record_count=len(image_records),
        audio_record_count=len(audio_records),
        fail_count=sum(1 for flag in flags if flag.severity == "fail"),
        warn_count=sum(1 for flag in flags if flag.severity == "warn"),
        skipped_count=sum(1 for bench in retrieval_benchmarks if bench.status == "skipped"),
        coverage_counts=_coverage_counts(lesson_records),
        inventory_counts=inventory_counts,
        lesson_records=lesson_records,
        retrieval_benchmarks=retrieval_benchmarks,
        duplicate_clusters=duplicate_clusters,
        flags=flags,
    )

    _write_summary(report_dir / "summary.json", summary)
    _write_json(
        report_dir / "retrieval_benchmark.json",
        [bench.model_dump() for bench in retrieval_benchmarks],
    )
    _write_record_metrics(
        report_dir / "record_metrics.csv",
        normalized_records=normalized_records,
        image_records=image_records,
        audio_records=audio_records,
        lesson_records=lesson_records,
        image_metrics=image_metrics,
        audio_metrics=audio_metrics,
        flags=flags,
    )
    _write_flags(report_dir / "flags.csv", flags)
    _write_manual_review(report_dir / "manual_review_sample.csv", manual_review_rows)
    _write_markdown_report(report_dir / "report.md", summary, manual_review_rows)

    if use_ai_judge:
        logger.warning("AI judge mode is advisory only and remains offline in this audit run")
    logger.info("Audit report written to %s", report_dir)
    return summary


def load_normalized_records(path: Path, flags: list[AuditFlag]) -> list[NormalizedLessonRecord]:
    """Load normalized curriculum records from JSONL."""
    return _load_jsonl(path, NormalizedLessonRecord, "text", flags)


def load_image_companion_records(
    path: Path,
    flags: list[AuditFlag],
) -> list[ImageCompanionRecord]:
    """Load optional image companion manifest."""
    if not path.exists():
        return []
    return _load_jsonl(path, ImageCompanionRecord, "image", flags)


def load_audio_companion_records(
    path: Path,
    flags: list[AuditFlag],
) -> list[AudioCompanionRecord]:
    """Load optional audio companion manifest."""
    if not path.exists():
        return []
    return _load_jsonl(path, AudioCompanionRecord, "audio", flags)


def _load_jsonl(
    path: Path,
    model_type: type[Any],
    record_type: Literal["text", "image", "audio"],
    flags: list[AuditFlag],
) -> list[Any]:
    records: list[Any] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            flags.append(
                AuditFlag(
                    lesson_id="",
                    record_type=record_type,
                    asset_id_or_segment_id=str(line_number),
                    severity="fail",
                    code="malformed_jsonl",
                    message=f"{path.name}:{line_number} is not valid JSON ({exc.msg})",
                )
            )
            continue
        try:
            records.append(model_type.model_validate(raw))
        except ValidationError as exc:
            lesson_id = str(raw.get("lesson_id", ""))
            record_id = str(
                raw.get("asset_id") or raw.get("segment_id") or line_number
            )
            flags.append(
                AuditFlag(
                    lesson_id=lesson_id,
                    record_type=record_type,
                    asset_id_or_segment_id=record_id,
                    severity="fail",
                    code="missing_required_fields",
                    message=(
                        f"{path.name}:{line_number} failed validation: "
                        f"{exc.errors()[0]['msg']}"
                    ),
                )
            )
    return records


def _audit_text_records(
    normalized_records: Sequence[NormalizedLessonRecord],
    flags: list[AuditFlag],
) -> None:
    seen_lessons: set[str] = set()
    for record in normalized_records:
        if record.lesson_id in seen_lessons:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="text",
                    severity="fail",
                    code="duplicate_lesson_id",
                    message=f"Lesson {record.lesson_id} appears more than once in normalized.jsonl",
                )
            )
        seen_lessons.add(record.lesson_id)

        combined_text = _combined_text(record)
        word_count = len(_tokenize(combined_text))
        if not combined_text.strip():
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="text",
                    severity="fail",
                    code="empty_extracted_text",
                    message="Combined extracted text is empty",
                )
            )
        elif word_count < 20:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="text",
                    severity="warn",
                    code="very_short_record",
                    message=f"Combined extracted text is short ({word_count} words)",
                )
            )

        if not record.concept.strip():
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="text",
                    severity="warn",
                    code="missing_concept",
                    message="Concept text is missing",
                )
            )


def _find_text_duplicates(
    normalized_records: Sequence[NormalizedLessonRecord],
    flags: list[AuditFlag],
) -> list[DuplicateCluster]:
    clusters: list[DuplicateCluster] = []
    normalized_docs = {
        record.lesson_id: _normalize_for_similarity(_combined_text(record))
        for record in normalized_records
        if _combined_text(record).strip()
    }
    lesson_ids = sorted(normalized_docs)
    for index, lesson_id in enumerate(lesson_ids):
        for other_id in lesson_ids[index + 1 :]:
            similarity = SequenceMatcher(
                None,
                normalized_docs[lesson_id],
                normalized_docs[other_id],
            ).ratio()
            if similarity >= 0.98:
                flags.append(
                    AuditFlag(
                        lesson_id=lesson_id,
                        record_type="text",
                        severity="warn",
                        code="near_duplicate_lesson_text",
                        message=f"Lesson {lesson_id} is near-duplicate with lesson {other_id}",
                    )
                )
                clusters.append(
                    DuplicateCluster(
                        cluster_id=f"text-near-{lesson_id}-{other_id}",
                        record_type="text",
                        duplicate_type="near",
                        similarity=similarity,
                        lesson_ids=[lesson_id, other_id],
                        record_ids=[lesson_id, other_id],
                    )
                )
    return clusters


def _audit_image_records(
    image_records: Sequence[ImageCompanionRecord],
    lesson_by_id: dict[str, NormalizedLessonRecord],
    base_dir: Path,
    flags: list[AuditFlag],
) -> dict[str, Any]:
    record_metrics: dict[str, dict[str, float | int | str]] = {}
    lesson_alignment: dict[str, list[float]] = defaultdict(list)
    duplicate_clusters: list[DuplicateCluster] = []
    exact_hashes: dict[str, list[ImageCompanionRecord]] = defaultdict(list)
    phashes: dict[str, tuple[ImageCompanionRecord, int]] = {}
    thumbnails: dict[str, tuple[ImageCompanionRecord, list[int]]] = {}

    for record in image_records:
        resolved_path = _resolve_asset_path(record.image_path, base_dir)
        caption_word_count = len(_tokenize(record.caption_text))
        metric: dict[str, float | int | str] = {
            "width": 0,
            "height": 0,
            "file_size": 0,
            "caption_overlap": 0.0,
            "caption_word_count": caption_word_count,
        }
        if record.lesson_id not in lesson_by_id:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="unknown_lesson_id",
                    message="Image companion references a lesson not present in normalized.jsonl",
                )
            )

        if not record.caption_text.strip():
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="missing_caption",
                    message="Caption text is required",
                )
            )
        if not record.alt_text.strip():
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="missing_alt_text",
                    message="Alt text is required",
                )
            )
        if caption_word_count < 8:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="warn",
                    code="short_caption",
                    message="Caption has fewer than 8 words",
                )
            )
        if _is_placeholder_text(record.caption_text, record.image_path):
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="warn",
                    code="placeholder_caption",
                    message="Caption looks generic or filename-derived",
                )
            )

        if resolved_path is None or not resolved_path.exists():
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="missing_image_file",
                    message=f"Image file not found: {record.image_path}",
                )
            )
            record_metrics[record.asset_id] = metric
            continue

        try:
            with Image.open(resolved_path) as image:
                image.load()
                metric["width"] = image.width
                metric["height"] = image.height
                metric["file_size"] = resolved_path.stat().st_size
                phashes[record.asset_id] = (record, _average_hash(image))
                thumbnails[record.asset_id] = (record, _thumbnail_pixels(image))
        except Exception as exc:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="unreadable_image",
                    message=f"Could not read image asset: {exc}",
                )
            )
            record_metrics[record.asset_id] = metric
            continue

        if int(metric["file_size"]) <= 0:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="empty_image_file",
                    message="Image file is empty",
                )
            )

        exact_hash = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        exact_hashes[exact_hash].append(record)

        lesson = lesson_by_id.get(record.lesson_id)
        overlap = _lexical_overlap(
            _tokenize(record.caption_text),
            _lesson_tokens(lesson),
        )
        metric["caption_overlap"] = overlap
        lesson_alignment[record.lesson_id].append(overlap)
        if overlap == 0.0 and lesson is not None:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="warn",
                    code="caption_concept_mismatch",
                    message="Caption has no lexical overlap with the lesson concept/text",
                )
            )

        record_metrics[record.asset_id] = metric

    for digest, records in exact_hashes.items():
        lesson_ids = sorted({record.lesson_id for record in records})
        if len(lesson_ids) <= 1:
            continue
        duplicate_clusters.append(
            DuplicateCluster(
                cluster_id=f"image-exact-{digest[:8]}",
                record_type="image",
                duplicate_type="exact",
                similarity=1.0,
                lesson_ids=lesson_ids,
                record_ids=[record.asset_id for record in records],
            )
        )
        for record in records:
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="image",
                    asset_id_or_segment_id=record.asset_id,
                    severity="fail",
                    code="exact_duplicate_image",
                    message="Exact duplicate image reused across lessons",
                )
            )

    sorted_hashes = sorted(phashes.items(), key=lambda item: item[0])
    for index, (asset_id, (record, phash_value)) in enumerate(sorted_hashes):
        for other_asset_id, (other_record, other_hash) in sorted_hashes[index + 1 :]:
            if record.lesson_id == other_record.lesson_id:
                continue
            similarity = max(
                1.0 - (_hamming_distance(phash_value, other_hash) / 256.0),
                _pixel_similarity(
                    thumbnails[asset_id][1],
                    thumbnails[other_asset_id][1],
                ),
            )
            if similarity >= 0.98:
                duplicate_clusters.append(
                    DuplicateCluster(
                        cluster_id=f"image-near-{asset_id}-{other_asset_id}",
                        record_type="image",
                        duplicate_type="near",
                        similarity=similarity,
                        lesson_ids=[record.lesson_id, other_record.lesson_id],
                        record_ids=[asset_id, other_asset_id],
                    )
                )
                flags.append(
                    AuditFlag(
                        lesson_id=record.lesson_id,
                        record_type="image",
                        asset_id_or_segment_id=asset_id,
                        severity="warn",
                        code="near_duplicate_image",
                        message=f"Near-duplicate image found in lesson {other_record.lesson_id}",
                    )
                )

    return {
        "record_metrics": record_metrics,
        "lesson_alignment": lesson_alignment,
        "duplicate_clusters": duplicate_clusters,
    }


def _audit_audio_records(
    audio_records: Sequence[AudioCompanionRecord],
    lesson_by_id: dict[str, NormalizedLessonRecord],
    base_dir: Path,
    flags: list[AuditFlag],
) -> dict[str, Any]:
    record_metrics: dict[str, dict[str, float | int | str]] = {}
    lesson_alignment: dict[str, list[float]] = defaultdict(list)
    duplicate_clusters: list[DuplicateCluster] = []
    transcript_map: dict[str, list[AudioCompanionRecord]] = defaultdict(list)
    by_lesson: dict[str, list[AudioCompanionRecord]] = defaultdict(list)

    for audio_record in audio_records:
        by_lesson[audio_record.lesson_id].append(audio_record)
        normalized_transcript = _normalize_for_similarity(audio_record.transcript_text)
        word_count = len(_tokenize(audio_record.transcript_text))
        transcript_map[normalized_transcript].append(audio_record)
        resolved_path = _resolve_asset_path(audio_record.audio_path, base_dir)
        metric: dict[str, float | int | str] = {
            "duration_ms": audio_record.duration_ms,
            "file_size": 0,
            "word_count": word_count,
            "wpm": 0.0,
            "transcript_overlap": 0.0,
        }
        if audio_record.lesson_id not in lesson_by_id:
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="fail",
                    code="unknown_lesson_id",
                    message="Audio companion references a lesson not present in normalized.jsonl",
                )
            )

        if resolved_path is None or not resolved_path.exists():
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="fail",
                    code="missing_audio_file",
                    message=f"Audio file not found: {audio_record.audio_path}",
                )
            )
        else:
            file_size = resolved_path.stat().st_size
            metric["file_size"] = file_size
            if file_size <= 0:
                flags.append(
                    AuditFlag(
                        lesson_id=audio_record.lesson_id,
                        record_type="audio",
                        asset_id_or_segment_id=audio_record.segment_id,
                        severity="fail",
                        code="empty_audio_file",
                        message="Audio file is empty",
                    )
                )
            elif resolved_path.suffix.lower() == ".wav":
                try:
                    with wave.open(str(resolved_path), "rb") as wav_file:
                        _ = wav_file.getnframes()
                except wave.Error as exc:
                    flags.append(
                        AuditFlag(
                            lesson_id=audio_record.lesson_id,
                            record_type="audio",
                            asset_id_or_segment_id=audio_record.segment_id,
                            severity="fail",
                            code="unreadable_audio",
                            message=f"Audio asset could not be parsed: {exc}",
                        )
                    )

        if audio_record.duration_ms <= 0:
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="fail",
                    code="invalid_duration",
                    message="duration_ms must be greater than 0",
                )
            )
        if not audio_record.transcript_text.strip():
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="fail",
                    code="missing_transcript",
                    message="Transcript text is required for audio companions",
                )
            )
        elif word_count < 5:
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="fail",
                    code="short_transcript",
                    message="Transcript has fewer than 5 words",
                )
            )
        if _is_placeholder_text(audio_record.transcript_text, audio_record.audio_path):
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="warn",
                    code="placeholder_transcript",
                    message="Transcript looks generic or placeholder-like",
                )
            )

        if audio_record.duration_ms > 0 and word_count > 0:
            wpm = (float(word_count) * 60000.0) / float(audio_record.duration_ms)
            metric["wpm"] = wpm
            if wpm < 80.0 or wpm > 220.0:
                flags.append(
                    AuditFlag(
                        lesson_id=audio_record.lesson_id,
                        record_type="audio",
                        asset_id_or_segment_id=audio_record.segment_id,
                        severity="warn",
                        code="wpm_outlier",
                        message=(
                            "Transcript pacing is outside expected range "
                            f"({wpm:.1f} WPM)"
                        ),
                    )
                )

        lesson = lesson_by_id.get(audio_record.lesson_id)
        overlap = _lexical_overlap(
            _tokenize(audio_record.transcript_text),
            _lesson_tokens(lesson),
        )
        metric["transcript_overlap"] = overlap
        lesson_alignment[audio_record.lesson_id].append(overlap)
        if overlap == 0.0 and lesson is not None:
            flags.append(
                AuditFlag(
                    lesson_id=audio_record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=audio_record.segment_id,
                    severity="warn",
                    code="transcript_concept_mismatch",
                    message="Transcript has no lexical overlap with the lesson concept/text",
                )
            )

        record_metrics[audio_record.segment_id] = metric

    for transcript, records in transcript_map.items():
        if not transcript:
            continue
        lesson_ids = sorted({record.lesson_id for record in records})
        if len(lesson_ids) <= 1:
            continue
        segment_types = {record.segment_type for record in records}
        overuse = False
        if any(segment_type not in _BOILERPLATE_AUDIO_TYPES for segment_type in segment_types):
            ratio = len(lesson_ids) / max(len(lesson_by_id), 1)
            if ratio > 0.2:
                overuse = True
        duplicate_clusters.append(
            DuplicateCluster(
                cluster_id=f"audio-exact-{hashlib.sha256(transcript.encode()).hexdigest()[:8]}",
                record_type="audio",
                duplicate_type="exact",
                similarity=1.0,
                lesson_ids=lesson_ids,
                record_ids=[record.segment_id for record in records],
            )
        )
        for record in records:
            if record.segment_type in _BOILERPLATE_AUDIO_TYPES and not overuse:
                continue
            flags.append(
                AuditFlag(
                    lesson_id=record.lesson_id,
                    record_type="audio",
                    asset_id_or_segment_id=record.segment_id,
                    severity="warn",
                    code="duplicate_transcript",
                    message="Transcript is reused across multiple lessons",
                )
            )
            if overuse:
                flags.append(
                    AuditFlag(
                        lesson_id=record.lesson_id,
                        record_type="audio",
                        asset_id_or_segment_id=record.segment_id,
                        severity="fail",
                        code="boilerplate_transcript_overuse",
                        message="Transcript is overused across too many lessons",
                    )
                )

    for lesson_id, records in by_lesson.items():
        sequence_indexes = sorted(record.sequence_index for record in records)
        if len(sequence_indexes) != len(set(sequence_indexes)):
            flags.append(
                AuditFlag(
                    lesson_id=lesson_id,
                    record_type="audio",
                    severity="warn",
                    code="duplicate_sequence_index",
                    message="Audio segments contain duplicate sequence_index values",
                )
            )
        if sequence_indexes:
            expected = list(range(sequence_indexes[0], sequence_indexes[0] + len(sequence_indexes)))
            if sequence_indexes != expected:
                flags.append(
                    AuditFlag(
                        lesson_id=lesson_id,
                        record_type="audio",
                        severity="warn",
                        code="non_contiguous_sequence_index",
                        message="Audio segments do not form a contiguous sequence",
                    )
                )

    return {
        "record_metrics": record_metrics,
        "lesson_alignment": lesson_alignment,
        "duplicate_clusters": duplicate_clusters,
    }


def _inventory_counts(
    data_dir: Path,
    normalized_records: Sequence[NormalizedLessonRecord],
    db_path: str,
    flags: list[AuditFlag],
) -> dict[str, int]:
    manifest_ids = _load_manifest_ids(data_dir / "manifest.jsonl", flags)
    raw_ids = {
        child.name
        for child in (data_dir / "raw").iterdir()
        if (data_dir / "raw").exists() and child.is_dir()
    }
    normalized_ids = {record.lesson_id for record in normalized_records}
    indexed_ids = _load_indexed_lesson_ids(db_path, CURRICULUM)

    for lesson_id in sorted(manifest_ids - raw_ids):
        flags.append(
            AuditFlag(
                lesson_id=lesson_id,
                record_type="text",
                severity="warn",
                code="missing_raw_dir",
                message="Lesson appears in manifest.jsonl but is missing from raw/",
            )
        )
    for lesson_id in sorted(normalized_ids - indexed_ids):
        flags.append(
            AuditFlag(
                lesson_id=lesson_id,
                record_type="text",
                severity="warn",
                code="missing_curriculum_index",
                message="Lesson is present in normalized.jsonl but missing from curriculum index",
            )
        )
    for lesson_id in sorted(indexed_ids - normalized_ids):
        flags.append(
            AuditFlag(
                lesson_id=lesson_id,
                record_type="text",
                severity="warn",
                code="stale_curriculum_index",
                message="Curriculum index contains a lesson missing from normalized.jsonl",
            )
        )

    return {
        "manifest_lessons": len(manifest_ids),
        "raw_lessons": len(raw_ids),
        "normalized_lessons": len(normalized_ids),
        "indexed_lessons": len(indexed_ids),
    }


def _load_manifest_ids(path: Path, flags: list[AuditFlag]) -> set[str]:
    if not path.exists():
        return set()
    lesson_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            flags.append(
                AuditFlag(
                    lesson_id="",
                    record_type="text",
                    asset_id_or_segment_id=str(line_number),
                    severity="fail",
                    code="malformed_manifest_jsonl",
                    message=f"manifest.jsonl:{line_number} is not valid JSON ({exc.msg})",
                )
            )
            continue
        lesson_id = str(raw.get("lesson_id", "")).strip()
        if lesson_id:
            lesson_ids.add(lesson_id)
    return lesson_ids


def _load_indexed_lesson_ids(db_path: str, collection_name: str) -> set[str]:
    collection = _get_existing_collection(db_path, (collection_name,))
    if collection is None:
        return set()
    result = collection.get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    lesson_ids: set[str] = set()
    for metadata in metadatas:
        if isinstance(metadata, dict) and metadata.get("lesson_id"):
            lesson_ids.add(str(metadata["lesson_id"]))
    return lesson_ids


def _build_lesson_records(
    normalized_records: Sequence[NormalizedLessonRecord],
    image_records: Sequence[ImageCompanionRecord],
    audio_records: Sequence[AudioCompanionRecord],
    image_alignment: dict[str, list[float]],
    audio_alignment: dict[str, list[float]],
    flags: Sequence[AuditFlag],
) -> list[LessonAuditRecord]:
    image_by_lesson: dict[str, list[ImageCompanionRecord]] = defaultdict(list)
    for image_record in image_records:
        image_by_lesson[image_record.lesson_id].append(image_record)
    audio_by_lesson: dict[str, list[AudioCompanionRecord]] = defaultdict(list)
    for audio_record in audio_records:
        audio_by_lesson[audio_record.lesson_id].append(audio_record)
    flag_counts = Counter(flag.lesson_id for flag in flags if flag.lesson_id)

    lesson_ids = sorted(
        {record.lesson_id for record in normalized_records}
        | set(image_by_lesson)
        | set(audio_by_lesson)
    )
    normalized_by_id = {record.lesson_id: record for record in normalized_records}

    rows: list[LessonAuditRecord] = []
    for lesson_id in lesson_ids:
        lesson = normalized_by_id.get(lesson_id)
        text_present = lesson is not None
        images = image_by_lesson.get(lesson_id, [])
        audio = audio_by_lesson.get(lesson_id, [])
        image_present = bool(images)
        audio_present = bool(audio)
        rows.append(
            LessonAuditRecord(
                lesson_id=lesson_id,
                lesson_group=lesson.lesson_group if lesson else "",
                concept=lesson.concept if lesson else "",
                text_present=text_present,
                image_present=image_present,
                audio_present=audio_present,
                image_count=len(images),
                audio_count=len(audio),
                text_word_count=len(_tokenize(_combined_text(lesson))) if lesson else 0,
                image_alignment_score=_mean(image_alignment.get(lesson_id, [])),
                audio_alignment_score=_mean(audio_alignment.get(lesson_id, [])),
                modality_coverage_score=round(
                    (
                        float(text_present)
                        + float(image_present)
                        + float(audio_present)
                    )
                    / 3.0,
                    2,
                ),
                missing_image_companions=bool(image_records) and not image_present,
                missing_audio_companions=bool(audio_records) and not audio_present,
                flag_count=flag_counts.get(lesson_id, 0),
            )
        )
    return rows


def _build_retrieval_benchmarks(
    normalized_records: Sequence[NormalizedLessonRecord],
    image_records: Sequence[ImageCompanionRecord],
    audio_records: Sequence[AudioCompanionRecord],
    db_path: str,
    benchmark_size: int,
    seed: int,
) -> list[RetrievalBenchmarkResult]:
    results = [
        _text_retrieval_benchmark(normalized_records, db_path, benchmark_size, seed),
    ]
    results.append(
        _companion_retrieval_benchmark(
            modality="image",
            records=image_records,
            db_path=db_path,
            collection_names=_IMAGE_COLLECTION_NAMES,
            benchmark_size=benchmark_size,
            seed=seed,
        )
    )
    results.append(
        _companion_retrieval_benchmark(
            modality="audio",
            records=audio_records,
            db_path=db_path,
            collection_names=_AUDIO_COLLECTION_NAMES,
            benchmark_size=benchmark_size,
            seed=seed,
        )
    )
    return results


def _text_retrieval_benchmark(
    normalized_records: Sequence[NormalizedLessonRecord],
    db_path: str,
    benchmark_size: int,
    seed: int,
) -> RetrievalBenchmarkResult:
    collection = _get_existing_collection(db_path, (CURRICULUM,))
    if collection is None or int(collection.count()) == 0:
        return RetrievalBenchmarkResult(
            modality="text",
            status="skipped",
            collection_name=CURRICULUM,
            skipped_reason="curriculum collection missing",
        )

    result = collection.get(include=["documents", "metadatas"])
    ids = [str(item) for item in result.get("ids") or []]
    documents = [str(item) for item in result.get("documents") or []]
    metadatas = [item if isinstance(item, dict) else {} for item in result.get("metadatas") or []]
    indexed_docs = [
        {
            "lesson_id": str(metadata.get("lesson_id", "")),
            "grade_level": str(metadata.get("grade_level", "")),
            "concept": str(metadata.get("concept", "")),
            "document": document,
            "id": doc_id,
        }
        for doc_id, document, metadata in zip(ids, documents, metadatas, strict=False)
    ]
    if not indexed_docs:
        return RetrievalBenchmarkResult(
            modality="text",
            status="skipped",
            collection_name=CURRICULUM,
            skipped_reason="curriculum collection has no readable documents",
        )

    sampled: list[NormalizedLessonRecord] = _sample_records(
        normalized_records,
        benchmark_size,
        seed,
    )
    cases: list[tuple[str, str, str]] = []
    for record in sampled:
        if record.concept.strip():
            cases.append((record.lesson_id, record.concept, _derive_grade(record.lesson_id)))
        lexical_tokens = [
            token for token in _tokenize(_combined_text(record)) if len(token) > 2
        ][:5]
        if lexical_tokens:
            cases.append(
                (
                    record.lesson_id,
                    " ".join(lexical_tokens),
                    _derive_grade(record.lesson_id),
                )
            )

    return _score_retrieval_cases(
        modality="text",
        collection_name=CURRICULUM,
        cases=cases,
        indexed_docs=indexed_docs,
    )


def _companion_retrieval_benchmark(
    modality: Literal["image", "audio"],
    records: Sequence[CompanionRecord],
    db_path: str,
    collection_names: Sequence[str],
    benchmark_size: int,
    seed: int,
) -> RetrievalBenchmarkResult:
    collection = _get_existing_collection(db_path, collection_names)
    if not records:
        return RetrievalBenchmarkResult(
            modality=modality,
            status="skipped",
            skipped_reason=f"{modality} companion manifest not present",
        )
    if collection is None or int(collection.count()) == 0:
        return RetrievalBenchmarkResult(
            modality=modality,
            status="skipped",
            skipped_reason=f"{modality} companion index missing",
        )

    result = collection.get(include=["documents", "metadatas"])
    ids = [str(item) for item in result.get("ids") or []]
    documents = [str(item) for item in result.get("documents") or []]
    metadatas = [item if isinstance(item, dict) else {} for item in result.get("metadatas") or []]
    indexed_docs = [
        {
            "lesson_id": str(metadata.get("lesson_id", "")),
            "grade_level": str(metadata.get("grade_level", "")),
            "concept": str(metadata.get("concept", "")),
            "document": document,
            "id": doc_id,
        }
        for doc_id, document, metadata in zip(ids, documents, metadatas, strict=False)
    ]
    sampled: list[CompanionRecord] = _sample_records(records, benchmark_size, seed)
    cases: list[tuple[str, str, str]] = []
    for record in sampled:
        if isinstance(record, ImageCompanionRecord):
            cases.append((record.lesson_id, record.caption_text, _derive_grade(record.lesson_id)))
        else:
            cases.append(
                (
                    record.lesson_id,
                    record.transcript_text,
                    _derive_grade(record.lesson_id),
                )
            )
    return _score_retrieval_cases(
        modality=modality,
        collection_name=_collection_name(collection, collection_names),
        cases=cases,
        indexed_docs=indexed_docs,
    )


def _score_retrieval_cases(
    modality: RecordType,
    collection_name: str,
    cases: Sequence[tuple[str, str, str]],
    indexed_docs: Sequence[dict[str, str]],
) -> RetrievalBenchmarkResult:
    if not cases:
        return RetrievalBenchmarkResult(
            modality=modality,
            status="skipped",
            collection_name=collection_name,
            skipped_reason="no benchmark cases available",
        )

    hits_1 = 0
    hits_3 = 0
    hits_5 = 0
    mrr_total = 0.0
    grade_correct = 0

    for lesson_id, query, expected_grade in cases:
        ranked = _lexical_rank(query, indexed_docs)
        top_ids = [candidate["lesson_id"] for candidate in ranked[:5]]
        if lesson_id in top_ids[:1]:
            hits_1 += 1
        if lesson_id in top_ids[:3]:
            hits_3 += 1
        if lesson_id in top_ids[:5]:
            hits_5 += 1
            mrr_total += 1.0 / (top_ids.index(lesson_id) + 1)
        if ranked and ranked[0]["grade_level"] == expected_grade:
            grade_correct += 1

    count = len(cases)
    return RetrievalBenchmarkResult(
        modality=modality,
        status="completed",
        collection_name=collection_name,
        case_count=count,
        hit_at_1=hits_1 / count,
        hit_at_3=hits_3 / count,
        hit_at_5=hits_5 / count,
        mrr=mrr_total / count,
        grade_filter_correctness=grade_correct / count,
    )


def _build_manual_review_rows(
    lesson_records: Sequence[LessonAuditRecord],
    flags: Sequence[AuditFlag],
    sample_size: int,
    seed: int,
) -> list[ManualReviewRow]:
    grouped_flags: dict[tuple[str, str, str], list[AuditFlag]] = defaultdict(list)
    for flag in flags:
        key = (flag.lesson_id, flag.record_type, flag.asset_id_or_segment_id)
        grouped_flags[key].append(flag)

    candidates: list[ManualReviewRow] = []
    lesson_lookup = {row.lesson_id: row for row in lesson_records}
    for (lesson_id, record_type, record_id), row_flags in grouped_flags.items():
        codes = ",".join(sorted(flag.code for flag in row_flags))
        candidates.append(
            ManualReviewRow(
                lesson_id=lesson_id,
                record_type=record_type,  # type: ignore[arg-type]
                asset_id_or_segment_id=record_id,
                flags=codes,
            )
        )

    candidates.sort(
        key=lambda row: (
            lesson_lookup.get(
                row.lesson_id,
                LessonAuditRecord(lesson_id=row.lesson_id),
            ).lesson_group,
            row.record_type,
            row.lesson_id,
            row.asset_id_or_segment_id,
        )
    )

    rng = random.Random(seed)
    grouped: dict[str, list[ManualReviewRow]] = defaultdict(list)
    for row in candidates:
        grouped[row.record_type].append(row)
    for rows in grouped.values():
        rng.shuffle(rows)

    sampled: list[ManualReviewRow] = []
    record_types = ["text", "image", "audio"]
    while len(sampled) < sample_size and any(grouped.values()):
        for record_type in record_types:
            if grouped[record_type] and len(sampled) < sample_size:
                sampled.append(grouped[record_type].pop())
    return sampled


def _write_summary(path: Path, summary: CorpusAuditSummary) -> None:
    path.write_text(summary.model_dump_json(indent=2))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_record_metrics(
    path: Path,
    normalized_records: Sequence[NormalizedLessonRecord],
    image_records: Sequence[ImageCompanionRecord],
    audio_records: Sequence[AudioCompanionRecord],
    lesson_records: Sequence[LessonAuditRecord],
    image_metrics: dict[str, Any],
    audio_metrics: dict[str, Any],
    flags: Sequence[AuditFlag],
) -> None:
    fieldnames = [
        "record_type",
        "lesson_id",
        "record_id",
        "lesson_group",
        "concept",
        "text_word_count",
        "image_count",
        "audio_count",
        "modality_coverage_score",
        "alignment_score",
        "width",
        "height",
        "duration_ms",
        "wpm",
        "flag_count",
    ]
    flag_counter = Counter(
        (flag.record_type, flag.lesson_id, flag.asset_id_or_segment_id) for flag in flags
    )
    lesson_by_id = {row.lesson_id: row for row in lesson_records}
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for lesson_record in normalized_records:
            lesson = lesson_by_id[lesson_record.lesson_id]
            writer.writerow(
                {
                    "record_type": "text",
                    "lesson_id": lesson_record.lesson_id,
                    "record_id": lesson_record.lesson_id,
                    "lesson_group": lesson_record.lesson_group,
                    "concept": lesson_record.concept,
                    "text_word_count": lesson.text_word_count,
                    "image_count": lesson.image_count,
                    "audio_count": lesson.audio_count,
                    "modality_coverage_score": lesson.modality_coverage_score,
                    "alignment_score": "",
                    "width": "",
                    "height": "",
                    "duration_ms": "",
                    "wpm": "",
                    "flag_count": flag_counter[("text", lesson_record.lesson_id, "")],
                }
            )
        for image_record in image_records:
            metric = image_metrics["record_metrics"].get(image_record.asset_id, {})
            lesson = lesson_by_id.get(
                image_record.lesson_id,
                LessonAuditRecord(lesson_id=image_record.lesson_id),
            )
            writer.writerow(
                {
                    "record_type": "image",
                    "lesson_id": image_record.lesson_id,
                    "record_id": image_record.asset_id,
                    "lesson_group": lesson.lesson_group,
                    "concept": lesson.concept,
                    "text_word_count": lesson.text_word_count,
                    "image_count": lesson.image_count,
                    "audio_count": lesson.audio_count,
                    "modality_coverage_score": lesson.modality_coverage_score,
                    "alignment_score": metric.get("caption_overlap", ""),
                    "width": metric.get("width", ""),
                    "height": metric.get("height", ""),
                    "duration_ms": "",
                    "wpm": "",
                    "flag_count": flag_counter[
                        ("image", image_record.lesson_id, image_record.asset_id)
                    ],
                }
            )
        for audio_record in audio_records:
            metric = audio_metrics["record_metrics"].get(audio_record.segment_id, {})
            lesson = lesson_by_id.get(
                audio_record.lesson_id,
                LessonAuditRecord(lesson_id=audio_record.lesson_id),
            )
            writer.writerow(
                {
                    "record_type": "audio",
                    "lesson_id": audio_record.lesson_id,
                    "record_id": audio_record.segment_id,
                    "lesson_group": lesson.lesson_group,
                    "concept": lesson.concept,
                    "text_word_count": lesson.text_word_count,
                    "image_count": lesson.image_count,
                    "audio_count": lesson.audio_count,
                    "modality_coverage_score": lesson.modality_coverage_score,
                    "alignment_score": metric.get("transcript_overlap", ""),
                    "width": "",
                    "height": "",
                    "duration_ms": metric.get("duration_ms", ""),
                    "wpm": metric.get("wpm", ""),
                    "flag_count": flag_counter[
                        ("audio", audio_record.lesson_id, audio_record.segment_id)
                    ],
                }
            )


def _write_flags(path: Path, flags: Sequence[AuditFlag]) -> None:
    fieldnames = [
        "lesson_id",
        "record_type",
        "asset_id_or_segment_id",
        "severity",
        "code",
        "message",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for flag in flags:
            writer.writerow(flag.model_dump())


def _write_manual_review(path: Path, rows: Sequence[ManualReviewRow]) -> None:
    fieldnames = list(ManualReviewRow.model_fields)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())


def _write_markdown_report(
    path: Path,
    summary: CorpusAuditSummary,
    manual_review_rows: Sequence[ManualReviewRow],
) -> None:
    benchmarks = {bench.modality: bench for bench in summary.retrieval_benchmarks}
    lines = [
        "# UFLI Multimodal Corpus Audit",
        "",
        "## Executive summary",
        f"- Generated at: {summary.generated_at}",
        f"- Lessons audited: {summary.text_lesson_count}",
        f"- Image records: {summary.image_record_count} ({summary.image_status})",
        f"- Audio records: {summary.audio_record_count} ({summary.audio_status})",
        f"- Failures: {summary.fail_count}",
        f"- Warnings: {summary.warn_count}",
        "",
        "## Corpus inventory and modality coverage",
        f"- Manifest lessons: {summary.inventory_counts.get('manifest_lessons', 0)}",
        f"- Raw lessons: {summary.inventory_counts.get('raw_lessons', 0)}",
        f"- Normalized lessons: {summary.inventory_counts.get('normalized_lessons', 0)}",
        f"- Indexed curriculum lessons: {summary.inventory_counts.get('indexed_lessons', 0)}",
        f"- Text only lessons: {summary.coverage_counts.get('text_only', 0)}",
        f"- Text + image lessons: {summary.coverage_counts.get('text_image', 0)}",
        f"- Text + audio lessons: {summary.coverage_counts.get('text_audio', 0)}",
        f"- Full multimodal lessons: {summary.coverage_counts.get('full_multimodal', 0)}",
        "",
        "## Text curriculum quality",
        f"- Text retrieval benchmark: {benchmarks['text'].status}",
        (
            "- Hit@1 / Hit@3 / Hit@5: "
            f"{benchmarks['text'].hit_at_1:.2f} / "
            f"{benchmarks['text'].hit_at_3:.2f} / "
            f"{benchmarks['text'].hit_at_5:.2f}"
        ),
        f"- MRR: {benchmarks['text'].mrr:.2f}",
        f"- Grade correctness: {benchmarks['text'].grade_filter_correctness:.2f}",
        "",
        "## Image companion quality",
        f"- Status: {summary.image_status}",
        f"- Retrieval benchmark: {benchmarks['image'].status}",
        (
            "- Retrieval note: "
            f"{benchmarks['image'].skipped_reason or benchmarks['image'].collection_name}"
        ),
        "",
        "## Audio companion quality",
        f"- Status: {summary.audio_status}",
        f"- Retrieval benchmark: {benchmarks['audio'].status}",
        (
            "- Retrieval note: "
            f"{benchmarks['audio'].skipped_reason or benchmarks['audio'].collection_name}"
        ),
        "",
        "## Retrieval benchmark",
    ]
    for bench in summary.retrieval_benchmarks:
        lines.append(

                f"- {bench.modality}: status={bench.status}, cases={bench.case_count}, "
                f"hit@3={bench.hit_at_3:.2f}, mrr={bench.mrr:.2f}"

        )
    lines.extend(
        [
            "",
            "## Manual review pack",
            f"- Rows sampled: {len(manual_review_rows)}",
            "",
            "## Action items",
        ]
    )
    top_flags = Counter(flag.code for flag in summary.flags).most_common(5)
    if not top_flags:
        lines.append("- No action items. Audit found no flags.")
    else:
        for code, count in top_flags:
            lines.append(f"- {code}: {count}")
    path.write_text("\n".join(lines) + "\n")


def _coverage_counts(lesson_records: Sequence[LessonAuditRecord]) -> dict[str, int]:
    counts = {
        "text_only": 0,
        "text_image": 0,
        "text_audio": 0,
        "full_multimodal": 0,
    }
    for row in lesson_records:
        if row.text_present and not row.image_present and not row.audio_present:
            counts["text_only"] += 1
        if row.text_present and row.image_present and not row.audio_present:
            counts["text_image"] += 1
        if row.text_present and row.audio_present and not row.image_present:
            counts["text_audio"] += 1
        if row.text_present and row.image_present and row.audio_present:
            counts["full_multimodal"] += 1
    return counts


def _sample_records(records: Sequence[Any], limit: int, seed: int) -> list[Any]:
    ordered = list(records)
    if len(ordered) <= limit:
        return ordered
    rng = random.Random(seed)
    chosen = rng.sample(ordered, k=limit)
    return list(chosen)


def _lexical_rank(query: str, indexed_docs: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    query_tokens = set(_tokenize(query))
    scored: list[tuple[float, dict[str, str]]] = []
    for candidate in indexed_docs:
        doc_tokens = set(_tokenize(candidate.get("document", "")))
        concept_tokens = set(_tokenize(candidate.get("concept", "")))
        overlap = 0.0
        if query_tokens:
            overlap += len(query_tokens & doc_tokens) / len(query_tokens)
            overlap += 0.5 * len(query_tokens & concept_tokens) / len(query_tokens)
        scored.append((overlap, candidate))
    scored.sort(key=lambda item: (-item[0], item[1].get("lesson_id", ""), item[1].get("id", "")))
    return [candidate for _, candidate in scored]


def _combined_text(record: NormalizedLessonRecord | None) -> str:
    if record is None:
        return ""
    parts = [
        record.slide_text,
        record.decodable_text,
        record.home_practice_text,
        record.additional_text,
    ]
    return "\n\n".join(part for part in parts if part).strip()


def _lesson_tokens(record: NormalizedLessonRecord | None) -> set[str]:
    if record is None:
        return set()
    return set(_tokenize(f"{record.concept} {_combined_text(record)}"))


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [token for token in tokens if token not in _STOPWORDS]


def _lexical_overlap(tokens: Iterable[str], lesson_tokens: set[str]) -> float:
    token_set = {token for token in tokens if token}
    if not token_set or not lesson_tokens:
        return 0.0
    return len(token_set & lesson_tokens) / len(token_set)


def _normalize_for_similarity(text: str) -> str:
    return " ".join(_tokenize(text))


def _is_placeholder_text(text: str, asset_path: str) -> bool:
    stripped = text.strip().lower()
    if not stripped:
        return False
    normalized_text = " ".join(_tokenize(stripped))
    normalized_stem = " ".join(_tokenize(Path(asset_path).stem.lower()))
    if normalized_text and normalized_text == normalized_stem:
        return True
    text_tokens = set(_tokenize(stripped))
    return bool(text_tokens & _PLACEHOLDER_TOKENS)


def _resolve_asset_path(path_str: str, data_dir: Path) -> Path | None:
    path = Path(path_str)
    if path.is_absolute():
        return path
    candidates = [
        data_dir / path,
        data_dir / "companion" / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _average_hash(image: Image.Image) -> int:
    pixels = _thumbnail_pixels(image)
    mean_value = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= mean_value)
    return value


def _thumbnail_pixels(image: Image.Image) -> list[int]:
    grayscale = image.convert("L").resize((16, 16))
    return list(grayscale.tobytes())


def _pixel_similarity(left: Sequence[int], right: Sequence[int]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    mean_abs_diff = sum(abs(a - b) for a, b in zip(left, right, strict=False)) / len(left)
    return 1.0 - (mean_abs_diff / 255.0)


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _get_existing_collection(db_path: str, names: Sequence[str]) -> Any | None:
    try:
        store = get_store(db_path)
    except Exception:
        return None
    try:
        available = {getattr(item, "name", str(item)) for item in store.list_collections()}
    except Exception:
        available = set()
    for name in names:
        if name in available:
            return store.get_collection(name=name)
    return None


def _collection_name(collection: Any, names: Sequence[str]) -> str:
    return str(getattr(collection, "name", "")) or names[0]
