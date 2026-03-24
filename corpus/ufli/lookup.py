"""Deterministic corpus lookup for UFLI lesson data.

Reads data/ufli/normalized.jsonl and returns structured lesson content
(decodable passage, Roll and Read word list, etc.) by lesson number.
No API calls — pure file lookup with in-memory caching for batch mode.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ufli"

# Module-level cache: populated on first lookup, reused across calls
_corpus_cache: dict[str, _CorpusRecord] | None = None


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


def lookup_lesson(
    lesson_number: int,
    data_dir: str | Path | None = None,
) -> CorpusLookupResult | None:
    """Look up a UFLI lesson's corpus data by lesson number.

    Returns None if the lesson is not found or the corpus file is missing.
    """
    global _corpus_cache

    if _corpus_cache is None:
        _corpus_cache = _load_corpus(data_dir or _DEFAULT_DATA_DIR)

    key = str(lesson_number)
    record = _corpus_cache.get(key)
    if record is None:
        return None

    return CorpusLookupResult(
        lesson_id=record.lesson_id,
        concept=record.concept,
        decodable_text=record.decodable_text,
        additional_text=record.additional_text,
        home_practice_text=record.home_practice_text,
    )


def _load_corpus(data_dir: str | Path) -> dict[str, _CorpusRecord]:
    """Parse normalized.jsonl into a lesson_id-keyed dict."""
    corpus_path = Path(data_dir) / "normalized.jsonl"
    if not corpus_path.exists():
        logger.warning("Corpus file not found: %s", corpus_path)
        return {}

    records: dict[str, _CorpusRecord] = {}
    with open(corpus_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed line %d in %s", line_num, corpus_path)
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

    logger.info("Loaded %d lessons from corpus", len(records))
    return records
