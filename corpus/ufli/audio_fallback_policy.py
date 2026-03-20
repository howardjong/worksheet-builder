"""Deterministic fallback-policy triage for generated UFLI audio clips."""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from corpus.ufli.audio_companion import (
    _BUNDLE_DIR,
    _PILOT_LESSONS,
    _VOICE_PROFILES,
    _resolve_selected_lessons,
    _write_bundle,
    load_audio_bundles,
    load_pilot_lessons,
    load_voice_profiles,
)
from corpus.ufli.audio_companion_schema import (
    AudioClipDefinition,
    AudioFallbackClipDecision,
    AudioFallbackPolicySummary,
    FallbackDecisionBucket,
    FallbackExecutionClipResult,
    FallbackExecutionSummary,
    FallbackPacingRisk,
    GeminiFallbackPlan,
    GoogleCloudTtsSettings,
    LessonAudioBundle,
)
from corpus.ufli.audio_judge import _build_pacing_metrics

logger = logging.getLogger(__name__)

_FALLBACK_REPORT_DIR = "fallbacks"
_POLICY_NAME = "ufli_gemini_pacing_fallback_v1"
_KNOWN_RISK_SEGMENTS = {
    "lesson_014_passage_sentence_03",
}


@dataclass(frozen=True)
class _FamilyPolicy:
    auto_accept_slack_wpm: float
    min_transcript_words: int
    prompt_target_wpm: float
    prompt_wpm_min: float
    prompt_wpm_max: float
    prompt_guidance: str


_GEMINI_FAMILY_POLICIES: dict[str, _FamilyPolicy] = {
    "passage_sentence": _FamilyPolicy(
        auto_accept_slack_wpm=6.0,
        min_transcript_words=4,
        prompt_target_wpm=104.0,
        prompt_wpm_min=96.0,
        prompt_wpm_max=112.0,
        prompt_guidance=(
            "Read exactly the transcript with calm child-directed pacing at about 104 WPM. "
            "Keep it neutral and steady, preserve punctuation naturally, and do not add "
            "coaching, filler words, or extra pauses that are not already implied by the text."
        ),
    ),
    "passage_full": _FamilyPolicy(
        auto_accept_slack_wpm=4.0,
        min_transcript_words=20,
        prompt_target_wpm=112.0,
        prompt_wpm_min=104.0,
        prompt_wpm_max=118.0,
        prompt_guidance=(
            "Read exactly the transcript as a calm, neutral decodable passage at about 112 WPM. "
            "Keep the pace steady, preserve sentence boundaries naturally, and do not add "
            "coaching, embellishment, or dramatic interpretation."
        ),
    ),
}


def classify_audio_fallback_policy(
    data_dir: str = "data/ufli",
    lesson_set: str = "pilot_micro",
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
    voice_profile: str | None = None,
    output_dir: str | None = None,
    clip_limit: int | None = None,
) -> AudioFallbackPolicySummary:
    """Classify generated clips into deterministic fallback-policy buckets."""
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
    voice_catalog = load_voice_profiles(companion_dir / _VOICE_PROFILES)
    selected_voice = voice_profile or voice_catalog.default_profile
    if selected_voice not in voice_catalog.profiles:
        raise ValueError(f"Unknown voice profile: {selected_voice}")

    bundles = load_audio_bundles(
        companion_dir / _BUNDLE_DIR,
        selected_lessons=selected_lessons,
    )
    generated_clips = [
        (bundle, clip)
        for bundle in bundles
        for clip in bundle.clips
        if clip.voice_profile == selected_voice
        and clip.status == "generated"
        and clip.audio_path
        and (companion_dir / clip.audio_path).exists()
    ]
    if clip_limit is not None:
        generated_clips = generated_clips[:clip_limit]
    if not generated_clips:
        raise RuntimeError(
            f"No generated clips found for voice profile {selected_voice}. "
            "Run generate-audio --live first."
        )

    clip_results = [
        _classify_clip(
            companion_dir=companion_dir,
            bundle=bundle,
            clip=clip,
        )
        for bundle, clip in generated_clips
    ]
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir or companion_dir / _FALLBACK_REPORT_DIR) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    family_bucket_counts = _family_bucket_counts(clip_results)
    summary = AudioFallbackPolicySummary(
        generated_at=datetime.now(tz=UTC).isoformat(),
        policy_name=_POLICY_NAME,
        data_dir=str(base),
        output_dir=str(report_dir),
        voice_profile=selected_voice,
        lesson_ids=sorted({result.lesson_id for result in clip_results}, key=int),
        clip_count=len(clip_results),
        bucket_counts=dict(Counter(result.bucket for result in clip_results)),
        family_bucket_counts=family_bucket_counts,
        gemini_fallback_segments=[
            result.segment_id
            for result in clip_results
            if result.bucket == "gemini_fallback_eligible"
        ],
        required_manual_review_segments=[
            result.segment_id
            for result in clip_results
            if result.bucket == "needs_llm_or_manual_review"
        ],
        clip_results=clip_results,
    )
    _write_summary(report_dir / "fallback_summary.json", summary)
    _write_clip_results_csv(report_dir / "fallback_results.csv", clip_results)
    _write_markdown_report(report_dir / "fallback_report.md", summary)
    return summary


