"""Deterministic composed renderer: classic layout + curated theme slots.

The fresh-build architecture doc's R5 decision, applied to this codebase:
generate content, never pages. Layout correctness comes from the ReportLab
engine (render/pdf.py) by construction; theme identity comes from curated,
pre-approved art in fixed slots; render-time AI calls are structurally zero.
"""

from __future__ import annotations

import json
from typing import cast

from adapt.schema import AdaptedActivityModel
from render.pdf import render_worksheet
from render.strategies import RenderContext
from theme.curated import load_curated_assets
from theme.schema import ThemeConfig

# Fixed page-area fractions per slot — enforced by construction (the classic
# renderer's avatar clearance floor), recorded for the fail-closed budget
# check in validate/composed_checks.py. Sum must stay ≤ 0.15 (fresh-build
# doc's measured decoration budget).
SLOT_BUDGETS = {"mascot": 0.06, "header_banner": 0.07}


def compose_worksheet(context: RenderContext) -> dict[str, object]:
    adapted = cast(AdaptedActivityModel, context.adapted)
    theme = cast(ThemeConfig, context.theme)

    # Pipeline avatar (identity-consistent, per-child, produced upstream at the
    # asset stage — NOT a render-time AI call) wins; curated art is the
    # offline/deterministic fallback for the mascot slot.
    curated = load_curated_assets(theme.theme_id)
    slots_used: dict[str, dict[str, str]] = {}
    mascot_path = context.avatar_image
    if mascot_path:
        slots_used["mascot"] = {"source": "pipeline", "path": mascot_path}
    elif curated is not None:
        resolved = curated.resolve("mascot")
        if resolved is not None:
            mascot_path = str(resolved)
            slots_used["mascot"] = {"source": "curated", "path": resolved.name}

    render_worksheet(
        adapted,
        theme,
        str(context.output_path),
        avatar_image=mascot_path,
        asset_manifest=context.asset_manifest,
    )

    worksheet_number = adapted.worksheet_number
    manifest: dict[str, object] = {
        "renderer": "hybrid_shell",
        "theme_id": theme.theme_id,
        "worksheet_number": worksheet_number,
        "slots_used": slots_used,
        "decoration_budget": {slot: SLOT_BUDGETS[slot] for slot in slots_used},
        "render_api_calls": 0,
    }
    context.artifacts_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = context.artifacts_dir / f"composed_manifest_{worksheet_number}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
