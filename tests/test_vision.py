from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from extract.vision import _configured_api_key, extract_with_vision


def test_configured_api_key_uses_only_router(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert _configured_api_key() == "router-key"


def test_configured_api_key_does_not_fall_back_to_google(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert _configured_api_key() == ""


def test_extract_with_vision_returns_none_without_any_api_key(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with caplog.at_level(logging.INFO):
        result = extract_with_vision("unused.jpg", "hash123")

    assert result is None
    assert "No OPENROUTER_API_KEY" in caplog.text


def test_schema_rejects_invented_templates_missing_confidence_and_empty_regions() -> None:
    from extract.vision import _valid_extraction

    valid = {
        "template_type": "unknown",
        "regions": [
            {"type": "word_list", "content": "cat dog", "confidence": 0.9},
        ],
    }
    assert _valid_extraction(valid)
    assert not _valid_extraction({**valid, "template_type": "made_up"})
    assert not _valid_extraction({**valid, "regions": []})
    assert not _valid_extraction({**valid, "regions": [{"type": "word_list", "content": "cat"}]})


def test_extraction_routes_independently_and_propagates_uncertainty(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_EXTRACTION_MODELS", "fast-vision")
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"mock-photo")

    def fake_extract(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["model_ids"] == ["fast-vision"] and kwargs["json_schema"]
        data = {
            "template_type": "unknown",
            "regions": [
                {"type": "concept_label", "content": "CVC", "confidence": 0.95},
                {"type": "word_list", "content": "[unreadable]", "confidence": 0.2},
            ],
        }
        assert kwargs["validate"](data)
        return data

    monkeypatch.setattr("ai.openrouter.complete_json", fake_extract)
    result = extract_with_vision(str(photo), "hash")
    assert result and result.low_confidence_flags == [1]
    assert all(r.metadata["bbox_unavailable"] for r in result.regions)


def test_corpus_mismatch_cannot_leave_confidence_flags_empty(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"mock-photo")
    monkeypatch.setattr(
        "ai.openrouter.complete_json",
        lambda *args, **kwargs: {
            "template_type": "ufli_word_work",
            "regions": [
                {"type": "sample_words", "content": "cat dog", "confidence": 0.95},
            ],
        },
    )
    monkeypatch.setattr("extract.vision._check_corpus_hallucination", lambda _: "mismatch")
    result = extract_with_vision(str(photo), "hash")
    assert result and result.low_confidence_flags == [0]


def test_mixed_visible_pages_preserve_both_passage_and_word_work() -> None:
    from extract.schema import SourceRegion, SourceWorksheetModel
    from extract.vision import _validate_template_type
    from skill.extractor import extract_skill

    regions = [
        SourceRegion(type=kind, content=text, bbox=(0, 0, 1, 1), confidence=1, metadata={})
        for kind, text in [
            ("concept_label", "CVC"),
            ("sample_words", "cat map"),
            ("word_chain", "cat -> cap -> map"),
            ("decodable_passage", "The cat sat on a mat."),
        ]
    ]
    template = _validate_template_type("ufli_word_work", regions)
    assert template == "unknown"
    source = SourceWorksheetModel(
        source_image_hash="test",
        pipeline_version="test",
        template_type=template,
        regions=regions,
        raw_text="test",
        ocr_engine="test",
        low_confidence_flags=[],
    )
    skill = extract_skill(source)
    assert {item.source_region_index for item in skill.source_items} == {1, 2, 3}
