"""Compose-time checks: budget cap and asset integrity, fail closed."""

from pathlib import Path

import pytest

from render.strategies import RenderContext
from validate.composed_checks import check_composition


def test_budget_within_cap_passes() -> None:
    manifest: dict[str, object] = {"decoration_budget": {"mascot": 0.06}, "slots_used": {}}
    assert check_composition(manifest, None) == []


def test_budget_over_cap_fails() -> None:
    manifest: dict[str, object] = {
        "decoration_budget": {"mascot": 0.10, "header_banner": 0.07},
        "slots_used": {},
    }
    violations = check_composition(manifest, None)
    assert any("budget" in v for v in violations)


def test_missing_curated_file_fails(tmp_path: Path) -> None:
    from theme.curated import CuratedThemeAssets

    curated = CuratedThemeAssets(
        theme_id="x",
        theme_dir=str(tmp_path),
        slots=[{"slot": "mascot", "path": "gone.png"}],  # type: ignore[list-item]
    )
    manifest: dict[str, object] = {
        "decoration_budget": {},
        "slots_used": {"mascot": {"source": "curated", "path": "gone.png"}},
    }
    violations = check_composition(manifest, curated)
    assert any("gone.png" in v for v in violations)


def test_path_escape_is_a_violation_not_a_crash(tmp_path: Path) -> None:
    # A malicious/typo'd manifest path must surface as a violation (fail
    # closed), never as an unhandled ValueError that aborts mid-compose.
    from theme.curated import CuratedThemeAssets

    curated = CuratedThemeAssets(
        theme_id="x",
        theme_dir=str(tmp_path),
        slots=[{"slot": "mascot", "path": "../../etc/passwd"}],  # type: ignore[list-item]
    )
    manifest: dict[str, object] = {
        "decoration_budget": {},
        "slots_used": {"mascot": {"source": "curated", "path": "../../etc/passwd"}},
    }
    violations = check_composition(manifest, curated)
    assert any("escape" in v for v in violations)


def test_missing_pipeline_avatar_file_fails(tmp_path: Path) -> None:
    manifest: dict[str, object] = {
        "decoration_budget": {},
        "slots_used": {"mascot": {"source": "pipeline", "path": str(tmp_path / "gone.png")}},
    }
    violations = check_composition(manifest, None)
    assert any("gone.png" in v for v in violations)


def test_compose_worksheet_raises_on_violation(
    monkeypatch: pytest.MonkeyPatch, render_context: RenderContext
) -> None:
    import render.composed as composed
    from render.composed import ComposedRenderError, compose_worksheet

    monkeypatch.setattr(composed, "SLOT_BUDGETS", {"mascot": 0.99, "header_banner": 0.07})

    with pytest.raises(ComposedRenderError):
        compose_worksheet(render_context)
