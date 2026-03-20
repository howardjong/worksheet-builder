"""Focused tests for the pilot-first UFLI audio companion rollout."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytest.importorskip("chromadb")

from corpus.ufli.audio_companion import (
    _clause_pause_only_tts,
    _pause_shaped_passage_tts,
    build_audio_companion_manifests,
    generate_audio_companion,
    index_audio_companion,
    load_audio_bundles,
    load_voice_profiles,
    validate_audio_companion,
)
from corpus.ufli.audio_companion_schema import LessonAudioBundle
from rag.store import (
    AUDIO_COMPANION_CLIPS,
    AUDIO_COMPANION_LESSONS,
    get_or_create_collection,
    get_store,
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


def _normalized_words(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z']+", text)]


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
        {
            "lesson_id": "95",
            "lesson_group": "95-98",
            "concept": "oi /oi/, oy /oi/",
            "slide_text": "Lesson 95 oi /oi/, oy /oi/ point coin oil boy toy voice choice.",
            "slide_count": 8,
            "decodable_text": (
                "Lesson 95: oi, oy /oi/ The Right Choice Illustrate the story here: "
                "In February, Boyd and James had a choice to make. "
                "The yellow bird joined them."
            ),
            "home_practice_text": (
                "1. foil → coil → soil → spoil "
                "2. coin → join → joint → point February"
            ),
            "additional_text": "",
        },
        {
            "lesson_id": "128",
            "lesson_group": "99-128",
            "concept": "a /ă/",
            "slide_text": "Lesson 128 a /ă/ cat map at as.",
            "slide_count": 4,
            "decodable_text": "",
            "home_practice_text": "1. at → cat → cap",
            "additional_text": "",
        },
        {
            "lesson_id": "A",
            "lesson_group": "a-j",
            "concept": "alpha",
            "slide_text": "alpha",
            "slide_count": 1,
            "decodable_text": "",
            "home_practice_text": "",
            "additional_text": "",
        },
    ]


def test_build_audio_bundles_use_taxonomy_and_pilot_scope(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())

    bundles = build_audio_companion_manifests(data_dir=str(tmp_path))

    assert [bundle.lesson_id for bundle in bundles] == ["1", "14", "95", "128"]
    lesson_1 = bundles[0]
    assert {clip.segment_type for clip in lesson_1.clips} == {
        "lesson_instruction",
        "phoneme_model",
        "word_model",
        "review",
    }
    lesson_14 = bundles[1]
    assert "Can Cam fit on the cot?" in lesson_14.passage_text
    assert "read these words" not in lesson_1.clips[0].transcript_text.casefold()
    assert "with these words" not in lesson_1.clips[-1].transcript_text.casefold()
    assert "..." in lesson_1.clips[0].tts_text
    first_passage_sentence = next(
        clip for clip in lesson_14.clips if clip.segment_type == "passage_sentence"
    )
    assert "..." in first_passage_sentence.tts_text
    assert _normalized_words(first_passage_sentence.tts_text) == _normalized_words(
        first_passage_sentence.transcript_text
    )
    assert {"passage_sentence", "passage_full"}.issubset(
        {clip.segment_type for clip in lesson_14.clips}
    )


def test_build_audio_supports_committed_pilot_sets(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())

    bundles = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_set="pilot_rep",
    )

    assert [bundle.lesson_id for bundle in bundles] == ["1", "14", "95", "128"]


def test_build_audio_applies_lexicon_overrides_for_phonemes_and_words(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(
        tmp_path / "normalized.jsonl",
        [
            {
                "lesson_id": "95",
                "lesson_group": "95-98",
                "concept": "a /ă/",
                "slide_text": "February February February",
                "slide_count": 4,
                "decodable_text": "",
                "home_practice_text": "February",
                "additional_text": "",
            }
        ],
    )

    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="95",
    )[0]

    phoneme_clip = next(clip for clip in bundle.clips if clip.segment_type == "phoneme_model")
    word_clip = next(
        clip
        for clip in bundle.clips
        if clip.segment_type == "word_model" and clip.transcript_text == "February"
    )
    assert "the short a sound" in phoneme_clip.tts_text
    assert word_clip.tts_text == "Feb roo air ee"


def test_build_audio_uses_pause_shaped_tts_without_changing_transcript(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())

    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="14",
    )[0]

    instruction = next(clip for clip in bundle.clips if clip.segment_type == "lesson_instruction")
    review = next(clip for clip in bundle.clips if clip.segment_type == "review")
    passage_sentence = next(
        clip for clip in bundle.clips if clip.segment_type == "passage_sentence"
    )
    passage_full = next(clip for clip in bundle.clips if clip.segment_type == "passage_full")

    assert "..." not in instruction.transcript_text
    assert "..." in instruction.tts_text
    assert "..." not in review.transcript_text
    assert "..." in review.tts_text
    assert review.transcript_text.endswith("Focus on c in cat.")
    assert passage_sentence.tts_text != passage_sentence.transcript_text
    assert "..." in passage_sentence.tts_text
    assert passage_sentence.tts_text.count("...") >= 2
    assert _normalized_words(passage_sentence.tts_text) == _normalized_words(
        passage_sentence.transcript_text
    )
    assert "..." in passage_full.tts_text
    assert _normalized_words(passage_full.tts_text) == _normalized_words(
        passage_full.transcript_text
    )
    assert ". ... . ..." not in passage_full.tts_text
    assert ", . ..." not in passage_full.tts_text


def test_clause_pause_shaping_avoids_duplicate_pause_tokens() -> None:
    shaped = _clause_pause_only_tts(
        "In February, Boyd and James had a choice to make."
    )

    assert shaped == "In February, ... Boyd and James had a choice to make. ..."
    assert "... ..." not in shaped


def test_passage_pause_shaping_handles_quoted_dialogue_clause_breaks() -> None:
    shaped = _pause_shaped_passage_tts('"This kitten is cute," said Boyd.')

    assert shaped == '"This kitten is cute," ... said Boyd. ...'
    assert "is ... cute" not in shaped


def test_build_audio_uses_exact_anchor_for_oy(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())

    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="95",
    )[0]

    oy_clip = next(
        clip
        for clip in bundle.clips
        if clip.segment_id.endswith("phoneme_02_oy")
    )
    assert oy_clip.transcript_text.endswith("toy.")


def test_generate_audio_dry_run_estimates_both_pilot_voices(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    summary = generate_audio_companion(
        data_dir=str(tmp_path),
        dry_run=True,
    )

    assert summary["generated"] == 0
    assert summary["planned"] > 0
    assert set(summary["voice_profiles"]) == {"dorothy", "neutral_na_pilot"}
    assert summary["voice_profiles"]["dorothy"]["projected_costs_usd"]["eleven_multilingual_v2"] > 0


def test_load_voice_profiles_rejects_invalid_elevenlabs_speed(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    voice_profiles_path = tmp_path / "companion" / "voice_profiles.yaml"
    payload = yaml.safe_load(voice_profiles_path.read_text())
    payload["profiles"]["dorothy"]["clip_settings"]["phoneme_model"]["speed"] = 0.69
    voice_profiles_path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="ElevenLabs speed must be between 0.7 and 1.2"):
        load_voice_profiles(voice_profiles_path)


def test_generate_audio_allows_pilot_rep_scope(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_set="pilot_rep",
    )

    summary = generate_audio_companion(
        data_dir=str(tmp_path),
        lesson_set="pilot_rep",
        dry_run=True,
        voice_profile="dorothy",
    )
    assert summary["planned"] > 0


def test_generate_audio_rejects_non_pilot_live_scope(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_set="all",
    )

    with pytest.raises(RuntimeError, match="pilot-only"):
        generate_audio_companion(
            data_dir=str(tmp_path),
            lesson_set="all",
            dry_run=False,
            voice_profile="dorothy",
        )


def test_validate_audio_detects_contaminated_targets(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="1",
    )[0]
    bundle.word_targets.append("activity")
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )

    report = validate_audio_companion(
        data_dir=str(tmp_path),
        lesson_id="1",
    )

    assert report.passed is False
    assert any(issue.code == "contaminated_word_target" for issue in report.issues)


def test_validate_audio_detects_answer_giving_prompt(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="14",
    )[0]
    instruction = next(clip for clip in bundle.clips if clip.segment_type == "lesson_instruction")
    instruction.transcript_text = "Listen first. Read these words: cat, cap, cop, cod."
    instruction.tts_text = instruction.transcript_text
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )

    report = validate_audio_companion(
        data_dir=str(tmp_path),
        lesson_id="14",
    )

    assert report.passed is False
    assert any(issue.code == "answer_giving_prompt" for issue in report.issues)


def test_validate_audio_detects_missing_anchor_word(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_id="95",
    )[0]
    lexicon_path = tmp_path / "companion" / "pronunciation_lexicon.yaml"
    lexicon_payload = yaml.safe_load(lexicon_path.read_text())
    lexicon_payload["graphemes"]["oy"].pop("anchor_word", None)
    lexicon_path.write_text(yaml.safe_dump(lexicon_payload, sort_keys=False))
    bundle.word_targets = [word for word in bundle.word_targets if "oy" not in word]
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )

    report = validate_audio_companion(
        data_dir=str(tmp_path),
        lesson_id="95",
    )

    assert report.passed is False
    assert any(issue.code == "missing_anchor_word" for issue in report.issues)


def test_generate_audio_writes_review_packet_with_stubbed_tts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(data_dir=str(tmp_path))

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "corpus.ufli.audio_companion._synthesize_elevenlabs",
        lambda **_: (b"mp3-bytes", "eleven_multilingual_v2"),
    )
    monkeypatch.setattr("corpus.ufli.audio_companion.time.sleep", lambda _seconds: None)

    summary = generate_audio_companion(
        data_dir=str(tmp_path),
        lesson_id="14",
        voice_profile="dorothy",
        dry_run=False,
        review_packet=True,
    )

    review_dir = Path(summary["review_packet_dir"])
    assert summary["generated"] > 0
    assert review_dir.exists()
    assert {"review.md", "review.csv", "clips.json", "playlist.m3u"}.issubset(
        {path.name for path in review_dir.iterdir()}
    )
    bundle = load_audio_bundles(tmp_path / "companion" / "lessons", selected_lessons={14})[0]
    generated_clip = next(clip for clip in bundle.clips if clip.status == "generated")
    assert (tmp_path / "companion" / generated_clip.audio_path).exists()
    assert (review_dir / generated_clip.audio_path).exists()
    manifest_rows = [
        json.loads(line)
        for line in (tmp_path / "companion" / "audio.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert all(row["voice_profile"] == "dorothy" for row in manifest_rows)


def _prepare_generated_bundle(
    tmp_path: Path,
    lesson_number: int = 14,
) -> LessonAudioBundle:
    """Mark all clips in a bundle as generated with stub audio files."""
    bundles = build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_set="pilot_rep",
    )
    bundle = next(item for item in bundles if item.lesson_number == lesson_number)
    for clip in bundle.clips:
        clip.status = "generated"
        clip.voice_profile = "dorothy"
        clip.speaker = "dorothy"
        clip.duration_ms = 2000
        clip.audio_path = f"audio/dorothy/lessons/{bundle.lesson_key}/{clip.audio_file_name}"
        audio_path = tmp_path / "companion" / clip.audio_path
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"mp3")
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )
    return bundle


def test_index_audio_companion_clips_filters_by_voice_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = _prepare_generated_bundle(tmp_path, lesson_number=14)

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="clips",
        include_pending=True,
    )

    assert count == len(bundle.clips)
    store = get_store(str(tmp_path / "vs"))
    clips_collection = get_or_create_collection(store, AUDIO_COMPANION_CLIPS)
    assert clips_collection.count() == len(bundle.clips)


def test_index_audio_companion_lessons_creates_aggregate_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    _prepare_generated_bundle(tmp_path, lesson_number=14)

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="lessons",
        include_pending=True,
    )

    assert count == 1
    store = get_store(str(tmp_path / "vs"))
    lessons_collection = get_or_create_collection(store, AUDIO_COMPANION_LESSONS)
    assert lessons_collection.count() == 1
    result = lessons_collection.get(ids=["lesson_14_dorothy"])
    assert result["ids"] == ["lesson_14_dorothy"]
    meta = result["metadatas"][0]
    assert meta["lesson_number"] == 14
    assert meta["concept"] == "c /k/"
    assert meta["clip_count"] > 0
    assert meta["voice_profile"] == "dorothy"


def test_index_audio_companion_both_populates_two_collections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = _prepare_generated_bundle(tmp_path, lesson_number=14)

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="both",
        include_pending=True,
    )

    assert count == len(bundle.clips) + 1
    store = get_store(str(tmp_path / "vs"))
    clips_collection = get_or_create_collection(store, AUDIO_COMPANION_CLIPS)
    lessons_collection = get_or_create_collection(store, AUDIO_COMPANION_LESSONS)
    assert clips_collection.count() == len(bundle.clips)
    assert lessons_collection.count() == 1


def test_index_clips_skips_pending_review_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = _prepare_generated_bundle(tmp_path, lesson_number=14)

    # All clips have default review_status "pending"
    assert all(clip.review_status == "pending" for clip in bundle.clips)

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="both",
        include_pending=False,
    )

    assert count == 0


def test_index_clips_includes_pending_when_flag_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = _prepare_generated_bundle(tmp_path, lesson_number=14)

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="both",
        include_pending=True,
    )

    assert count == len(bundle.clips) + 1


def test_index_clips_only_indexes_approved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundle = _prepare_generated_bundle(tmp_path, lesson_number=14)

    # Approve only the first clip
    bundle.clips[0].review_status = "approved"
    (tmp_path / "companion" / "lessons" / f"{bundle.lesson_key}.json").write_text(
        bundle.model_dump_json(indent=2)
    )

    class _FakeEmbedding:
        values = [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        "corpus.ufli.audio_companion.embed_text",
        lambda *_args, **_kwargs: _FakeEmbedding(),
    )

    count = index_audio_companion(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        lesson_id="14",
        voice_profile="dorothy",
        granularity="clips",
        include_pending=False,
    )

    assert count == 1
