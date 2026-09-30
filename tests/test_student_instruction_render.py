"""Rendering regressions for clearer directions and truthful picture fallback."""

from pathlib import Path

import fitz
import pytest

from adapt.engine import adapt_activity, adapt_lesson
from adapt.schema import Step
from companion.schema import LearnerProfile
from render.design_spec import compile_worksheet_design_spec
from render.image_prompt_builder import build_page_prompt
from render.pdf import (
    MARGIN,
    PAGE_WIDTH,
    RenderContractError,
    prepare_pdf_activity,
    render_worksheet,
)
from skill.lesson_loader import skill_model_from_lesson
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import load_theme
from theme.schema import AssetManifest


def test_ambiguous_directions_fail_before_creating_a_pdf(tmp_path: Path) -> None:
    skill = skill_model_from_lesson(49)
    adapted = adapt_activity(skill, LearnerProfile(name="Reader", grade_level="1"))
    adapted.chunks[0].instructions = [Step(number=1, text="Try the list three times.")]
    path = tmp_path / "ambiguous.pdf"
    with pytest.raises(RenderContractError, match="unclear worksheet instructions"):
        render_worksheet(adapted, load_theme("space"), str(path))
    assert not path.exists()


def test_default_image_prompt_keeps_matching_and_its_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSHEET_LLM_ADAPT", "0")
    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.delenv("WORKSHEET_PLANNER_V2", raising=False)
    profile = LearnerProfile(name="Reader", grade_level="1")
    worksheets = adapt_lesson(skill_model_from_lesson(74), profile, theme_id="roblox_obby")
    worksheet = next(
        ws
        for ws in worksheets
        if any(item.response_format == "match" for chunk in ws.chunks for item in chunk.items)
    )
    spec = compile_worksheet_design_spec(
        worksheet, load_theme("roblox_obby"), profile, render_mode="image_gen"
    )
    prompt = build_page_prompt(spec)
    assert "two columns" in prompt
    assert "Follow the completed match example:" in prompt
    assert "Draw one line from each picture to its matching word." in prompt

    fallback = prepare_pdf_activity(worksheet, None)
    assert all(item.response_format != "match" for chunk in fallback.chunks for item in chunk.items)
    assert all(
        chunk.worked_example is None or "picture" not in chunk.worked_example.content
        for chunk in fallback.chunks
    )
    # A PDF fallback must not alter the original model or its image prompt.
    assert build_page_prompt(spec) == prompt
    assert any(
        item.response_format == "match" for chunk in worksheet.chunks for item in chunk.items
    )

    picture_path = str(Path(__file__).parents[1] / "assets/themes/space/rocket.png")
    manifest = AssetManifest(
        word_picture_paths={
            item.options[0]: picture_path
            for chunk in worksheet.chunks
            for item in chunk.items
            if item.response_format == "match" and item.options
        }
    )
    assert prepare_pdf_activity(worksheet, manifest) == worksheet


@pytest.mark.parametrize("grade", ["K", "1", "2", "3"])
@pytest.mark.parametrize("with_scene", [False, True])
def test_long_student_directions_fit_their_printed_column(
    tmp_path: Path,
    grade: str,
    with_scene: bool,
) -> None:
    skill = LiteracySkillModel(
        grade_level=grade,
        domain="phonics",
        specific_skill="a_e",
        learning_objectives=["Read and write words"],
        target_words=["cake"],
        response_types=["write"],
        source_items=[SourceItem(item_type="word_list", content="cake", source_region_index=0)],
        extraction_confidence=1.0,
        template_type="teacher_created_word_list",
    )
    adapted = adapt_activity(skill, LearnerProfile(name="Reader", grade_level=grade))
    direction = "Underline these target words in the story: cake, lake, gate, late."
    adapted.chunks[0].instructions = [Step(number=1, text=direction)]
    adapted.chunks[0].worked_example = None
    adapted.chunks[0].micro_goal = "Practice one word"
    theme = load_theme("roblox_obby" if with_scene else "space")
    scene_path = str(
        Path(__file__).parents[1] / "assets/style_sheets/ian_roblox_buddy/pose_working.png"
    )
    manifest = (
        AssetManifest(scene_paths={adapted.chunks[0].chunk_id: scene_path}) if with_scene else None
    )
    path = tmp_path / "directions.pdf"
    render_worksheet(adapted, theme, str(path), asset_manifest=manifest)

    with fitz.open(path) as doc:
        assert direction in " ".join(" ".join(page.get_text().split()) for page in doc)
        assert any(page.get_images() for page in doc) == with_scene
        for page in doc:
            images = [
                rect for image in page.get_images() for rect in page.get_image_rects(image[0])
            ]
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if "Worksheet Builder" in span["text"]:
                            continue
                        rect = fitz.Rect(span["bbox"])
                        assert rect.x1 <= PAGE_WIDTH - MARGIN + 1, span["text"]
                        assert all(not rect.intersects(image) for image in images), span["text"]
