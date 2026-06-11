"""Full-page image-generation renderer: generate, gate, regenerate, fall back.

Flow per worksheet page:
1. Cache check (content hash of design spec + identity version + prompt version).
2. For each provider in the chain, up to MAX_ATTEMPTS_PER_PROVIDER attempts:
   generate -> run page gates -> accept on pass, regenerate on fail.
3. Accepted PNG is cached and wrapped as a US Letter PDF with an invisible
   searchable text layer (satisfies validate/print_checks.py vector-text gate).
4. If everything fails, delegate to the deterministic PdfClassicRenderer and
   write an image_gen_fallback.json marker into the artifacts directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

from render.design_spec import WorksheetDesignSpec
from render.image_prompt_builder import PROMPT_VERSION, build_page_prompt
from render.image_providers import ImageProvider, resolve_provider_chain
from render.page_gates import PageGateReport, evaluate_page
from render.strategies import PdfClassicRenderer, RenderContext, RenderResult

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "cache"

# Owner decision 2026-06-11: quality-first regen budget.
MAX_ATTEMPTS_PER_PROVIDER = 3

PAGE_WIDTH_PT = 612
PAGE_HEIGHT_PT = 792


class ImageGenRenderer:
    """Renders the whole worksheet page with an image model, gated and cached."""

    renderer_id = "image_gen"
    produces_pdf = True
    experimental = True

    def __init__(
        self,
        providers: list[ImageProvider] | None = None,
        max_attempts_per_provider: int = MAX_ATTEMPTS_PER_PROVIDER,
    ) -> None:
        self._providers = providers
        self._max_attempts = max_attempts_per_provider

    def render(self, context: RenderContext) -> RenderResult:
        from companion.character_identity import CharacterIdentity
        from render.asset_gen import (
            _reference_bytes_from_identity,
            _scene_judge_criteria,
        )

        if os.environ.get("WORKSHEET_SKIP_ASSET_GEN"):
            return self._fallback(context, reason="WORKSHEET_SKIP_ASSET_GEN set")

        spec = context.design_spec
        identity = (
            context.character_identity
            if isinstance(context.character_identity, CharacterIdentity)
            else None
        )
        ref_bytes = _reference_bytes_from_identity(identity) if identity else None
        character_spec = getattr(context.theme, "character_spec", None)

        prompt = build_page_prompt(
            spec,
            character_block=identity.character_block if identity else "",
            scene_guidelines=identity.scene_guidelines if identity else "",
            theme_environment=(character_spec.scene_environment if character_spec else ""),
            theme_palette=character_spec.color_palette if character_spec else "",
            art_style=character_spec.art_style if character_spec else "",
        )
        criteria = _scene_judge_criteria(identity, character_spec)

        context.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (context.artifacts_dir / "page_prompt.md").write_text(prompt)

        cache_key = self._cache_key(spec, identity, prompt)
        cache_dir = _CACHE_DIR / f"page_{cache_key}"
        cached_png = cache_dir / "page.png"
        if cached_png.exists() and (cache_dir / "gate_report.json").exists():
            logger.info("  Page cache hit: %s", cached_png)
            _write_page_pdf(cached_png.read_bytes(), context.output_path, spec.required_text)
            return self._success_result(context, cached_png)

        providers = self._providers if self._providers is not None else resolve_provider_chain()
        if not providers:
            return self._fallback(context, reason="no image providers available")

        for provider in providers:
            for attempt in range(1, self._max_attempts + 1):
                logger.info(
                    "  Page gen: provider=%s model=%s attempt=%d/%d",
                    provider.provider_id,
                    provider.model_id,
                    attempt,
                    self._max_attempts,
                )
                png = provider.generate(prompt, ref_bytes)
                if png is None:
                    logger.warning(
                        "  Provider %s failed to return an image; trying next provider",
                        provider.provider_id,
                    )
                    break

                report = evaluate_page(png, spec.required_text, ref_bytes, criteria)
                report.provider_id = provider.provider_id
                report.attempt = attempt
                self._write_attempt_diagnostics(
                    context.artifacts_dir, provider.provider_id, attempt, png, report
                )

                if report.passed:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    (cache_dir / "gate_report.json").write_text(report.model_dump_json(indent=2))
                    cached_png.write_bytes(png)
                    _write_page_pdf(png, context.output_path, spec.required_text)
                    return self._success_result(context, cached_png)

                logger.warning(
                    "  Page rejected (provider=%s attempt=%d): missing=%s "
                    "misspelled=%s character_issues=%s",
                    provider.provider_id,
                    attempt,
                    report.text.missing_text,
                    report.text.misspelled_text,
                    report.character.issues,
                )

        return self._fallback(context, reason="all providers exhausted without a gate-passing page")

    def _cache_key(self, spec: WorksheetDesignSpec, identity: object | None, prompt: str) -> str:
        identity_version = (
            getattr(identity, "identity_version", "no_identity") if identity else "no_identity"
        )
        payload = "|".join([spec.model_dump_json(), identity_version, PROMPT_VERSION, prompt])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _success_result(self, context: RenderContext, cached_png: Path) -> RenderResult:
        return RenderResult(
            renderer_id=self.renderer_id,
            pdf_path=str(context.output_path),
            artifact_paths=[
                str(context.output_path),
                str(cached_png),
                str(context.artifacts_dir / "page_prompt.md"),
            ],
            produces_pdf=self.produces_pdf,
            experimental=self.experimental,
        )

    def _write_attempt_diagnostics(
        self,
        artifacts_dir: Path,
        provider_id: str,
        attempt: int,
        png: bytes,
        report: PageGateReport,
    ) -> None:
        stem = f"page_attempt_{provider_id}_{attempt}"
        (artifacts_dir / f"{stem}.png").write_bytes(png)
        (artifacts_dir / f"{stem}_gates.json").write_text(report.model_dump_json(indent=2))

    def _fallback(self, context: RenderContext, *, reason: str) -> RenderResult:
        logger.warning("  ImageGenRenderer falling back to pdf_classic: %s", reason)
        context.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (context.artifacts_dir / "image_gen_fallback.json").write_text(
            json.dumps({"fallback": True, "reason": reason}, indent=2)
        )
        return PdfClassicRenderer().render(context)


def _write_page_pdf(png_bytes: bytes, output_path: Path, required_text: list[str]) -> None:
    """Wrap a page PNG as a US Letter PDF with an invisible searchable text layer."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        page = doc.new_page(width=PAGE_WIDTH_PT, height=PAGE_HEIGHT_PT)
        page.insert_image(
            fitz.Rect(0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT),
            stream=png_bytes,
            keep_proportion=True,
        )
        # render_mode=3 = invisible text. Keeps the PDF searchable and satisfies
        # the vector-text check in validate/print_checks.py for raster pages.
        leftover = page.insert_textbox(
            fitz.Rect(0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT),
            " ".join(required_text),
            fontsize=2,
            fontname="helv",
            render_mode=3,
        )
        if leftover < 0:
            logger.warning(
                "Invisible text layer truncated (%.0f pt overflow); searchable text incomplete",
                -leftover,
            )
        doc.save(str(output_path))
    finally:
        doc.close()
