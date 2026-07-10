"""Tests for pluggable worksheet render strategies."""

from __future__ import annotations

from pathlib import Path

import pytest

from render.design_spec import PageSpec, VisualBudget, WorksheetDesignSpec


def _design_spec(render_mode: str = "pdf_classic") -> WorksheetDesignSpec:
    return WorksheetDesignSpec(
        render_mode=render_mode,  # type: ignore[arg-type]
        source_hash="source",
        skill_model_hash="skill",
        learner_profile_hash="profile",
        theme_id="geometry_dash",
        theme_name="Geometry Dash Calm",
        learner_name="Ian",
        learner_grade_level="1",
        learner_theme_preferences=["geometry_dash", "roblox_obby"],
        worksheet_title="Vowel Team Adventure",
        worksheet_number=1,
        worksheet_count=1,
        domain="phonics",
        specific_skill="vowel teams ai ay",
        page=PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        visual_budget=VisualBudget(
            style="calm",
            intensity="low",
            max_decorative_elements=2,
            max_colors=4,
        ),
        required_text=[
            "Vowel Team Adventure",
            "Read each word.",
            "rain",
            "play",
        ],
        learning_goal="I can read words with the ai ay pattern",
    )


def test_default_render_strategy_is_image_gen() -> None:
    from render.strategies import default_render_mode, resolve_render_strategy

    strategy = resolve_render_strategy(None)

    assert default_render_mode() == "image_gen"
    assert strategy.renderer_id == "image_gen"
    assert strategy.produces_pdf is True
    assert strategy.experimental is True


def test_unknown_render_strategy_fails_fast() -> None:
    from render.strategies import resolve_render_strategy

    with pytest.raises(ValueError, match="Unknown render mode"):
        resolve_render_strategy("not_a_renderer")


def test_pdf_classic_strategy_calls_existing_pdf_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from render.strategies import RenderContext, resolve_render_strategy

    calls: list[tuple[str, str]] = []

    def fake_render_worksheet(*args: object, **kwargs: object) -> str:
        calls.append((str(args[2]), str(kwargs.get("avatar_image"))))
        Path(str(args[2])).write_text("pdf placeholder")
        return str(args[2])

    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)
    output_path = tmp_path / "worksheet.pdf"
    context = RenderContext(
        design_spec=_design_spec("pdf_classic"),
        adapted=object(),
        theme=object(),
        output_path=output_path,
        artifacts_dir=tmp_path,
        avatar_image="avatar.png",
    )

    result = resolve_render_strategy("pdf_classic").render(context)

    assert calls == [(str(output_path), "avatar.png")]
    assert result.renderer_id == "pdf_classic"
    assert result.pdf_path == str(output_path)
    assert result.artifact_paths == [str(output_path)]


def test_image_prompt_strategy_writes_offline_prompt_artifacts(tmp_path: Path) -> None:
    import json

    from render.strategies import RenderContext, resolve_render_strategy

    context = RenderContext(
        design_spec=_design_spec("image_prompt"),
        adapted=object(),
        theme=object(),
        output_path=tmp_path / "unused.pdf",
        artifacts_dir=tmp_path,
    )

    strategy = resolve_render_strategy("image_prompt")
    result = strategy.render(context)

    prompt_path = tmp_path / "worksheet_image_prompt.md"
    manifest_path = tmp_path / "renderer_manifest.json"
    prompt = prompt_path.read_text()
    manifest = json.loads(manifest_path.read_text())

    assert strategy.renderer_id == "image_prompt"
    assert strategy.produces_pdf is False
    assert strategy.experimental is True
    assert result.pdf_path is None
    assert result.produces_pdf is False
    assert str(prompt_path) in result.artifact_paths
    assert str(manifest_path) in result.artifact_paths
    assert "OFFLINE PROMPT ONLY" in prompt
    assert "Do not add, remove, rewrite, or misspell required text." in prompt
    assert "Vowel Team Adventure" in prompt
    assert "Read each word." in prompt
    assert "rain" in prompt
    assert "play" in prompt
    assert manifest["renderer_id"] == "image_prompt"
    assert manifest["provider"] == "offline_prompt_only"
    assert manifest["required_text_count"] == 4


def test_hybrid_shell_strategy_is_experimental_pdf_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from render.strategies import RenderContext, resolve_render_strategy

    calls: list[str] = []

    def fake_render_worksheet(*args: object, **kwargs: object) -> str:
        calls.append(str(args[2]))
        Path(str(args[2])).write_text("pdf placeholder")
        return str(args[2])

    monkeypatch.setattr("render.strategies.render_worksheet", fake_render_worksheet)
    output_path = tmp_path / "hybrid.pdf"
    context = RenderContext(
        design_spec=_design_spec("hybrid_shell"),
        adapted=object(),
        theme=object(),
        output_path=output_path,
        artifacts_dir=tmp_path,
    )

    strategy = resolve_render_strategy("hybrid_shell")
    result = strategy.render(context)

    assert calls == [str(output_path)]
    assert strategy.renderer_id == "hybrid_shell"
    assert strategy.produces_pdf is True
    assert strategy.experimental is True
    assert result.pdf_path == str(output_path)


def test_render_artifacts_dir_isolates_experimental_renderers(tmp_path: Path) -> None:
    from render.strategies import resolve_render_strategy
    from transform import _render_artifacts_dir

    image_gen = resolve_render_strategy("image_gen")
    classic = resolve_render_strategy("pdf_classic")
    prompt_only = resolve_render_strategy("image_prompt")

    assert _render_artifacts_dir(tmp_path, image_gen, 2) == tmp_path / "render_2"
    assert _render_artifacts_dir(tmp_path, classic, 2) == tmp_path
    assert _render_artifacts_dir(tmp_path, prompt_only, 2) == tmp_path / "render_2"


def test_aggregate_renderer_id_reports_fallbacks() -> None:
    from render.strategies import RenderResult
    from transform import _aggregate_renderer_id

    def _result(renderer_id: str) -> RenderResult:
        return RenderResult(
            renderer_id=renderer_id,
            pdf_path=None,
            artifact_paths=[],
            produces_pdf=True,
            experimental=False,
        )

    assert _aggregate_renderer_id([], "image_gen") == "image_gen"
    assert (
        _aggregate_renderer_id([_result("image_gen"), _result("image_gen")], "image_gen")
        == "image_gen"
    )
    assert (
        _aggregate_renderer_id([_result("image_gen"), _result("pdf_classic")], "image_gen")
        == "pdf_classic"
    )
    assert _aggregate_renderer_id([_result("pdf_classic")], "pdf_classic") == "pdf_classic"
