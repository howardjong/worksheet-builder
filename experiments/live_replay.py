"""Validate or replay a frozen, approved package. Dry-run by default; live is explicit."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import traced_pipeline
from render.concurrency import image_workers, ordered_parallel_map
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import _scene_judge_models, generate_scene, load_approved_scene
from render.merge import merge_worksheet_package
from render.replay import FrozenRenderPackage
from render.strategies import RenderContext, resolve_render_strategy
from validate.print_checks import validate_print_quality


@traced_pipeline
def replay(
    artifacts_dir: str,
    manifest_path: str,
    *,
    live: bool = False,
    worksheet: int | None = None,
    reuse_scenes: str | None = None,
) -> dict[str, object]:
    if live and reuse_scenes:
        raise ValueError("Scene reuse is no-inference recomposition, not a live benchmark")
    package = FrozenRenderPackage.model_validate_json(Path(manifest_path).read_text())
    package.verify()
    if worksheet is not None and not 1 <= worksheet <= len(package.worksheets):
        raise ValueError("Worksheet index is outside the approved package")
    selected = [
        (index, ws)
        for index, ws in enumerate(package.worksheets, 1)
        if worksheet is None or index == worksheet
    ]
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
        "mode": (
            "recompose_no_inference"
            if reuse_scenes
            else "live_render_only"
            if live
            else "dry_run_no_inference"
        ),
        "package_hash": package.package_hash,
        "worksheets": len(package.worksheets),
        "rendered_worksheets": len(selected),
        "workers": image_workers(),
        "image_models": openrouter.models("image"),
        "scene_judge_models": _scene_judge_models(),
        "extracts_or_plans_content": False,
    }
    if not live and not reuse_scenes:
        return plan
    limits = current_limits()
    if live and (
        not openrouter.available()
        or limits is None
        or any(value is None for value in (limits.max_usd, limits.deadline_s, limits.max_calls))
    ):
        raise ValueError(
            "Live replay requires a vault key, run USD/call/deadline limits and ceilings"
        )
    candidates = openrouter.models("image")
    gate_models = _scene_judge_models()
    if live and (
        limits is None
        or not candidates
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
        for index, ws in selected
    ]
    if reuse_scenes:
        from dataclasses import replace

        scenes: list[str | None] = []
        provenance: list[dict[str, object]] = []
        for context in contexts:
            source = Path(reuse_scenes) / context.artifacts_dir.name
            cached = load_approved_scene(replace(context, artifacts_dir=source))
            if cached is None:
                raise ValueError("Saved scene is missing, changed, unapproved or incompatible")
            context.artifacts_dir.mkdir(parents=True, exist_ok=True)
            target = context.artifacts_dir / "learning_scene.png"
            shutil.copyfile(cached, target)
            shutil.copyfile(
                source / "learning_scene.json", context.artifacts_dir / "learning_scene.json"
            )
            receipt = json.loads((source / "learning_scene.json").read_text())
            provenance.append(
                {
                    "worksheet": context.design_spec.worksheet_number,
                    "scene_version": receipt["scene_version"],
                    "gate_models": receipt.get("gate_models"),
                    "new_gate_performed": False,
                }
            )
            scenes.append(str(target))
        plan["scene_approval_provenance"] = provenance
        plan["scene_judge_models"] = []  # no model served by this recomposition
    else:
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Make paid image/gate calls")
    mode.add_argument(
        "--reuse-scenes", help="Recompose without inference using saved approved render_* folders"
    )
    parser.add_argument(
        "--worksheet",
        type=int,
        help="Render just one approved worksheet for a small compatibility trial",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            replay(
                args.output,
                args.manifest,
                live=args.live,
                worksheet=args.worksheet,
                reuse_scenes=args.reuse_scenes,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
