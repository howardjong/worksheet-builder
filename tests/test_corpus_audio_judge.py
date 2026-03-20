"""Tests for UFLI audio companion LLM-judge evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("chromadb")

from corpus.ufli.audio_companion import build_audio_companion_manifests, load_audio_bundles
from corpus.ufli.audio_companion_schema import (
    AudioJudgeClipResult,
    AudioJudgeSummary,
    JudgeRecommendation,
)
from corpus.ufli.audio_judge import (
    _judge_clip_with_gemini,
    _parse_judge_response,
    apply_judge_verdicts,
    judge_audio_companion,
)
from corpus.ufli.extract import LessonContent


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


def test_parse_judge_response_strips_markdown_fences() -> None:
    parsed = _parse_judge_response(
        """```json
        {
          "heard_text": "cat",
          "clarity_score": 4,
          "pronunciation_accuracy_score": 5,
          "instructional_match_score": 4,
          "target_accuracy_score": 5,
          "decoding_support_score": 4,
          "passage_neutrality_score": null,
          "adhd_supportiveness_score": 5,
          "pacing_suitability_score": 4,
          "pacing_consistency_score": 5,
          "blocker": false,
          "recommendation": "use",
          "strengths": ["calm wording"],
          "concerns": [],
          "rationale": "Looks instructionally aligned."
        }
        ```"""
    )

    assert parsed["recommendation"] == "use"
    assert parsed["heard_text"] == "cat"
    assert parsed["clarity_score"] == 4
    assert parsed["pronunciation_accuracy_score"] == 5
    assert parsed["passage_neutrality_score"] is None
    assert parsed["pacing_suitability_score"] == 4
    assert parsed["strengths"] == ["calm wording"]


def test_judge_audio_companion_writes_reports_with_stubbed_judge(
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

    monkeypatch.setattr("corpus.ufli.audio_judge.get_rag_client", lambda: object())
    monkeypatch.setattr(
        "corpus.ufli.audio_judge._judge_clip_with_gemini",
        lambda **kwargs: AudioJudgeClipResult(
            voice_profile="dorothy",
            lesson_id=kwargs["clip"].lesson_id,
            lesson_number=kwargs["clip"].lesson_number,
            segment_id=kwargs["clip"].segment_id,
            segment_type=kwargs["clip"].segment_type,
            audio_path=kwargs["clip"].audio_path,
            transcript_word_count=max(len(kwargs["clip"].transcript_text.split()), 1),
            actual_duration_ms=1200,
            actual_wpm=90.0,
            expected_wpm_target=92.0,
            expected_wpm_min=78.0,
            expected_wpm_max=108.0,
            pacing_measurement_source="audio_file",
            heard_text=kwargs["clip"].transcript_text,
            clarity_score=5,
            pronunciation_accuracy_score=5,
            instructional_match_score=4,
            target_accuracy_score=4,
            decoding_support_score=4,
            passage_neutrality_score=5
            if kwargs["clip"].segment_type.startswith("passage")
            else None,
            adhd_supportiveness_score=5,
            pacing_suitability_score=5,
            pacing_consistency_score=5,
            blocker=False,
            recommendation="use",
            strengths=["aligned"],
            concerns=[],
            rationale="Looks good.",
        ),
    )

    summary = judge_audio_companion(
        data_dir=str(tmp_path),
        lesson_id="14",
        voice_profile="dorothy",
    )

    report_dir = Path(summary.output_dir)
    assert summary.clip_count == len(bundle.clips)
    assert summary.blocker_count == 0
    assert summary.recommendation_counts == {"use": len(bundle.clips)}
    assert summary.family_summaries
    assert summary.required_manual_review_segments
    assert (report_dir / "judge_summary.json").exists()
    assert (report_dir / "judge_results.csv").exists()
    assert (report_dir / "judge_report.md").exists()


def test_judge_clip_uses_audio_pacing_and_clarity_guardrails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundles = build_audio_companion_manifests(data_dir=str(tmp_path))
    bundle = bundles[0]
    clip = bundle.clips[0]
    clip.status = "generated"
    clip.voice_profile = "dorothy"
    clip.speaker = "dorothy"
    clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
    audio_path = tmp_path / "companion" / clip.audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"mp3")

    monkeypatch.setattr("corpus.ufli.audio_judge._measure_audio_duration_ms", lambda _path: 500)

    fake_response = SimpleNamespace(
        text=json.dumps(
            {
                "heard_text": "unclear metadata words",
                "clarity_score": 5,
                "pronunciation_accuracy_score": 2,
                "instructional_match_score": 5,
                "target_accuracy_score": 5,
                "decoding_support_score": 5,
                "passage_neutrality_score": None,
                "adhd_supportiveness_score": 5,
                "pacing_suitability_score": 5,
                "pacing_consistency_score": 5,
                "blocker": False,
                "recommendation": "use",
                "strengths": ["clear enough"],
                "concerns": [],
                "rationale": "Looks fine.",
            }
        )
    )
    fake_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **_kwargs: fake_response,
        )
    )

    result = _judge_clip_with_gemini(
        client=fake_client,
        judge_model="gemini-3-flash-preview",
        companion_dir=tmp_path / "companion",
        lesson=LessonContent(
            lesson_id="1",
            lesson_group="1-34",
            concept="a /ă/",
            slide_text="Lesson 1 a /ă/ cat map at as.",
            slide_count=4,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        ),
        bundle=bundle,
        clip=clip,
    )

    assert result.actual_duration_ms == 500
    assert result.pacing_measurement_source == "audio_file"
    assert result.blocker is True
    assert result.recommendation == "block"
    assert result.clarity_score <= 3
    assert result.pronunciation_accuracy_score == 2
    assert result.pacing_suitability_score <= 3
    assert result.pacing_consistency_score <= 3
    assert any("expected band" in concern for concern in result.concerns)
    assert any("Acoustic pronunciation" in concern for concern in result.concerns)
    assert any(
        "does not closely match the intended transcript" in concern
        for concern in result.concerns
    )


def test_judge_short_word_model_clip_avoids_pacing_false_positive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(data_dir=str(tmp_path))[0]
    clip = next(item for item in bundle.clips if item.segment_type == "word_model")
    clip.status = "generated"
    clip.voice_profile = "dorothy"
    clip.speaker = "dorothy"
    clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
    audio_path = tmp_path / "companion" / clip.audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"mp3")

    monkeypatch.setattr("corpus.ufli.audio_judge._measure_audio_duration_ms", lambda _path: 1200)
    fake_response = SimpleNamespace(
        text=json.dumps(
            {
                "heard_text": clip.transcript_text,
                "clarity_score": 5,
                "pronunciation_accuracy_score": 5,
                "instructional_match_score": 5,
                "target_accuracy_score": 5,
                "decoding_support_score": 5,
                "passage_neutrality_score": None,
                "adhd_supportiveness_score": 5,
                "pacing_suitability_score": 5,
                "pacing_consistency_score": 5,
                "blocker": False,
                "recommendation": "use",
                "strengths": ["clear word model"],
                "concerns": [],
                "rationale": "Looks good.",
            }
        )
    )
    fake_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_kwargs: fake_response)
    )

    result = _judge_clip_with_gemini(
        client=fake_client,
        judge_model="gemini-3-flash-preview",
        companion_dir=tmp_path / "companion",
        lesson=LessonContent(
            lesson_id="1",
            lesson_group="1-34",
            concept="a /ă/",
            slide_text="Lesson 1 a /ă/ cat map at as.",
            slide_count=4,
            decodable_text="",
            home_practice_text="",
            additional_text="",
        ),
        bundle=bundle,
        clip=clip,
    )

    assert result.recommendation == "use"
    assert not any("expected band" in concern for concern in result.concerns)


def test_apply_judge_verdicts_writes_back_to_bundles(tmp_path: Path) -> None:
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

    clip_results = []
    for clip in bundle.clips:
        recommendation: JudgeRecommendation
        if clip.segment_type != "word_model":
            recommendation = "use"
        else:
            recommendation = "revise"
        clip_results.append(
            AudioJudgeClipResult(
                voice_profile="dorothy",
                lesson_id=clip.lesson_id,
                lesson_number=clip.lesson_number,
                segment_id=clip.segment_id,
                segment_type=clip.segment_type,
                audio_path=clip.audio_path,
                clarity_score=5,
                pronunciation_accuracy_score=5,
                instructional_match_score=5,
                target_accuracy_score=5,
                decoding_support_score=5,
                adhd_supportiveness_score=5,
                pacing_suitability_score=5,
                pacing_consistency_score=5,
                recommendation=recommendation,
            )
        )

    summary = AudioJudgeSummary(
        generated_at="2025-01-01T00:00:00+00:00",
        judge_model="test",
        data_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        voice_profile="dorothy",
        clip_results=clip_results,
    )

    updated = apply_judge_verdicts(data_dir=str(tmp_path), summary=summary)

    assert updated > 0
    reloaded = load_audio_bundles(
        tmp_path / "companion" / "lessons", selected_lessons={14}
    )
    for clip in reloaded[0].clips:
        if clip.segment_type != "word_model":
            assert clip.review_status == "approved"
        else:
            assert clip.review_status == "needs_revision"
