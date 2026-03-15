"""Tests for the UFLI multimodal corpus audit."""

from __future__ import annotations

import csv
import json
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

pytest.importorskip("chromadb")

from corpus.ufli.audit import (
    load_audio_companion_records,
    load_image_companion_records,
    run_audit,
)
from corpus.ufli.audit_schema import AuditFlag
from corpus.ufli.ingest import cli
from rag.store import CURRICULUM, add_document, get_or_create_collection, get_store


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _write_text_fixture(
    base: Path,
    lesson_id: str = "58",
    concept: str = "CVCe grade chase",
) -> None:
    _write_jsonl(
        base / "manifest.jsonl",
        [
            {
                "lesson_id": lesson_id,
                "lesson_group": "35-64",
                "concept": concept,
                "status": "acquired",
            }
        ],
    )
    (base / "raw" / lesson_id).mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        base / "normalized.jsonl",
        [
            {
                "lesson_id": lesson_id,
                "lesson_group": "35-64",
                "concept": concept,
                "slide_text": "Introduce grade and chase in the long a pattern lesson.",
                "slide_count": 10,
                "decodable_text": "The grade was on the page and Chase came late.",
                "home_practice_text": "Read grade chase flame game.",
                "additional_text": "",
            }
        ],
    )


def _add_curriculum_doc(
    db_path: Path,
    lesson_id: str = "58",
    concept: str = "CVCe grade chase",
) -> None:
    store = get_store(str(db_path))
    collection = get_or_create_collection(store, CURRICULUM)
    add_document(
        collection,
        doc_id=f"curriculum_ufli_{lesson_id}",
        embedding=[1.0, 0.0, 0.0],
        metadata={
            "lesson_id": lesson_id,
            "concept": concept,
            "grade_level": "1",
        },
        document="Introduce grade and chase in the long a pattern lesson.",
    )


def _write_image(path: Path, color: tuple[int, int, int], tweak: bool = False) -> None:
    image = Image.new("RGB", (24, 24), color=color)
    if tweak:
        image.putpixel((0, 0), (color[0], min(color[1] + 1, 255), color[2]))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_wav(path: Path, duration_ms: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(16000 * (duration_ms / 1000))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * frames)


