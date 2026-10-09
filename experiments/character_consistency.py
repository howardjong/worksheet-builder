"""Factorial character-consistency experiment: prompt x reference pack.

2x2 design (prompt: current/structured x references: original/original+crop),
balanced across procedures and repetitions, interleaved with a saved seed.
Dry-run by default; ``--live`` requires vault key, run limits and verified
ceilings. No automatic generation retries or provider fallback during the
screen; every repetition generates a fresh image. Gate always judges against
the immutable original reference, never a generator-side crop or anchor.
"""

from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ai import openrouter
from ai.run_limits import current_limits
from ai.telemetry import stage, traced_pipeline
from render.design_spec import compile_worksheet_design_spec
from render.live_scene import (
    DECISION_THRESHOLDS,
    SCENE_VERSION,
    derive_face_crop,
    generation_reference_pack,
    judge_reference,
    judge_scene,
    scene_action,
    scene_prompt,
)
from render.replay import FrozenRenderPackage
from theme.schema import ThemeConfig

IMAGE_MODEL = "openai/gpt-image-2.5-sunburst"
GATE_MODEL = "openai/gpt-6-luna-decisions"
SCHEDULE_SEED = 20261009
CONCURRENCY = 3

IDENTITY_DESCRIPTOR = (
    "rainbow spiky hair sweeping up (red, orange, yellow, green, blue, purple), "
    "blocky rounded tan face, simple black dot eyes, small curved smile, "
    "compact blocky body with short limbs"
)


def structured_scene_prompt(
    action_text: str,
    props_text: str,
    num_references: int,
    procedure: str,
) -> str:
    """Experiment-only structured prompt (arms B/D). Not production.

    Separates identity, costume, one action, props, sparse composition and
    exclusions per the research template. Reference roles are rendered only
    for images actually supplied.
    """
    ref_roles = (
        "Image 1 is the original customized character. It is the identity authority "
        "for face, hair, skin markings, and body proportions. Ignore its casual clothing."
    )
    if num_references > 1:
        ref_roles += (
            " Image 2 is a crop of the original face and hairstyle. It provides "
            "additional identity detail and does not introduce another character."
        )
    ref_roles += " All images depict the same character; show that character once."
    if procedure == "word_building":
        action_block = (
            "Show a shallow horizontal track with exactly three outlined tile slots. "
            "The middle and right slots each hold one blank ivory square tile. "
            "The left slot is empty. One matching tile sits just outside the left end "
            "of the track. The buddy's fingertip visibly contacts that moving tile and "
            "pushes it toward the empty slot. Exactly three solid tiles exist in the "
            "whole image: two stationary and one moving. Do not draw a duplicate or "
            "motion ghost. One simple arrow beside the moving tile points into the "
            "empty slot; keep its path clear of the hand, tiles, and face."
        )
    else:
        action_block = (
            "Show three blank ivory square cards in a row on a plain surface. "
            "The buddy holds a pencil poised above the middle card without touching, "
            "circling, or marking any card. The posture reads as considering which "
            "card to choose. Exactly three cards exist in the whole image."
        )
    return f"""DELIVERABLE
One text-free worksheet illustration for children ages 5 to 8.
Show one learning buddy performing one clear action: {action_text}.

REFERENCE ROLES
{ref_roles}

IDENTITY - PRESERVE
Preserve the original character's face shape, eye design and spacing, mouth
design, hairline, hairstyle silhouette, skin colors, distinctive markings, age,
and recognizable head/body/limb proportions. {IDENTITY_DESCRIPTOR}.
Preserve the canonical cartoon illustration style. Do not redesign or age the buddy.

ALLOWED CHANGES
Change the pose, gaze, hand positions, and expression only as needed for the
action. Dress the buddy in a close-fitting spacesuit that preserves recognizable
proportions. Keep the face and identity-defining hair unobstructed; no closed
helmet, opaque visor, or bulky padding.

ACTION AND OBJECT STATE
{action_block}
Required props: {props_text}.

COMPOSITION
Show the recognizable face, both hands, and the complete action clearly. Use a
plain work surface. Character and action dominate the useful image area. Do not
place decorative objects over the face, hands, or destination. Background: pale
and sparse, with at most two small distant space motifs near the edges.

HARD CONSTRAINTS
One character. No extra hands, fingers, tiles, cards, or tracks. No words,
letters, numbers, logos, watermarks, captions, pseudo-text, speech bubbles,
signage, or decorative control-panel markings anywhere. Every tile and card is
completely blank: matte ivory, simple outline, no printing or color coding.
"""


