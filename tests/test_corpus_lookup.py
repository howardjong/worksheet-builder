"""Tests for corpus/ufli/lookup.py — fixture fallback, real-corpus precedence, cache."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

import corpus.ufli.lookup as lookup_module
from corpus.ufli.lookup import CorpusLookupResult, lookup_lesson, reset_lookup_cache


def _concept(result: CorpusLookupResult | None) -> str:
    assert result is not None
    return result.concept


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    reset_lookup_cache()
    yield
    reset_lookup_cache()


def _write_corpus(path: Path, lesson_id: str, concept: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lesson_id": lesson_id,
                "concept": concept,
                "decodable_text": "",
                "additional_text": "",
                "home_practice_text": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_falls_back_to_fixture_when_real_corpus_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", tmp_path / "missing")
    result = lookup_lesson(74)
    assert result is not None
    assert result.concept == "ay"  # committed fixture value


def test_real_corpus_wins_over_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_dir = tmp_path / "ufli"
    _write_corpus(real_dir / "normalized.jsonl", "74", "REAL-WINS")
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", real_dir)
    result = lookup_lesson(74)
    assert result is not None
    assert result.concept == "REAL-WINS"


def test_explicit_data_dir_is_used(tmp_path: Path) -> None:
    data_dir = tmp_path / "custom"
    _write_corpus(data_dir / "normalized.jsonl", "5", "custom-concept")
    result = lookup_lesson(5, data_dir=str(data_dir))
    assert result is not None
    assert result.concept == "custom-concept"


def test_cache_is_path_keyed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Load the fixture first (real corpus absent).
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", tmp_path / "missing")
    fixture_result = lookup_lesson(74)
    assert fixture_result is not None and fixture_result.concept == "ay"

    # Point at a real corpus at a different path — the path-keyed cache loads it
    # fresh without a manual reset because the resolved key changed.
    real_dir = tmp_path / "ufli"
    _write_corpus(real_dir / "normalized.jsonl", "74", "REAL")
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", real_dir)
    result = lookup_lesson(74)
    assert result is not None and result.concept == "REAL"


def test_reset_reloads_same_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_dir = tmp_path / "ufli"
    corpus_path = real_dir / "normalized.jsonl"
    _write_corpus(corpus_path, "5", "v1")
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", real_dir)
    assert _concept(lookup_lesson(5)) == "v1"

    # Overwrite the same path; without a reset the cache still serves v1.
    _write_corpus(corpus_path, "5", "v2")
    assert _concept(lookup_lesson(5)) == "v1"

    reset_lookup_cache()
    assert _concept(lookup_lesson(5)) == "v2"


def test_missing_lesson_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lookup_module, "_DEFAULT_DATA_DIR", tmp_path / "missing")
    assert lookup_lesson(9999) is None
