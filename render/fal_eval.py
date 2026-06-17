"""Small fal.ai image-model eval harness for worksheet renderer candidates."""

from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
import re
import ssl
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import certifi
from dotenv import load_dotenv

DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "gpt-image-2": "openai/gpt-image-2",
    "recraft-v4": "fal-ai/recraft/v4/text-to-image",
    "recraft-v4-pro": "fal-ai/recraft/v4/pro/text-to-image",
    "qwen-image-2512": "fal-ai/qwen-image-2512",
    "qwen-image": "fal-ai/qwen-image",
    "wan-v2.7": "fal-ai/wan/v2.7/text-to-image",
    "flux-2-pro": "fal-ai/flux-2-pro",
    "ideogram-v4": "fal-ai/ideogram/v4",
    "krea-v2-large": "fal-ai/krea/v2/large/text-to-image",
}

DEFAULT_MODELS: tuple[str, ...] = (
    "gpt-image-2",
    "recraft-v4",
    "qwen-image-2512",
    "wan-v2.7",
)

DEFAULT_PROMPT = "\n".join(
    [
        (
            "Create a print-ready 8.5x11 inch portrait worksheet page for a "
            "6-year-old learner with ADHD."
        ),
        "",
        (
            "Theme: calm space explorer, friendly and low-distraction. Use simple "
            "black-and-white line art with one soft accent color. No copyrighted "
            "characters. No busy background. Leave generous white space."
        ),
        "",
        'Literacy skill: short "a" CVC words.',
        "",
        "The page must include exactly this title:",
        "Short A Mission",
        "",
        "Include exactly these directions:",
        "Read each word. Circle the picture that matches.",
        "",
        (
            "Create 6 rows. Each row has one large, clearly readable word on the "
            "left and two simple picture choices on the right. The correct picture "
            "should be obvious."
        ),
        "",
        "Rows:",
        "1. cat: cat and dog",
        "2. map: map and mug",
        "3. fan: fan and fish",
        "4. jam: jam jar and hat",
        "5. bag: bag and box",
        "6. cap: cap and cup",
        "",
        "Add one small recurring mascot character: a calm round robot named Pip.",
        "",
        "Pip should appear exactly three times only:",
        "1. in the top-right margin, outside the worksheet activity area",
        (
            "2. in the left margin halfway down the page, outside all word rows "
            "and picture choices"
        ),
        "3. in the bottom-left margin, outside the Mission Progress area",
        "",
        (
            "Pip must not appear beside, between, or inside any word row. Pip must "
            "not appear inside any answer choice. Pip must not appear near, "
            "touching, or holding any stars. Pip must not hold any object. Pip must "
            "look like the same character all three times."
        ),
        "",
        (
            "At the bottom center, add exactly three empty outline stars in one "
            "horizontal row, with the label:"
        ),
        "Mission Progress",
        "",
        "No other stars should appear anywhere on the page.",
        "",
        (
            "Make all text large, correctly spelled, high contrast, and easy to read "
            "when printed. Keep decorations minimal and outside the work area."
        ),
        "",
    ]
)

SubscribeFn = Callable[..., Mapping[str, Any]]
DownloadFn = Callable[[str], bytes]
RunStatus = Literal["success", "error"]


@dataclass(frozen=True)
class FalEvalConfig:
    """Configuration shared by all fal model eval runs."""

    output_dir: Path
    image_size: str = "portrait_4_3"
    num_images: int = 1
    extra_arguments: dict[str, Any] = field(default_factory=dict)
    with_logs: bool = False


@dataclass(frozen=True)
class FalRunResult:
    """Persisted metadata for one model run."""

    model_id: str
    status: RunStatus
    latency_seconds: float
    prompt_sha256: str
    arguments: dict[str, Any]
    created_at: str
    request_id: str | None = None
    image_url: str | None = None
    image_path: str | None = None
    metadata_path: str | None = None
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def load_fal_env(env_path: Path = Path(".env")) -> bool:
    """Load `.env` and normalize the common FAL_API_KEY alias to FAL_KEY."""

    if env_path.exists():
        load_dotenv(env_path)
    if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
        os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
    return bool(os.environ.get("FAL_KEY"))


def expand_model_ids(models: list[str]) -> list[str]:
    """Expand friendly model aliases while preserving explicit fal model IDs."""

    expanded: list[str] = []
    for model in models:
        key = model.strip()
        if not key:
            continue
        expanded.append(DEFAULT_MODEL_ALIASES.get(key, key))
    return expanded


def extract_image_url(result: Mapping[str, Any]) -> str | None:
    """Find the first image URL in common fal response shapes."""

    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, Mapping):
            url = first.get("url")
            if isinstance(url, str):
                return url

    for key in ("image", "output"):
        value = result.get(key)
        if isinstance(value, Mapping):
            url = value.get("url")
            if isinstance(url, str):
                return url

    return None


def download_image_bytes(url: str) -> bytes:
    """Download a generated image URL or decode a data URI."""

    if url.startswith("data:"):
        _, encoded = url.split(",", 1)
        return base64.b64decode(encoded)

    request = urllib.request.Request(url, headers={"User-Agent": "worksheet-builder-eval/1.0"})
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=120, context=context) as response:
        return cast(bytes, response.read())


