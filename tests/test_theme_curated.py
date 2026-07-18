"""Curated theme asset manifests: pre-approved art in named slots."""

from pathlib import Path

from theme.curated import CuratedThemeAssets, load_curated_assets


def test_roblox_obby_has_a_curated_manifest_with_resolvable_files() -> None:
    assets = load_curated_assets("roblox_obby")
    assert assets is not None
    mascot = assets.resolve("mascot")
    assert mascot is not None and mascot.exists()


def test_unknown_theme_returns_none() -> None:
    assert load_curated_assets("no_such_theme") is None


def test_manifest_paths_may_not_escape_the_theme_dir(tmp_path: Path) -> None:
    import pytest

    assets = CuratedThemeAssets(
        theme_id="x",
        theme_dir=str(tmp_path),
        slots=[{"slot": "mascot", "path": "../../etc/passwd"}],  # type: ignore[list-item]
    )
    with pytest.raises(ValueError):
        assets.resolve("mascot")
