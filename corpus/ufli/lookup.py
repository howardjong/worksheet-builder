"""Deterministic corpus lookup for UFLI lesson data.

Reads data/ufli/normalized.jsonl and returns structured lesson content
(decodable passage, Roll and Read word list, etc.) by lesson number.
No API calls — pure file lookup with in-memory caching for batch mode.

The real corpus (data/ufli/normalized.jsonl) is gitignored. When it is absent
— fresh clones, CI — lookups fall back to a small committed fixture corpus
(corpus/ufli/fixtures/normalized_fixture.jsonl) so tests and demos still work.
The real file always wins when present.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ufli"
_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "normalized_fixture.jsonl"

# Cache keyed by the resolved corpus path so a fallback to the fixture and a
# later real-corpus lookup don't collide. Reset with reset_lookup_cache().
_corpus_caches: dict[str, dict[str, _CorpusRecord]] = {}


@dataclass(frozen=True)
class CorpusLookupResult:
    """Structured result from a corpus lookup."""

    lesson_id: str
    concept: str
    decodable_text: str
    additional_text: str
    home_practice_text: str


@dataclass(frozen=True)
class _CorpusRecord:
    """Internal parsed record from normalized.jsonl."""

    lesson_id: str
    concept: str
    decodable_text: str
    additional_text: str
    home_practice_text: str


def reset_lookup_cache() -> None:
    """Clear the corpus cache. Tests that swap the corpus file must call this."""
    _corpus_caches.clear()


def _resolve_corpus_path(data_dir: str | Path | None) -> Path:
    """Pick the corpus file: an explicit data_dir, else the real file, else fixture.

    The real corpus always wins when present; the committed fixture is only used
    when the real normalized.jsonl is absent (fresh clones, CI).
    """
    if data_dir is not None:
        return Path(data_dir) / "normalized.jsonl"
    real_path = _DEFAULT_DATA_DIR / "normalized.jsonl"
    if real_path.exists():
        return real_path
    return _FIXTURE_PATH


def lookup_lesson(
    lesson_number: int,
    data_dir: str | Path | None = None,
) -> CorpusLookupResult | None:
    """Look up a UFLI lesson's corpus data by lesson number.

    Returns None if the lesson is not found or the corpus file is missing.
    """
    corpus_path = _resolve_corpus_path(data_dir)
    cache_key = str(corpus_path.resolve())

    cache = _corpus_caches.get(cache_key)
    if cache is None:
        cache = _load_corpus(corpus_path)
        _corpus_caches[cache_key] = cache

    record = cache.get(str(lesson_number))
    if record is None:
        return None

    return CorpusLookupResult(
        lesson_id=record.lesson_id,
        concept=record.concept,
        decodable_text=record.decodable_text,
        additional_text=record.additional_text,
        home_practice_text=record.home_practice_text,
    )


def _load_corpus(corpus_path: str | Path) -> dict[str, _CorpusRecord]:
    """Parse a normalized.jsonl file into a lesson_id-keyed dict."""
    path = Path(corpus_path)
    if not path.exists():
        logger.warning("Corpus file not found: %s", path)
        return {}

    records: dict[str, _CorpusRecord] = {}
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed line %d in %s", line_num, path)
                continue

            lesson_id = str(data.get("lesson_id", ""))
            if not lesson_id:
                continue

            records[lesson_id] = _CorpusRecord(
                lesson_id=lesson_id,
                concept=str(data.get("concept", "")),
                decodable_text=str(data.get("decodable_text", "")),
                additional_text=str(data.get("additional_text", "")),
                home_practice_text=str(data.get("home_practice_text", "")),
            )

    logger.info("Loaded %d lessons from corpus %s", len(records), path)
    return records