def _classify_clip(
    companion_dir: Path,
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
) -> AudioFallbackClipDecision:
    pacing_metrics = _build_pacing_metrics(companion_dir=companion_dir, clip=clip)
    family_policy = _GEMINI_FAMILY_POLICIES.get(clip.segment_type)
    known_risk_segment = clip.segment_id in _KNOWN_RISK_SEGMENTS
    text_risk_markers = _text_risk_markers(bundle=bundle, clip=clip)
    pace_delta_wpm = round(
        pacing_metrics.actual_wpm - pacing_metrics.expected_wpm_target,
        1,
    )
    tts_differs = clip.tts_text.strip() != clip.transcript_text.strip()

    bucket: FallbackDecisionBucket = "needs_llm_or_manual_review"
    pacing_risk: FallbackPacingRisk = "missing_measurement"
    reasons: list[str] = []
    gemini_fallback_plan: GeminiFallbackPlan | None = None

    if pacing_metrics.measurement_source != "audio_file":
        reasons.append(
            "Actual audio duration was unavailable, so fallback triage should not rely on "
            "estimated pacing alone."
        )
    else:
        pacing_risk = _pacing_risk(
            actual_wpm=pacing_metrics.actual_wpm,
            expected_min=pacing_metrics.expected_wpm_min,
            expected_max=pacing_metrics.expected_wpm_max,
            family_policy=family_policy,
        )
        if pacing_risk in {"within_band", "near_band"}:
            bucket = "auto_accept"
            if pacing_risk == "within_band":
                reasons.append("Actual pace is inside the expected clip-family band.")
            else:
                reasons.append(
                    "Actual pace is only slightly outside the expected band and not worth a "
                    "Gemini fallback pass in the initial conservative policy."
                )
        elif family_policy is None:
            reasons.append(
                "This clip family is intentionally outside the initial Gemini fallback scope."
            )
        elif pacing_risk == "too_slow":
            reasons.append(
                "The pacing miss is not a fast-side passage failure, so it stays in the "
                "manual-review bucket."
            )
        elif not clip.transcript_text.strip():
            reasons.append("Exact transcript text is unavailable for a safe Gemini retry.")
        elif pacing_metrics.transcript_word_count < family_policy.min_transcript_words:
            reasons.append(
                "The clip is too short for the initial family-specific Gemini fallback rule."
            )
        else:
            bucket = "gemini_fallback_eligible"
            reasons.append(
                "This is an eligible passage-family clip with a measured fast-side pacing miss."
            )
            reasons.append(
                "The first fallback should use the source-side exact transcript rather than the "
                "pause-shaped ElevenLabs input."
            )
            if known_risk_segment:
                reasons.append(
                    "This segment is already a diagnostics-confirmed pacing risk in the current "
                    "Dorothy/ElevenLabs path."
                )
            if text_risk_markers:
                reasons.append(
                    "Text-shaping or punctuation markers suggest a promptable transcript-first "
                    "fallback may be safer than further ElevenLabs retuning."
                )
            gemini_fallback_plan = _gemini_fallback_plan(family_policy)

    if not reasons:
        reasons.append("No policy reason recorded.")

    return AudioFallbackClipDecision(
        voice_profile=clip.voice_profile,
        lesson_id=clip.lesson_id,
        lesson_number=clip.lesson_number,
        segment_id=clip.segment_id,
        segment_type=clip.segment_type,
        audio_path=clip.audio_path,
        transcript_word_count=pacing_metrics.transcript_word_count,
        actual_duration_ms=pacing_metrics.actual_duration_ms,
        actual_wpm=round(pacing_metrics.actual_wpm, 1),
        expected_wpm_target=pacing_metrics.expected_wpm_target,
        expected_wpm_min=pacing_metrics.expected_wpm_min,
        expected_wpm_max=pacing_metrics.expected_wpm_max,
        pacing_measurement_source=pacing_metrics.measurement_source,
        pacing_risk=pacing_risk,
        pace_delta_wpm=pace_delta_wpm,
        bucket=bucket,
        known_risk_segment=known_risk_segment,
        tts_differs_from_transcript=tts_differs,
        text_risk_markers=text_risk_markers,
        reasons=reasons,
        gemini_fallback_plan=gemini_fallback_plan,
    )


