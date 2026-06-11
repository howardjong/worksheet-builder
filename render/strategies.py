"""Pluggable worksheet render strategies."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, Field

from adapt.schema import AdaptedActivityModel
from render.design_spec import RenderMode, WorksheetDesignSpec
from render.pdf import render_worksheet
from theme.schema import AssetManifest, ThemeConfig


class RenderResult(BaseModel):
    """Result from a worksheet render strategy."""

    renderer_id: str = Field(description="Stable renderer identifier.")
    pdf_path: str | None = Field(default=None, description="Produced PDF path, if any.")
    artifact_paths: list[str] = Field(default_factory=list)
    produces_pdf: bool = Field(description="Whether this render produced a PDF.")
    experimental: bool = Field(description="Whether this render mode is experimental.")


@dataclass(frozen=True)
class RenderContext:
    """Inputs shared by render strategies."""

    design_spec: WorksheetDesignSpec
    adapted: object
    theme: object
    output_path: Path
    artifacts_dir: Path
    avatar_image: str | None = None
    asset_manifest: AssetManifest | None = None
    character_identity: object | None = None
    extra_artifacts: dict[str, str] = field(default_factory=dict)


class RenderStrategy(Protocol):
    """Renderer interface used by transform orchestration."""

    renderer_id: str
    produces_pdf: bool
    experimental: bool

    def render(self, context: RenderContext) -> RenderResult:
        """Render the worksheet from a renderer-neutral context."""


class PdfClassicRenderer:
    """Existing ReportLab PDF renderer wrapped as a strategy."""

    renderer_id = "pdf_classic"
    produces_pdf = True
    experimental = False

    def render(self, context: RenderContext) -> RenderResult:
        _render_pdf(context)
        return RenderResult(
            renderer_id=self.renderer_id,
            pdf_path=str(context.output_path),
            artifact_paths=[str(context.output_path)],
            produces_pdf=self.produces_pdf,
            experimental=self.experimental,
        )


class HybridShellRenderer:
    """Experimental hybrid shell renderer using deterministic PDF text."""

    renderer_id = "hybrid_shell"
    produces_pdf = True
    experimental = True

    def render(self, context: RenderContext) -> RenderResult:
        _render_pdf(context)
        return RenderResult(
            renderer_id=self.renderer_id,
            pdf_path=str(context.output_path),
            artifact_paths=[str(context.output_path)],
            produces_pdf=self.produces_pdf,
            experimental=self.experimental,
        )


class ImagePromptRenderer:
    """Offline full-page image prompt renderer.

    This intentionally does not call an image-generation API. It emits a prompt
    and manifest that can be passed to a provider later or benchmarked offline.
    """

    renderer_id = "image_prompt"
    produces_pdf = False
    experimental = True

    def render(self, context: RenderContext) -> RenderResult:
        context.artifacts_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = context.artifacts_dir / "worksheet_image_prompt.md"
        manifest_path = context.artifacts_dir / "renderer_manifest.json"

        prompt_path.write_text(_build_image_prompt(context.design_spec))
        manifest_path.write_text(
            json.dumps(_build_image_prompt_manifest(context.design_spec), indent=2)
        )

        return RenderResult(
            renderer_id=self.renderer_id,
            pdf_path=None,
            artifact_paths=[str(prompt_path), str(manifest_path)],
            produces_pdf=self.produces_pdf,
            experimental=self.experimental,
        )


def default_render_mode() -> RenderMode:
    """Return the production-safe renderer mode."""

    return "pdf_classic"


def resolve_render_strategy(mode: str | None) -> RenderStrategy:
    """Resolve a render strategy by mode."""

    selected = mode or default_render_mode()
    if selected == "image_gen":
        from render.image_gen import ImageGenRenderer

        return ImageGenRenderer()
    strategies: dict[str, RenderStrategy] = {
        "hybrid_shell": HybridShellRenderer(),
        "image_prompt": ImagePromptRenderer(),
        "pdf_classic": PdfClassicRenderer(),
    }
    strategy = strategies.get(selected)
    if strategy is None:
        known = ", ".join(sorted([*strategies, "image_gen"]))
        raise ValueError(f"Unknown render mode '{selected}'. Expected one of: {known}")
    return strategy


def _render_pdf(context: RenderContext) -> None:
    render_worksheet(
        cast(AdaptedActivityModel, context.adapted),
        cast(ThemeConfig, context.theme),
        str(context.output_path),
        avatar_image=context.avatar_image,
        asset_manifest=context.asset_manifest,
    )


def _build_image_prompt(spec: WorksheetDesignSpec) -> str:
    required_text = "\n".join(f"- {text}" for text in spec.required_text)
    answer_zones = "\n".join(
        (f"- item {zone.item_id} ({zone.response_format}): " f"{zone.prompt_text}")
        for zone in spec.answer_zones
    )
    if not answer_zones:
        answer_zones = "- None required."

    return "\n".join(
        [
            "# OFFLINE PROMPT ONLY",
            "",
            "Create a print-ready children's literacy worksheet image.",
            "Do not add, remove, rewrite, or misspell required text.",
            "Keep all instructional text legible, high contrast, and inside safe margins.",
            "Use a calm themed visual style with limited decorative elements.",
            "",
            "## Worksheet",
            f"Title: {spec.worksheet_title}",
            f"Theme: {spec.theme_name} ({spec.theme_id})",
            f"Skill: {spec.domain} - {spec.specific_skill}",
            f"Page: {spec.page.width_pt}x{spec.page.height_pt}pt, margin {spec.page.margin_pt}pt",
            (
                "Visual budget: "
                f"{spec.visual_budget.intensity} intensity, "
                f"max {spec.visual_budget.max_decorative_elements} decorative elements"
            ),
            "",
            "## Exact Required Text",
            required_text,
            "",
            "## Answer Zones",
            answer_zones,
            "",
            "## Risk Note",
            (
                "This prompt is experimental. Validate generated images with OCR/vision "
                "before using them for instruction."
            ),
        ]
    )


def _build_image_prompt_manifest(spec: WorksheetDesignSpec) -> dict[str, object]:
    return {
        "renderer_id": "image_prompt",
        "provider": "offline_prompt_only",
        "experimental": True,
        "produces_pdf": False,
        "spec_version": spec.spec_version,
        "source_hash": spec.source_hash,
        "skill_model_hash": spec.skill_model_hash,
        "learner_profile_hash": spec.learner_profile_hash,
        "theme_id": spec.theme_id,
        "worksheet_number": spec.worksheet_number,
        "worksheet_count": spec.worksheet_count,
        "required_text_count": len(spec.required_text),
    }
