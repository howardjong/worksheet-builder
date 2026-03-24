from __future__ import annotations

import logging

from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from extract.vision import _configured_api_key, extract_with_vision


def test_configured_api_key_prefers_gemini(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    assert _configured_api_key() == "gemini-key"


def test_configured_api_key_falls_back_to_google(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    assert _configured_api_key() == "google-key"


def test_extract_with_vision_returns_none_without_any_api_key(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with caplog.at_level(logging.INFO):
        result = extract_with_vision("unused.jpg", "hash123")

    assert result is None
    assert "No GEMINI_API_KEY or GOOGLE_API_KEY" in caplog.text
