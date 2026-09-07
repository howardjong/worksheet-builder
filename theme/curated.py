"""Curated theme assets: pre-approved art referenced by named slots.

The composed renderer (hybrid_shell) only ever draws art listed in a
theme's curated manifest — never generated at render time. A theme
without a curated dir simply has no composed-mode art.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

THEMES_ROOT = Path(__file__).parent / "themes"

SlotName = Literal["header_banner", "mascot"]


class CuratedSlot(BaseModel):
    slot: SlotName
    path: str


class CuratedThemeAssets(BaseModel):
    theme_id: str
    theme_dir: str
    slots: list[CuratedSlot]

    def resolve(self, slot: SlotName) -> Path | None:
        for entry in self.slots:
            if entry.slot == slot:
                base = Path(self.theme_dir).resolve()
                candidate = (base / entry.path).resolve()
                if not candidate.is_relative_to(base):
                    raise ValueError(f"curated asset path escapes theme dir: {entry.path}")
                return candidate
        return None


def load_curated_assets(theme_id: str) -> CuratedThemeAssets | None:
    manifest_path = THEMES_ROOT / theme_id / "curated" / "manifest.yaml"
    if not manifest_path.exists():
        return None
    data = yaml.safe_load(manifest_path.read_text())
    return CuratedThemeAssets(
        theme_id=data["theme_id"],
        theme_dir=str(manifest_path.parent),
        slots=data.get("slots", []),
    )
