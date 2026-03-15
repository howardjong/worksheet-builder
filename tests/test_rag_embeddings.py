"""Tests for the embedding service wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from rag import embeddings


@dataclass
class _FakeEmbedConfig:
    task_type: str
    output_dimensionality: int


@dataclass
class _FakePart:
    data: bytes | None = None
    mime_type: str | None = None
    text: str | None = None

    @staticmethod
    def from_bytes(data: bytes, mime_type: str) -> _FakePart:
        return _FakePart(data=data, mime_type=mime_type)

    @staticmethod
    def from_text(text: str) -> _FakePart:
        return _FakePart(text=text)


@dataclass
class _FakeContent:
    parts: list[_FakePart]


class _FakeTypes:
    EmbedContentConfig = _FakeEmbedConfig
    Part = _FakePart
    Content = _FakeContent


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def embed_content(
        self,
        model: str,
        contents: object,
        config: _FakeEmbedConfig,
    ) -> Any:
        self.calls.append(
            {
                "model": model,
                "contents": contents,
                "task_type": config.task_type,
                "dimensions": config.output_dimensionality,
            }
        )

        class _Embedding:
            values = [0.1, 0.2, 0.3]

        class _Response:
            embeddings = [_Embedding()]

        return _Response()


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()


def test_embed_text_returns_correct_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)

    result = embeddings.embed_text("phonics cvce", dimensions=3)
    assert len(result.values) == 3
    assert result.dimensions == 3
    assert result.content_type == "text"


def test_embed_text_retrieval_query_vs_document(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)

    embeddings.embed_text("query", task_type="RETRIEVAL_QUERY", dimensions=3)
    embeddings.embed_text("doc", task_type="RETRIEVAL_DOCUMENT", dimensions=3)

    assert fake_client.models.calls[0]["task_type"] == "RETRIEVAL_QUERY"
    assert fake_client.models.calls[1]["task_type"] == "RETRIEVAL_DOCUMENT"


def test_embed_image_returns_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)

    image = tmp_path / "img.png"
    image.write_bytes(b"image-bytes")

    result = embeddings.embed_image(str(image), dimensions=3)
    assert len(result.values) == 3
    assert result.content_type == "image"


def test_embed_pdf_returns_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)

    pdf = tmp_path / "file.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    result = embeddings.embed_pdf(str(pdf), dimensions=3)
    assert len(result.values) == 3
    assert result.content_type == "pdf"


def test_embed_multimodal_returns_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)

    image = tmp_path / "img.jpg"
    image.write_bytes(b"image-bytes")

    result = embeddings.embed_multimodal("phonics worksheet", str(image), dimensions=3)
    assert len(result.values) == 3
    assert result.content_type == "multimodal"


def test_embedding_model_configurable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)
    monkeypatch.setattr(
        embeddings,
        "get_embedding_models",
        lambda: ["gemini-embedding-test"],
    )

    embeddings.embed_text("phonics", dimensions=3)
    assert fake_client.models.calls[0]["model"] == "gemini-embedding-test"


def test_embed_text_falls_back_to_next_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FallbackModels(_FakeModels):
        def embed_content(
            self,
            model: str,
            contents: object,
            config: _FakeEmbedConfig,
        ) -> Any:
            if model == "gemini-embedding-exp-03-07":
                raise RuntimeError("403 permission denied")
            return super().embed_content(model, contents, config)

    class _FallbackClient(_FakeClient):
        def __init__(self) -> None:
            self.models = _FallbackModels()

    fake_client = _FallbackClient()
    monkeypatch.setattr(embeddings, "_types_module", lambda: _FakeTypes)
    monkeypatch.setattr(embeddings, "get_rag_client", lambda: fake_client)
    monkeypatch.setattr(
        embeddings,
        "get_embedding_models",
        lambda: ["gemini-embedding-exp-03-07", "text-embedding-005"],
    )

    result = embeddings.embed_text("phonics", dimensions=3)
    assert result.model == "text-embedding-005"
    assert fake_client.models.calls[0]["model"] == "text-embedding-005"