class TrialSpec(BaseModel):
    trial_id: str
    arm: str = Field(pattern="^[ABCD]$")
    procedure: str
    worksheet: int = Field(ge=1)
    repeat: int = Field(ge=1)
    prompt_version: str
    reference_roles: list[str]


class ExperimentManifest(BaseModel):
    package: str
    face_crop_rect: list[float] = Field(min_length=4, max_length=4)
    procedures: dict[str, int]
    repeats: int = Field(ge=1, le=4, default=2)
    arms: list[str] = Field(default_factory=lambda: ["A", "B", "C", "D"])
    trials: list[TrialSpec] = Field(default_factory=list)


def build_trials(manifest: ExperimentManifest) -> list[TrialSpec]:
    trials: list[TrialSpec] = []
    for arm in manifest.arms:
        for procedure in manifest.procedures:
            for repeat in range(1, manifest.repeats + 1):
                prompt_version = "current" if arm in ("A", "C") else "structured"
                reference_roles = (
                    ["original_full_body", "original_face_crop"]
                    if arm in ("C", "D")
                    else ["original_full_body"]
                )
                trials.append(
                    TrialSpec(
                        trial_id=f"{arm}_{procedure}_r{repeat}",
                        arm=arm,
                        procedure=procedure,
                        worksheet=manifest.procedures[procedure],
                        repeat=repeat,
                        prompt_version=prompt_version,
                        reference_roles=reference_roles,
                    )
                )
    return trials


def _prompt_for(
    trial: TrialSpec, spec: Any, theme: ThemeConfig, identity: Any
) -> str:
    if trial.prompt_version == "current":
        return scene_prompt(spec, theme, identity)
    action = scene_action(spec, theme)
    return structured_scene_prompt(
        action.action, action.props, len(trial.reference_roles), trial.procedure
    )


