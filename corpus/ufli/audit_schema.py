"""Schemas for multimodal UFLI corpus audit results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuditSeverity = Literal["fail", "warn", "info", "skipped"]
AuditStatus = Literal["completed", "skipped", "not_present"]
RecordType = Literal["text", "image", "audio"]
ImageAssetType = Literal["scene", "character", "word_picture", "diagram", "cover"]
AudioSegmentType = Literal[
    "intro",
    "instruction",
    "worked_example",
    "encouragement",
    "review",
]


class NormalizedLessonRecord(BaseModel):
    """Extracted core curriculum record from normalized.jsonl."""

    model_config = ConfigDict(extra="ignore")

    lesson_id: str
    lesson_group: str = ""
    concept: str = ""
    slide_text: str = ""
    slide_count: int = 0
    decodable_text: str = ""
    home_practice_text: str = ""
    additional_text: str = ""


class ImageCompanionRecord(BaseModel):
    """Normalized image companion manifest row."""

    model_config = ConfigDict(extra="ignore")

    lesson_id: str
    asset_id: str
    asset_type: ImageAssetType = "scene"
    sequence_index: int = 0
    image_path: str
    caption_text: str
    alt_text: str
    prompt_text: str | None = None
    source_modality: Literal["image_companion"] = "image_companion"
    status: str = ""


class AudioCompanionRecord(BaseModel):
    """Normalized audio companion manifest row."""

    model_config = ConfigDict(extra="ignore")

    lesson_id: str
    segment_id: str
    segment_type: AudioSegmentType = "instruction"
    sequence_index: int = 0
    audio_path: str
    duration_ms: int
    transcript_text: str
    speaker: str = ""
    source_modality: Literal["audio_companion"] = "audio_companion"
    status: str = ""


class AuditFlag(BaseModel):
    """One audit finding for a record or lesson."""

    lesson_id: str
    record_type: RecordType
    asset_id_or_segment_id: str = ""
    severity: AuditSeverity
    code: str
    message: str


class DuplicateCluster(BaseModel):
    """Exact or near-duplicate asset group."""

    cluster_id: str
    record_type: RecordType
    duplicate_type: Literal["exact", "near"]
    similarity: float = 1.0
    lesson_ids: list[str] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)


class RetrievalBenchmarkResult(BaseModel):
    """Aggregate retrieval benchmark metrics for one modality."""

    modality: RecordType
    status: AuditStatus
    collection_name: str = ""
    case_count: int = 0
    hit_at_1: float = 0.0
    hit_at_3: float = 0.0
    hit_at_5: float = 0.0
    mrr: float = 0.0
    grade_filter_correctness: float = 0.0
    skipped_reason: str = ""


class LessonAuditRecord(BaseModel):
    """Per-lesson modality coverage and quality summary."""

    lesson_id: str
    lesson_group: str = ""
    concept: str = ""
    text_present: bool = False
    image_present: bool = False
    audio_present: bool = False
    image_count: int = 0
    audio_count: int = 0
    text_word_count: int = 0
    image_alignment_score: float = 0.0
    audio_alignment_score: float = 0.0
    modality_coverage_score: float = 0.0
    missing_image_companions: bool = False
    missing_audio_companions: bool = False
    flag_count: int = 0


class ManualReviewRow(BaseModel):
    """Deterministic manual review sample row."""

    lesson_id: str
    record_type: RecordType
    asset_id_or_segment_id: str = ""
    flags: str = ""
    review_extraction_ok: str = ""
    review_metadata_ok: str = ""
    review_relevance_ok: str = ""
    notes: str = ""


class CorpusAuditSummary(BaseModel):
    """Top-level audit output written to summary.json."""

    generated_at: str
    data_dir: str
    db_path: str
    output_dir: str
    use_ai_judge: bool = False
    text_status: AuditStatus
    image_status: AuditStatus
    audio_status: AuditStatus
    text_lesson_count: int = 0
    image_record_count: int = 0
    audio_record_count: int = 0
    fail_count: int = 0
    warn_count: int = 0
    skipped_count: int = 0
    coverage_counts: dict[str, int] = Field(default_factory=dict)
    inventory_counts: dict[str, int] = Field(default_factory=dict)
    lesson_records: list[LessonAuditRecord] = Field(default_factory=list)
    retrieval_benchmarks: list[RetrievalBenchmarkResult] = Field(default_factory=list)
    duplicate_clusters: list[DuplicateCluster] = Field(default_factory=list)
    flags: list[AuditFlag] = Field(default_factory=list)
