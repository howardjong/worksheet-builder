"""Tests for deterministic UFLI audio fallback-policy classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from corpus.ufli.audio_companion import build_audio_companion_manifests
from corpus.ufli.audio_fallback_policy import (
    _classify_clip,
    classify_audio_fallback_policy,
)
from corpus.ufli.audio_judge import _PacingMetrics


def _write_normalized(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _write_companion_configs(base: Path) -> None:
    source_dir = Path("data/ufli/companion")
    target_dir = base / "companion"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "pronunciation_lexicon.yaml",
        "voice_profiles.yaml",
        "pilot_lessons.yaml",
    ):
        (target_dir / name).write_text((source_dir / name).read_text())


def _sample_rows() -> list[dict[str, object]]:
    return [
        {
            "lesson_id": "1",
            "lesson_group": "1-34",
            "concept": "a /ă/",
            "slide_text": "Lesson 1 a /ă/ cat map at as.",
            "slide_count": 4,
            "decodable_text": "",
            "home_practice_text": "",
            "additional_text": "",
        },
        {
            "lesson_id": "14",
            "lesson_group": "1-34",
            "concept": "c /k/",
            "slide_text": "Lesson 14 c /k/ can cat cap cot cod.",
            "slide_count": 6,
            "decodable_text": (
                "Lesson 14: c /k/ The Cat Can Illustrate the story here: "
                "Can Cam fit on the cot? The cat can fit on the cot."
            ),
            "home_practice_text": "1. cat → cap → cop → cod",
            "additional_text": "",
        },
    ]


def test_classify_clip_marks_fast_passage_sentence_as_gemini_fallback_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(data_dir=str(tmp_path))[1]
    clip = next(item for item in bundle.clips if item.segment_type == "passage_sentence")
    clip.status = "generated"
    clip.voice_profile = "dorothy"
    clip.speaker = "dorothy"
    clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
    audio_path = tmp_path / "companion" / clip.audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"mp3")
    monkeypatch.setattr(
        "corpus.ufli.audio_fallback_policy._KNOWN_RISK_SEGMENTS",
        {clip.segment_id},
    )

    monkeypatch.setattr(
        "corpus.ufli.audio_fallback_policy._build_pacing_metrics",
        lambda **_: _PacingMetrics(
            segment_type="passage_sentence",
            transcript_word_count=max(len(clip.transcript_text.split()), 1),
            actual_duration_ms=3100,
            actual_wpm=135.1,
            expected_wpm_target=108.0,
            expected_wpm_min=92.0,
            expected_wpm_max=122.0,
            measurement_source="audio_file",
        ),
    )

    result = _classify_clip(
        companion_dir=tmp_path / "companion",
        bundle=bundle,
        clip=clip,
    )

    assert result.bucket == "gemini_fallback_eligible"
    assert result.known_risk_segment is True
    assert result.gemini_fallback_plan is not None
    assert result.gemini_fallback_plan.transcript_strategy == "exact_transcript"
    assert result.gemini_fallback_plan.model_name == "gemini-2.5-pro-tts"
    assert any("fast-side pacing miss" in reason for reason in result.reasons)


def test_classify_clip_keeps_slow_passage_full_in_manual_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(data_dir=str(tmp_path))[1]
    clip = next(item for item in bundle.clips if item.segment_type == "passage_full")
    clip.status = "generated"
    clip.voice_profile = "dorothy"
    clip.speaker = "dorothy"
    clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
    audio_path = tmp_path / "companion" / clip.audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"mp3")

    monkeypatch.setattr(
        "corpus.ufli.audio_fallback_policy._build_pacing_metrics",
        lambda **_: _PacingMetrics(
            segment_type="passage_full",
            transcript_word_count=max(len(clip.transcript_text.split()), 1),
            actual_duration_ms=11000,
            actual_wpm=88.9,
            expected_wpm_target=115.0,
            expected_wpm_min=100.0,
            expected_wpm_max=128.0,
            measurement_source="audio_file",
        ),
    )

    result = _classify_clip(
        companion_dir=tmp_path / "companion",
        bundle=bundle,
        clip=clip,
    )

    assert result.bucket == "needs_llm_or_manual_review"
    assert result.gemini_fallback_plan is None
    assert result.pacing_risk == "too_slow"


def test_classify_clip_keeps_fast_phoneme_model_outside_fallback_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(data_dir=str(tmp_path))[0]
    clip = next(item for item in bundle.clips if item.segment_type == "phoneme_model")
    clip.status = "generated"
    clip.voice_profile = "dorothy"
    clip.speaker = "dorothy"
    clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
    audio_path = tmp_path / "companion" / clip.audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"mp3")

    monkeypatch.setattr(
        "corpus.ufli.audio_fallback_policy._build_pacing_metrics",
        lambda **_: _PacingMetrics(
            segment_type="phoneme_model",
            transcript_word_count=max(len(clip.transcript_text.split()), 1),
            actual_duration_ms=900,
            actual_wpm=100.6,
            expected_wpm_target=58.0,
            expected_wpm_min=35.0,
            expected_wpm_max=75.0,
            measurement_source="audio_file",
        ),
    )

    result = _classify_clip(
        companion_dir=tmp_path / "companion",
        bundle=bundle,
        clip=clip,
    )

    assert result.bucket == "needs_llm_or_manual_review"
    assert result.gemini_fallback_plan is None
    assert any("outside the initial Gemini fallback scope" in reason for reason in result.reasons)


def test_classify_audio_fallback_policy_writes_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundles = build_audio_companion_manifests(data_dir=str(tmp_path))
    bundle = bundles[1]
    for clip in bundle.clips:
        clip.status = "generated"
        clip.voice_profile = "dorothy"
        clip.speaker = "dorothy"
        clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
        audio_path = tmp_path / "companion" / clip.audio_path
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"mp3")
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )

    def _fake_build_pacing_metrics(**kwargs: object) -> _PacingMetrics:
        clip = kwargs["clip"]
        segment_type = getattr(clip, "segment_type")
        transcript_word_count = max(len(getattr(clip, "transcript_text").split()), 1)
        if segment_type == "passage_sentence":
            actual_wpm = 135.1
            duration_ms = 3100
            expected = (108.0, 92.0, 122.0)
        elif segment_type == "passage_full":
            actual_wpm = 88.9
            duration_ms = 11000
            expected = (115.0, 100.0, 128.0)
        elif segment_type == "review":
            actual_wpm = 90.0
            duration_ms = 2600
            expected = (92.0, 78.0, 108.0)
        else:
            actual_wpm = 80.0
            duration_ms = 1500
            expected = (78.0, 45.0, 92.0)
        return _PacingMetrics(
            segment_type=segment_type,
            transcript_word_count=transcript_word_count,
            actual_duration_ms=duration_ms,
            actual_wpm=actual_wpm,
            expected_wpm_target=expected[0],
            expected_wpm_min=expected[1],
            expected_wpm_max=expected[2],
            measurement_source="audio_file",
        )

    monkeypatch.setattr(
        "corpus.ufli.audio_fallback_policy._build_pacing_metrics",
        _fake_build_pacing_metrics,
    )

    summary = classify_audio_fallback_policy(
        data_dir=str(tmp_path),
        lesson_id="14",
        voice_profile="dorothy",
    )

    output_dir = Path(summary.output_dir)
    assert summary.clip_count == len(bundle.clips)
    assert summary.bucket_counts["gemini_fallback_eligible"] >= 1
    assert summary.bucket_counts["needs_llm_or_manual_review"] >= 1
    assert (output_dir / "fallback_summary.json").exists()
    assert (output_dir / "fallback_results.csv").exists()
    assert (output_dir / "fallback_report.md").exists()
