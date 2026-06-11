"""Tests for the full-page image generation renderer (offline; stubs only)."""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest

from companion.character_judge import CharacterJudgeResult
from render.design_spec import (
    PageSpec,
    SectionItemSpec,
    SectionSpec,
    VisualBudget,
    WorksheetDesignSpec,
)
from render.image_gen import ImageGenRenderer
from render.image_providers import ImageProvider
from render.page_gates import PageGateReport, TextGateReport
from render.strategies import RenderContext, RenderResult


def _png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (64, 96), "#FFFFFF")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _spec() -> WorksheetDesignSpec:
    return WorksheetDesignSpec(
        render_mode="image_gen",
        source_hash="src",
        skill_model_hash="skill",
        learner_profile_hash="prof",
        theme_id="roblox_obby",
        theme_name="Roblox Obby Quest",
        learner_name="Ian",
        learner_grade_level="1",
        worksheet_title="Word Work",
        worksheet_number=1,
        worksheet_count=1,
        domain="phonics",
        specific_skill="vowel teams",
        page=PageSpec(width_pt=612, height_pt=792, margin_pt=54),
        visual_budget=VisualBudget(
            style="calm", intensity="low", max_decorative_elements=2, max_colors=4
        ),
        required_text=["Word Work", "rain"],
        sections=[
            SectionSpec(
                chunk_id=1,
                micro_goal="Read the words",
                instructions=["Read each word."],
                response_format="write",
                items=[SectionItemSpec(item_id=1, content="rain", response_format="write")],
            )
        ],
    )


class _StubProvider:
    def __init__(self, provider_id: str, results: list[bytes | None]) -> None:
        self.provider_id = provider_id
        self.model_id = f"{provider_id}-model"
        self._results = list(results)
        self.calls = 0

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, reference_png: bytes | None) -> bytes | None:
        self.calls += 1
        if not self._results:
            return None
        return self._results.pop(0)


def _gate_report(passed: bool) -> PageGateReport:
    return PageGateReport(
        passed=passed,
        text=TextGateReport(available=True, passed=passed),
        character=CharacterJudgeResult(available=True, approved=passed, score=8),
    )


def _context(tmp_path: Path) -> RenderContext:
    from theme.schema import ThemeConfig

    return RenderContext(
        design_spec=_spec(),
        adapted=object(),
        theme=ThemeConfig(name="Roblox Obby Quest"),
        output_path=tmp_path / "worksheet.pdf",
        artifacts_dir=tmp_path / "artifacts",
    )


def _renderer(
    providers: list[ImageProvider], cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> ImageGenRenderer:
    import render.image_gen as image_gen

    monkeypatch.setattr(image_gen, "_CACHE_DIR", cache_dir)
    return ImageGenRenderer(providers=providers)


def test_accepts_first_gate_passing_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True))
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert result.pdf_path is not None and Path(result.pdf_path).exists()
    doc = fitz.open(result.pdf_path)
    assert doc.page_count == 1
    assert abs(doc[0].rect.width - 612) < 2
    assert "rain" in doc[0].get_text()  # invisible text layer is searchable
    doc.close()


def test_regenerates_after_failed_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    verdicts = iter([_gate_report(False), _gate_report(True)])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: next(verdicts))
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert provider.calls == 2


def test_falls_through_to_next_provider_on_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    broken = _StubProvider("broken", [None])
    working = _StubProvider("working", [_png_bytes()])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True))
    renderer = _renderer([broken, working], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "image_gen"
    assert broken.calls == 1
    assert working.calls == 1


def test_falls_back_to_pdf_classic_when_all_attempts_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()] * 3)
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(False))

    class _StubClassic:
        renderer_id = "pdf_classic"
        produces_pdf = True
        experimental = False

        def render(self, context: RenderContext) -> RenderResult:
            return RenderResult(
                renderer_id="pdf_classic",
                pdf_path=str(context.output_path),
                artifact_paths=[str(context.output_path)],
                produces_pdf=True,
                experimental=False,
            )

    monkeypatch.setattr(image_gen, "PdfClassicRenderer", _StubClassic)
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    result = renderer.render(_context(tmp_path))

    assert result.renderer_id == "pdf_classic"
    assert provider.calls == 3  # quality-first budget: 3 attempts per provider
    fallback_marker = tmp_path / "artifacts" / "image_gen_fallback.json"
    assert fallback_marker.exists()


def test_cache_hit_skips_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True))
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    renderer.render(_context(tmp_path))
    assert provider.calls == 1

    renderer.render(_context(tmp_path))
    assert provider.calls == 1  # second render served from cache


def test_resolve_render_strategy_knows_image_gen() -> None:
    from render.strategies import resolve_render_strategy

    strategy = resolve_render_strategy("image_gen")

    assert strategy.renderer_id == "image_gen"
    assert strategy.produces_pdf is True
    assert strategy.experimental is True


def test_theme_art_change_busts_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen
    from render.strategies import RenderContext
    from theme.schema import CharacterSpec, ThemeConfig

    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True))
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    def _ctx(art_style: str) -> RenderContext:
        return RenderContext(
            design_spec=_spec(),
            adapted=object(),
            theme=ThemeConfig(
                name="Roblox Obby Quest",
                character_spec=CharacterSpec(art_style=art_style),
            ),
            output_path=tmp_path / "worksheet.pdf",
            artifacts_dir=tmp_path / "artifacts",
        )

    renderer.render(_ctx("roblox_2d_comic_avatar"))
    assert provider.calls == 1

    renderer.render(_ctx("pixel_art"))
    assert provider.calls == 2  # different art style must not hit the old cache


def test_cache_hit_requires_gate_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(True))
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    renderer.render(_context(tmp_path))
    assert provider.calls == 1

    # Simulate a torn cache entry: page.png present, gate report missing.
    cache_entries = list((tmp_path / "cache").glob("page_*/gate_report.json"))
    assert cache_entries, "expected a gate report in the cache"
    cache_entries[0].unlink()

    renderer.render(_context(tmp_path))
    assert provider.calls == 2  # torn entry must not be served as a cache hit


def test_cache_not_written_on_gate_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import render.image_gen as image_gen

    provider = _StubProvider("stub", [_png_bytes()] * 3)
    monkeypatch.setattr(image_gen, "evaluate_page", lambda *args, **kwargs: _gate_report(False))

    class _StubClassic:
        renderer_id = "pdf_classic"
        produces_pdf = True
        experimental = False

        def render(self, context: RenderContext) -> RenderResult:
            return RenderResult(
                renderer_id="pdf_classic",
                pdf_path=str(context.output_path),
                artifact_paths=[str(context.output_path)],
                produces_pdf=True,
                experimental=False,
            )

    monkeypatch.setattr(image_gen, "PdfClassicRenderer", _StubClassic)
    renderer = _renderer([provider], tmp_path / "cache", monkeypatch)

    renderer.render(_context(tmp_path))

    assert not list((tmp_path / "cache").glob("page_*/page.png"))


def test_page_judge_criteria_expect_instructional_text() -> None:
    from render.image_gen import _page_judge_criteria
    from theme.schema import CharacterSpec

    spec = CharacterSpec(judge_criteria=["Rainbow hair preserved"])
    criteria = _page_judge_criteria(None, spec)

    joined = " ".join(criteria)
    assert "EXPECTED" in joined  # instructional text is expected on a full page
    assert "no text" not in joined.lower()
    assert "THEME FIDELITY: Rainbow hair preserved" in criteria
    assert not any("EQUIPPED ITEMS" in criterion for criterion in criteria)
