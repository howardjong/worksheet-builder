"""Replay two saved scene prompts/reference packs to measure image request wall time.

Expected tradeoff: GPT Image 2.5 Flare targets faster generation; Sunburst targets
precise editing/detail. Lower quality may reduce latency and detail/likeness.
Neither is a measured improvement for this buddy. Compare PNGs visually against
all three references; two scenes cannot establish a pass rate or p95 latency.
Guidance: https://developers.openai.com/api/docs/guides/image-prompting

Dry run (default, no inference):
    python -m experiments.image_speed_bench --cases /private/cases.json \
        --output /private/bench-dry

Manifest (paths relative to the manifest, exactly two scenes):
    {"scenes": [
      {"id": "building", "prompt": "building/scene_prompt.txt", "references": [
        {"role": "original_identity", "path": "original.png"},
        {"role": "expression_detail", "path": "happy-open-smile.png"},
        {"role": "theme_costume", "path": "astronaut.png"}]},
      {"id": "choosing", "prompt": "choosing/scene_prompt.txt", "references": [
        {"role": "original_identity", "path": "original.png"},
        {"role": "expression_detail", "path": "thinking.png"},
        {"role": "theme_costume", "path": "astronaut.png"}]}]}

Paid runs require BOTH --live and WORKSHEET_IMAGE_SPEED_BENCH_LIVE=1, plus a
separately authorized OpenRouter key and verified run USD/call/deadline ceilings.
Select models with WORKSHEET_OPENROUTER_IMAGE_MODELS (e.g. Sunburst,Flare full
OpenRouter IDs); quality with WORKSHEET_IMAGE_QUALITY (default auto). All configured
models run on each scene, sequentially, reversing model order on alternate blocks.
Use separate fresh directories for quality comparisons, with identical inputs.
No image cache, judge calls, quality retries, provider fallback or worksheet
approval. Transport can retry once: elapsed_s includes retries, backoff, reference
upload and PNG normalization; inference_calls.jsonl records HTTP/served-model
telemetry. Each result and failed attempt is saved before proceeding. Private
prompts, references and images belong in ignored artifacts, never in git.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import candidate, stage, traced_pipeline


class SavedReference(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["original_identity", "expression_detail", "theme_costume"]
    path: str = Field(min_length=1)


class SavedScene(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    references: list[SavedReference] = Field(min_length=3, max_length=3)

    @field_validator("references")
    @classmethod
    def ordered_roles(cls, refs: list[SavedReference]) -> list[SavedReference]:
        if [ref.role for ref in refs] != [
            "original_identity",
            "expression_detail",
            "theme_costume",
        ]:
            raise ValueError("References must be original identity, expression, then costume")
        return refs


class BenchManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    scenes: list[SavedScene] = Field(min_length=2, max_length=2)

    @field_validator("scenes")
    @classmethod
    def unique_ids(cls, scenes: list[SavedScene]) -> list[SavedScene]:
        if scenes[0].id == scenes[1].id:
            raise ValueError("Scene IDs must be unique")
        return scenes


def benchmark(
    artifacts_dir: str, cases_path: str, *, live: bool = False, repeats: int = 1
) -> dict[str, Any]:
    """Default offline preflight; paid mode needs an independent explicit opt-in."""
    if Path(artifacts_dir).exists():
        raise ValueError("Use a fresh output directory to preserve previous evidence")
    if not 1 <= repeats <= 3:
        raise ValueError("Repeats must be 1-3")
    if live and os.environ.get("WORKSHEET_IMAGE_SPEED_BENCH_LIVE") != "1":
        raise ValueError("Live benchmark requires WORKSHEET_IMAGE_SPEED_BENCH_LIVE=1")
    source = Path(cases_path)
    manifest = BenchManifest.model_validate_json(source.read_text())
    prepared: list[tuple[SavedScene, str, list[bytes]]] = []
    for scene in manifest.scenes:
        prompt = (source.parent / scene.prompt).read_text()
        if not prompt.strip():
            raise ValueError("Scene prompt must not be empty")
        refs = [(source.parent / ref.path).read_bytes() for ref in scene.references]
        for raw in refs:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
        prepared.append((scene, prompt, refs))
    return _run(artifacts_dir, prepared, live=live, repeats=repeats)


@traced_pipeline
def _run(
    artifacts_dir: str,
    prepared: list[tuple[SavedScene, str, list[bytes]]],
    *,
    live: bool,
    repeats: int,
) -> dict[str, Any]:
    models = openrouter.models("image")
    quality = openrouter.image_quality()
    if not models:
        raise ValueError("Configure at least one image model")
    requests = len(prepared) * repeats * len(models)
    if live:
        limits = current_limits()
        if (
            not openrouter.available()
            or os.environ.get("WORKSHEET_SKIP_ASSET_GEN") == "1"
            or limits is None
            or limits.max_usd is None
            or limits.max_calls is None
            or limits.deadline_s is None
            or any(model not in limits.call_ceilings for model in models)
        ):
            raise ValueError(
                "Live benchmark requires a key and verified USD/call/deadline ceilings"
            )
        reservation = len(prepared) * repeats * 2 * sum(limits.call_ceilings[m] for m in models)
        if limits.max_calls < requests * 2 or limits.max_usd < reservation:
            raise ValueError("Allocation cannot cover verified ceilings and one retry per call")
    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "mode": "live_benchmark" if live else "dry_run_no_inference",
        "can_approve_worksheet": False,
        "requested_models": models,
        "quality": quality,
        "aspect_ratio": "16:9",
        "background": "opaque",
        "allow_provider_fallback": False,
        "planned_image_requests": requests,
        "maximum_http_attempts": requests * 2,
        "inputs": [],
        "results": [],
        "completed": False,
    }
    for index, (scene, prompt, refs) in enumerate(prepared, 1):
        prompt_path = f"scene_{index}_prompt.txt"
        (directory / prompt_path).write_text(prompt)
        ref_paths = [f"scene_{index}_reference_{n}.png" for n in range(1, 4)]
        for name, raw in zip(ref_paths, refs, strict=True):
            # Keep original bytes; the suffix does not affect MIME sniffing.
            (directory / name).write_bytes(raw)
        report["inputs"].append(
            {
                "scene_id": scene.id,
                "prompt_path": prompt_path,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "reference_roles": [ref.role for ref in scene.references],
                "reference_paths": ref_paths,
                "reference_hashes": [hashlib.sha256(raw).hexdigest() for raw in refs],
            }
        )

    def save() -> None:
        (directory / "image_speed_bench.json").write_text(json.dumps(report, indent=2))

    save()
    if not live:
        return report
    try:
        for repeat in range(1, repeats + 1):
            for index, (scene, prompt, refs) in enumerate(prepared, 1):
                ordered = models if (repeat + index) % 2 == 0 else list(reversed(models))
                for model in ordered:
                    trial = f"trial_{len(report['results']) + 1}"
                    row: dict[str, Any] = {
                        "trial_id": trial,
                        "scene_id": scene.id,
                        "repeat": repeat,
                        "requested_model": model,
                        "outcome": "failed",
                    }
                    started = time.perf_counter()
                    try:
                        with candidate(trial), stage("image_speed_bench"):
                            png = openrouter.generate_image(
                                prompt,
                                reference_pngs=refs,
                                model=model,
                                aspect_ratio="16:9",
                                quality=quality,
                                background="opaque",
                                allow_provider_fallback=False,
                            )
                        if png:
                            (directory / f"{trial}.png").write_bytes(png)
                            row.update(
                                outcome="generated_unreviewed",
                                image_path=f"{trial}.png",
                                sha256=hashlib.sha256(png).hexdigest(),
                            )
                    except Exception as exc:
                        row["error_type"] = type(exc).__name__  # No private provider error bodies.
                        raise
                    finally:
                        row["elapsed_s"] = time.perf_counter() - started
                        report["results"].append(row)
                        save()
        report["completed"] = True
    finally:
        save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Private two-scene manifest")
    parser.add_argument("--output", required=True, help="Fresh private output directory")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    report = benchmark(args.output, args.cases, live=args.live, repeats=args.repeats)
    print(json.dumps(report, indent=2))
    if args.live and any(row["outcome"] == "failed" for row in report["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
