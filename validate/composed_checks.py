"""Deterministic compose-time checks for the hybrid_shell renderer.

Fail closed (D45): if the composition declares slots or budgets that
violate the constraints, the render never ships — there is no advisory
mode here because these are exact, zero-noise checks.
"""

from __future__ import annotations

from pathlib import Path

from theme.curated import CuratedThemeAssets

DECORATION_BUDGET_CAP = 0.15  # fraction of page area, fresh-build doc §2.2


def check_composition(
    manifest: dict[str, object],
    curated: CuratedThemeAssets | None,
) -> list[str]:
    violations: list[str] = []

    budget = manifest.get("decoration_budget")
    if isinstance(budget, dict):
        total = sum(v for v in budget.values() if isinstance(v, (int, float)))
        if total > DECORATION_BUDGET_CAP:
            violations.append(
                f"decoration budget {total:.2f} exceeds cap {DECORATION_BUDGET_CAP:.2f}"
            )

    slots_used = manifest.get("slots_used")
    if isinstance(slots_used, dict):
        for slot, entry in slots_used.items():
            if not isinstance(entry, dict):
                violations.append(f"malformed slot entry for {slot}: {entry!r}")
                continue
            source, rel = entry.get("source"), entry.get("path", "")
            if source == "curated":
                if curated is None:
                    violations.append(f"slot {slot} claims curated source but no manifest loaded")
                    continue
                try:
                    resolved = curated.resolve(slot)
                except ValueError as exc:
                    violations.append(str(exc))  # path escape → violation, never a crash
                    continue
                if resolved is None or not resolved.exists():
                    violations.append(f"curated asset missing for slot {slot}: {rel}")
            elif source == "pipeline":
                if not Path(rel).exists():
                    violations.append(f"pipeline asset missing for slot {slot}: {rel}")
            else:
                violations.append(f"unknown slot source for {slot}: {source!r}")

    return violations
