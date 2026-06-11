"""A/B render battery: run inputs through pdf_classic and image_gen, score both.

Usage:
    python render_battery.py --input samples/input/IMG_0004.JPG \
        --profile profiles/ian.yaml --theme roblox_obby

Writes <output>/<timestamp>/scorecard.md plus per-variant pipeline outputs.
The owner reviews the side-by-side PDFs against the ChatGPT reference at
samples/output/ian-worksheet-geo-dash-1.png to make the promotion decision.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import click
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class BatteryRow(BaseModel):
    """One input's A/B outcome."""

    input_name: str
    classic_all_pass: bool
    image_all_pass: bool
    image_fell_back: bool
    classic_pdf_paths: list[str] = Field(default_factory=list)
    image_pdf_paths: list[str] = Field(default_factory=list)


def build_scorecard(rows: list[BatteryRow]) -> str:
    lines = [
        "# Render battery scorecard",
        "",
        "| input | classic all-pass | image_gen all-pass | fell back |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.input_name} | {row.classic_all_pass} | "
            f"{row.image_all_pass} | {row.image_fell_back} |"
        )
    fallbacks = sum(1 for row in rows if row.image_fell_back)
    lines.append("")
    lines.append(f"image_gen fallbacks: {fallbacks}/{len(rows)}")
    lines.append("")
    lines.append("## PDFs to compare")
    for row in rows:
        lines.append(f"### {row.input_name}")
        for path in row.classic_pdf_paths:
            lines.append(f"- classic: {path}")
        for path in row.image_pdf_paths:
            lines.append(f"- image_gen: {path}")
        if not row.image_pdf_paths:
            lines.append("- image_gen: (fell back / no PDF)")
    lines.append("")
    lines.append("## Review checklist (owner)")
    lines.append("- Compare each image_gen PDF against the classic PDF side by side.")
    lines.append("- Compare against samples/output/ian-worksheet-geo-dash-1.png for richness.")
    lines.append("- Check Buddy likeness, text legibility, and calm-focus rules.")
    return "\n".join(lines)


def _run_variant(
    input_path: Path, profile: str, theme: str, out_dir: Path, render_mode: str
) -> tuple[bool, bool, list[str]]:
    """Run one pipeline variant. Returns (all_pass, fell_back, pdf_paths)."""
    from transform import run_pipeline_collect_artifacts

    artifacts_dir = out_dir / "artifacts"
    run = run_pipeline_collect_artifacts(
        input_path=str(input_path),
        profile_path=profile,
        theme_id=theme,
        output_dir=str(out_dir),
        artifacts_dir=str(artifacts_dir),
        index_results=False,
        render_mode=render_mode,
    )
    all_pass = bool(run.validation_results.get("all_validators_passed", False))
    fell_back = render_mode == "image_gen" and run.renderer_id != "image_gen"
    return all_pass, fell_back, list(run.pdf_paths)


@click.command()
@click.option(
    "--input",
    "input_paths",
    multiple=True,
    required=True,
    help="Worksheet photo path. Repeat for multiple inputs.",
)
@click.option("--profile", "profile_path", required=True)
@click.option("--theme", "theme_id", default="roblox_obby")
@click.option("--output", "output_dir", default="./samples/output/render_battery")
def battery(
    input_paths: tuple[str, ...], profile_path: str, theme_id: str, output_dir: str
) -> None:
    """Run each input through pdf_classic and image_gen; write a scorecard."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    root = Path(output_dir) / stamp
    rows: list[BatteryRow] = []

    for raw_path in input_paths:
        input_path = Path(raw_path)
        name = input_path.name
        logger.info("Battery input: %s", name)

        classic_pass, _, classic_pdfs = _run_variant(
            input_path,
            profile_path,
            theme_id,
            root / f"{input_path.stem}_classic",
            "pdf_classic",
        )
        image_pass, fell_back, image_pdfs = _run_variant(
            input_path,
            profile_path,
            theme_id,
            root / f"{input_path.stem}_image",
            "image_gen",
        )
        rows.append(
            BatteryRow(
                input_name=name,
                classic_all_pass=classic_pass,
                image_all_pass=image_pass,
                image_fell_back=fell_back,
                classic_pdf_paths=classic_pdfs,
                image_pdf_paths=image_pdfs,
            )
        )

    root.mkdir(parents=True, exist_ok=True)
    scorecard_path = root / "scorecard.md"
    scorecard_path.write_text(build_scorecard(rows))
    logger.info("Scorecard: %s", scorecard_path)


if __name__ == "__main__":
    battery()
