"""OpenRouter protocol, failures, fallback chains, and gate integration."""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from ai import openrouter


def _image(format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 48), "white").save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setenv("WORKSHEET_AI_PROVIDER", "openrouter")
    monkeypatch.setattr(time, "sleep", lambda _: None)


def _responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response | Exception]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)), trust_env=False
    )
    monkeypatch.setattr(client, "post", post)
    monkeypatch.setattr(openrouter, "_client", client)
    return calls


def _text(value: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})


def test_image_api_preserves_reference_and_normalizes_raster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _image("JPEG")
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(raw).decode()}],
                },
            )
        ],
    )
    result = openrouter.generate_image("worksheet", raw, model="openai/gpt-image-2.5-sunburst")
    assert result and result.startswith(b"\x89PNG")
    payload = calls[0]["json"]
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/images"
    assert payload["input_references"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert payload["provider"]["allow_fallbacks"] is True
    assert payload["aspect_ratio"] == "3:4"


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_transient_failures_retry_once(monkeypatch: pytest.MonkeyPatch, failure: int | str) -> None:
    first = httpx.ReadTimeout("temporary") if failure == "timeout" else httpx.Response(int(failure))
    calls = _responses(monkeypatch, [first, _text("ok")])
    result = openrouter.complete("prompt")
    assert result and result.text == "ok"
    assert len(calls) == 2
    assert calls[0]["json"]["model"] == calls[1]["json"]["model"]


def test_text_chain_advances_after_exhausted_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_TEXT_MODELS", "model-a,model-b")
    calls = _responses(monkeypatch, [httpx.Response(503), httpx.Response(503), _text("ok")])
    result = openrouter.complete("prompt")
    assert result and result.model == "model-b"
    assert [c["json"]["model"] for c in calls] == ["model-a", "model-a", "model-b"]


def test_invalid_json_and_missing_fields_use_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_VISION_MODELS", "a,b,c")
    calls = _responses(
        monkeypatch, [_text("garbled"), _text("{}"), _text('{"missing": [], "misspelled": []}')]
    )
    from render.page_gates import evaluate_page_text

    result = evaluate_page_text(_image(), ["ship"])
    assert result.available and result.passed
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 402])
def test_credentials_failure_stops_the_model_chain_and_redacts_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    calls = _responses(
        monkeypatch, [httpx.Response(status, text="test-router-key private learner content")]
    )
    assert openrouter.complete("private learner content") is None
    assert len(calls) == 1
    assert "test-router-key" not in caplog.text
    assert "private learner content" not in caplog.text


def test_image_auth_failure_stops_asset_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _responses(monkeypatch, [httpx.Response(401)])
    assert openrouter.generate_with_fallbacks("image") is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"b64_json": "not-base64"}]},
        {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]},
    ],
)
def test_missing_or_corrupt_images_are_rejected(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    _responses(monkeypatch, [httpx.Response(200, json=payload)])
    assert openrouter.generate_image("page", model="model-a") is None


def test_image_chain_retries_other_models_after_missing_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", "a,b")
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(200, json={}),
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(_image()).decode()}],
                },
            ),
        ],
    )
    assert openrouter.generate_with_fallbacks("page", _image())
    assert [call["json"]["model"] for call in calls] == ["a", "b"]
    assert all(call["json"]["input_references"] for call in calls)


def test_configured_default_chain_has_four_reference_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from render.image_providers import resolve_provider_chain

    monkeypatch.delenv("WORKSHEET_IMAGE_PROVIDERS", raising=False)
    monkeypatch.delenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", raising=False)
    chain = resolve_provider_chain()
    assert [p.model_id for p in chain] == list(openrouter.DEFAULT_MODELS["image"])
    assert len(chain) == 4


def test_no_key_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    calls = _responses(monkeypatch, [])
    assert openrouter.complete("prompt") is None
    assert openrouter.generate_with_fallbacks("page") is None
    assert not calls


