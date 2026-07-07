"""Renderer benchmark gates for promoting experimental renderers."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from render.design_spec import WorksheetDesignSpec, intensity_budget_ceiling
from render.strategies import RenderResult


class RendererBenchmarkReport(BaseModel):
    """Promotion-gate report for one renderer output."""

    renderer_id: str = Field(description="Renderer being evaluated.")
    passed: bool = Field(description="Whether all promotion gates passed.")
    gates: dict[str, bool] = Field(description="Individual gate results.")
    blocking_issues: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)


def evaluate_renderer_artifacts(
    design_spec: WorksheetDesignSpec,
    render_result: RenderResult,
) -> RendererBenchmarkReport:
    """Evaluate renderer output against promotion gates."""

    blocking_issues: list[str] = []
    required_text_present, missing_text = _required_text_present(design_spec, render_result)
    if not required_text_present:
        blocking_issues.extend(f"Missing required text: {text}" for text in missing_text)

    answer_zones_present, missing_zone_items = _answer_zones_present(
        design_spec,
        render_result,
    )
    if not answer_zones_present:
        blocking_issues.extend(
            f"Missing answer zone affordance for item {item_id}" for item_id in missing_zone_items
        )

    max_decorations, max_colors = intensity_budget_ceiling(design_spec.visual_budget.intensity)
    visual_budget_respected = (
        design_spec.visual_budget.max_decorative_elements <= max_decorations
        and design_spec.visual_budget.max_colors <= max_colors
    )
    if not visual_budget_respected:
        blocking_issues.append("ADHD visual budget exceeded")

    print_ready_output = (
        render_result.produces_pdf
        and render_result.pdf_path is not None
        and Path(render_result.pdf_path).exists()
    )
    if not print_ready_output:
        blocking_issues.append("Print-ready PDF was not produced")

    gates = {
        "required_text_present": required_text_present,
        "answer_zones_present": answer_zones_present,
        "visual_budget_respected": visual_budget_respected,
        "print_ready_output": print_ready_output,
    }

    return RendererBenchmarkReport(
        renderer_id=render_result.renderer_id,
        passed=all(gates.values()),
        gates=gates,
        blocking_issues=blocking_issues,
        artifact_paths=render_result.artifact_paths,
    )


def _required_text_present(
    design_spec: WorksheetDesignSpec,
    render_result: RenderResult,
) -> tuple[bool, list[str]]:
    if render_result.produces_pdf:
        return True, []

    artifact_text = _combined_artifact_text(render_result.artifact_paths)
    missing = [text for text in design_spec.required_text if text not in artifact_text]
    return not missing, missing


def _answer_zones_present(
    design_spec: WorksheetDesignSpec,
    render_result: RenderResult,
) -> tuple[bool, list[int]]:
    if not design_spec.answer_zones or render_result.produces_pdf:
        return True, []

    artifact_text = _combined_artifact_text(render_result.artifact_paths)
    missing = [
        zone.item_id
        for zone in design_spec.answer_zones
        if zone.prompt_text not in artifact_text
        or zone.response_format not in artifact_text
        or f"item {zone.item_id}" not in artifact_text
    ]
    return not missing, missing


def _combined_artifact_text(paths: list[str]) -> str:
    content: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        content.append(path.read_text())
    return "\n".join(content)