def test_manifest_loaders_parse_image_and_audio_records(tmp_path: Path) -> None:
    flags: list[AuditFlag] = []
    _write_jsonl(
        tmp_path / "companion" / "images.jsonl",
        [
            {
                "lesson_id": "58",
                "asset_id": "img-1",
                "asset_type": "scene",
                "sequence_index": 0,
                "image_path": "companion/images/58.png",
                "caption_text": "Chase reads a grade page during the lesson scene.",
                "alt_text": "A child reading a page.",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "companion" / "audio.jsonl",
        [
            {
                "lesson_id": "58",
                "segment_id": "seg-1",
                "segment_type": "instruction",
                "sequence_index": 0,
                "audio_path": "companion/audio/58.wav",
                "duration_ms": 1200,
                "transcript_text": "Read the grade and chase words out loud now.",
                "speaker": "coach",
            }
        ],
    )

    images = load_image_companion_records(tmp_path / "companion" / "images.jsonl", flags)
    audio = load_audio_companion_records(tmp_path / "companion" / "audio.jsonl", flags)

    assert len(images) == 1
    assert images[0].asset_type == "scene"
    assert len(audio) == 1
    assert audio[0].segment_type == "instruction"
    assert flags == []


def test_run_audit_flags_image_audio_quality_and_skips_companion_retrieval(
    tmp_path: Path,
) -> None:
    _write_text_fixture(tmp_path)
    _add_curriculum_doc(tmp_path / "vs")

    _write_image(tmp_path / "companion" / "images" / "58-a.png", (120, 50, 50))
    _write_wav(tmp_path / "companion" / "audio" / "58.wav", duration_ms=1500)

    _write_jsonl(
        tmp_path / "companion" / "images.jsonl",
        [
            {
                "lesson_id": "58",
                "asset_id": "img-1",
                "asset_type": "scene",
                "sequence_index": 0,
                "image_path": "companion/images/58-a.png",
                "caption_text": "58-a",
                "alt_text": "",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "companion" / "audio.jsonl",
        [
            {
                "lesson_id": "58",
                "segment_id": "seg-1",
                "segment_type": "instruction",
                "sequence_index": 0,
                "audio_path": "companion/audio/58.wav",
                "duration_ms": 1500,
                "transcript_text": "TODO",
                "speaker": "coach",
            }
        ],
    )

    summary = run_audit(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        output_dir=str(tmp_path / "audit"),
        sample_size=5,
        benchmark_size=5,
        seed=7,
    )

    codes = {flag.code for flag in summary.flags}
    assert "missing_alt_text" in codes
    assert "placeholder_caption" in codes
    assert "short_transcript" in codes
    retrieval = {bench.modality: bench for bench in summary.retrieval_benchmarks}
    assert retrieval["text"].status == "completed"
    assert retrieval["image"].status == "skipped"
    assert retrieval["audio"].status == "skipped"
    assert Path(summary.output_dir, "report.md").exists()


def test_run_audit_detects_near_duplicate_images_and_duplicate_transcripts(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "manifest.jsonl",
        [
            {"lesson_id": "58", "lesson_group": "35-64", "concept": "grade chase"},
            {"lesson_id": "59", "lesson_group": "35-64", "concept": "grade chase"},
        ],
    )
    (tmp_path / "raw" / "58").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "59").mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        tmp_path / "normalized.jsonl",
        [
            {
                "lesson_id": "58",
                "lesson_group": "35-64",
                "concept": "grade chase",
                "slide_text": "grade chase page flame game",
                "slide_count": 10,
                "decodable_text": "",
                "home_practice_text": "",
                "additional_text": "",
            },
            {
                "lesson_id": "59",
                "lesson_group": "35-64",
                "concept": "grade chase",
                "slide_text": "grade chase page flame game",
                "slide_count": 10,
                "decodable_text": "",
                "home_practice_text": "",
                "additional_text": "",
            },
        ],
    )
    _add_curriculum_doc(tmp_path / "vs", lesson_id="58")
    _add_curriculum_doc(tmp_path / "vs", lesson_id="59")

    _write_image(tmp_path / "companion" / "images" / "58.png", (10, 20, 30))
    _write_image(tmp_path / "companion" / "images" / "59.png", (10, 20, 30), tweak=True)
    _write_wav(tmp_path / "companion" / "audio" / "58.wav")
    _write_wav(tmp_path / "companion" / "audio" / "59.wav")

    _write_jsonl(
        tmp_path / "companion" / "images.jsonl",
        [
            {
                "lesson_id": "58",
                "asset_id": "img-58",
                "asset_type": "scene",
                "sequence_index": 0,
                "image_path": "companion/images/58.png",
                "caption_text": "A scene showing grade and chase words on a page.",
                "alt_text": "The grade and chase page scene.",
            },
            {
                "lesson_id": "59",
                "asset_id": "img-59",
                "asset_type": "scene",
                "sequence_index": 0,
                "image_path": "companion/images/59.png",
                "caption_text": "Another scene showing grade and chase words on a page.",
                "alt_text": "The grade and chase page scene.",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "companion" / "audio.jsonl",
        [
            {
                "lesson_id": "58",
                "segment_id": "seg-58",
                "segment_type": "instruction",
                "sequence_index": 0,
                "audio_path": "companion/audio/58.wav",
                "duration_ms": 2000,
                "transcript_text": "Read the grade and chase words with me now.",
                "speaker": "coach",
            },
            {
                "lesson_id": "59",
                "segment_id": "seg-59",
                "segment_type": "instruction",
                "sequence_index": 0,
                "audio_path": "companion/audio/59.wav",
                "duration_ms": 2000,
                "transcript_text": "Read the grade and chase words with me now.",
                "speaker": "coach",
            },
        ],
    )

    summary = run_audit(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        output_dir=str(tmp_path / "audit"),
        sample_size=6,
        benchmark_size=5,
        seed=3,
    )

    codes = [flag.code for flag in summary.flags]
    assert "near_duplicate_image" in codes
    assert "duplicate_transcript" in codes
    assert any(cluster.record_type == "image" for cluster in summary.duplicate_clusters)


def test_run_audit_tracks_modality_coverage_and_cross_modality_mismatch(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "manifest.jsonl",
        [
            {"lesson_id": "58", "lesson_group": "35-64", "concept": "grade chase"},
            {"lesson_id": "59", "lesson_group": "35-64", "concept": "flame game"},
        ],
    )
    (tmp_path / "raw" / "58").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "59").mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        tmp_path / "normalized.jsonl",
        [
            {
                "lesson_id": "58",
                "lesson_group": "35-64",
                "concept": "grade chase",
                "slide_text": "grade chase page",
                "slide_count": 10,
                "decodable_text": "grade chase page",
                "home_practice_text": "",
                "additional_text": "",
            },
            {
                "lesson_id": "59",
                "lesson_group": "35-64",
                "concept": "flame game",
                "slide_text": "flame game page",
                "slide_count": 10,
                "decodable_text": "flame game page",
                "home_practice_text": "",
                "additional_text": "",
            },
        ],
    )
    _add_curriculum_doc(tmp_path / "vs", lesson_id="58", concept="grade chase")
    _add_curriculum_doc(tmp_path / "vs", lesson_id="59", concept="flame game")

    _write_image(tmp_path / "companion" / "images" / "58.png", (0, 0, 0))
    _write_wav(tmp_path / "companion" / "audio" / "58.wav")

    _write_jsonl(
        tmp_path / "companion" / "images.jsonl",
        [
            {
                "lesson_id": "58",
                "asset_id": "img-58",
                "asset_type": "scene",
                "sequence_index": 0,
                "image_path": "companion/images/58.png",
                "caption_text": "Robots on Mars flying around space helmets.",
                "alt_text": "Robots on Mars.",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "companion" / "audio.jsonl",
        [
            {
                "lesson_id": "58",
                "segment_id": "seg-58",
                "segment_type": "instruction",
                "sequence_index": 0,
                "audio_path": "companion/audio/58.wav",
                "duration_ms": 5000,
                "transcript_text": "Read the grade chase page with me slowly now.",
                "speaker": "coach",
            }
        ],
    )

    summary = run_audit(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "vs"),
        output_dir=str(tmp_path / "audit"),
        sample_size=6,
        benchmark_size=5,
        seed=11,
    )

    lesson_map = {row.lesson_id: row for row in summary.lesson_records}
    assert lesson_map["58"].modality_coverage_score == 1.0
    assert lesson_map["59"].modality_coverage_score == pytest.approx(1 / 3, rel=0.01)
    assert "caption_concept_mismatch" in {flag.code for flag in summary.flags}


def test_cli_audit_writes_all_report_artifacts(tmp_path: Path) -> None:
    _write_text_fixture(tmp_path)
    _add_curriculum_doc(tmp_path / "vs")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "audit",
            "--data-dir",
            str(tmp_path),
            "--db-path",
            str(tmp_path / "vs"),
            "--output-dir",
            str(tmp_path / "audit"),
            "--sample-size",
            "3",
            "--benchmark-size",
            "3",
            "--seed",
            "9",
        ],
    )

    assert result.exit_code == 0, result.output
    audit_dirs = sorted((tmp_path / "audit").iterdir())
    assert len(audit_dirs) == 1
    audit_dir = audit_dirs[0]
    expected = {
        "report.md",
        "summary.json",
        "record_metrics.csv",
        "flags.csv",
        "manual_review_sample.csv",
        "retrieval_benchmark.json",
    }
    assert expected == {path.name for path in audit_dir.iterdir()}
    with (audit_dir / "report.md").open() as handle:
        report = handle.read()
    assert "Image companion quality" in report
    assert "Audio companion quality" in report
    with (audit_dir / "flags.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows
