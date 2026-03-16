"""Tests for controlled UFLI audio probe diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from corpus.ufli.audio_companion import build_audio_companion_manifests
from corpus.ufli.audio_companion_schema import (
    AudioJudgeClipResult,
    AudioProbeVariant,
    AudioVoiceSettings,
    JudgeRecommendation,
)
from corpus.ufli.audio_diagnostics import _derive_probe_findings, run_audio_probe_matrix


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
        "corpus.ufli.audio_diagnostics._synthesize_probe_variant",
        lambda **_: b"mp3",
    )
    monkeypatch.setattr("corpus.ufli.audio_diagnostics._elevenlabs_api_key", lambda: "test-key")

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
        "corpus.ufli.audio_diagnostics._judge_probe_variant",
        _fake_judge_probe_variant,
    )
    monkeypatch.setattr("corpus.ufli.audio_diagnostics.get_rag_client", lambda: object())

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
