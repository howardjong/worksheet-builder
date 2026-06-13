"""Tests for transform._source_model_with_cache (B' frozen extraction)."""

from __future__ import annotations

from pathlib import Path

import pytest

import transform
from extract.schema import SourceRegion, SourceWorksheetModel


def _src(tag: str = "v") -> SourceWorksheetModel:
    return SourceWorksheetModel(
        source_image_hash="h",
        pipeline_version="0.1.0",
        template_type="ufli_word_work",
        regions=[
            SourceRegion(
                type="title",
                content=tag,
                bbox=(0, 0, 1, 1),
                confidence=0.9,
                metadata={},
            )
        ],
        raw_text=tag,
        ocr_engine="vision",
        low_confidence_flags=[],
    )


def test_cache_freezes_extraction_after_first_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the cache dir set, vision runs once per image; later calls reload it."""
    calls: list[str] = []

    def fake_resolve(
        input_path: str, preprocessed_path: str, image_hash: str
    ) -> SourceWorksheetModel:
        calls.append(image_hash)
        return _src("resolved")

    monkeypatch.setattr(transform, "_resolve_source_model", fake_resolve)
    monkeypatch.setenv("WORKSHEET_EXTRACTION_CACHE", str(tmp_path))

    first = transform._source_model_with_cache("in.png", "pre.png", "hash123")
    second = transform._source_model_with_cache("in.png", "pre.png", "hash123")

    assert calls == ["hash123"]  # resolved once, second call hit the cache
    assert first.model_dump() == second.model_dump()


def test_no_cache_env_resolves_every_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_resolve(
        input_path: str, preprocessed_path: str, image_hash: str
    ) -> SourceWorksheetModel:
        calls.append(image_hash)
        return _src()

    monkeypatch.setattr(transform, "_resolve_source_model", fake_resolve)
    monkeypatch.delenv("WORKSHEET_EXTRACTION_CACHE", raising=False)

    transform._source_model_with_cache("in.png", "pre.png", "h")
    transform._source_model_with_cache("in.png", "pre.png", "h")

    assert calls == ["h", "h"]
