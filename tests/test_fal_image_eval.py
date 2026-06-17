from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def test_fal_model_aliases_expand_to_model_ids() -> None:
    from render.fal_eval import expand_model_ids

    assert expand_model_ids(["gpt-image-2", "recraft-v4", "qwen-image-2512"]) == [
        "openai/gpt-image-2",
        "fal-ai/recraft/v4/text-to-image",
        "fal-ai/qwen-image-2512",
    ]


def test_load_fal_env_accepts_fal_api_key_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from render.fal_eval import load_fal_env

    env_path = tmp_path / ".env"
    env_path.write_text("FAL_API_KEY=from-alias\n")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)

    assert load_fal_env(env_path)
    assert os_environ("FAL_KEY") == "from-alias"


def test_extract_image_url_handles_common_fal_shapes() -> None:
    from render.fal_eval import extract_image_url

    assert (
        extract_image_url({"images": [{"url": "https://example.com/a.png"}]})
        == "https://example.com/a.png"
    )
    assert (
        extract_image_url({"image": {"url": "https://example.com/b.png"}})
        == "https://example.com/b.png"
    )
    assert (
        extract_image_url({"output": {"url": "https://example.com/c.png"}})
        == "https://example.com/c.png"
    )


def test_run_model_writes_image_and_metadata(tmp_path: Path) -> None:
    from render.fal_eval import FalEvalConfig, run_one_model

    calls: list[dict[str, Any]] = []

    def fake_subscribe(
        model_id: str,
        *,
        arguments: dict[str, Any],
        with_logs: bool,
        on_queue_update: object | None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "model_id": model_id,
                "arguments": arguments,
                "with_logs": with_logs,
                "on_queue_update": on_queue_update,
            }
        )
        return {"images": [{"url": "https://example.com/image.png"}], "request_id": "req_123"}

    result = run_one_model(
        model_id="fal-ai/qwen-image-2512",
        prompt="worksheet prompt",
        config=FalEvalConfig(output_dir=tmp_path, image_size="portrait_4_3"),
        subscribe=fake_subscribe,
        download=lambda _url: b"png-bytes",
    )

    assert calls == [
        {
            "model_id": "fal-ai/qwen-image-2512",
            "arguments": {
                "prompt": "worksheet prompt",
                "image_size": "portrait_4_3",
                "num_images": 1,
            },
            "with_logs": False,
            "on_queue_update": None,
        }
    ]
    assert result.status == "success"
    assert Path(result.image_path or "").read_bytes() == b"png-bytes"
    sidecar = Path(result.metadata_path or "")
    payload = json.loads(sidecar.read_text())
    assert payload["model_id"] == "fal-ai/qwen-image-2512"
    assert payload["request_id"] == "req_123"
    assert payload["image_url"] == "https://example.com/image.png"


def os_environ(name: str) -> str | None:
    import os

    return os.environ.get(name)
