"""Tests for RAG client backend selection."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from rag import client


class _FakeModels:
    def get(self, model: str) -> None:
        self.last_model = model


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()


def _install_fake_google(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, object]],
) -> None:
    fake_client = _FakeClient()

    def _fake_client_factory(**kwargs: object) -> _FakeClient:
        calls.append(dict(kwargs))
        return fake_client

    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    setattr(genai_module, "Client", _fake_client_factory)
    setattr(google_module, "genai", genai_module)

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)


def test_rag_available_accepts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RAG_GEMINI_BACKEND", "auto")

    assert client.rag_available() is True


def test_get_rag_client_uses_api_key_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    _install_fake_google(monkeypatch, calls)
    client.get_rag_client.cache_clear()
    monkeypatch.setenv("RAG_GEMINI_BACKEND", "api_key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    client.get_rag_client()

    assert calls == [{"api_key": "test-key"}]


def test_get_rag_client_uses_vertex_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    _install_fake_google(monkeypatch, calls)
    client.get_rag_client.cache_clear()
    monkeypatch.setenv("RAG_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "ws-builder-rag")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    client.get_rag_client()

    assert calls == [
        {
            "vertexai": True,
            "project": "ws-builder-rag",
            "location": "us-central1",
        }
    ]
