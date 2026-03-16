"""LLM-judge evaluation for generated UFLI audio companion clips."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from corpus.ufli.audio_companion import (
    _estimate_duration_ms,
    _load_lessons,
    _measure_audio_duration_ms,
    _resolve_selected_lessons,
    load_audio_bundles,
    load_pilot_lessons,
    load_voice_profiles,
)
from corpus.ufli.audio_companion_schema import (
    AudioClipDefinition,
    AudioJudgeClipResult,
    AudioJudgeSummary,
    LessonAudioBundle,
    PacingMeasurementSource,
)
from corpus.ufli.extract import LessonContent
from rag.client import get_rag_client

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = os.environ.get("UFLI_AUDIO_JUDGE_MODEL", "gemini-3-flash-preview")
_BUNDLE_DIR = "lessons"
_PILOT_LESSONS = "pilot_lessons.yaml"
_VOICE_PROFILES = "voice_profiles.yaml"
_EVAL_DIR = "evals"


@dataclass(frozen=True)
class _PacingMetrics:
    actual_duration_ms: int
    actual_wpm: float
    expected_wpm_target: float
    expected_wpm_min: float
    expected_wpm_max: float
    measurement_source: PacingMeasurementSource


# Conservative child-directed pacing bands for ages 5-8, set below the 150 WPM
# TTS research baseline reported for older students and aligned to explicit,
# decoding-first instruction where slower segmented delivery is preferable.
_PACING_PROFILES: dict[str, tuple[float, float, float]] = {
    "lesson_instruction": (92.0, 78.0, 108.0),
    "phoneme_model": (58.0, 35.0, 75.0),
    "word_model": (78.0, 45.0, 92.0),
    "passage_sentence": (108.0, 92.0, 122.0),
    "passage_full": (115.0, 100.0, 128.0),
    "review": (92.0, 78.0, 108.0),
}


def judge_audio_companion(
    data_dir: str = "data/ufli",
    lesson_set: str = "pilot_micro",
    lesson_id: str | None = None,
    lesson_min: int = 1,
    lesson_max: int = 128,
    voice_profile: str | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    output_dir: str | None = None,
    clip_limit: int | None = None,
) -> AudioJudgeSummary:
    """Judge generated audio companion clips against lesson content."""
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
    lessons = {
        lesson.lesson_id: lesson
        for lesson in _load_lessons(base / "normalized.jsonl")
        if lesson.lesson_id in {bundle.lesson_id for bundle in bundles}
    }

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

    client = get_rag_client()
    clip_results: list[AudioJudgeClipResult] = []
    for bundle, clip in generated_clips:
        lesson = lessons.get(bundle.lesson_id)
        if lesson is None:
            continue
        clip_results.append(
            _judge_clip_with_gemini(
                client=client,
                judge_model=judge_model,
                companion_dir=companion_dir,
                lesson=lesson,
                bundle=bundle,
                clip=clip,
            )
        )

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir or companion_dir / _EVAL_DIR) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = AudioJudgeSummary(
        generated_at=datetime.now(tz=UTC).isoformat(),
        judge_model=judge_model,
        data_dir=str(base),
        output_dir=str(report_dir),
        voice_profile=selected_voice,
        lesson_ids=sorted({result.lesson_id for result in clip_results}, key=int),
        clip_count=len(clip_results),
        blocker_count=sum(1 for result in clip_results if result.blocker),
        recommendation_counts=dict(
            Counter(result.recommendation for result in clip_results)
        ),
        median_scores=_median_scores(clip_results),
        clip_results=clip_results,
    )

    _write_summary(report_dir / "judge_summary.json", summary)
    _write_clip_results_csv(report_dir / "judge_results.csv", clip_results)
    _write_markdown_report(report_dir / "judge_report.md", summary)
    logger.info("Audio judge report written to %s", report_dir)
    return summary


def _judge_clip_with_gemini(
    client: Any,
    judge_model: str,
    companion_dir: Path,
    lesson: LessonContent,
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
) -> AudioJudgeClipResult:
    pacing_metrics = _build_pacing_metrics(companion_dir=companion_dir, clip=clip)
    prompt = _build_judge_prompt(
        lesson=lesson,
        bundle=bundle,
        clip=clip,
        pacing_metrics=pacing_metrics,
    )
    contents = _build_judge_contents(
        companion_dir=companion_dir,
        clip=clip,
        prompt=prompt,
    )
    response = client.models.generate_content(
        model=judge_model,
        contents=contents,
    )
    parsed = _apply_clarity_guardrails(
        _apply_pronunciation_guardrails(
            _apply_pacing_guardrails(
                _parse_judge_response(str(response.text)),
                pacing_metrics=pacing_metrics,
            )
        ),
        expected_transcript=clip.transcript_text,
    )
    return AudioJudgeClipResult(
        voice_profile=clip.voice_profile,
        lesson_id=clip.lesson_id,
        lesson_number=clip.lesson_number,
        segment_id=clip.segment_id,
        segment_type=clip.segment_type,
        audio_path=clip.audio_path,
        actual_duration_ms=pacing_metrics.actual_duration_ms,
        actual_wpm=round(pacing_metrics.actual_wpm, 1),
        expected_wpm_target=pacing_metrics.expected_wpm_target,
        expected_wpm_min=pacing_metrics.expected_wpm_min,
        expected_wpm_max=pacing_metrics.expected_wpm_max,
        pacing_measurement_source=pacing_metrics.measurement_source,
        **parsed,
    )


def _build_judge_prompt(
    lesson: LessonContent,
    bundle: LessonAudioBundle,
    clip: AudioClipDefinition,
    pacing_metrics: _PacingMetrics,
) -> str:
    source_excerpt = _source_excerpt(lesson, clip)
    return (
        "You are judging whether a generated audio companion clip is instructionally "
        "appropriate for UFLI explicit reading instruction for children ages 5 to 8 "
        "with ADHD traits.\n\n"
        "Judge the intended spoken content and the measured pacing from the generated "
        "audio file. Do not judge voice pleasantness. Do judge whether the actual "
        "spoken pronunciation in the waveform is clear and phonetically appropriate "
        "for the lesson targets. Focus on whether the transcript/script matches the "
        "UFLI lesson content, supports decoding instead of replacing it, and moves at "
        "a calm, consistent pace for a child ages 5 to 8 with ADHD traits.\n\n"
        "Scoring rules:\n"
        "- clarity_score: Based on the ACTUAL audio file, are the words clear, "
        "intelligible, and easy for a young child to distinguish?\n"
        "- pronunciation_accuracy_score: Based on the ACTUAL audio file, are the target "
        "phoneme/grapheme/word pronunciations acoustically accurate and distinct for "
        "explicit reading instruction?\n"
        "- instructional_match_score: Does this clip match the lesson concept, words, "
        "or passage content?\n"
        "- target_accuracy_score: Are the grapheme/phoneme/word targets correct and "
        "non-misleading?\n"
        "- decoding_support_score: Does the clip support explicit reading instruction "
        "without giving away the work too early?\n"
        "- passage_neutrality_score: Only for passage clips. Is the passage read "
        "neutrally without extra coaching embedded in the text? Use null when not "
        "applicable.\n"
        "- adhd_supportiveness_score: Is the wording calm, predictable, low stimulation, "
        "and one task at a time?\n"
        "- pacing_suitability_score: Based on the ACTUAL audio duration and WPM, is the "
        "pace manageable for the child and clip type?\n"
        "- pacing_consistency_score: Based on the ACTUAL audio duration and WPM, does the "
        "pace stay reasonably consistent with the intended pace band for this clip type?\n"
        "- blocker: true if this clip should not be used with children until revised.\n"
        "- recommendation: one of use, revise, block.\n\n"
        f"Lesson ID: {lesson.lesson_id}\n"
        f"Lesson concept: {bundle.concept}\n"
        f"Word targets: {', '.join(bundle.word_targets)}\n"
        f"Phoneme targets: {', '.join(bundle.phoneme_targets)}\n"
        f"Passage text: {bundle.passage_text or '[no passage]'}\n"
        f"Clip type: {clip.segment_type}\n"
        f"Clip transcript: {clip.transcript_text}\n"
        f"Clip TTS text: {clip.tts_text}\n"
        f"Pronunciation targets: {', '.join(clip.pronunciation_targets) or '[none]'}\n"
        f"Source fields: {', '.join(clip.source_fields)}\n"
        f"Audio pacing measurement source: {pacing_metrics.measurement_source}\n"
        f"Actual audio duration (ms): {pacing_metrics.actual_duration_ms}\n"
        f"Actual audio WPM: {pacing_metrics.actual_wpm:.1f}\n"
        f"Expected pacing target WPM: {pacing_metrics.expected_wpm_target:.1f}\n"
        f"Expected pacing band WPM: {pacing_metrics.expected_wpm_min:.1f}-"
        f"{pacing_metrics.expected_wpm_max:.1f}\n"
        f"Lesson source excerpt: {source_excerpt}\n\n"
        "Return ONLY JSON with this shape:\n"
        "{\n"
        '  "heard_text": "best-effort transcript of what you hear in the audio",\n'
        '  "clarity_score": 1-5,\n'
        '  "pronunciation_accuracy_score": 1-5,\n'
        '  "instructional_match_score": 1-5,\n'
        '  "target_accuracy_score": 1-5,\n'
        '  "decoding_support_score": 1-5,\n'
        '  "passage_neutrality_score": 1-5 or null,\n'
        '  "adhd_supportiveness_score": 1-5,\n'
        '  "pacing_suitability_score": 1-5,\n'
        '  "pacing_consistency_score": 1-5,\n'
        '  "blocker": true or false,\n'
        '  "recommendation": "use" or "revise" or "block",\n'
        '  "strengths": ["..."],\n'
        '  "concerns": ["..."],\n'
        '  "rationale": "short paragraph"\n'
        "}\n"
    )


def _source_excerpt(lesson: LessonContent, clip: AudioClipDefinition) -> str:
    parts: list[str] = []
    for field in clip.source_fields:
        value = getattr(lesson, field, "")
        if value:
            parts.append(_clean_excerpt(value))
    if not parts:
        parts = [
            _clean_excerpt(lesson.concept),
            _clean_excerpt(lesson.slide_text),
        ]
    return "\n\n".join(part for part in parts if part)


def _build_judge_contents(
    companion_dir: Path,
    clip: AudioClipDefinition,
    prompt: str,
) -> Any:
    audio_path = companion_dir / clip.audio_path if clip.audio_path else None
    if audio_path is None or not audio_path.exists():
        return prompt

    try:
        from google.genai import types

        mime_type = "audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav"
        audio_part = types.Part.from_bytes(
            data=audio_path.read_bytes(),
            mime_type=mime_type,
        )
        text_part = types.Part.from_text(text=prompt)
        return [audio_part, text_part]
    except Exception as exc:
        logger.warning("Falling back to text-only judge prompt for %s: %s", audio_path, exc)
        return prompt


def _clean_excerpt(text: str, limit: int = 600) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit].rstrip()}..."


def _parse_judge_response(text: str) -> dict[str, Any]:
    payload = text.strip()
    if payload.startswith("```"):
        lines = payload.splitlines()
        payload = "\n".join(
            line
            for line in lines
            if not line.strip().startswith("```")
        )
    data = json.loads(payload)
    return {
        "heard_text": str(data.get("heard_text", "")).strip(),
        "clarity_score": int(data["clarity_score"]),
        "pronunciation_accuracy_score": int(data["pronunciation_accuracy_score"]),
        "instructional_match_score": int(data["instructional_match_score"]),
        "target_accuracy_score": int(data["target_accuracy_score"]),
        "decoding_support_score": int(data["decoding_support_score"]),
        "passage_neutrality_score": (
            int(data["passage_neutrality_score"])
            if data.get("passage_neutrality_score") is not None
            else None
        ),
        "adhd_supportiveness_score": int(data["adhd_supportiveness_score"]),
        "pacing_suitability_score": int(data["pacing_suitability_score"]),
        "pacing_consistency_score": int(data["pacing_consistency_score"]),
        "blocker": bool(data.get("blocker", False)),
        "recommendation": str(data["recommendation"]),
        "strengths": [str(item) for item in data.get("strengths", [])],
        "concerns": [str(item) for item in data.get("concerns", [])],
        "rationale": str(data.get("rationale", "")),
    }


def _median_scores(clip_results: list[AudioJudgeClipResult]) -> dict[str, float]:
    passage_scores = [
        result.passage_neutrality_score
        for result in clip_results
        if result.passage_neutrality_score is not None
    ]
    scores: dict[str, float] = {
        "instructional_match_score": float(
            median(result.instructional_match_score for result in clip_results)
        ),
        "clarity_score": float(
            median(result.clarity_score for result in clip_results)
        ),
        "pronunciation_accuracy_score": float(
            median(result.pronunciation_accuracy_score for result in clip_results)
        ),
        "target_accuracy_score": float(
            median(result.target_accuracy_score for result in clip_results)
        ),
        "decoding_support_score": float(
            median(result.decoding_support_score for result in clip_results)
        ),
        "adhd_supportiveness_score": float(
            median(result.adhd_supportiveness_score for result in clip_results)
        ),
        "pacing_suitability_score": float(
            median(result.pacing_suitability_score for result in clip_results)
        ),
        "pacing_consistency_score": float(
            median(result.pacing_consistency_score for result in clip_results)
        ),
    }
    if passage_scores:
        scores["passage_neutrality_score"] = float(median(passage_scores))
    return scores


def _build_pacing_metrics(companion_dir: Path, clip: AudioClipDefinition) -> _PacingMetrics:
    target_wpm, min_wpm, max_wpm = _PACING_PROFILES[clip.segment_type]
    transcript_word_count = max(len(clip.transcript_text.split()), 1)
    audio_path = companion_dir / clip.audio_path if clip.audio_path else None
    actual_duration_ms = (
        _measure_audio_duration_ms(audio_path)
        if audio_path is not None
        else None
    )
    measurement_source: PacingMeasurementSource = "audio_file"
    if actual_duration_ms is None:
        actual_duration_ms = clip.duration_ms or _estimate_duration_ms(
            clip.tts_text,
            clip.segment_type,
        )
        measurement_source = "estimate_fallback"
    actual_wpm = (float(transcript_word_count) * 60000.0) / float(actual_duration_ms)
    return _PacingMetrics(
        actual_duration_ms=actual_duration_ms,
        actual_wpm=actual_wpm,
        expected_wpm_target=target_wpm,
        expected_wpm_min=min_wpm,
        expected_wpm_max=max_wpm,
        measurement_source=measurement_source,
    )


def _apply_pacing_guardrails(
    result: dict[str, Any],
    pacing_metrics: _PacingMetrics,
) -> dict[str, Any]:
    concerns = [str(item) for item in result.get("concerns", [])]
    actual_wpm = pacing_metrics.actual_wpm
    target_wpm = pacing_metrics.expected_wpm_target
    min_wpm = pacing_metrics.expected_wpm_min
    max_wpm = pacing_metrics.expected_wpm_max

    if actual_wpm < min_wpm or actual_wpm > max_wpm:
        concerns.append(
            "Actual audio pace is outside the expected band "
            f"({actual_wpm:.1f} WPM vs {min_wpm:.1f}-{max_wpm:.1f} WPM)."
        )
        result["pacing_suitability_score"] = min(
            int(result["pacing_suitability_score"]),
            3,
        )
        result["pacing_consistency_score"] = min(
            int(result["pacing_consistency_score"]),
            2,
        )
        if result["recommendation"] == "use":
            result["recommendation"] = "revise"
        if actual_wpm < (min_wpm * 0.7) or actual_wpm > (max_wpm * 1.3):
            result["blocker"] = True

    deviation_ratio = abs(actual_wpm - target_wpm) / target_wpm if target_wpm else 0.0
    if deviation_ratio > 0.2:
        concerns.append(
            "Actual audio pace is materially inconsistent with the target pace "
            f"for this clip family ({actual_wpm:.1f} WPM vs target {target_wpm:.1f} WPM)."
        )
        result["pacing_consistency_score"] = min(
            int(result["pacing_consistency_score"]),
            3,
        )
        if result["recommendation"] == "use":
            result["recommendation"] = "revise"

    result["concerns"] = concerns
    return result


def _apply_clarity_guardrails(
    result: dict[str, Any],
    expected_transcript: str,
) -> dict[str, Any]:
    heard_text = str(result.get("heard_text", "")).strip()
    if not heard_text:
        return result

    concerns = [str(item) for item in result.get("concerns", [])]
    expected_normalized = _normalize_for_match(expected_transcript)
    heard_normalized = _normalize_for_match(heard_text)
    if not expected_normalized or not heard_normalized:
        return result

    overlap = _token_overlap_ratio(expected_normalized, heard_normalized)
    if overlap < 0.85:
        concerns.append(
            "Best-effort transcription of the audio does not closely match the intended "
            f"transcript (match={overlap:.2f})."
        )
        result["clarity_score"] = min(int(result["clarity_score"]), 3)
        if result["recommendation"] == "use":
            result["recommendation"] = "revise"
        if overlap < 0.6:
            result["blocker"] = True

    result["concerns"] = concerns
    return result


def _apply_pronunciation_guardrails(result: dict[str, Any]) -> dict[str, Any]:
    pronunciation_score = int(result["pronunciation_accuracy_score"])
    if pronunciation_score >= 4:
        return result

    concerns = [str(item) for item in result.get("concerns", [])]
    concerns.append(
        "Acoustic pronunciation of the target sound/word is not strong enough for "
        "explicit reading instruction."
    )
    if pronunciation_score <= 2:
        result["blocker"] = True
        if result["recommendation"] != "block":
            result["recommendation"] = "block"
    elif result["recommendation"] == "use":
        result["recommendation"] = "revise"
    result["concerns"] = concerns
    return result


def _normalize_for_match(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def _token_overlap_ratio(expected_tokens: list[str], heard_tokens: list[str]) -> float:
    if not expected_tokens or not heard_tokens:
        return 0.0
    matched = sum(1 for token in expected_tokens if token in heard_tokens)
    return matched / float(len(expected_tokens))


def _write_summary(path: Path, summary: AudioJudgeSummary) -> None:
    path.write_text(summary.model_dump_json(indent=2))


def _write_clip_results_csv(path: Path, clip_results: list[AudioJudgeClipResult]) -> None:
    if not clip_results:
        return
    rows = [result.model_dump() for result in clip_results]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value) if isinstance(value, list) else value
                    for key, value in row.items()
                }
            )


def _write_markdown_report(path: Path, summary: AudioJudgeSummary) -> None:
    lines = [
        "# UFLI Audio Judge Report",
        "",
        f"- Judge model: `{summary.judge_model}`",
        f"- Voice profile: `{summary.voice_profile}`",
        f"- Lessons: `{', '.join(summary.lesson_ids)}`",
        f"- Clips judged: `{summary.clip_count}`",
        f"- Blockers: `{summary.blocker_count}`",
        f"- Recommendations: `{summary.recommendation_counts}`",
        f"- Median scores: `{summary.median_scores}`",
        "",
        "Note: This judge evaluates transcript/script alignment, actual audio clarity, "
        "actual audio pacing, and model-based acoustic pronunciation judgments from the "
        "generated file. It is still not a forced-alignment or phonetics-lab measurement.",
        "",
        "## Blocked or Revision Clips",
        "",
    ]
    flagged = [
        result
        for result in summary.clip_results
        if result.blocker or result.recommendation != "use"
    ]
    if not flagged:
        lines.append("- None")
    else:
        for result in flagged:
            lines.append(
                f"- `{result.segment_id}` ({result.segment_type}): "
                f"`{result.recommendation}` blocker={result.blocker} "
                f"wpm={result.actual_wpm:.1f} "
                f"clarity={result.clarity_score} "
                f"pronunciation={result.pronunciation_accuracy_score} "
                f"concerns={result.concerns}"
            )
    path.write_text("\n".join(lines) + "\n")
