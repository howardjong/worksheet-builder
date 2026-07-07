"""A/B adaptation battery — legacy retry/takeover loop vs single-call planner.

Runs each input through both adaptation paths with render mode pdf_classic
and asset generation skipped (adaptation is the variable under test), then
writes <output>/<timestamp>/scorecard.md comparing judge verdicts, sections
per worksheet, content coverage, and outcomes.

Usage (requires API keys; see Session 42 notes re SSL_CERT_FILE on macOS):
    WORKSHEET_LLM_ADAPT=1 .venv/bin/python adapt_battery.py \
        --input samples/input/IMG_0004.JPG \
        --profile profiles/ian.yaml \
        --theme roblox_obby
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

VARIANTS = ("loop", "planner")
_VARIANT_ENV = ("WORKSHEET_PLANNER_V2", "WORKSHEET_SKIP_ASSET_GEN", "WORKSHEET_LLM_ADAPT")


class AdaptBatteryRow(BaseModel):
    """One battery cell: a single input run through one adaptation variant."""

    input_name: str
    variant: str  # "loop" | "planner"
    outcome: str
    judge_approved: bool | None
    judge_score: float | None
    sections_per_worksheet: list[int]
    content_coverage_passed: bool | None
    adhd_compliance_passed: bool | None
    error: str | None = None


_APPROVED_OUTCOMES = {"planned_approved", "planned_regen_approved"}


class GateResult(BaseModel):
    """Promotion-gate verdict for one battery run."""

    passed: bool
    reasons: list[str]


def evaluate_gate(rows: list[AdaptBatteryRow]) -> GateResult:
    """Evaluate the documented planner promotion gate over one run's rows.

    Criteria (all must hold):
      (a) at least two-thirds of planner cells approved, and zero planner errors;
      (b) every planner cell passes the ADHD check (the section-cap hard error
          lives there);
      (c) planner content-coverage >= loop content-coverage.
    """
    planner = [r for r in rows if r.variant == "planner"]
    loop = [r for r in rows if r.variant == "loop"]
    reasons: list[str] = []

    errored = [r for r in planner if r.error or r.outcome == "error"]
    approved = [r for r in planner if r.judge_approved is True and r.outcome in _APPROVED_OUTCOMES]
    # (a) >= 2/3 approved, zero errors
    if errored:
        names = [r.input_name for r in errored]
        reasons.append(f"(a) {len(errored)} planner error cell(s): {names}")
    if not planner or len(approved) * 3 < len(planner) * 2:
        reasons.append(
            f"(a) only {len(approved)}/{len(planner)} planner cells approved (need >= 2/3)"
        )

    # (b) ADHD compliance (encodes the section cap)
    adhd_fail = [r for r in planner if r.adhd_compliance_passed is not True]
    if adhd_fail:
        reasons.append(
            f"(b) {len(adhd_fail)} planner cell(s) fail ADHD/section-cap: "
            f"{[r.input_name for r in adhd_fail]}"
        )

    # (c) coverage >= loop
    planner_cov = sum(1 for r in planner if r.content_coverage_passed)
    loop_cov = sum(1 for r in loop if r.content_coverage_passed)
    if planner_cov < loop_cov:
        reasons.append(f"(c) planner coverage {planner_cov} < loop coverage {loop_cov}")

    return GateResult(passed=not reasons, reasons=reasons)


def gate_over_runs(results: list[GateResult]) -> bool:
    """True iff two consecutive runs both pass the gate."""
    return any(a.passed and b.passed for a, b in zip(results, results[1:], strict=False))


def build_scorecard(rows: list[AdaptBatteryRow]) -> str:
    lines = [
        "# Adaptation battery scorecard",
        "",
        "| input | variant | outcome | judge | score | sections/ws | coverage | adhd |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        judge = {True: "PASS", False: "FAIL", None: "—"}[row.judge_approved]
        score = f"{row.judge_score:.2f}" if row.judge_score is not None else "—"
        sections = "/".join(str(n) for n in row.sections_per_worksheet) or "—"
        coverage = {True: "PASS", False: "FAIL", None: "—"}[row.content_coverage_passed]
        adhd = {True: "PASS", False: "FAIL", None: "—"}[row.adhd_compliance_passed]
        lines.append(
            f"| {row.input_name} | {row.variant} | {row.outcome} | {judge} "
            f"| {score} | {sections} | {coverage} | {adhd} |"
        )
    errors = [row for row in rows if row.error]
    if errors:
        lines.append("")
        lines.append("## Errors")
        for row in errors:
            lines.append(f"- {row.input_name} ({row.variant}): {row.error}")

    gate = evaluate_gate(rows)
    lines.append("")
    lines.append("## Gate")
    lines.append(f"- Result: {'PASS' if gate.passed else 'FAIL'}")
    for reason in gate.reasons:
        lines.append(f"- {reason}")
    lines.append("")
    return "\n".join(lines)


def _collect_row(
    input_name: str,
    variant: str,
    artifacts: Path,
    validation_results: dict[str, bool],
) -> AdaptBatteryRow:
    judge_approved: bool | None = None
    judge_score: float | None = None
    outcome = "unknown"

    judge_json = artifacts / "judge_verdict.json"
    if judge_json.exists():
        verdict = json.loads(judge_json.read_text())
        approved = verdict.get("approved")
        if isinstance(approved, bool):
            judge_approved = approved
        score = verdict.get("overall_score")
        if isinstance(score, int | float):
            judge_score = float(score)
        if isinstance(verdict.get("outcome"), str):
            outcome = str(verdict["outcome"])

    log_path = artifacts / "llm_adaptation_log.jsonl"
    if log_path.exists():
        log_lines = log_path.read_text().splitlines()
        if log_lines:
            outcome = str(json.loads(log_lines[-1]).get("outcome", outcome))

    sections: list[int] = []
    for model_path in sorted(artifacts.glob("adapted_model_*.json")):
        data = json.loads(model_path.read_text())
        sections.append(len(data.get("chunks", [])))

    return AdaptBatteryRow(
        input_name=input_name,
        variant=variant,
        outcome=outcome,
        judge_approved=judge_approved,
        judge_score=judge_score,
        sections_per_worksheet=sections,
        content_coverage_passed=validation_results.get("content_coverage_passed"),
        adhd_compliance_passed=validation_results.get("adhd_compliance_passed"),
    )


def _run_variant(
    input_path: str,
    profile_path: str,
    theme_id: str,
    out_root: Path,
    variant: str,
) -> AdaptBatteryRow:
    from transform import run_pipeline_collect_artifacts

    input_name = Path(input_path).stem
    out_dir = out_root / f"{input_name}_{variant}"
    artifacts = out_dir / "artifacts"

    backup = {key: os.environ.get(key) for key in _VARIANT_ENV}
    os.environ["WORKSHEET_LLM_ADAPT"] = "1"
    os.environ["WORKSHEET_SKIP_ASSET_GEN"] = "1"
    if variant == "planner":
        os.environ["WORKSHEET_PLANNER_V2"] = "1"
    else:
        os.environ.pop("WORKSHEET_PLANNER_V2", None)
    try:
        run = run_pipeline_collect_artifacts(
            input_path=input_path,
            profile_path=profile_path,
            theme_id=theme_id,
            output_dir=str(out_dir),
            artifacts_dir=str(artifacts),
            index_results=False,
            render_mode="pdf_classic",
        )
    except Exception as exc:  # battery must keep going past a failed cell
        logger.exception("Battery cell failed: %s %s", input_name, variant)
        return AdaptBatteryRow(
            input_name=input_name,
            variant=variant,
            outcome="error",
            judge_approved=None,
            judge_score=None,
            sections_per_worksheet=[],
            content_coverage_passed=None,
            adhd_compliance_passed=None,
            error=str(exc),
        )
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    flags = {key: value for key, value in run.validation_results.items() if isinstance(value, bool)}
    return _collect_row(input_name, variant, artifacts, flags)


def _run_once(
    inputs: list[str],
    profile_path: str,
    theme_id: str,
    output_dir: str,
) -> tuple[Path, GateResult]:
    """Run every input through both variants once; write the scorecard."""
    root = Path(output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)

    rows: list[AdaptBatteryRow] = []
    for input_path in inputs:
        for variant in VARIANTS:
            logger.info("Battery cell: %s × %s", Path(input_path).stem, variant)
            rows.append(_run_variant(input_path, profile_path, theme_id, root, variant))

    scorecard_path = root / "scorecard.md"
    scorecard_path.write_text(build_scorecard(rows))
    (root / "scorecard.json").write_text(json.dumps([row.model_dump() for row in rows], indent=2))
    gate = evaluate_gate(rows)
    logger.info("Scorecard: %s — gate %s", scorecard_path, "PASS" if gate.passed else "FAIL")
    return scorecard_path, gate


def battery(
    inputs: list[str],
    profile_path: str,
    theme_id: str,
    output_dir: str,
    runs: int = 1,
) -> bool:
    """Run the battery ``runs`` times; return whether the promotion gate passed.

    ``runs == 1`` passes iff that single run passes. ``runs >= 2`` passes only
    on two consecutive passing runs (set ``WORKSHEET_EXTRACTION_CACHE`` so every
    run consumes the same frozen extraction).
    """
    runs = max(1, runs)
    gates: list[GateResult] = []
    for i in range(runs):
        if runs > 1:
            logger.info("=== Battery run %d/%d ===", i + 1, runs)
        _, gate = _run_once(inputs, profile_path, theme_id, output_dir)
        gates.append(gate)

    passed = gate_over_runs(gates) if runs > 1 else gates[0].passed
    logger.info("Gate over %d run(s): %s", len(gates), "PASS" if passed else "FAIL")
    return passed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, dest="inputs")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--theme", default="default")
    parser.add_argument("--output", default="samples/output/adapt_battery")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Battery runs; >= 2 requires two consecutive passing runs for the gate.",
    )
    args = parser.parse_args()
    battery(args.inputs, args.profile, args.theme, args.output, args.runs)


if __name__ == "__main__":
    main()