@traced_pipeline
def run_experiment(
    artifacts_dir: str, manifest_path: str, *, live: bool = False
) -> dict[str, Any]:
    root = Path(manifest_path).parent
    manifest = ExperimentManifest.model_validate_json(Path(manifest_path).read_text())
    package = FrozenRenderPackage.model_validate_json(
        (root / manifest.package).read_text()
        if not Path(manifest.package).is_absolute()
        else Path(manifest.package).read_text()
    )
    package.verify()
    for procedure, worksheet in manifest.procedures.items():
        if worksheet > len(package.worksheets):
            raise ValueError(f"Procedure {procedure} worksheet out of range")
    original = judge_reference(package.identity)
    if not original:
        raise ValueError("Frozen package has no resolvable original reference")
    crop_png, crop_prov = derive_face_crop(original, tuple(manifest.face_crop_rect))  # type: ignore[arg-type]
    trials = manifest.trials or build_trials(manifest)
    if len({t.trial_id for t in trials}) != len(trials):
        raise ValueError("Trial IDs must be unique")

    directory = Path(artifacts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / "experiment_report.json"
    results_path = directory / "trials.jsonl"
    if report_path.exists():
        raise ValueError("Use a fresh artifacts directory to preserve prior evidence")

    # Snapshot every prompt before any inference.
    theme = ThemeConfig.model_validate(package.theme)
    prompts: dict[str, str] = {}
    for trial in trials:
        spec = compile_worksheet_design_spec(
            package.worksheets[trial.worksheet - 1],
            package.theme,
            package.profile,
            render_mode="hybrid_shell",
        )
        prompts[trial.trial_id] = _prompt_for(trial, spec, theme, package.identity)
    (directory / "prompts.json").write_text(json.dumps(prompts, indent=1))
    (directory / "face_crop_provenance.json").write_text(json.dumps(crop_prov, indent=1))
    Path(directory / "face_crop.png").write_bytes(crop_png)

    planned_image_calls = len(trials)
    planned_gate_calls = len(trials)
    report: dict[str, Any] = {
        "mode": "live" if live else "dry_run_no_inference",
        "can_approve_worksheet": False,
        "rubric_version": SCENE_VERSION,
        "decision_thresholds": DECISION_THRESHOLDS,
        "image_model": IMAGE_MODEL,
        "gate_model": GATE_MODEL,
        "schedule_seed": SCHEDULE_SEED,
        "concurrency": CONCURRENCY,
        "original_reference_sha256": hashlib.sha256(original).hexdigest(),
        "package_hash": package.package_hash,
        "trials_planned": len(trials),
        "planned_image_calls": planned_image_calls,
        "planned_gate_calls": planned_gate_calls,
        "completed": False,
    }
    report_path.write_text(json.dumps(report, indent=1))

    if not live:
        return report

    limits = current_limits()
    required_models = [IMAGE_MODEL, GATE_MODEL]
    if (
        not openrouter.available()
        or limits is None
        or any(v is None for v in (limits.max_usd, limits.max_calls, limits.deadline_s))
        or any(m not in limits.call_ceilings for m in required_models)
    ):
        raise ValueError("Live run requires vault key and verified USD/call/deadline ceilings")
    # One image + one gate per trial; each transport may retry once.
    max_attempts = len(trials) * 4
    max_reservation = len(trials) * 2 * sum(limits.call_ceilings[m] for m in required_models)
    if limits.max_calls < max_attempts or limits.max_usd < max_reservation:  # type: ignore[operator]
        raise ValueError("Allocation cannot cover verified ceilings and one retry per call")

    done_ids: set[str] = set()
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["trial_id"])
    pending = [t for t in trials if t.trial_id not in done_ids]
    rng = random.Random(SCHEDULE_SEED)
    rng.shuffle(pending)

    def run_trial(trial: TrialSpec) -> dict[str, Any]:
        spec = compile_worksheet_design_spec(
            package.worksheets[trial.worksheet - 1],
            package.theme,
            package.profile,
            render_mode="hybrid_shell",
        )
        prompt = prompts[trial.trial_id]
        refs = generation_reference_pack(
            package.identity,
            extra=(crop_png,) if "original_face_crop" in trial.reference_roles else (),
        )
        record: dict[str, Any] = {
            "trial_id": trial.trial_id,
            "arm": trial.arm,
            "procedure": trial.procedure,
            "repeat": trial.repeat,
            "prompt_version": trial.prompt_version,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "reference_roles": trial.reference_roles,
            "reference_hashes": [hashlib.sha256(r).hexdigest() for r in refs],
            "judge_reference_sha256": hashlib.sha256(original).hexdigest(),
            "requested_model": IMAGE_MODEL,
            "quality": "auto",
            "background": "opaque",
        }
        gen_start = time.perf_counter()
        with stage("experiment_image"):
            png = openrouter.generate_image(
                prompt,
                reference_pngs=refs,
                model=IMAGE_MODEL,
                aspect_ratio="16:9",
                quality="auto",
                background="opaque",
                allow_provider_fallback=False,
            )
        record["gen_elapsed_s"] = round(time.perf_counter() - gen_start, 1)
        if not png:
            record["outcome"] = "generation_failed"
            return record
        record["candidate_sha256"] = hashlib.sha256(png).hexdigest()
        (directory / f"{trial.trial_id}.png").write_bytes(png)
        gate_start = time.perf_counter()
        with stage("experiment_gate"):
            gate = judge_scene(png, original, spec, theme)
        record["gate_elapsed_s"] = round(time.perf_counter() - gate_start, 1)
        record["gate"] = gate.model_dump() if gate else None
        record["approved"] = bool(gate and gate.approved)
        record["outcome"] = "approved" if record["approved"] else "gate_rejected"
        return record

    try:
        # ContextVars (telemetry recorder, run limits) do not cross thread
        # boundaries on their own; without explicit propagation, worker
        # threads would bypass cost recording and budget enforcement.
        # Copy the current context once per submission so every trial
        # records and settles against the same limits.
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {
                pool.submit(contextvars.copy_context().run, run_trial, t): t
                for t in pending
            }
            for future in as_completed(futures):
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001 - preserve partial evidence
                    trial = futures[future]
                    record = {"trial_id": trial.trial_id, "outcome": "error",
                              "error": f"{type(exc).__name__}: {exc}"[:300]}
                with results_path.open("a") as handle:
                    handle.write(json.dumps(record) + "\n")
        report["completed"] = True
    finally:
        report_path.write_text(json.dumps(report, indent=1))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.output, args.manifest, live=args.live), indent=1))


if __name__ == "__main__":
    main()