def test_decisions_use_the_alpha_endpoint_and_typed_probabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "answers": {
                        "clear": {"type": "noul", "noul": 0.93},
                    }
                },
            )
        ],
    )
    result = openrouter.decide_yes_no(
        "Read cat.",
        {"clear": "Is the instruction clear?"},
        model="openai/gpt-6-luna-decisions",
        images=[_image()],
    )
    assert result == {"clear": 0.93}
    assert calls[0]["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert calls[0]["json"]["state"][1]["image_url"]["url"].startswith("data:image/png")
    assert calls[0]["json"]["questions"]["clear"]["type"] == "noul"


@pytest.mark.parametrize(
    "answer", [{}, {"type": "noul", "noul": True}, {"type": "noul", "noul": 1.2}]
)
def test_decisions_missing_or_invalid_answers_never_become_approval(
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
) -> None:
    _responses(monkeypatch, [httpx.Response(200, json={"answers": {"clear": answer}})])
    assert openrouter.decide_yes_no("text", {"clear": "Clear?"}, model="typesafe/jev-1.13") is None


def test_jev_image_request_is_rejected_before_any_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _responses(monkeypatch, [])
    with pytest.raises(ValueError, match="text only"):
        openrouter.decide_yes_no(
            "text", {"clear": "Clear?"}, model="typesafe/jev-1.13", images=[_image()]
        )
    assert not calls


def test_model_configuration_deduplicates_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_IMAGE_MODELS", " a, b,a, ,c ")
    assert openrouter.models("image") == ["a", "b", "c"]


def test_current_sol_defaults_have_medium_effort_and_no_old_model_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSHEET_OPENROUTER_TEXT_MODELS", raising=False)
    monkeypatch.delenv("WORKSHEET_OPENROUTER_VISION_MODELS", raising=False)
    calls = _responses(monkeypatch, [_text("ok")])
    assert openrouter.models("text") == openrouter.models("vision") == ["openai/gpt-6.1-sol"]
    assert openrouter.complete("prompt")
    assert calls[0]["json"]["reasoning"] == {"effort": "medium"}


def test_character_judge_uses_openrouter_without_direct_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from companion.character_judge import judge_character_consistency

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls = _responses(
        monkeypatch, [_text(json.dumps({"approved": True, "score": 9, "issues": []}))]
    )
    result = judge_character_consistency(_image(), _image(), ["same hair"])
    assert result.available and result.approved and result.judge == "openrouter"
    assert len(calls[0]["json"]["messages"][0]["content"]) == 3


def test_photo_extraction_with_only_router_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from extract.vision import extract_with_vision

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    source = tmp_path / "photo.jpg"
    source.write_bytes(_image("JPEG"))
    _responses(
        monkeypatch,
        [
            _text(
                json.dumps(
                    {
                        "template_type": "unknown",
                        "regions": [
                            {"type": "word_list", "content": "ship shop fish", "confidence": 0.95}
                        ],
                    }
                )
            )
        ],
    )
    result = extract_with_vision(str(source), "source-hash")
    assert result is not None
    assert result.ocr_engine == "openrouter_vision"
    assert "ship" in result.raw_text


def test_adapter_and_planner_prefer_router(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapt.llm_planner import _call_planner
    from extract.adapter import OpenRouterAdapter, get_adapter

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(get_adapter(), OpenRouterAdapter)
    _responses(monkeypatch, [_text("plan")])
    text, model = _call_planner("plan a lesson")
    assert text == "plan" and model == openrouter.DEFAULT_MODELS["text"][0]


def test_empty_review_is_not_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_REVIEW_MODELS", "review-a,review-b")
    from adapt.schema import AdaptedActivityModel
    from validate.ai_review import _run_review

    adapted = AdaptedActivityModel.model_validate(
        {
            "source_hash": "source",
            "skill_model_hash": "skill",
            "learner_profile_hash": "profile",
            "grade_level": "1",
            "domain": "phonics",
            "specific_skill": "vowel_teams",
            "theme_id": "space",
            "decoration_zones": [],
            "scaffolding": {},
            "chunks": [],
        }
    )
    calls = _responses(
        monkeypatch,
        [
            _text("{}"),
            _text(
                json.dumps(
                    {
                        "passed": False,
                        "issues": [{"criterion": "completeness", "description": "no activities"}],
                        "suggestions": [],
                    }
                )
            ),
        ],
    )
    result = _run_review(adapted)
    assert not result.passed
    assert len(calls) == 2


def test_audio_inputs_preserve_waveform_and_model_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _responses(monkeypatch, [_text('{"heard_text": "ship"}')])
    result = openrouter.complete_json(
        "Judge pronunciation",
        audio=[(b"actual waveform", "wav")],
        role="audio",
        model_ids=["google/gemini-3-flash-preview"],
    )
    assert result == {"heard_text": "ship"}
    payload = calls[0]["json"]
    assert payload["model"] == "google/gemini-3-flash-preview"
    part = payload["messages"][0]["content"][1]
    assert part["type"] == "input_audio"
    assert part["input_audio"]["format"] == "wav"
    assert base64.b64decode(part["input_audio"]["data"]) == b"actual waveform"


def test_legacy_keys_and_direct_setting_cannot_bypass_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapt.llm_adapt import _call_gemini
    from adapt.llm_judge import _call_openai
    from extract.adapter import NoOpAdapter, get_adapter
    from extract.vision import _configured_api_key
    from render.asset_gen import _has_api_key
    from render.image_providers import resolve_provider_chain

    monkeypatch.setenv("WORKSHEET_AI_PROVIDER", "direct")
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "legacy-key")
    calls = _responses(monkeypatch, [_text("{}")])
    assert _call_openai("judge") == "{}"
    assert calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert isinstance(get_adapter(), NoOpAdapter)
    assert _configured_api_key() == ""
    assert not _has_api_key()
    assert resolve_provider_chain() == []
    assert _call_openai("judge") is None
    assert _call_gemini("adapt") is None
    assert len(calls) == 1


def test_adapter_image_generation_creates_output_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from extract.adapter import OpenRouterAdapter

    png = _image()
    _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(png).decode()}],
                },
            )
        ],
    )
    path = tmp_path / "new" / "avatar.png"
    assert OpenRouterAdapter().generate_image("avatar", str(path)) == str(path)
    assert path.read_bytes().startswith(b"\x89PNG")


