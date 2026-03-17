"""Shared Google Cloud TTS request helper with bounded retries."""

from __future__ import annotations

import base64
import json
import logging
import random
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

from corpus.ufli.audio_companion_schema import AudioInputFormat, GoogleCloudTtsSettings

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 60.0
_MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 20.0
_JITTER_MIN = 0.8
_JITTER_MAX = 1.2
_RETRYABLE_HTTP_STATUS_CODES = {429, 499, 500, 502, 503, 504}
_GOOGLE_AUTH_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)

GoogleTtsFailureCategory = Literal[
    "http_retryable",
    "http_non_retryable",
    "transport",
    "auth",
    "response",
    "unknown",
]


@dataclass(frozen=True)
class GoogleTtsRequestContext:
    """Prepared auth context for a burst of Google TTS requests."""

    access_token: str
    project_id: str = ""


@dataclass(frozen=True)
class GoogleTtsSynthesisResult:
    """Successful Google TTS response plus retry metadata."""

    audio_bytes: bytes
    attempt_count: int
    retry_delays_s: tuple[float, ...] = ()


class GoogleTtsSynthesisError(RuntimeError):
    """Structured Google TTS failure after retry handling."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        failure_category: GoogleTtsFailureCategory,
        attempt_count: int,
        retryable: bool,
        retry_exhausted: bool,
        retry_delays_s: tuple[float, ...] = (),
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.failure_category = failure_category
        self.attempt_count = attempt_count
        self.retryable = retryable
        self.retry_exhausted = retry_exhausted
        self.retry_delays_s = retry_delays_s
        self.retry_after_seconds = retry_after_seconds


def build_google_tts_request_context() -> GoogleTtsRequestContext:
    """Fetch ADC credentials once for a burst of Google TTS requests."""
    credentials, project_id = google.auth.default(scopes=list(_GOOGLE_AUTH_SCOPES))
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())  # type: ignore[no-untyped-call]
    token = credentials.token
    if not token:
        raise GoogleTtsSynthesisError(
            "Google Cloud TTS auth failed: missing access token",
            status_code=None,
            failure_category="auth",
            attempt_count=0,
            retryable=False,
            retry_exhausted=False,
        )
    return GoogleTtsRequestContext(
        access_token=str(token),
        project_id=str(project_id or ""),
    )


def synthesize_google_tts_audio(
    *,
    text: str,
    input_format: AudioInputFormat,
    settings: GoogleCloudTtsSettings,
    context: GoogleTtsRequestContext,
    request_label: str = "google_tts",
) -> GoogleTtsSynthesisResult:
    """Synthesize Google TTS audio with bounded retries and structured failures."""
    payload = _build_payload(text=text, input_format=input_format, settings=settings)
    retry_delays: list[float] = []
    last_error: GoogleTtsSynthesisError | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        request = _build_request(
            payload=payload,
            settings=settings,
            context=context,
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            audio_bytes = _decode_audio_content(
                response_payload,
                attempt_count=attempt,
            )
            return GoogleTtsSynthesisResult(
                audio_bytes=audio_bytes,
                attempt_count=attempt,
                retry_delays_s=tuple(retry_delays),
            )
        except urllib.error.HTTPError as exc:  # pragma: no cover - exercised via tests
            failure = _http_failure(exc=exc, attempt_count=attempt)
        except urllib.error.URLError as exc:  # pragma: no cover - exercised via tests
            failure = GoogleTtsSynthesisError(
                f"Google Cloud TTS transport failed: {exc}",
                status_code=None,
                failure_category="transport",
                attempt_count=attempt,
                retryable=True,
                retry_exhausted=False,
                retry_delays_s=tuple(retry_delays),
            )
        except GoogleTtsSynthesisError as exc:
            failure = exc

        if not failure.retryable or attempt >= _MAX_ATTEMPTS:
            final_failure = GoogleTtsSynthesisError(
                str(failure),
                status_code=failure.status_code,
                failure_category=failure.failure_category,
                attempt_count=attempt,
                retryable=failure.retryable,
                retry_exhausted=failure.retryable and attempt >= _MAX_ATTEMPTS,
                retry_delays_s=tuple(retry_delays),
                retry_after_seconds=failure.retry_after_seconds,
            )
            logger.error(
                "Google TTS failed for %s after %d attempts: category=%s status=%s message=%s",
                request_label,
                attempt,
                final_failure.failure_category,
                final_failure.status_code,
                final_failure,
            )
            raise final_failure from last_error or failure

        delay = _retry_delay_seconds(
            attempt=attempt,
            retry_after=failure.retry_after_seconds,
        )
        retry_delays.append(delay)
        logger.warning(
            "Google TTS retry for %s: attempt=%d/%d "
            "category=%s status=%s next_delay=%.2fs message=%s",
            request_label,
            attempt,
            _MAX_ATTEMPTS,
            failure.failure_category,
            failure.status_code,
            delay,
            failure,
        )
        last_error = failure
        _sleep(delay)

    raise RuntimeError("unreachable")


def _build_payload(
    *,
    text: str,
    input_format: AudioInputFormat,
    settings: GoogleCloudTtsSettings,
) -> dict[str, object]:
    input_payload: dict[str, object] = (
        {"markup": text}
        if input_format == "markup"
        else {"text": text}
    )
    if settings.style_prompt:
        input_payload["prompt"] = settings.style_prompt
    return {
        "input": input_payload,
        "voice": {
            "languageCode": settings.language_code,
            "name": settings.voice_name,
            **({"modelName": settings.model_name} if settings.model_name else {}),
        },
        "audioConfig": {
            "audioEncoding": settings.audio_encoding,
            "speakingRate": settings.speaking_rate,
            **(
                {"sampleRateHertz": settings.sample_rate_hz}
                if settings.sample_rate_hz > 0
                else {}
            ),
            "volumeGainDb": settings.volume_gain_db,
        },
    }


def _build_request(
    *,
    payload: dict[str, object],
    settings: GoogleCloudTtsSettings,
    context: GoogleTtsRequestContext,
) -> urllib.request.Request:
    return urllib.request.Request(
        f"{settings.api_endpoint}/v1/text:synthesize",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {context.access_token}",
            "Content-Type": "application/json",
            **(
                {"x-goog-user-project": context.project_id}
                if context.project_id
                else {}
            ),
        },
        method="POST",
    )


def _decode_audio_content(
    response_payload: object,
    *,
    attempt_count: int,
) -> bytes:
    if not isinstance(response_payload, dict):
        raise GoogleTtsSynthesisError(
            "Google Cloud TTS returned a malformed response payload",
            status_code=None,
            failure_category="response",
            attempt_count=attempt_count,
            retryable=False,
            retry_exhausted=False,
        )
    audio_content = response_payload.get("audioContent", "")
    if not isinstance(audio_content, str) or not audio_content:
        raise GoogleTtsSynthesisError(
            "Google Cloud TTS returned no audioContent",
            status_code=None,
            failure_category="response",
            attempt_count=attempt_count,
            retryable=False,
            retry_exhausted=False,
        )
    try:
        return base64.b64decode(audio_content)
    except Exception as exc:  # pragma: no cover - defensive
        raise GoogleTtsSynthesisError(
            f"Google Cloud TTS returned invalid base64 audioContent: {exc}",
            status_code=None,
            failure_category="response",
            attempt_count=attempt_count,
            retryable=False,
            retry_exhausted=False,
        ) from exc


def _http_failure(
    *,
    exc: urllib.error.HTTPError,
    attempt_count: int,
) -> GoogleTtsSynthesisError:
    body = exc.read().decode("utf-8", errors="ignore")
    category: GoogleTtsFailureCategory
    retryable = exc.code in _RETRYABLE_HTTP_STATUS_CODES
    if exc.code in {401, 403}:
        category = "auth"
        retryable = False
    elif retryable:
        category = "http_retryable"
    else:
        category = "http_non_retryable"
    return GoogleTtsSynthesisError(
        f"Google Cloud TTS failed ({exc.code}): {body}",
        status_code=exc.code,
        failure_category=category,
        attempt_count=attempt_count,
        retryable=retryable,
        retry_exhausted=False,
        retry_after_seconds=_retry_after_seconds(exc.headers.get("Retry-After", "")),
    )


def _retry_after_seconds(header_value: str) -> float | None:
    if not header_value:
        return None
    parsed_seconds = _parse_retry_after(header_value)
    if parsed_seconds is None:
        return None
    return min(parsed_seconds, _MAX_BACKOFF_SECONDS)


def _parse_retry_after(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return float(stripped)
    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delta = (retry_at - datetime.now(tz=UTC)).total_seconds()
    return max(delta, 0.0)


def _retry_delay_seconds(*, attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after
    base_delay = min(_BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
    return float(min(base_delay * _jitter_multiplier(), _MAX_BACKOFF_SECONDS))


def _jitter_multiplier() -> float:
    return float(random.uniform(_JITTER_MIN, _JITTER_MAX))


def _sleep(delay: float) -> None:
    import time

    time.sleep(delay)
