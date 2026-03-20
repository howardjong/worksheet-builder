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
AudioSynthesisProvider = Literal["elevenlabs", "google_cloud_tts"]
AudioInputFormat = Literal["text", "markup"]
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
FallbackDecisionBucket = Literal[
    "auto_accept",
    "gemini_fallback_eligible",
    "needs_llm_or_manual_review",
]
FallbackPacingRisk = Literal[
    "within_band",
    "near_band",
    "too_fast",
    "too_slow",
    "missing_measurement",
]
GoogleTtsFailureCategory = Literal[
    "http_retryable",
    "http_non_retryable",
    "transport",
    "auth",
    "response",
    "unknown",
]


class AudioVoiceSettings(BaseModel):
    """Per-request voice settings used for ElevenLabs synthesis."""

    model_config = ConfigDict(extra="forbid")

    stability: float
    similarity_boost: float
    style: float
    speed: float

    @field_validator("stability", "similarity_boost", "style")
    @classmethod
    def _validate_unit_interval(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("voice setting must be between 0.0 and 1.0")
        return value

    @field_validator("speed")
    @classmethod
    def _validate_elevenlabs_speed(cls, value: float) -> float:
        if value < 0.7 or value > 1.2:
            raise ValueError("ElevenLabs speed must be between 0.7 and 1.2")
        return value


class GoogleCloudTtsSettings(BaseModel):
    """Experimental Cloud TTS settings for diagnostics-only canary probes."""

    model_config = ConfigDict(extra="forbid")

    api_endpoint: str
    voice_name: str
    language_code: str = "en-US"
    model_name: str = ""
    style_prompt: str = ""
    audio_encoding: Literal["MP3", "LINEAR16"] = "MP3"
    speaking_rate: float = 1.0
    sample_rate_hz: int = 0
    volume_gain_db: float = 0.0

    @field_validator("speaking_rate")
    @classmethod
    def _validate_speaking_rate(cls, value: float) -> float:
        if value < 0.25 or value > 2.0:
            raise ValueError("Google Cloud TTS speaking_rate must be between 0.25 and 2.0")
        return value

    @field_validator("sample_rate_hz")
    @classmethod
    def _validate_sample_rate_hz(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Google Cloud TTS sample_rate_hz must be non-negative")
        return value

    @field_validator("volume_gain_db")
    @classmethod
    def _validate_volume_gain_db(cls, value: float) -> float:
        if value < -96.0 or value > 16.0:
            raise ValueError("Google Cloud TTS volume_gain_db must be between -96.0 and 16.0")
        return value


class PronunciationLexiconEntry(BaseModel):
    """Approved transcript/TTS text for a pronunciation target."""

    model_config = ConfigDict(extra="forbid")

    transcript_text: str
    approved_tts_text: str
    notes: str = ""
    anchor_word: str = ""
    modeling_tts_text: str = ""


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


class BundleValidationIssue(BaseModel):
    """One deterministic validation failure for a built lesson bundle."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_number: int
    bundle_key: str
    segment_id: str = ""
    severity: Literal["error", "warning"] = "error"
    code: str
    message: str


class BundleValidationReport(BaseModel):
    """Aggregate validation output for selected built lesson bundles."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    data_dir: str
    lesson_ids: list[str] = Field(default_factory=list)
    bundle_count: int = 0
    passed: bool = False
    issue_count: int = 0
    issues: list[BundleValidationIssue] = Field(default_factory=list)


class AudioJudgeClipResult(BaseModel):
    """LLM-judge result for one generated audio companion clip."""

    model_config = ConfigDict(extra="forbid")

    voice_profile: str
    lesson_id: str
    lesson_number: int
    segment_id: str
    segment_type: AudioClipKind
    audio_path: str
    transcript_word_count: int = Field(ge=1, default=1)
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


class AudioJudgeFamilySummary(BaseModel):
    """Per clip-family aggregate metrics for one judge run."""

    model_config = ConfigDict(extra="forbid")

    clip_count: int = 0
    blocker_count: int = 0
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    median_actual_wpm: float = 0.0
    min_actual_wpm: float = 0.0
    max_actual_wpm: float = 0.0
    median_scores: dict[str, float] = Field(default_factory=dict)


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
    family_summaries: dict[str, AudioJudgeFamilySummary] = Field(default_factory=dict)
    pilot_ready: bool = False
    pilot_gate_failures: list[str] = Field(default_factory=list)
    required_manual_review_segments: list[str] = Field(default_factory=list)
    clip_results: list[AudioJudgeClipResult] = Field(default_factory=list)


class AudioGenerationLogEntry(BaseModel):
    """One generated clip with the exact TTS inputs and settings used."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    voice_profile: str
    model_id: str
    lesson_id: str
    segment_id: str
    segment_type: AudioClipKind
    audio_path: str
    character_count: int
    transcript_text: str
    tts_text: str
    pronunciation_targets: list[str] = Field(default_factory=list)
    source_fields: list[ClipSourceField] = Field(default_factory=list)
    audio_settings: AudioVoiceSettings


class GeminiFallbackPlan(BaseModel):
    """Recommended Gemini TTS request shape for a fallback-eligible clip."""

    model_config = ConfigDict(extra="forbid")

    provider: AudioSynthesisProvider = "google_cloud_tts"
    model_name: str = "gemini-2.5-pro-tts"
    voice_name: str = "Leda"
    transcript_strategy: Literal["exact_transcript"] = "exact_transcript"
    prompt_guidance: str
    prompt_target_wpm: float = Field(ge=0.0)
    prompt_wpm_min: float = Field(ge=0.0)
    prompt_wpm_max: float = Field(ge=0.0)


class AudioFallbackClipDecision(BaseModel):
    """Deterministic fallback-policy classification for one generated clip."""

    model_config = ConfigDict(extra="forbid")

    voice_profile: str
    lesson_id: str
    lesson_number: int
    segment_id: str
    segment_type: AudioClipKind
    audio_path: str
    transcript_word_count: int = Field(ge=1, default=1)
    actual_duration_ms: int = Field(ge=0, default=0)
    actual_wpm: float = Field(ge=0.0, default=0.0)
    expected_wpm_target: float = Field(ge=0.0, default=0.0)
    expected_wpm_min: float = Field(ge=0.0, default=0.0)
    expected_wpm_max: float = Field(ge=0.0, default=0.0)
    pacing_measurement_source: PacingMeasurementSource = "estimate_fallback"
    pacing_risk: FallbackPacingRisk = "missing_measurement"
    pace_delta_wpm: float = 0.0
    bucket: FallbackDecisionBucket
    known_risk_segment: bool = False
    tts_differs_from_transcript: bool = False
    text_risk_markers: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    gemini_fallback_plan: GeminiFallbackPlan | None = None


class AudioFallbackPolicySummary(BaseModel):
    """Aggregate output for one deterministic audio fallback-policy run."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    policy_name: str
    execution_mode: Literal["manual_opt_in"] = "manual_opt_in"
    data_dir: str
    output_dir: str
    voice_profile: str
    lesson_ids: list[str] = Field(default_factory=list)
    clip_count: int = 0
    bucket_counts: dict[str, int] = Field(default_factory=dict)
    family_bucket_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    gemini_fallback_segments: list[str] = Field(default_factory=list)
    required_manual_review_segments: list[str] = Field(default_factory=list)
    clip_results: list[AudioFallbackClipDecision] = Field(default_factory=list)


FallbackExecutionStatus = Literal[
    "synthesized",
    "synthesis_failed",
    "improved",
    "not_improved",
    "skipped",
]


class FallbackExecutionClipResult(BaseModel):
    """Result of executing Gemini fallback for one clip."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    original_audio_path: str = ""
    fallback_audio_path: str = ""
    original_wpm: float = Field(ge=0.0, default=0.0)
    fallback_wpm: float = Field(ge=0.0, default=0.0)
    original_recommendation: str = ""
    fallback_recommendation: str = ""
    status: FallbackExecutionStatus = "skipped"
    replaced: bool = False
    failure_message: str = ""


class FallbackExecutionSummary(BaseModel):
    """Aggregate output for one Gemini fallback execution run."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    data_dir: str
    output_dir: str
    voice_profile: str = ""
    clip_count: int = 0
    synthesized_count: int = 0
    improved_count: int = 0
    replaced_count: int = 0
    failed_count: int = 0
    clip_results: list[FallbackExecutionClipResult] = Field(default_factory=list)


ProbeAssessment = Literal[
    "pipeline_input_problem",
    "model_or_voice_limitation",
    "mixed_or_inconclusive",
    "current_pipeline_preferred",
]


class AudioProbeFinding(BaseModel):
    """Root-cause interpretation for one probe segment."""

    model_config = ConfigDict(extra="forbid")

    source_segment_id: str
    probable_cause: ProbeAssessment
    best_variant_id: str = ""
    evidence: list[str] = Field(default_factory=list)
    recommended_next_step: str = ""


class AudioProbeVariant(BaseModel):
    """One controlled diagnostic variant for a generated audio clip."""

    model_config = ConfigDict(extra="forbid")

    source_segment_id: str
    variant_id: str
    lesson_id: str
    lesson_number: int
    segment_type: AudioClipKind
    variant_family: str
    hypothesis: str
    voice_profile: str
    provider: AudioSynthesisProvider = "elevenlabs"
    model_id: str
    transcript_text: str
    tts_text: str
    provider_input: str = ""
    input_format: AudioInputFormat = "text"
    audio_settings: AudioVoiceSettings | GoogleCloudTtsSettings
    audio_path: str = ""
    attempt_count: int = Field(ge=0, default=0)
    failure_status_code: int | None = Field(default=None, ge=100, le=599)
    failure_category: GoogleTtsFailureCategory | None = None
    failure_message: str = ""
    retry_exhausted: bool = False
    generation_status: GenerationStatus = "planned"
    judge_result: AudioJudgeClipResult | None = None


class LessonAudioAggregate(BaseModel):
    """Lesson-level aggregate document for audio companion indexing (Stage 2)."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    lesson_number: int
    title: str
    concept: str
    grade_level: str
    phoneme_targets: list[str] = Field(default_factory=list)
    word_targets: list[str] = Field(default_factory=list)
    passage_text: str = ""
    clip_count: int = 0
    clip_types: list[str] = Field(default_factory=list)
    aggregate_transcript: str = ""
    voice_profile: str = ""
    total_duration_ms: int = 0


class AudioProbeRunSummary(BaseModel):
    """Summary artifact for one controlled audio probe run."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    output_dir: str
    data_dir: str
    voice_profile: str
    judge_model: str = ""
    live: bool = False
    judged: bool = False
    segment_ids: list[str] = Field(default_factory=list)
    variant_count: int = 0
    findings: list[AudioProbeFinding] = Field(default_factory=list)
    variants: list[AudioProbeVariant] = Field(default_factory=list)
