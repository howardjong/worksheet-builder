"""Tests for run artifact indexing into ChromaDB."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("chromadb")

from rag.embeddings import EmbeddingResult
from rag.indexer import index_run
from rag.store import (
    ADAPTATIONS,
    EXEMPLARS,
    SKILLS,
    WORKSHEETS,
    get_or_create_collection,
    get_store,
)


def _fake_embedding(content_type: str = "text") -> EmbeddingResult:
    return EmbeddingResult(
        values=[1.0, 0.0, 0.0],
        dimensions=3,
        task_type="RETRIEVAL_DOCUMENT",
        content_type=content_type,
    )


def test_index_run_creates_all_collections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rag.indexer.embed_text", lambda *args, **kwargs: _fake_embedding("text"))
    monkeypatch.setattr(
        "rag.indexer.embed_multimodal",
        lambda *args, **kwargs: _fake_embedding("multimodal"),
    )
    monkeypatch.setattr("rag.indexer.embed_pdf", lambda *args, **kwargs: _fake_embedding("pdf"))

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")
    pdf_path = tmp_path / "ws.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    index_run(
        source_image_path=str(image_path),
        source_image_hash="abc123",
        extracted_text="Student name: Ian\nword list grade chase",
        template_type="ufli_word_work",
        ocr_engine="gemini_vision",
        region_count=6,
        skill_domain="phonics",
        skill_name="cvce_pattern",
        grade_level="1",
        adapted_summaries=[
            {
                "worksheet_title": "Word Discovery",
                "response_formats": "match,trace,circle",
                "chunk_count": 3,
                "estimated_minutes": 5,
                "distractor_words": "the,and,cat",
            }
        ],
        pdf_paths=[str(pdf_path)],
        theme_id="space",
        validation_results={
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        worksheet_mode="single",
        db_path=str(tmp_path / "vector_store"),
        profile_name="Ian",
    )

    store = get_store(str(tmp_path / "vector_store"))
    assert get_or_create_collection(store, WORKSHEETS).count() == 1
    assert get_or_create_collection(store, SKILLS).count() == 1
    assert get_or_create_collection(store, ADAPTATIONS).count() == 1
    assert get_or_create_collection(store, EXEMPLARS).count() == 1


def test_only_validated_runs_become_exemplars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rag.indexer.embed_text", lambda *args, **kwargs: _fake_embedding("text"))
    monkeypatch.setattr(
        "rag.indexer.embed_multimodal",
        lambda *args, **kwargs: _fake_embedding("multimodal"),
    )
    monkeypatch.setattr("rag.indexer.embed_pdf", lambda *args, **kwargs: _fake_embedding("pdf"))

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")
    pdf_path = tmp_path / "ws.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    index_run(
        source_image_path=str(image_path),
        source_image_hash="abc123",
        extracted_text="grade chase slide",
        template_type="ufli_word_work",
        ocr_engine="gemini_vision",
        region_count=4,
        skill_domain="phonics",
        skill_name="cvce_pattern",
        grade_level="1",
        adapted_summaries=[{"response_formats": "match,trace,circle"}],
        pdf_paths=[str(pdf_path)],
        theme_id="space",
        validation_results={
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": False,
            "print_quality_passed": True,
        },
        worksheet_mode="single",
        db_path=str(tmp_path / "vector_store"),
    )

    store = get_store(str(tmp_path / "vector_store"))
    assert get_or_create_collection(store, ADAPTATIONS).count() == 1
    assert get_or_create_collection(store, EXEMPLARS).count() == 0


def test_enriched_metadata_stored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rag.indexer.embed_text", lambda *args, **kwargs: _fake_embedding("text"))
    monkeypatch.setattr(
        "rag.indexer.embed_multimodal",
        lambda *args, **kwargs: _fake_embedding("multimodal"),
    )
    monkeypatch.setattr("rag.indexer.embed_pdf", lambda *args, **kwargs: _fake_embedding("pdf"))

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")
    pdf_path = tmp_path / "ws.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    index_run(
        source_image_path=str(image_path),
        source_image_hash="abc123",
        extracted_text="grade chase slide",
        template_type="ufli_word_work",
        ocr_engine="gemini_vision",
        region_count=4,
        skill_domain="phonics",
        skill_name="cvce_pattern",
        grade_level="1",
        adapted_summaries=[
            {
                "worksheet_title": "Word Discovery",
                "response_formats": "match,trace,circle",
                "estimated_minutes": 5,
                "chunk_count": 3,
            }
        ],
        pdf_paths=[str(pdf_path)],
        theme_id="space",
        validation_results={
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        worksheet_mode="single",
        db_path=str(tmp_path / "vector_store"),
    )

    store = get_store(str(tmp_path / "vector_store"))
    collection = get_or_create_collection(store, ADAPTATIONS)
    results = collection.get(ids=["adapt_abc123_space_1"])
    metadata = results["metadatas"][0]
    assert metadata["response_formats"] == "match,trace,circle"
    assert metadata["estimated_minutes"] == 5
    assert metadata["all_validators_passed"] is True

    exemplar_collection = get_or_create_collection(store, EXEMPLARS)
    exemplar = exemplar_collection.get(ids=["exemplar_abc123_space_1"])
    exemplar_meta = exemplar["metadatas"][0]
    assert exemplar_meta["response_formats"] == "match,trace,circle"
    assert exemplar_meta["estimated_minutes"] == 5


def test_indexer_failures_dont_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rag.indexer.embed_text", lambda *args, **kwargs: _fake_embedding("text"))

    def _raise(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr("rag.indexer.embed_multimodal", _raise)
    monkeypatch.setattr("rag.indexer.embed_pdf", _raise)

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")
    pdf_path = tmp_path / "ws.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    # Should not raise despite embedding failures in worksheet/pdf indexing.
    index_run(
        source_image_path=str(image_path),
        source_image_hash="abc123",
        extracted_text="grade chase slide",
        template_type="ufli_word_work",
        ocr_engine="gemini_vision",
        region_count=4,
        skill_domain="phonics",
        skill_name="cvce_pattern",
        grade_level="1",
        adapted_summaries=[{"response_formats": "match,trace,circle"}],
        pdf_paths=[str(pdf_path)],
        theme_id="space",
        validation_results={
            "skill_parity_passed": True,
            "age_band_passed": True,
            "adhd_compliance_passed": True,
            "print_quality_passed": True,
        },
        worksheet_mode="single",
        db_path=str(tmp_path / "vector_store"),
    )
