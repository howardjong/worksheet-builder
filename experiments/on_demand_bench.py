"""Offline layout/concurrency benchmark. Synthetic artwork; never live inference.

Run: python -m experiments.on_demand_bench --output /tmp/worksheet-bench
The simulated network delay demonstrates overlap, not provider performance.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

from adapt.engine import adapt_lesson
from adapt.schema import AdaptationCapabilities
from ai.telemetry import traced_pipeline
from companion.schema import LearnerProfile
from render.concurrency import ordered_parallel_map
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import SceneGate, generate_scene
from render.merge import merge_worksheet_package
from render.strategies import RenderContext, resolve_render_strategy
from skill.lesson_loader import skill_model_from_lesson
from theme.engine import load_theme
from validate.print_checks import validate_print_quality


@traced_pipeline
def benchmark(artifacts_dir: str, lesson: int, workers: int, delay_s: float) -> dict[str, object]:
    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    profile = LearnerProfile(name="Synthetic benchmark", grade_level="2")
    theme = load_theme("space")
    image = io.BytesIO()
    Image.new("RGB", (1024, 576), "#DBEAFE").save(image, format="PNG")
    calls = 0
    lock = threading.Lock()
    # This is deliberately a synthetic blank scene: no visual quality claim.
    gate = SceneGate(
        identity_ok=True,
        supports_task=True,
        action_ok=True,
        outfit_ok=True,
        child_safe=True,
        no_text=True,
        no_answers=True,
        bounds=(0.02, 0.02, 0.98, 0.98),
    )

    def synthetic_art(*args: object, **kwargs: object) -> bytes:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(delay_s)
        return image.getvalue()

    with (
        patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "offline-surrogate",
                "WORKSHEET_LLM_ADAPT": "0",
                "WORKSHEET_IMAGE_CONCURRENCY": str(workers),
                "WORKSHEET_MAX_WORKSHEETS": "auto",
                "WORKSHEET_OPENROUTER_IMAGE_MODELS": "synthetic",
                "WORKSHEET_SKIP_ASSET_GEN": "0",
            },
        ),
        patch("ai.openrouter.generate_image", synthetic_art),
        patch("render.live_scene.judge_scene", lambda *args: gate),
    ):
        worksheets = adapt_lesson(
            skill_model_from_lesson(lesson),
            profile,
            theme_id="space",
            capabilities=AdaptationCapabilities(picture_assets_guaranteed=False),
        )
        contexts = [
            RenderContext(
                design_spec=compile_worksheet_design_spec(
                    ws, theme, profile, render_mode="hybrid_shell"
                ),
                adapted=ws,
                theme=theme,
                output_path=directory / f"worksheet-{index}.pdf",
                artifacts_dir=directory / f"render_{index}",
            )
            for index, ws in enumerate(worksheets, 1)
        ]
        scenes = ordered_parallel_map(generate_scene, contexts)
        paths: list[str] = []
        for context, scene in zip(contexts, scenes, strict=True):
            context.extra_artifacts.update(scene_prepared="1", learning_scene=scene or "")
            result = resolve_render_strategy("hybrid_shell").render(context)
            assert result.pdf_path and result.artwork_approved
            paths.append(result.pdf_path)
        merged = directory / "synthetic-layout.pdf"
        merge_worksheet_package(paths, str(merged), cleanup=True)
        assert validate_print_quality(str(merged)).passed
        with fitz.open(merged) as pdf:
            pages = len(pdf)
    return {
        "mode": "offline_mock_artwork",
        "lesson": lesson,
        "workers": workers,
        "worksheets": len(worksheets),
        "pages": pages,
        "synthetic_image_calls": calls,
        "simulated_delay_s_per_image": delay_s,
        "elapsed_s": time.perf_counter() - started,
        "live_latency_measured": False,
        "visual_quality_measured": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--lessons", type=int, nargs="+", default=[31, 49, 74, 90, 100])
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()
    if args.delay < 0 or args.delay > 5:
        parser.error("simulated delay must be between 0 and 5 seconds")

    # Ban transport even if a caller's shell has a real key.
    def offline_only(*args: object, **kwargs: object) -> None:
        raise AssertionError("Offline benchmark attempted live HTTP")

    with tempfile.TemporaryDirectory(prefix="worksheet-bench-") as temporary:
        root = args.output or Path(temporary)
        root.mkdir(parents=True, exist_ok=True)
        with patch("httpx.Client.post", offline_only), patch("httpx.post", offline_only):
            rows = [
                benchmark(
                    str(root / f"lesson-{lesson}-workers-{workers}"), lesson, workers, args.delay
                )
                for lesson in args.lessons
                for workers in [1, 3]
            ]
        report = root / "offline-results.json"
        report.write_text(json.dumps(rows, indent=2))
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