def test_image_eval_uses_shared_router_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from render.fal_eval import FalEvalConfig, run_one_model

    _responses(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(_image()).decode()}],
                },
            )
        ],
    )
    result = run_one_model(
        model_id="google/gemini-3-pro-image",
        prompt="page",
        config=FalEvalConfig(output_dir=tmp_path),
    )
    assert result.status == "success"
    assert Path(result.image_path or "").read_bytes().startswith(b"\x89PNG")


def test_inference_sources_have_no_direct_vendor_transport() -> None:
    """Catch inference in less-used scripts as well as the production pipeline."""
    import ast

    root = Path(__file__).parents[1]
    sources = list(root.glob("*.py"))
    for folder in (
        "ai",
        "adapt",
        "companion",
        "extract",
        "render",
        "validate",
        "rag",
        "experiments",
        "corpus",
        "skill",
        "capture",
        "theme",
    ):
        sources.extend((root / folder).rglob("*.py"))
    for path in sources:
        if "tests" in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call = ast.unparse(node.func)
                assert not call.endswith(
                    (
                        ".generate_content",
                        ".chat.completions.create",
                        ".messages.create",
                        ".responses.create",
                        ".images.generate",
                        ".images.edit",
                    )
                ), f"Direct inference bypass in {path.relative_to(root)}: {call}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                assert not any(
                    module.split(".")[0] in {"openai", "anthropic", "fal_client"}
                    for module in modules
                ), path


def test_audio_judge_cannot_degrade_to_transcript_only(tmp_path: Path) -> None:
    from experiments.corpus_ufli.audio_companion_schema import AudioClipDefinition
    from experiments.corpus_ufli.audio_judge import _build_judge_audio

    clip = AudioClipDefinition.model_construct(audio_path="missing.mp3")
    with pytest.raises(FileNotFoundError):
        _build_judge_audio(tmp_path, clip)
    (tmp_path / "missing.mp3").write_bytes(b"")
    with pytest.raises(ValueError, match="nonempty"):
        _build_judge_audio(tmp_path, clip)


@pytest.mark.parametrize(
    "endpoint,alpha",
    [
        ("/chat/completions", False),
        ("/images", False),
        ("/alpha/decisions", True),
    ],
)
def test_privacy_routing_is_enforced_without_weaker_fallback(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    alpha: bool,
) -> None:
    monkeypatch.setenv("WORKSHEET_OPENROUTER_REQUIRE_ZDR", "1")
    calls = _responses(monkeypatch, [httpx.Response(400)])
    assert openrouter._request(endpoint, {"model": "test-model"}, alpha=alpha) is None
    assert calls[0]["json"]["provider"] == {"zdr": True, "data_collection": "deny"}
    assert len(calls) == 1
