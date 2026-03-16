"""Focused tests for the pilot-first UFLI audio companion rollout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from corpus.ufli.audio_companion import (
    build_audio_companion_manifests,
    generate_audio_companion,
    index_audio_companion,
    load_audio_bundles,
)
from rag.store import AUDIO_COMPANION, get_or_create_collection, get_store


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
            "concept": "ignored",
            "slide_text": "ignored",
            "slide_count": 1,
            "decodable_text": "",
            "home_practice_text": "",
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


def test_build_audio_bundles_use_stage1_taxonomy_and_pilot_scope(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())

    bundles = build_audio_companion_manifests(data_dir=str(tmp_path))

    assert [bundle.lesson_id for bundle in bundles] == ["1", "14", "95"]
    lesson_1 = bundles[0]
    assert {clip.segment_type for clip in lesson_1.clips} == {
        "lesson_instruction",
        "phoneme_model",
        "word_model",
        "review",
    }
    lesson_14 = bundles[1]
    assert "Can Cam fit on the cot?" in lesson_14.passage_text
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
    assert "short a" in phoneme_clip.tts_text
    assert word_clip.tts_text == "Feb roo air ee"


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


def test_generate_audio_rejects_non_pilot_live_scope(tmp_path: Path) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    build_audio_companion_manifests(
        data_dir=str(tmp_path),
        lesson_set="pilot_rep",
    )

    with pytest.raises(RuntimeError, match="pilot-only"):
        generate_audio_companion(
            data_dir=str(tmp_path),
            lesson_set="pilot_rep",
            dry_run=False,
            voice_profile="dorothy",
        )


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


def test_index_audio_companion_filters_by_voice_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_companion_configs(tmp_path)
    _write_normalized(tmp_path / "normalized.jsonl", _sample_rows())
    bundles = build_audio_companion_manifests(data_dir=str(tmp_path))
    bundle = next(item for item in bundles if item.lesson_number == 14)
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
    )

    assert count == len(bundle.clips)
    store = get_store(str(tmp_path / "vs"))
    collection = get_or_create_collection(store, AUDIO_COMPANION)
    assert collection.count() == len(bundle.clips)
