"""Validate or replay a frozen, approved package. Dry-run by default; live is explicit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import traced_pipeline
from render.concurrency import image_workers, ordered_parallel_map
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import generate_scene
from render.merge import merge_worksheet_package
from render.replay import FrozenRenderPackage
from render.strategies import RenderContext, resolve_render_strategy
from validate.print_checks import validate_print_quality


@traced_pipeline
def replay(
    artifacts_dir: str, manifest_path: str, *, live: bool = False, worksheet: int | None = None
) -> dict[str, object]:
    package = FrozenRenderPackage.model_validate_json(Path(manifest_path).read_text())
    package.verify()
    if worksheet is not None and not 1 <= worksheet <= len(package.worksheets):
        raise ValueError("Worksheet index is outside the approved package")
    selected = [package.worksheets[worksheet - 1]] if worksheet is not None else package.worksheets
    # A changed rubric may invalidate an old package; validate again without a paid judge.
    from transform import _validate_before_artwork

    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    existing = list(directory.glob("render_*"))
    if existing:
        raise ValueError(
            "Use an empty replay directory; artwork cache hits invalidate the comparison"
        )
    _validate_before_artwork(
        package.skill,
        package.worksheets,
        package.profile,
        directory,
        objective_mode=package.coverage_mode == "lesson_objective",
    )
    plan: dict[str, object] = {
        "mode": "live_render_only" if live else "dry_run_no_inference",
        "package_hash": package.package_hash,
        "worksheets": len(package.worksheets),
        "rendered_worksheets": len(selected),
        "workers": image_workers(),
        "image_models": openrouter.models("image"),
        "scene_judge_models": openrouter.stage_models("scene_judge", role="vision"),
        "extracts_or_plans_content": False,
    }
    if not live:
        return plan
    limits = current_limits()
    if (
        not openrouter.available()
        or limits is None
        or any(value is None for value in (limits.max_usd, limits.deadline_s, limits.max_calls))
    ):
        raise ValueError(
            "Live replay requires a vault key, run USD/call/deadline limits and ceilings"
        )
    candidates = openrouter.models("image")
    gate_models = openrouter.stage_models("scene_judge", role="vision")
    if (
        not candidates
        or not gate_models
        or any(model not in limits.call_ceilings for model in [*candidates, *gate_models])
    ):
        raise ValueError(
            "Live replay requires verified ceilings for every configured image/gate model"
        )
    # Never substitute a plain PDF for failed live artwork.
    contexts = [
        RenderContext(
            design_spec=compile_worksheet_design_spec(
                ws, package.theme, package.profile, render_mode="hybrid_shell"
            ),
            adapted=ws,
            theme=package.theme,
            character_identity=package.identity,
            output_path=directory / f"worksheet_{index}.pdf",
            artifacts_dir=directory / f"render_{index}",
        )
        for index, ws in enumerate(selected, 1)
    ]
    scenes = ordered_parallel_map(generate_scene, contexts)
    if not all(scenes):
        raise RuntimeError("Live replay artwork failed; no approved PDF produced")
    pdfs: list[str] = []
    for context, scene in zip(contexts, scenes, strict=True):
        context.extra_artifacts.update(scene_prepared="1", learning_scene=scene or "")
        rendered = resolve_render_strategy("hybrid_shell").render(context)
        if not rendered.pdf_path or not rendered.artwork_approved:
            raise RuntimeError("Replay did not produce an approved illustrated worksheet")
        pdfs.append(rendered.pdf_path)
    output = directory / "replayed-package.pdf"
    merge_worksheet_package(pdfs, str(output), cleanup=True)
    if not validate_print_quality(str(output)).passed:
        output.unlink(missing_ok=True)
        raise RuntimeError("Replayed PDF failed print validation")
    plan.update(pdf_path=str(output), approved=True)
    (directory / "replay_summary.json").write_text(json.dumps(plan, indent=2))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--live", action="store_true", help="Make paid image/gate calls")
    parser.add_argument(
        "--worksheet",
        type=int,
        help="Render just one approved worksheet for a small compatibility trial",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            replay(args.output, args.manifest, live=args.live, worksheet=args.worksheet), indent=2
        )
    )


if __name__ == "__main__":
    main()
