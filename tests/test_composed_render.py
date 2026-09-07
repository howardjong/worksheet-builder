"""hybrid_shell composed renderer: deterministic layout + curated slots, zero AI."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from render.strategies import HybridShellRenderer, RenderContext
from theme.engine import load_theme


def test_hybrid_shell_writes_a_per_worksheet_composed_manifest(
    render_context: RenderContext,
) -> None:
    # Manifest is numbered per worksheet: a 3-sheet package shares one
    # artifacts_dir, so a fixed filename would be silently overwritten twice.
    result = HybridShellRenderer().render(render_context)
    manifest_path = render_context.artifacts_dir / "composed_manifest_1.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["renderer"] == "hybrid_shell"
    assert manifest["render_api_calls"] == 0
    assert result.pdf_path is not None and Path(result.pdf_path).exists()
    assert str(manifest_path) in result.artifact_paths


def test_hybrid_shell_uses_curated_mascot_when_pipeline_has_none(
    render_context: RenderContext,
) -> None:
    # render_context fixture uses theme roblox_obby (has a curated mascot) and
    # avatar_image=None — the curated asset fills the empty slot.
    HybridShellRenderer().render(render_context)
    manifest = json.loads((render_context.artifacts_dir / "composed_manifest_1.json").read_text())
    assert manifest["slots_used"]["mascot"]["source"] == "curated"


def test_pipeline_avatar_takes_precedence_over_curated(
    render_context: RenderContext, tmp_path: Path
) -> None:
    # The identity-consistent, per-child avatar from the asset stage must WIN
    # over the generic curated mascot — curated is the offline/deterministic
    # fallback, not a replacement for personalization.
    avatar = tmp_path / "pipeline_avatar.png"
    avatar.write_bytes(Path("theme/themes/roblox_obby/curated/mascot.png").read_bytes())
    ctx = dataclasses.replace(render_context, avatar_image=str(avatar))
    HybridShellRenderer().render(ctx)
    manifest = json.loads((ctx.artifacts_dir / "composed_manifest_1.json").read_text())
    assert manifest["slots_used"]["mascot"]["source"] == "pipeline"


def test_theme_without_curated_assets_still_renders(render_context: RenderContext) -> None:
    # Every non-roblox theme has no curated dir yet — hybrid_shell must not
    # require one. Swap the theme for one without a curated manifest.
    ctx = dataclasses.replace(render_context, theme=load_theme("space"))
    result = HybridShellRenderer().render(ctx)
    manifest = json.loads((ctx.artifacts_dir / "composed_manifest_1.json").read_text())
    assert manifest["slots_used"] == {}
    assert result.pdf_path is not None and Path(result.pdf_path).exists()


def test_hybrid_shell_makes_no_network_calls(
    render_context: RenderContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen
    import render.image_providers as providers

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("hybrid_shell must not touch image providers")

    # Patch the real call surfaces image_gen uses: provider .generate class
    # methods (bite every instance) and resolve_provider_chain in BOTH the
    # defining module and image_gen's namespace (image_gen imports it by name).
    monkeypatch.setattr(providers.GeminiImageProvider, "generate", _explode)
    monkeypatch.setattr(providers.OpenAIImageProvider, "generate", _explode)
    monkeypatch.setattr(providers, "resolve_provider_chain", _explode)
    monkeypatch.setattr(image_gen, "resolve_provider_chain", _explode)

    # Prove the patches bite: direct calls to the patched surfaces explode.
    # (getattr keeps mypy happy — image_gen does not re-export the symbol.)
    image_gen_chain = getattr(image_gen, "resolve_provider_chain")  # noqa: B009
    with pytest.raises(AssertionError, match="must not touch image providers"):
        providers.GeminiImageProvider().generate("prompt", None)
    with pytest.raises(AssertionError, match="must not touch image providers"):
        providers.OpenAIImageProvider().generate("prompt", None)
    with pytest.raises(AssertionError, match="must not touch image providers"):
        image_gen_chain()

    result = HybridShellRenderer().render(render_context)  # must not raise
    assert result.pdf_path is not None and Path(result.pdf_path).exists()


def test_decoration_budget_within_cap(render_context: RenderContext) -> None:
    HybridShellRenderer().render(render_context)
    manifest = json.loads((render_context.artifacts_dir / "composed_manifest_1.json").read_text())
    assert sum(manifest["decoration_budget"].values()) <= 0.15