def _pacing_risk(
    *,
    actual_wpm: float,
    expected_min: float,
    expected_max: float,
    family_policy: _FamilyPolicy | None,
) -> FallbackPacingRisk:
    if expected_min <= actual_wpm <= expected_max:
        return "within_band"
    if family_policy is not None:
        lower_bound = expected_min - family_policy.auto_accept_slack_wpm
        upper_bound = expected_max + family_policy.auto_accept_slack_wpm
        if lower_bound <= actual_wpm <= upper_bound:
            return "near_band"
    if actual_wpm > expected_max:
        return "too_fast"
    return "too_slow"


def _text_risk_markers(
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
) -> list[str]:
    transcript = clip.transcript_text
    markers: list[str] = []
    if clip.tts_text.strip() != transcript.strip():
        markers.append("pause_shaped_tts")
    if any(char in transcript for char in {'"', "“", "”"}):
        markers.append("quoted_dialogue")
    if "," in transcript:
        markers.append("comma_clause")
    if ";" in transcript or ":" in transcript:
        markers.append("complex_clause_punctuation")
    if clip.segment_type == "passage_sentence" and len(transcript.split()) >= 10:
        markers.append("long_sentence")
    if clip.segment_type == "passage_full" and len(bundle.passage_text.split()) >= 30:
        markers.append("long_passage")
    return markers


def _gemini_fallback_plan(family_policy: _FamilyPolicy) -> GeminiFallbackPlan:
    return GeminiFallbackPlan(
        prompt_guidance=family_policy.prompt_guidance,
        prompt_target_wpm=family_policy.prompt_target_wpm,
        prompt_wpm_min=family_policy.prompt_wpm_min,
        prompt_wpm_max=family_policy.prompt_wpm_max,
    )


