"""Tests for automated Gemini fallback execution in audio_fallback_policy."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

pytest.importorskip("chromadb")

from experiments.corpus_ufli.audio_companion import (
    build_audio_companion_manifests,
    load_audio_bundles,
)
from experiments.corpus_ufli.audio_companion_schema import AudioClipDefinition, AudioJudgeClipResult
from experiments.corpus_ufli.audio_fallback_policy import execute_gemini_fallback
from experiments.corpus_ufli.audio_judge import _PacingMetrics


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
            "lesson_id": "14",
            "lesson_group": "1-34",
            "concept": "c /k/",
            "slide_text": "Lesson 14 c /k/ can cat cap cot cod.",
            "slide_count": 6,
            "decodable_text": (
                "Lesson 14: c /k/ The Cat Can Illustrate the story here: "
                "Can Cam fit on the cot? The cat can fit on the cot."
            ),
            "home_practice_text": "1. cat -> cap -> cop -> cod",
            "additional_text": "",
        },
    ]


def _prepare_generated_bundle(tmp_path: Path) -> None:
    bundles = build_audio_companion_manifests(data_dir=str(tmp_path), lesson_id="14")
    bundle = bundles[0]
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


def _fast_pacing_metrics(**kwargs: object) -> _PacingMetrics:
    clip = kwargs["clip"]
    segment_type = getattr(clip, "segment_type")
    transcript_word_count = max(len(getattr(clip, "transcript_text").split()), 1)
    if segment_type == "passage_sentence":
        return _PacingMetrics(
            segment_type=segment_type,
            transcript_word_count=transcript_word_count,
            actual_duration_ms=3100,
            actual_wpm=135.1,
            expected_wpm_target=108.0,
            expected_wpm_min=92.0,
            expected_wpm_max=122.0,
            measurement_source="audio_file",
        )
    if segment_type == "passage_full":
        return _PacingMetrics(
            segment_type=segment_type,
            transcript_word_count=transcript_word_count,
            actual_duration_ms=3100,
            actual_wpm=135.1,
            expected_wpm_target=115.0,
            expected_wpm_min=100.0,
            expected_wpm_max=128.0,
            measurement_source="audio_file",
        )
    return _PacingMetrics(
        segment_type=segment_type,
        transcript_word_count=transcript_word_count,
        actual_duration_ms=2000,
        actual_wpm=90.0,
        expected_wpm_target=92.0,
        expected_wpm_min=78.0,
        expected_wpm_max=108.0,
        measurement_source="audio_file",
    )


def test_dry_run_skips_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path)

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_fallback_policy._build_pacing_metrics",
        _fast_pacing_metrics,
    )

    summary = execute_gemini_fallback(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        lesson_id="14",
        dry_run=True,
    )

    assert summary.synthesized_count == 0
    assert all(r.status == "skipped" for r in summary.clip_results)


def test_live_synthesizes_and_replaces_when_improved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path)

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_fallback_policy._build_pacing_metrics",
        _fast_pacing_metrics,
    )

    fake_tts_result = SimpleNamespace(audio_bytes=b"gemini-mp3", attempt_count=1, retry_delays_s=())
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.build_google_tts_request_context",
        lambda: SimpleNamespace(access_token="test", project_id="test"),
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.synthesize_google_tts_audio",
        lambda **_kw: fake_tts_result,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_companion._measure_audio_duration_ms",
        lambda _path: 5000,
    )
    monkeypatch.setattr(
        "rag.client.get_rag_client",
        lambda: object(),
    )

    def _fake_judge(**kwargs: object) -> AudioJudgeClipResult:
        clip = cast(AudioClipDefinition, kwargs["clip"])
        return AudioJudgeClipResult(
            voice_profile="dorothy",
            lesson_id=clip.lesson_id,
            lesson_number=clip.lesson_number,
            segment_id=clip.segment_id,
            segment_type=clip.segment_type,
            audio_path=clip.audio_path,
            transcript_word_count=max(len(clip.transcript_text.split()), 1),
            actual_duration_ms=5000,
            actual_wpm=105.0,
            expected_wpm_target=108.0,
            expected_wpm_min=92.0,
            expected_wpm_max=122.0,
            pacing_measurement_source="audio_file",
            heard_text=clip.transcript_text,
            clarity_score=5,
            pronunciation_accuracy_score=5,
            instructional_match_score=5,
            target_accuracy_score=5,
            decoding_support_score=5,
            passage_neutrality_score=5 if clip.segment_type.startswith("passage") else None,
            adhd_supportiveness_score=5,
            pacing_suitability_score=5,
            pacing_consistency_score=5,
            blocker=False,
            recommendation="use",
            strengths=["improved pacing"],
            concerns=[],
            rationale="Good.",
        )

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_judge._judge_clip_with_gemini",
        _fake_judge,
    )

    summary = execute_gemini_fallback(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        lesson_id="14",
        dry_run=False,
    )

    assert summary.synthesized_count > 0
    assert summary.improved_count > 0
    assert summary.replaced_count > 0
    improved = [r for r in summary.clip_results if r.status == "improved"]
    assert len(improved) > 0
    assert all(r.replaced for r in improved)

    # Verify bundle was updated
    bundles = load_audio_bundles(tmp_path / "companion" / "lessons", selected_lessons={14})
    replaced_ids = {r.segment_id for r in improved}
    for clip in bundles[0].clips:
        if clip.segment_id in replaced_ids:
            assert "gemini" in clip.audio_path
            assert clip.review_status == "approved"


def test_keeps_original_when_not_improved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path)

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_fallback_policy._build_pacing_metrics",
        _fast_pacing_metrics,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.build_google_tts_request_context",
        lambda: SimpleNamespace(access_token="test", project_id="test"),
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.synthesize_google_tts_audio",
        lambda **_kw: SimpleNamespace(audio_bytes=b"gemini-mp3", attempt_count=1),
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_companion._measure_audio_duration_ms",
        lambda _path: 2000,
    )
    monkeypatch.setattr(
        "rag.client.get_rag_client",
        lambda: object(),
    )

    def _judge_revise(**kwargs: object) -> AudioJudgeClipResult:
        clip = cast(AudioClipDefinition, kwargs["clip"])
        return AudioJudgeClipResult(
            voice_profile="dorothy",
            lesson_id=clip.lesson_id,
            lesson_number=clip.lesson_number,
            segment_id=clip.segment_id,
            segment_type=clip.segment_type,
            audio_path=clip.audio_path,
            clarity_score=3,
            pronunciation_accuracy_score=3,
            instructional_match_score=3,
            target_accuracy_score=3,
            decoding_support_score=3,
            adhd_supportiveness_score=3,
            pacing_suitability_score=2,
            pacing_consistency_score=2,
            blocker=False,
            recommendation="revise",
        )

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_judge._judge_clip_with_gemini",
        _judge_revise,
    )

    summary = execute_gemini_fallback(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        lesson_id="14",
        dry_run=False,
    )

    not_improved = [r for r in summary.clip_results if r.status == "not_improved"]
    assert len(not_improved) > 0
    assert all(not r.replaced for r in not_improved)
    assert summary.replaced_count == 0


def test_fails_early_on_auth_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path)

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_fallback_policy._build_pacing_metrics",
        _fast_pacing_metrics,
    )

    def _fail_auth() -> None:
        raise RuntimeError("no credentials")

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.build_google_tts_request_context",
        _fail_auth,
    )

    with pytest.raises(RuntimeError, match="auth failed"):
        execute_gemini_fallback(
            data_dir=str(tmp_path),
            voice_profile="dorothy",
            lesson_id="14",
            dry_run=False,
        )


def test_handles_synthesis_failure_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path)

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_fallback_policy._build_pacing_metrics",
        _fast_pacing_metrics,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.build_google_tts_request_context",
        lambda: SimpleNamespace(access_token="test", project_id="test"),
    )

    from experiments.corpus_ufli.google_tts_client import GoogleTtsSynthesisError

    def _fail_tts(**_kw: object) -> None:
        raise GoogleTtsSynthesisError(
            "Google Cloud TTS failed: 502",
            status_code=502,
            failure_category="http_retryable",
            attempt_count=5,
            retryable=True,
            retry_exhausted=True,
        )

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.synthesize_google_tts_audio",
        _fail_tts,
    )
    monkeypatch.setattr(
        "rag.client.get_rag_client",
        lambda: object(),
    )

    summary = execute_gemini_fallback(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        lesson_id="14",
        dry_run=False,
    )

    failed = [r for r in summary.clip_results if r.status == "synthesis_failed"]
    assert summary.failed_count > 0
    assert len(failed) > 0
    assert summary.replaced_count == 0
