"""Tests for controlled UFLI audio probe diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from experiments.corpus_ufli.audio_companion import build_audio_companion_manifests
from experiments.corpus_ufli.audio_companion_schema import (
    AudioJudgeClipResult,
    AudioProbeVariant,
    AudioVoiceSettings,
    GoogleCloudTtsSettings,
    JudgeRecommendation,
)
from experiments.corpus_ufli.audio_diagnostics import (
    _derive_probe_findings,
    _google_markup_from_tts_text,
    _resolve_google_tts_region,
    run_audio_probe_matrix,
)
from experiments.corpus_ufli.google_tts_client import (
    GoogleTtsRequestContext,
    GoogleTtsSynthesisError,
)


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


def _probe_variant(
    *,
    variant_id: str,
    variant_family: str,
    model_id: str,
    tts_text: str,
    recommendation: JudgeRecommendation,
    blocker: bool,
    pronunciation_score: int,
    pacing_score: int,
) -> AudioProbeVariant:
    return AudioProbeVariant(
        source_segment_id="lesson_001_phoneme_01_a",
        variant_id=variant_id,
        lesson_id="1",
        lesson_number=1,
        segment_type="phoneme_model",
        variant_family=variant_family,
        hypothesis="test",
        voice_profile="dorothy",
        model_id=model_id,
        transcript_text="a. /a/. As in cat.",
        tts_text=tts_text,
        audio_settings=AudioVoiceSettings(
            stability=0.7,
            similarity_boost=0.7,
            style=0.0,
            speed=0.7,
        ),
        judge_result=AudioJudgeClipResult(
            voice_profile="dorothy",
            lesson_id="1",
            lesson_number=1,
            segment_id=variant_id,
            segment_type="phoneme_model",
            audio_path=f"audio/{variant_id}.mp3",
            transcript_word_count=5,
            actual_duration_ms=3000,
            actual_wpm=80.0,
            expected_wpm_target=58.0,
            expected_wpm_min=35.0,
            expected_wpm_max=75.0,
            pacing_measurement_source="audio_file",
            heard_text="heard",
            instructional_match_score=pronunciation_score,
            target_accuracy_score=pronunciation_score,
            decoding_support_score=pronunciation_score,
            passage_neutrality_score=None,
            adhd_supportiveness_score=4,
            clarity_score=4,
            pronunciation_accuracy_score=pronunciation_score,
            pacing_suitability_score=pacing_score,
            pacing_consistency_score=pacing_score,
            blocker=blocker,
            recommendation=recommendation,
            strengths=[],
            concerns=[],
            rationale="test",
        ),
    )


def test_run_audio_probe_matrix_writes_probe_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics._synthesize_probe_variant",
        lambda **_: (b"mp3", 1),
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics._elevenlabs_api_key", lambda: "test-key"
    )

    def _fake_judge_probe_variant(**kwargs: object) -> AudioJudgeClipResult:
        variant = kwargs["variant"]
        recommendation: JudgeRecommendation
        if getattr(variant, "variant_family") == "exact_transcript":
            recommendation = "use"
            blocker = False
            pacing_score = 5
        else:
            recommendation = "revise"
            blocker = False
            pacing_score = 3
        return AudioJudgeClipResult(
            voice_profile=getattr(variant, "voice_profile"),
            lesson_id=getattr(variant, "lesson_id"),
            lesson_number=getattr(variant, "lesson_number"),
            segment_id=getattr(variant, "variant_id"),
            segment_type=getattr(variant, "segment_type"),
            audio_path=getattr(variant, "audio_path"),
            transcript_word_count=max(len(getattr(variant, "transcript_text").split()), 1),
            actual_duration_ms=1200,
            actual_wpm=95.0,
            expected_wpm_target=108.0,
            expected_wpm_min=92.0,
            expected_wpm_max=122.0,
            pacing_measurement_source="audio_file",
            heard_text=getattr(variant, "transcript_text"),
            clarity_score=5,
            pronunciation_accuracy_score=5,
            instructional_match_score=5,
            target_accuracy_score=5,
            decoding_support_score=5,
            passage_neutrality_score=5,
            adhd_supportiveness_score=5,
            pacing_suitability_score=pacing_score,
            pacing_consistency_score=pacing_score,
            blocker=blocker,
            recommendation=recommendation,
            strengths=["controlled"],
            concerns=[],
            rationale="Controlled probe result.",
        )

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics._judge_probe_variant",
        _fake_judge_probe_variant,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics.get_rag_client", lambda: object()
    )

    summary = run_audio_probe_matrix(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        segment_ids=["lesson_014_passage_sentence_01"],
        live=True,
        judge=True,
    )

    output_dir = Path(summary.output_dir)
    assert summary.variant_count >= 3
    assert summary.findings[0].probable_cause == "pipeline_input_problem"
    assert (output_dir / "probe_summary.json").exists()
    assert (output_dir / "probe_results.jsonl").exists()
    assert (output_dir / "probe_report.md").exists()
    assert any(variant.audio_path for variant in summary.variants)


def test_run_audio_probe_matrix_soft_fails_google_variant_and_skips_judging_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics.build_google_tts_request_context",
        lambda: GoogleTtsRequestContext(access_token="token", project_id="project"),
    )

    def _fake_synthesize_probe_variant(**kwargs: object) -> tuple[bytes, int]:
        variant = kwargs["variant"]
        if getattr(variant, "variant_family") == "exact_transcript":
            raise GoogleTtsSynthesisError(
                "Google Cloud TTS failed (502): upstream unavailable",
                status_code=502,
                failure_category="http_retryable",
                attempt_count=5,
                retryable=True,
                retry_exhausted=True,
            )
        return b"mp3", 2

    judged_variants: list[str] = []

    def _fake_judge_probe_variant(**kwargs: object) -> AudioJudgeClipResult:
        variant = kwargs["variant"]
        judged_variants.append(getattr(variant, "variant_id"))
        return AudioJudgeClipResult(
            voice_profile=getattr(variant, "voice_profile"),
            lesson_id=getattr(variant, "lesson_id"),
            lesson_number=getattr(variant, "lesson_number"),
            segment_id=getattr(variant, "variant_id"),
            segment_type=getattr(variant, "segment_type"),
            audio_path=getattr(variant, "audio_path"),
            transcript_word_count=max(len(getattr(variant, "transcript_text").split()), 1),
            actual_duration_ms=1200,
            actual_wpm=95.0,
            expected_wpm_target=108.0,
            expected_wpm_min=92.0,
            expected_wpm_max=122.0,
            pacing_measurement_source="audio_file",
            heard_text=getattr(variant, "transcript_text"),
            clarity_score=5,
            pronunciation_accuracy_score=5,
            instructional_match_score=5,
            target_accuracy_score=5,
            decoding_support_score=5,
            passage_neutrality_score=5,
            adhd_supportiveness_score=5,
            pacing_suitability_score=5,
            pacing_consistency_score=5,
            blocker=False,
            recommendation="use",
            strengths=["controlled"],
            concerns=[],
            rationale="Controlled probe result.",
        )

    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics._synthesize_probe_variant",
        _fake_synthesize_probe_variant,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics._judge_probe_variant",
        _fake_judge_probe_variant,
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.audio_diagnostics.get_rag_client", lambda: object()
    )

    summary = run_audio_probe_matrix(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        segment_ids=["lesson_014_passage_sentence_01"],
        provider_scope="google",
        live=True,
        judge=True,
    )

    failed_variant = next(
        variant for variant in summary.variants if variant.variant_family == "exact_transcript"
    )
    generated_variant = next(
        variant for variant in summary.variants if variant.variant_family == "current_pipeline"
    )
    output_dir = Path(summary.output_dir)
    report_text = (output_dir / "probe_report.md").read_text()

    assert generated_variant.generation_status == "generated"
    assert generated_variant.attempt_count == 2
    assert failed_variant.generation_status == "failed"
    assert failed_variant.attempt_count == 5
    assert failed_variant.failure_status_code == 502
    assert failed_variant.failure_category == "http_retryable"
    assert failed_variant.retry_exhausted is True
    assert failed_variant.judge_result is None
    assert judged_variants == [generated_variant.variant_id]
    assert "status=`failed`" in report_text
    assert "status_code=502" in report_text


def test_run_audio_probe_matrix_supports_google_only_dry_run(
    tmp_path: Path,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    summary = run_audio_probe_matrix(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        segment_ids=["lesson_014_passage_sentence_01"],
        provider_scope="google",
        live=False,
        judge=False,
    )

    assert summary.variant_count == 2
    assert all(variant.provider == "google_cloud_tts" for variant in summary.variants)
    current_variant = next(
        variant for variant in summary.variants if variant.variant_family == "current_pipeline"
    )
    assert current_variant.input_format == "markup"
    assert "[pause]" in current_variant.provider_input
    assert isinstance(current_variant.audio_settings, GoogleCloudTtsSettings)
    assert current_variant.audio_settings.voice_name == "en-US-Chirp3-HD-Leda"


def test_run_audio_probe_matrix_can_filter_google_exact_transcript_only(
    tmp_path: Path,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    summary = run_audio_probe_matrix(
        data_dir=str(tmp_path),
        voice_profile="dorothy",
        segment_ids=["lesson_014_passage_sentence_01"],
        provider_scope="google",
        google_variant_scope="exact_transcript",
        live=False,
        judge=False,
    )

    assert summary.variant_count == 1
    only_variant = summary.variants[0]
    assert only_variant.provider == "google_cloud_tts"
    assert only_variant.variant_family == "exact_transcript"
    assert only_variant.provider_input == only_variant.transcript_text


def test_google_markup_translation_preserves_words() -> None:
    markup = _google_markup_from_tts_text(
        '"This kitten is cute," ... said Boyd. ... The toy is in the box.',
        "passage_full",
    )

    assert "[pause long]" in markup
    assert "This kitten is cute" in markup
    assert "said Boyd." in markup
    assert "The toy is in the box." in markup


def test_google_markup_uses_gemini_pause_tags_when_model_is_promptable() -> None:
    markup = _google_markup_from_tts_text(
        "Can the cat ... fit on the cot? ...",
        "passage_sentence",
        GoogleCloudTtsSettings(
            api_endpoint="https://texttospeech.googleapis.com",
            voice_name="Leda",
            model_name="gemini-2.5-pro-tts",
        ),
    )

    assert "[medium pause]" in markup
    assert "[pause]" not in markup


def test_resolve_google_tts_region_falls_back_from_unsupported_vertex_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    assert _resolve_google_tts_region(None) == "us"


def test_probe_findings_treat_same_model_text_win_as_pipeline_issue() -> None:
    findings = _derive_probe_findings(
        [
            _probe_variant(
                variant_id="current",
                variant_family="current_pipeline",
                model_id="eleven_multilingual_v2",
                tts_text="current",
                recommendation="block",
                blocker=True,
                pronunciation_score=1,
                pacing_score=2,
            ),
            _probe_variant(
                variant_id="better_text",
                variant_family="approved_phoneme",
                model_id="eleven_multilingual_v2",
                tts_text="better",
                recommendation="revise",
                blocker=False,
                pronunciation_score=5,
                pacing_score=3,
            ),
            _probe_variant(
                variant_id="other_model",
                variant_family="current_pipeline",
                model_id="eleven_flash_v2_5",
                tts_text="current",
                recommendation="block",
                blocker=True,
                pronunciation_score=1,
                pacing_score=2,
            ),
        ]
    )

    assert findings[0].probable_cause == "pipeline_input_problem"
    assert findings[0].best_variant_id == "better_text"


def test_probe_findings_treat_best_failing_current_variant_as_model_limit() -> None:
    findings = _derive_probe_findings(
        [
            _probe_variant(
                variant_id="current",
                variant_family="current_pipeline",
                model_id="eleven_multilingual_v2",
                tts_text="current",
                recommendation="revise",
                blocker=True,
                pronunciation_score=3,
                pacing_score=2,
            ),
            _probe_variant(
                variant_id="same_text_other_model",
                variant_family="current_pipeline",
                model_id="eleven_flash_v2_5",
                tts_text="current",
                recommendation="revise",
                blocker=True,
                pronunciation_score=2,
                pacing_score=2,
            ),
            _probe_variant(
                variant_id="same_model_other_text",
                variant_family="exact_transcript",
                model_id="eleven_multilingual_v2",
                tts_text="other",
                recommendation="revise",
                blocker=True,
                pronunciation_score=2,
                pacing_score=2,
            ),
        ]
    )

    assert findings[0].probable_cause == "model_or_voice_limitation"
    assert findings[0].best_variant_id == "current"


def test_probe_findings_mark_both_text_and_model_improvements_as_mixed() -> None:
    findings = _derive_probe_findings(
        [
            _probe_variant(
                variant_id="current",
                variant_family="current_pipeline",
                model_id="eleven_multilingual_v2",
                tts_text="current",
                recommendation="block",
                blocker=True,
                pronunciation_score=2,
                pacing_score=2,
            ),
            _probe_variant(
                variant_id="same_model_other_text",
                variant_family="exact_transcript",
                model_id="eleven_multilingual_v2",
                tts_text="other",
                recommendation="revise",
                blocker=False,
                pronunciation_score=3,
                pacing_score=3,
            ),
            _probe_variant(
                variant_id="same_text_other_model",
                variant_family="current_pipeline",
                model_id="eleven_flash_v2_5",
                tts_text="current",
                recommendation="use",
                blocker=False,
                pronunciation_score=5,
                pacing_score=5,
            ),
        ]
    )

    assert findings[0].probable_cause == "mixed_or_inconclusive"
    assert findings[0].best_variant_id == "same_text_other_model"