def execute_gemini_fallback(
    data_dir: str = "data/ufli",
    voice_profile: str | None = None,
    output_dir: str | None = None,
    dry_run: bool = True,
    judge_model: str = "gemini-3-flash-preview",
    lesson_set: str = "pilot_micro",
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
    clip_limit: int | None = None,
) -> FallbackExecutionSummary:
    """Synthesize, re-judge, and conditionally replace pacing-failed clips.

    Only clips classified as ``gemini_fallback_eligible`` are processed.
    """
    from corpus.ufli.audio_judge import _judge_clip_with_gemini
    from corpus.ufli.extract import LessonContent

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
    voice_catalog = load_voice_profiles(companion_dir / _VOICE_PROFILES)
    selected_voice = voice_profile or voice_catalog.default_profile
    if selected_voice not in voice_catalog.profiles:
        raise ValueError(f"Unknown voice profile: {selected_voice}")

    bundle_dir = companion_dir / _BUNDLE_DIR
    bundles = load_audio_bundles(bundle_dir, selected_lessons=selected_lessons)

    policy_summary = classify_audio_fallback_policy(
        data_dir=data_dir,
        lesson_set=lesson_set,
        lesson_id=lesson_id,
        lesson_min=lesson_min,
        lesson_max=lesson_max,
        voice_profile=selected_voice,
        clip_limit=clip_limit,
    )

    eligible_ids = set(policy_summary.gemini_fallback_segments)
    eligible_decisions: dict[str, AudioFallbackClipDecision] = {
        d.segment_id: d
        for d in policy_summary.clip_results
        if d.segment_id in eligible_ids
    }
    if clip_limit is not None:
        eligible_ids = set(list(eligible_ids)[:clip_limit])

    clip_results: list[FallbackExecutionClipResult] = []
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir or companion_dir / _FALLBACK_REPORT_DIR) / f"exec_{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    clip_lookup: dict[str, tuple[LessonAudioBundle, AudioClipDefinition]] = {}
    for bundle in bundles:
        for clip in bundle.clips:
            if clip.segment_id in eligible_ids and clip.voice_profile == selected_voice:
                clip_lookup[clip.segment_id] = (bundle, clip)

    if dry_run:
        for segment_id in sorted(eligible_ids):
            decision = eligible_decisions.get(segment_id)
            clip_results.append(
                FallbackExecutionClipResult(
                    segment_id=segment_id,
                    original_audio_path=decision.audio_path if decision else "",
                    original_wpm=decision.actual_wpm if decision else 0.0,
                    status="skipped",
                    replaced=False,
                )
            )
        summary = FallbackExecutionSummary(
            generated_at=datetime.now(tz=UTC).isoformat(),
            data_dir=str(base),
            output_dir=str(report_dir),
            voice_profile=selected_voice,
            clip_count=len(clip_results),
            synthesized_count=0,
            improved_count=0,
            replaced_count=0,
            failed_count=0,
            clip_results=clip_results,
        )
        (report_dir / "fallback_execution_summary.json").write_text(
            summary.model_dump_json(indent=2)
        )
        return summary

    # Live mode: synthesize, judge, conditionally replace
    from corpus.ufli.audio_companion import _load_lessons, _measure_audio_duration_ms
    from corpus.ufli.google_tts_client import (
        GoogleTtsSynthesisError,
        build_google_tts_request_context,
        synthesize_google_tts_audio,
    )
    from rag.client import get_rag_client

    try:
        tts_context = build_google_tts_request_context()
    except Exception as exc:
        raise RuntimeError(f"Google Cloud TTS auth failed: {exc}") from exc

    gemini_client = get_rag_client()
    lessons_by_id: dict[str, LessonContent] = {
        lesson.lesson_id: lesson
        for lesson in _load_lessons(base / "normalized.jsonl")
    }

    synthesized_count = 0
    improved_count = 0
    replaced_count = 0
    failed_count = 0

    for segment_id in sorted(eligible_ids):
        entry = clip_lookup.get(segment_id)
        decision = eligible_decisions.get(segment_id)
        if entry is None or decision is None or decision.gemini_fallback_plan is None:
            clip_results.append(
                FallbackExecutionClipResult(
                    segment_id=segment_id,
                    status="skipped",
                    failure_message="Clip not found or no fallback plan",
                )
            )
            continue

        bundle, clip = entry
        plan = decision.gemini_fallback_plan
        lesson = lessons_by_id.get(bundle.lesson_id)

        settings = GoogleCloudTtsSettings(
            api_endpoint="https://us-texttospeech.googleapis.com",
            voice_name=plan.voice_name,
            model_name=plan.model_name,
            style_prompt=plan.prompt_guidance,
        )

        fallback_audio_dir = (
            companion_dir / "audio" / selected_voice / "lessons" / bundle.lesson_key
        )
        fallback_audio_dir.mkdir(parents=True, exist_ok=True)
        fallback_filename = f"{segment_id}_gemini.mp3"
        fallback_audio_path = fallback_audio_dir / fallback_filename

        try:
            result = synthesize_google_tts_audio(
                text=clip.transcript_text,
                input_format="text",
                settings=settings,
                context=tts_context,
                request_label=f"fallback_{segment_id}",
            )
            fallback_audio_path.write_bytes(result.audio_bytes)
            synthesized_count += 1
        except GoogleTtsSynthesisError as exc:
            logger.warning("TTS synthesis failed for %s: %s", segment_id, exc)
            clip_results.append(
                FallbackExecutionClipResult(
                    segment_id=segment_id,
                    original_audio_path=clip.audio_path,
                    original_wpm=decision.actual_wpm,
                    status="synthesis_failed",
                    replaced=False,
                    failure_message=str(exc),
                )
            )
            failed_count += 1
            continue
        except Exception as exc:
            logger.warning("Unexpected TTS error for %s: %s", segment_id, exc)
            clip_results.append(
                FallbackExecutionClipResult(
                    segment_id=segment_id,
                    original_audio_path=clip.audio_path,
                    original_wpm=decision.actual_wpm,
                    status="synthesis_failed",
                    replaced=False,
                    failure_message=str(exc),
                )
            )
            failed_count += 1
            continue

        # Measure fallback duration and re-judge
        fallback_duration_ms = _measure_audio_duration_ms(fallback_audio_path)
        fallback_wpm = 0.0
        if fallback_duration_ms and fallback_duration_ms > 0:
            word_count = max(len(clip.transcript_text.split()), 1)
            fallback_wpm = (float(word_count) * 60000.0) / float(fallback_duration_ms)

        fallback_recommendation = "revise"
        if lesson is not None:
            fallback_clip = clip.model_copy(
                update={
                    "audio_path": str(
                        fallback_audio_path.relative_to(companion_dir)
                    ),
                }
            )
            try:
                judge_result = _judge_clip_with_gemini(
                    client=gemini_client,
                    judge_model=judge_model,
                    companion_dir=companion_dir,
                    lesson=lesson,
                    bundle=bundle,
                    clip=fallback_clip,
                )
                fallback_recommendation = judge_result.recommendation
                fallback_wpm = judge_result.actual_wpm
            except Exception as exc:
                logger.warning("Judge failed for fallback %s: %s", segment_id, exc)

        improved = fallback_recommendation == "use"
        replaced = False
        if improved:
            improved_count += 1
            clip.audio_path = str(fallback_audio_path.relative_to(companion_dir))
            clip.review_status = "approved"
            replaced = True
            replaced_count += 1
            _write_bundle(bundle_dir, bundle)

        clip_results.append(
            FallbackExecutionClipResult(
                segment_id=segment_id,
                original_audio_path=decision.audio_path,
                fallback_audio_path=str(fallback_audio_path.relative_to(companion_dir)),
                original_wpm=decision.actual_wpm,
                fallback_wpm=round(fallback_wpm, 1),
                original_recommendation="revise",
                fallback_recommendation=fallback_recommendation,
                status="improved" if improved else "not_improved",
                replaced=replaced,
            )
        )

    summary = FallbackExecutionSummary(
        generated_at=datetime.now(tz=UTC).isoformat(),
        data_dir=str(base),
        output_dir=str(report_dir),
        voice_profile=selected_voice,
        clip_count=len(clip_results),
        synthesized_count=synthesized_count,
        improved_count=improved_count,
        replaced_count=replaced_count,
        failed_count=failed_count,
        clip_results=clip_results,
    )
    (report_dir / "fallback_execution_summary.json").write_text(
        summary.model_dump_json(indent=2)
    )
    return summary