def run_one_model(
    *,
    model_id: str,
    prompt: str,
    config: FalEvalConfig,
    subscribe: SubscribeFn | None = None,
    download: DownloadFn = download_image_bytes,
) -> FalRunResult:
    """Run one fal model once and persist image plus JSON sidecar."""

    started = time.monotonic()
    created_at = datetime.now(UTC).isoformat()
    prompt_hash = _sha256_text(prompt)
    arguments = {
        "prompt": prompt,
        "image_size": config.image_size,
        "num_images": config.num_images,
        **config.extra_arguments,
    }
    safe_model = _safe_slug(model_id)
    run_dir = config.output_dir / safe_model
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        subscribe_fn = subscribe or _load_fal_subscribe()
        result = subscribe_fn(
            model_id,
            arguments=arguments,
            with_logs=config.with_logs,
            on_queue_update=_queue_logger if config.with_logs else None,
        )
        image_url = extract_image_url(result)
        if not image_url:
            raise RuntimeError(f"No image URL in fal response keys={sorted(result.keys())}")

        image_bytes = download(image_url)
        image_path = run_dir / "output.png"
        image_path.write_bytes(image_bytes)
        metadata_path = run_dir / "metadata.json"
        request_id = result.get("request_id")
        run_result = FalRunResult(
            model_id=model_id,
            status="success",
            latency_seconds=round(time.monotonic() - started, 3),
            prompt_sha256=prompt_hash,
            arguments=arguments,
            created_at=created_at,
            request_id=request_id if isinstance(request_id, str) else None,
            image_url=image_url,
            image_path=str(image_path),
            metadata_path=str(metadata_path),
        )
        metadata_path.write_text(run_result.to_json())
        return run_result
    except Exception as exc:
        metadata_path = run_dir / "metadata.json"
        run_result = FalRunResult(
            model_id=model_id,
            status="error",
            latency_seconds=round(time.monotonic() - started, 3),
            prompt_sha256=prompt_hash,
            arguments=arguments,
            created_at=created_at,
            metadata_path=str(metadata_path),
            error=str(exc),
        )
        metadata_path.write_text(run_result.to_json())
        return run_result


def run_eval(
    *,
    models: list[str],
    prompt: str,
    config: FalEvalConfig,
) -> list[FalRunResult]:
    """Run the configured model list sequentially and write an aggregate JSONL."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "prompt.txt").write_text(prompt)
    model_ids = expand_model_ids(models)
    results = [
        run_one_model(model_id=model_id, prompt=prompt, config=config) for model_id in model_ids
    ]
    (config.output_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(asdict(result), sort_keys=True) for result in results) + "\n"
    )
    (config.output_dir / "summary.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)
    )
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help="Model aliases or explicit fal model IDs. Defaults to the current finalists.",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help="Prompt text file. Defaults to the hardened short-a worksheet prompt.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("samples/output/fal_image_eval"),
        help="Root output directory for prompt, images, and metadata.",
    )
    parser.add_argument(
        "--image-size",
        default="portrait_4_3",
        help="fal image_size argument. Use portrait_4_3 for the 3:4 sandbox test.",
    )
    parser.add_argument(
        "--extra-arguments",
        default="{}",
        help='JSON object merged into fal arguments, e.g. \'{"output_format":"png"}\'.',
    )
    parser.add_argument("--with-logs", action="store_true", help="Print fal queue logs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not load_fal_env():
        raise SystemExit("FAL_KEY is missing. Add FAL_KEY=... to .env or the shell environment.")

    prompt = args.prompt_file.read_text() if args.prompt_file else DEFAULT_PROMPT
    extra_arguments = _parse_extra_arguments(args.extra_arguments)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir / timestamp
    config = FalEvalConfig(
        output_dir=output_dir,
        image_size=args.image_size,
        extra_arguments=extra_arguments,
        with_logs=args.with_logs,
    )
    results = run_eval(models=args.models, prompt=prompt, config=config)
    for result in results:
        print(
            f"{result.status:7} {result.model_id:42} "
            f"{result.latency_seconds:7.1f}s {result.image_path or result.error}"
        )
    print(f"\nArtifacts: {output_dir}")
    return 0 if all(result.status == "success" for result in results) else 1


def _load_fal_subscribe() -> SubscribeFn:
    try:
        fal_client = importlib.import_module("fal_client")
    except ImportError as exc:
        raise RuntimeError(
            "fal-client is not installed. Run `.venv/bin/pip install -r requirements.txt`."
        ) from exc

    subscribe = getattr(fal_client, "subscribe", None)
    if not callable(subscribe):
        raise RuntimeError("fal_client.subscribe is not available")
    return cast(SubscribeFn, subscribe)


def _queue_logger(update: object) -> None:
    logs = getattr(update, "logs", None)
    if not isinstance(logs, list):
        return
    for log in logs:
        if isinstance(log, Mapping):
            message = log.get("message")
            if isinstance(message, str):
                print(message)


def _parse_extra_arguments(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--extra-arguments must be a JSON object")
    return dict(parsed)


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
