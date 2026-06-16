"""Committed-fixture corpus lookup for objective-sufficiency tests (CI-safe).

The live UFLI corpus (``data/ufli/normalized.jsonl``) is gitignored, so the
default ``corpus_lookup=lookup_lesson`` reaches a file absent on a clean clone /
CI. These tests inject :func:`fixture_corpus_lookup` instead, which reads a
committed three-lesson subset (43 / 58 / 59) extracted verbatim from the live
file — so it parses to the identical :class:`CorpusLookupResult`.

Built independent of ``corpus.ufli.lookup._corpus_cache`` (which locks to the
first ``data_dir`` and ignores later args): we parse the fixture file directly
into a module-level ``dict[int, CorpusLookupResult]`` once at import.
"""

from __future__ import annotations

import json
from pathlib import Path

from corpus.ufli.lookup import CorpusLookupResult

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "objective_ledger" / "corpus_subset.jsonl"


def _load_fixture_corpus() -> dict[int, CorpusLookupResult]:
    """Parse the committed corpus subset into a lesson-number-keyed dict."""
    records: dict[int, CorpusLookupResult] = {}
    for line in _FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        lesson_id = str(data.get("lesson_id", ""))
        if not lesson_id:
            continue
        records[int(lesson_id)] = CorpusLookupResult(
            lesson_id=lesson_id,
            concept=str(data.get("concept", "")),
            decodable_text=str(data.get("decodable_text", "")),
            additional_text=str(data.get("additional_text", "")),
            home_practice_text=str(data.get("home_practice_text", "")),
        )
    return records


_FIXTURE_CORPUS: dict[int, CorpusLookupResult] = _load_fixture_corpus()


def fixture_corpus_lookup(lesson_number: int) -> CorpusLookupResult | None:
    """Look up a lesson in the committed corpus subset; None if absent.

    Drop-in replacement for ``corpus.ufli.lookup.lookup_lesson`` at test sites,
    routing objective tests through committed data instead of the gitignored live
    corpus file.
    """
    return _FIXTURE_CORPUS.get(lesson_number)