def _family_bucket_counts(
    clip_results: list[AudioFallbackClipDecision],
) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for result in clip_results:
        grouped[result.segment_type][result.bucket] += 1
    return {
        segment_type: dict(counter)
        for segment_type, counter in grouped.items()
    }


def _write_summary(path: Path, summary: AudioFallbackPolicySummary) -> None:
    path.write_text(summary.model_dump_json(indent=2))


def _write_clip_results_csv(
    path: Path,
    clip_results: list[AudioFallbackClipDecision],
) -> None:
    if not clip_results:
        return
    rows = [result.model_dump(mode="json") for result in clip_results]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )


def _write_markdown_report(path: Path, summary: AudioFallbackPolicySummary) -> None:
    lines = [
        "# UFLI Audio Fallback Policy Report",
        "",
        f"- Policy: `{summary.policy_name}`",
        f"- Execution mode: `{summary.execution_mode}`",
        f"- Voice profile: `{summary.voice_profile}`",
        f"- Lessons: `{', '.join(summary.lesson_ids)}`",
        f"- Clips classified: `{summary.clip_count}`",
        f"- Bucket counts: `{summary.bucket_counts}`",
        "",
        "Note: This report is heuristic-first and intentionally conservative. "
        "Gemini fallback remains advisory/manual because Google provider instability "
        "(for example transient 499/502 errors) is assumed.",
        "",
        "## Family Buckets",
        "",
    ]
    if not summary.family_bucket_counts:
        lines.append("- None")
    else:
        for segment_type, counts in summary.family_bucket_counts.items():
            lines.append(f"- `{segment_type}`: `{counts}`")

    lines.extend(["", "## Gemini Fallback Eligible", ""])
    eligible = [
        result
        for result in summary.clip_results
        if result.bucket == "gemini_fallback_eligible"
    ]
    if not eligible:
        lines.append("- None")
    else:
        for result in eligible:
            lines.append(
                f"- `{result.segment_id}` ({result.segment_type}): "
                f"wpm={result.actual_wpm:.1f} target={result.expected_wpm_target:.1f} "
                f"markers={result.text_risk_markers} reasons={result.reasons}"
            )

    lines.extend(["", "## Needs LLM Or Manual Review", ""])
    manual_review = [
        result
        for result in summary.clip_results
        if result.bucket == "needs_llm_or_manual_review"
    ]
    if not manual_review:
        lines.append("- None")
    else:
        for result in manual_review:
            lines.append(
                f"- `{result.segment_id}` ({result.segment_type}): "
                f"risk={result.pacing_risk} wpm={result.actual_wpm:.1f} "
                f"reasons={result.reasons}"
            )

    path.write_text("\n".join(lines) + "\n")
