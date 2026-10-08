"""Compare Luna and Haiku on human-labelled saved scenes; no image generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import stage, traced_pipeline
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import (
    AREA_POLICY,
    DECISION_THRESHOLDS,
    DECISIONS_MODEL,
    HAIKU_MODEL,
    SCENE_VERSION,
    _reference,
    judge_scene,
)
from render.replay import FrozenRenderPackage
from render.scene_geometry import meaningful_page_fraction


class SavedCase(BaseModel):
    id: str = Field(min_length=1)
    image: str
    worksheet: int = Field(ge=1)
    human_approved: bool = Field(strict=True)
    package: str | None = None
    expected_failed_checks: list[str] = Field(default_factory=list)
    notes: str = ""


class CaseManifest(BaseModel):
    package: str
    cases: list[SavedCase] = Field(min_length=1)


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {}
    for row in rows:
        model = row["requested_model"]
        counts = metrics.setdefault(
            model,
            {
                "true_accepts": 0,
                "true_rejects": 0,
                "false_accepts": 0,
                "false_rejects": 0,
                "invalid_responses": 0,
                "control_misses": 0,
            },
        )
        if row["gate"] is None:
            counts["invalid_responses"] += 1
        else:
            key = (
                ("true_accepts" if row["approved"] else "false_rejects")
                if row["human_approved"]
                else ("false_accepts" if row["approved"] else "true_rejects")
            )
            counts[key] += 1
            counts["control_misses"] += bool(row.get("expected_check_misses"))
    return metrics


@traced_pipeline
def compare(
    artifacts_dir: str, cases_path: str, *, live: bool = False, repeats: int = 1
) -> dict[str, Any]:
    if not 1 <= repeats <= 3:
        raise ValueError("Repeats must be 1-3; each repeat costs two gate requests per scene")
    source = Path(cases_path)
    manifest = CaseManifest.model_validate_json(source.read_text())
    if len({case.id for case in manifest.cases}) != len(manifest.cases):
        raise ValueError("Case IDs must be unique")
    root = source.parent
    prepared = []
    for case in manifest.cases:
        if any(
            name
            not in {
                "identity_ok",
                "supports_task",
                "action_ok",
                "outfit_ok",
                "child_safe",
                "no_text",
                "no_answers",
            }
            for name in case.expected_failed_checks
        ):
            raise ValueError("Expected failed checks must name SceneGate fields")
        if case.human_approved and case.expected_failed_checks:
            raise ValueError("An approved human label cannot declare blocking failed checks")
        package = FrozenRenderPackage.model_validate_json(
            _path(root, case.package or manifest.package).read_text()
        )
        package.verify()
        if case.worksheet > len(package.worksheets):
            raise ValueError("Case worksheet is outside the frozen package")
        png = _path(root, case.image).read_bytes()
        # Validate inputs and references before admitting any paid request.
        with Image.open(_path(root, case.image)) as image:
            width, height = image.size
            image.verify()
        reference = _reference(package.identity)
        if not reference:
            raise ValueError("Case requires the frozen package's character reference")
        spec = compile_worksheet_design_spec(
            package.worksheets[case.worksheet - 1],
            package.theme,
            package.profile,
            render_mode="hybrid_shell",
        )
        prepared.append((case, package, png, reference, spec, width, height))
    report: dict[str, Any] = {
        "mode": "live_shadow" if live else "dry_run_no_inference",
        "can_approve_worksheet": False,
        "rubric_version": SCENE_VERSION,
        "area_policy": AREA_POLICY,
        "decision_thresholds": DECISION_THRESHOLDS,
        "requested_models": [DECISIONS_MODEL, HAIKU_MODEL],
        "cases": len(prepared),
        "repeats": repeats,
        "planned_gate_requests": len(prepared) * repeats * 2,
        "generates_artwork": False,
        "results": [],
        "completed": False,
    }
    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "scene_gate_comparison.json"
    if output.exists():
        raise ValueError("Use a fresh comparison directory to preserve previous evidence")

    def save() -> None:
        report["metrics"] = _metrics(report["results"])
        output.write_text(json.dumps(report, indent=2))

    if not live:
        save()
        return report
    limits = current_limits()
    if (
        not openrouter.available()
        or limits is None
        or any(value is None for value in (limits.max_usd, limits.max_calls, limits.deadline_s))
        or any(model not in limits.call_ceilings for model in report["requested_models"])
    ):
        raise ValueError(
            "Live comparison requires vault key and verified USD/call/deadline ceilings"
        )
    # Each transport may retry once. Refuse an obviously incomplete comparison
    # before spending, rather than discovering half-way that the allocation cannot fit.
    maximum_attempts = len(prepared) * repeats * 4
    maximum_reservation = (
        len(prepared)
        * repeats
        * 2
        * sum(limits.call_ceilings[model] for model in report["requested_models"])
    )
    if (
        limits.max_calls is None
        or limits.max_calls < maximum_attempts
        or limits.max_usd is None
        or limits.max_usd < maximum_reservation
    ):
        raise ValueError(
            "Comparison allocation cannot cover verified ceilings and one retry per call"
        )
    try:
        for case, package, png, reference, spec, width, height in prepared:
            for repeat in range(1, repeats + 1):
                for backend, model in (("decisions", DECISIONS_MODEL), ("vision", HAIKU_MODEL)):
                    started = time.perf_counter()
                    with stage("scene_gate_shadow"):
                        gate = judge_scene(
                            png, reference, spec, package.theme, backend=backend, model_ids=[model]
                        )
                    geometry_ok = bool(
                        gate
                        and width >= 800
                        and height >= 450
                        and meaningful_page_fraction(width, height, gate.bounds)
                        >= spec.learning_scene_min_area_fraction
                    )
                    report["results"].append(
                        {
                            "case_id": case.id,
                            "repeat": repeat,
                            "image_sha256": hashlib.sha256(png).hexdigest(),
                            "reference_sha256": hashlib.sha256(reference).hexdigest(),
                            "package_hash": package.package_hash,
                            "worksheet": case.worksheet,
                            "human_approved": case.human_approved,
                            "notes": case.notes,
                            "expected_failed_checks": case.expected_failed_checks,
                            "requested_model": model,
                            "backend": backend,
                            "bounds_source": (
                                "local_nonwhite_foreground_extent"
                                if backend == "decisions"
                                else "vision_semantic_extent"
                            ),
                            "elapsed_s": time.perf_counter() - started,
                            "gate": gate.model_dump() if gate else None,
                            "expected_check_misses": [
                                name
                                for name in case.expected_failed_checks
                                if gate is None or getattr(gate, name) is not False
                            ],
                            "geometry_ok": geometry_ok,
                            "approved": bool(gate and gate.approved and geometry_ok),
                        }
                    )
                    save()  # Preserve each paid result before the next admission.
        report["completed"] = True
    finally:
        save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Private human-labelled JSON manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(compare(args.output, args.cases, live=args.live, repeats=args.repeats), indent=2)
    )


if __name__ == "__main__":
    main()
