"""Source review happens without authoring or image calls and reuses the frozen photo."""

from pathlib import Path

import pytest
from PIL import Image

from experiments.photo_intake import intake
from extract.schema import SourceRegion, SourceWorksheetModel


def test_intake_is_dry_by_default_and_live_requires_limits(tmp_path: Path) -> None:
    photo = tmp_path / "photo.png"
    Image.new("RGB", (1000, 1300), "white").save(photo)
    report = intake(str(tmp_path / "dry"), str(photo))
    assert report["mode"] == "dry_run_no_inference" and not report["plans_or_renders"]
    with pytest.raises(ValueError, match="private extraction cache"):
        intake(str(tmp_path / "unbounded"), str(photo), live=True)


def test_frozen_intake_reuses_transcription_and_preserves_source_for_human_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import transform

    photo = tmp_path / "photo.png"
    Image.new("RGB", (1000, 1300), "white").save(photo)
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-surrogate")
    monkeypatch.setenv("WORKSHEET_EXTRACTION_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("WORKSHEET_RUN_MAX_USD", "0.1")
    monkeypatch.setenv("WORKSHEET_RUN_MAX_CALLS", "2")
    monkeypatch.setenv("WORKSHEET_RUN_DEADLINE_S", "10")
    monkeypatch.setenv("WORKSHEET_OPENROUTER_EXTRACTION_MODELS", "fast-vision")
    monkeypatch.setenv("WORKSHEET_CALL_CEILINGS_JSON", '{"fast-vision":0.01}')
    calls: list[str] = []

    def extract(path: str, preprocessed: str, image_hash: str) -> SourceWorksheetModel:
        calls.append(path)
        return SourceWorksheetModel(
            source_image_hash=image_hash,
            pipeline_version="test",
            template_type="unknown",
            regions=[
                SourceRegion(
                    type="concept_label",
                    content="CVC",
                    confidence=1,
                    bbox=(0, 0, 1, 1),
                    metadata={},
                ),
                SourceRegion(
                    type="word_list",
                    content="cat map",
                    confidence=1,
                    bbox=(0, 0, 1, 1),
                    metadata={},
                ),
            ],
            raw_text="CVC cat map",
            ocr_engine="mock",
            low_confidence_flags=[],
        )

    monkeypatch.setattr(transform, "_resolve_source_model", extract)
    first = intake(str(tmp_path / "intake"), str(photo), live=True)
    second = intake(str(tmp_path / "reused"), str(photo), live=True)
    assert first == second and calls == [str(photo)]
    assert (tmp_path / "intake/source_model.json").is_file()
    # Full pipeline changes the processed master hash but should reuse original-photo transcription.
    transform._source_model_with_cache(str(photo), "not-needed-on-cache-hit", "new-master-hash")
    assert calls == [str(photo)]
    monkeypatch.setenv("WORKSHEET_OPENROUTER_EXTRACTION_MODELS", "other-model")
    transform._source_model_with_cache(str(photo), "not-needed-by-mock", "new-master-hash")
    assert calls == [str(photo), str(photo)]
