"""Schemas for UFLI audio companion pilot bundles, configs, and review packets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AudioClipKind = Literal[
    "lesson_instruction",
    "phoneme_model",
    "word_model",
    "passage_sentence",
    "passage_full",
    "review",
]
ClipSourceField = Literal[
    "concept",
    "slide_text",
    "decodable_text",
    "home_practice_text",
    "additional_text",
]
GenerationStatus = Literal["planned", "generated", "skipped", "failed"]
ReviewStatus = Literal["pending", "approved", "needs_revision"]
JudgeRecommendation = Literal["use", "revise", "block"]
PacingMeasurementSource = Literal["audio_file", "estimate_fallback"]


class AudioVoiceSettings(BaseModel):
    """Per-request voice settings used for ElevenLabs synthesis."""

    model_config = ConfigDict(extra="forbid")

    stability: float
    similarity_boost: float
    style: float
    speed: float


class PronunciationLexiconEntry(BaseModel):
    """Approved transcript/TTS text for a pronunciation target."""

    model_config = ConfigDict(extra="forbid")

    transcript_text: str
    approved_tts_text: str
    notes: str = ""


class PronunciationLexicon(BaseModel):
    """Committed pronunciation overrides for UFLI audio generation."""

    model_config = ConfigDict(extra="forbid")

    phonemes: dict[str, PronunciationLexiconEntry] = Field(default_factory=dict)
    graphemes: dict[str, PronunciationLexiconEntry] = Field(default_factory=dict)
    affixes: dict[str, PronunciationLexiconEntry] = Field(default_factory=dict)
    special_words: dict[str, PronunciationLexiconEntry] = Field(default_factory=dict)


class VoiceProfile(BaseModel):
    """One named voice profile used in the pilot."""

    model_config = ConfigDict(extra="forbid")

    name: str
    voice_id: str = ""
    description: str = ""
    language_code: str = "en"
    default_model: str
    fallback_model: str
    estimated_cost_per_1k_chars_usd: dict[str, float] = Field(default_factory=dict)
    clip_settings: dict[AudioClipKind, AudioVoiceSettings]


class VoiceProfileCatalog(BaseModel):
    """Catalog of available voice profiles."""

    model_config = ConfigDict(extra="forbid")

    default_profile: str
    profiles: dict[str, VoiceProfile]


class PilotLessonCatalog(BaseModel):
    """Committed lesson sets for pilot execution."""

    model_config = ConfigDict(extra="forbid")

    lesson_sets: dict[str, list[int]]

    @field_validator("lesson_sets")
    @classmethod
    def _validate_lesson_sets(cls, lesson_sets: dict[str, list[int]]) -> dict[str, list[int]]:
        for lesson_set, lesson_numbers in lesson_sets.items():
            if not lesson_numbers:
                raise ValueError(f"{lesson_set} must include at least one lesson")
            for lesson_number in lesson_numbers:
                if lesson_number < 1 or lesson_number > 128:
                    raise ValueError("pilot lessons must be numeric lessons 1-128")
        return lesson_sets


class AudioClipDefinition(BaseModel):
    """One lesson-specific audio clip to synthesize and index."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_number: int
    segment_id: str
    segment_type: AudioClipKind
    sequence_index: int
    audio_file_name: str
    audio_path: str = ""
    transcript_text: str
    tts_text: str
    pronunciation_targets: list[str] = Field(default_factory=list)
    source_fields: list[ClipSourceField] = Field(default_factory=list)
    voice_profile: str = ""
    speaker: str = ""
    duration_ms: int = 0
    status: GenerationStatus = "planned"
    review_status: ReviewStatus = "pending"


class LessonAudioBundle(BaseModel):
    """Voice-neutral lesson bundle for audio companion generation."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_number: int
    lesson_key: str
    title: str
    concept: str
    grade_level: str
    phoneme_targets: list[str] = Field(default_factory=list)
    word_targets: list[str] = Field(default_factory=list)
    passage_text: str = ""
    clips: list[AudioClipDefinition] = Field(default_factory=list)


class DryRunEstimate(BaseModel):
    """Dry-run estimation summary for a selected voice profile."""

    model_config = ConfigDict(extra="forbid")

    voice_profile: str
    lesson_count: int
    clip_count: int
    character_count: int
    clip_counts_by_type: dict[str, int] = Field(default_factory=dict)
    projected_costs_usd: dict[str, float] = Field(default_factory=dict)


class PilotReviewRecord(BaseModel):
    """One row in a Stage 1 pilot review packet."""

    model_config = ConfigDict(extra="forbid")

    voice_profile: str
    lesson_id: str
    lesson_number: int
    segment_id: str
    segment_type: AudioClipKind
    sequence_index: int
    audio_path: str
    transcript_text: str
    pronunciation_score: int | None = None
    pacing_score: int | None = None
    focus_score: int | None = None
    helpfulness_score: int | None = None
    blocker: bool = False
    notes: str = ""


class AudioJudgeClipResult(BaseModel):
    """LLM-judge result for one generated audio companion clip."""

    model_config = ConfigDict(extra="forbid")

    voice_profile: str
    lesson_id: str
    lesson_number: int
    segment_id: str
    segment_type: AudioClipKind
    audio_path: str
    actual_duration_ms: int = Field(ge=0, default=0)
    actual_wpm: float = Field(ge=0.0, default=0.0)
    expected_wpm_target: float = Field(ge=0.0, default=0.0)
    expected_wpm_min: float = Field(ge=0.0, default=0.0)
    expected_wpm_max: float = Field(ge=0.0, default=0.0)
    pacing_measurement_source: PacingMeasurementSource = "estimate_fallback"
    heard_text: str = ""
    instructional_match_score: int = Field(ge=1, le=5)
    target_accuracy_score: int = Field(ge=1, le=5)
    decoding_support_score: int = Field(ge=1, le=5)
    passage_neutrality_score: int | None = Field(default=None, ge=1, le=5)
    adhd_supportiveness_score: int = Field(ge=1, le=5)
    clarity_score: int = Field(ge=1, le=5)
    pronunciation_accuracy_score: int = Field(ge=1, le=5)
    pacing_suitability_score: int = Field(ge=1, le=5)
    pacing_consistency_score: int = Field(ge=1, le=5)
    blocker: bool = False
    recommendation: JudgeRecommendation = "use"
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    rationale: str = ""


class AudioJudgeSummary(BaseModel):
    """Aggregate output for one audio judge run."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    judge_model: str
    data_dir: str
    output_dir: str
    voice_profile: str
    lesson_ids: list[str] = Field(default_factory=list)
    clip_count: int = 0
    blocker_count: int = 0
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    median_scores: dict[str, float] = Field(default_factory=dict)
    clip_results: list[AudioJudgeClipResult] = Field(default_factory=list)
