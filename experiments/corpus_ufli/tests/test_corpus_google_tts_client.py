"""Tests for shared Google Cloud TTS retry handling."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from email.message import Message
from typing import Literal

import pytest

from experiments.corpus_ufli.audio_companion_schema import GoogleCloudTtsSettings
from experiments.corpus_ufli.google_tts_client import (
    GoogleTtsRequestContext,
    GoogleTtsSynthesisError,
    synthesize_google_tts_audio,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _settings() -> GoogleCloudTtsSettings:
    return GoogleCloudTtsSettings(
        api_endpoint="https://texttospeech.googleapis.com",
        voice_name="Leda",
        model_name="gemini-2.5-pro-tts",
    )


def _context() -> GoogleTtsRequestContext:
    return GoogleTtsRequestContext(access_token="token", project_id="project")


def _success_response(audio_bytes: bytes = b"mp3") -> _FakeResponse:
    return _FakeResponse({"audioContent": base64.b64encode(audio_bytes).decode("utf-8")})


def _http_error(
    code: int,
    *,
    body: str = "boom",
    headers: dict[str, str] | None = None,
) -> urllib.error.HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(
        url="https://texttospeech.googleapis.com/v1/text:synthesize",
        code=code,
        msg="error",
        hdrs=message,
        fp=io.BytesIO(body.encode("utf-8")),
    )


def test_google_tts_client_retries_499_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    sleeps: list[float] = []
    responses: list[_FakeResponse | Exception] = [_http_error(499), _success_response()]

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        calls.append(int(timeout))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr("experiments.corpus_ufli.google_tts_client._jitter_multiplier", lambda: 1.0)
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    result = synthesize_google_tts_audio(
        text="Hello world",
        input_format="text",
        settings=_settings(),
        context=_context(),
        request_label="clip-499",
    )

    assert result.audio_bytes == b"mp3"
    assert result.attempt_count == 2
    assert result.retry_delays_s == (2.0,)
    assert sleeps == [2.0]
    assert calls == [60, 60]


def test_google_tts_client_retries_502_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    responses: list[_FakeResponse | Exception] = [_http_error(502), _success_response()]

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr("experiments.corpus_ufli.google_tts_client._jitter_multiplier", lambda: 1.0)
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    result = synthesize_google_tts_audio(
        text="Hello world",
        input_format="text",
        settings=_settings(),
        context=_context(),
        request_label="clip-502",
    )

    assert result.attempt_count == 2
    assert sleeps == [2.0]


def test_google_tts_client_retries_429_and_honors_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    responses: list[_FakeResponse | Exception] = [
        _http_error(429, headers={"Retry-After": "7"}),
        _success_response(),
    ]

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    result = synthesize_google_tts_audio(
        text="Hello world",
        input_format="text",
        settings=_settings(),
        context=_context(),
        request_label="clip-429",
    )

    assert result.attempt_count == 2
    assert sleeps == [7.0]


def test_google_tts_client_retries_urlerror_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    responses: list[_FakeResponse | Exception] = [
        urllib.error.URLError("temporary network"),
        _success_response(),
    ]

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr("experiments.corpus_ufli.google_tts_client._jitter_multiplier", lambda: 1.0)
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    result = synthesize_google_tts_audio(
        text="Hello world",
        input_format="text",
        settings=_settings(),
        context=_context(),
        request_label="clip-urlerror",
    )

    assert result.attempt_count == 2
    assert sleeps == [2.0]


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_google_tts_client_does_not_retry_non_retryable_http_codes(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    sleeps: list[float] = []

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        raise _http_error(status_code)

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    with pytest.raises(GoogleTtsSynthesisError) as exc_info:
        synthesize_google_tts_audio(
            text="Hello world",
            input_format="text",
            settings=_settings(),
            context=_context(),
            request_label=f"clip-{status_code}",
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.attempt_count == 1
    assert exc_info.value.retryable is False
    assert sleeps == []


def test_google_tts_client_raises_exhausted_error_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        raise _http_error(502)

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr("experiments.corpus_ufli.google_tts_client._jitter_multiplier", lambda: 1.0)
    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client._sleep", lambda delay: sleeps.append(delay)
    )

    with pytest.raises(GoogleTtsSynthesisError) as exc_info:
        synthesize_google_tts_audio(
            text="Hello world",
            input_format="text",
            settings=_settings(),
            context=_context(),
            request_label="clip-exhausted",
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.attempt_count == 5
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_exhausted is True
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_google_tts_client_raises_response_error_for_missing_audio_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(_request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse({})

    monkeypatch.setattr(
        "experiments.corpus_ufli.google_tts_client.urllib.request.urlopen", _fake_urlopen
    )

    with pytest.raises(GoogleTtsSynthesisError) as exc_info:
        synthesize_google_tts_audio(
            text="Hello world",
            input_format="text",
            settings=_settings(),
            context=_context(),
            request_label="clip-response",
        )

    assert exc_info.value.failure_category == "response"
    assert exc_info.value.retryable is False
