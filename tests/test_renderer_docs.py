"""Documentation checks for renderer-mode rollout."""

from __future__ import annotations

from pathlib import Path


def test_readme_documents_renderer_modes_and_promotion_gates() -> None:
    readme = Path("README.md").read_text()

    assert "--render-mode" in readme
    assert "pdf_classic" in readme
    assert "hybrid_shell" in readme
    assert "image_prompt" in readme
    assert "renderer benchmark" in readme.lower()
    assert "promotion gates" in readme.lower()
