"""Tests for render/pdf.py and validate/print_checks.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import fitz
from pytest import MonkeyPatch

from adapt.engine import adapt_activity, adapt_lesson
from companion.character_identity import CharacterIdentity
from companion.character_judge import CharacterJudgeResult
from companion.schema import Accommodations, AvatarConfig, CharacterStyleSheet, LearnerProfile
from render.asset_gen import (
    _build_cover_prompt,
    _build_scene_generation_prompt,
    compute_worksheet_hash,
    generate_worksheet_assets,
)
from render.pdf import (
    CONTENT_BOTTOM,
    CONTENT_TOP,
    MARGIN,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    render_cover_page,
    render_worksheet,
)
from render.pose_planner import ScenePlan, plan_scenes, plan_word_pictures
from skill.schema import LiteracySkillModel, SourceItem
from theme.engine import load_theme
from theme.schema import AssetManifest
from validate.print_checks import validate_print_quality


def _phonics_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvc_blending",
        learning_objectives=["Blend CVC words"],
        target_words=["tall", "call", "wall", "fall", "mall", "doll"],
        response_types=["write"],
        source_items=[
            SourceItem(item_type="word_list", content="tall, call, wall", source_region_index=0),
            SourceItem(item_type="word_list", content="fall, mall, doll", source_region_index=1),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _fluency_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="fluency",
        specific_skill="decodable_text_cvce",
        learning_objectives=["Read a decodable passage"],
        target_words=["june", "flute"],
        response_types=["read_aloud"],
        source_items=[
            SourceItem(
                item_type="passage",
                content="June has a flute. June likes to make tunes.",
                source_region_index=0,
            ),
        ],
        extraction_confidence=0.92,
        template_type="ufli_decodable_story",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(name="Test", grade_level="1")


def _render_pdf(skill: LiteracySkillModel | None = None, theme_id: str = "space") -> str:
    """Render a test PDF and return its path."""
    if skill is None:
        skill = _phonics_skill()
    adapted = adapt_activity(skill, _profile())
    theme = load_theme(theme_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    render_worksheet(adapted, theme, pdf_path)
    return pdf_path


class TestRenderWorksheet:
    def test_creates_pdf_file(self) -> None:
        pdf_path = _render_pdf()
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_different_themes_produce_different_pdfs(self) -> None:
        pdf1 = _render_pdf(theme_id="space")
        pdf2 = _render_pdf(theme_id="dinosaur")
        # Different themes should produce different files
        assert Path(pdf1).exists()
        assert Path(pdf2).exists()
        # Both should have content
        assert Path(pdf1).stat().st_size > 0
        assert Path(pdf2).stat().st_size > 0
        Path(pdf1).unlink()
        Path(pdf2).unlink()

    def test_phonics_render(self) -> None:
        pdf_path = _render_pdf(_phonics_skill())
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_fluency_render(self) -> None:
        pdf_path = _render_pdf(_fluency_skill())
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_grade_k_render(self) -> None:
        skill = _phonics_skill()
        profile = LearnerProfile(
            name="Test K",
            grade_level="K",
            accommodations=Accommodations(chunking_level="small"),
        )
        adapted = adapt_activity(skill, profile)
        theme = load_theme("space")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(adapted, theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_creates_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = str(Path(tmpdir) / "subdir" / "test.pdf")
            adapted = adapt_activity(_phonics_skill(), _profile())
            theme = load_theme("space")
            render_worksheet(adapted, theme, pdf_path)
            assert Path(pdf_path).exists()

    def test_cover_page_renders(self) -> None:
        """Cover page should render with skill info and worksheet list."""
        skill = _phonics_skill()
        worksheets = adapt_lesson(skill, _profile())
        theme = load_theme("space")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            cover_path = f.name

        render_cover_page(
            skill_model=skill,
            worksheets=worksheets,
            theme=theme,
            output_path=cover_path,
            profile_name="Test",
        )
        assert Path(cover_path).exists()
        assert Path(cover_path).stat().st_size > 0

        # Verify content
        doc = fitz.open(cover_path)
        assert doc.page_count == 1
        text = doc.load_page(0).get_text()
        assert "What's Inside" in text
        assert "Grade 1" in text
        doc.close()
        Path(cover_path).unlink()

    def test_page_geometry_constants(self) -> None:
        assert PAGE_WIDTH == 612.0
        assert PAGE_HEIGHT == 792.0
        assert MARGIN > 0
        assert CONTENT_TOP < PAGE_HEIGHT
        assert CONTENT_BOTTOM > 0


class TestPrintQuality:
    def test_valid_pdf_passes(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        assert result.passed
        assert result.checks_run >= 5
        Path(pdf_path).unlink()

    def test_letter_dimensions(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        dim_violations = [v for v in result.violations if v.check == "page_dimensions"]
        assert len(dim_violations) == 0
        Path(pdf_path).unlink()

    def test_has_vector_text(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        text_violations = [v for v in result.violations if v.check == "vector_text"]
        assert len(text_violations) == 0
        Path(pdf_path).unlink()

    def test_invalid_pdf_fails(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="w") as f:
            f.write("not a pdf")
            bad_path = f.name
        result = validate_print_quality(bad_path)
        assert not result.passed
        Path(bad_path).unlink()

    def test_has_pages(self) -> None:
        pdf_path = _render_pdf()
        result = validate_print_quality(pdf_path)
        page_violations = [v for v in result.violations if v.check == "has_pages"]
        assert len(page_violations) == 0
        Path(pdf_path).unlink()


# --- Multi-Worksheet Render Tests ---


def _ufli_59_skill() -> LiteracySkillModel:
    """UFLI Lesson 59 fixture for render tests."""
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="cvce_pattern",
        learning_objectives=["Read CVCe words"],
        target_words=["grade", "chase", "slide", "quite", "froze", "these"],
        response_types=["write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="grade, chase, slide, quite",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="1. tune \u2192 tone \u2192 cone \u2192 cane",
                source_region_index=1,
            ),
            SourceItem(
                item_type="sight_words",
                content="who, by, my",
                source_region_index=2,
            ),
            SourceItem(
                item_type="sentence",
                content="1. The slide was quite fun.",
                source_region_index=3,
            ),
            SourceItem(
                item_type="passage",
                content="A Cake for Tess. Tess had a cake. The cake was huge!",
                source_region_index=4,
            ),
        ],
        extraction_confidence=0.95,
        template_type="ufli_word_work",
    )


def _lesson74_home_skill() -> LiteracySkillModel:
    return LiteracySkillModel(
        grade_level="1",
        domain="phonics",
        specific_skill="y_as_long_e",
        learning_objectives=[
            "Read and spell words where final y says long e.",
            "Build new words by changing sounds in a word chain.",
            "Read connected sentences with the target pattern.",
        ],
        target_words=[
            "sunny",
            "funny",
            "bunny",
            "buddy",
            "happy",
            "hoppy",
            "poppy",
            "puppy",
            "muddy",
            "penny",
            "lady",
            "tiny",
            "forty",
            "teddy",
            "baby",
        ],
        response_types=["match", "trace", "circle", "fill_blank", "write", "read_aloud"],
        source_items=[
            SourceItem(
                item_type="word_list",
                content="sunny muddy penny puppy lady tiny",
                source_region_index=0,
            ),
            SourceItem(
                item_type="word_chain",
                content="sunny -> funny -> bunny -> buddy",
                source_region_index=1,
            ),
            SourceItem(
                item_type="word_chain",
                content="happy -> hoppy -> poppy -> puppy",
                source_region_index=2,
            ),
            SourceItem(item_type="sight_words", content="forty", source_region_index=3),
            SourceItem(
                item_type="sentence",
                content="The woman is not forty.",
                source_region_index=4,
            ),
            SourceItem(
                item_type="sentence",
                content="I will bring a teddy for the baby.",
                source_region_index=5,
            ),
        ],
        extraction_confidence=0.99,
        template_type="ufli_word_work",
    )


class TestMultiWorksheetRender:
    def test_render_match_items(self) -> None:
        """Word-picture matching items should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        # Section cap enforcement may split into multiple parts
        discovery = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert len(discovery) >= 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(discovery[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_trace_items(self) -> None:
        """Trace items (dotted letters) should render without error."""
        # Use a profile that explicitly allows trace format
        profile = LearnerProfile(
            name="Test",
            grade_level="1",
            accommodations=Accommodations(
                response_format_prefs=["write", "trace", "circle"],
            ),
        )
        worksheets = adapt_lesson(_ufli_59_skill(), profile)
        # Section cap enforcement may split into multiple parts
        discovery = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert len(discovery) >= 1
        # Verify trace items exist
        trace_items = [
            item
            for ws in discovery
            for chunk in ws.chunks
            for item in chunk.items
            if item.response_format == "trace"
        ]
        assert len(trace_items) >= 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(discovery[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_fill_blank_items(self) -> None:
        """Fill-blank items should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        builder = [ws for ws in worksheets if ws.worksheet_title == "Word Work"]
        assert len(builder) == 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(builder[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_read_aloud_items(self) -> None:
        """Read-aloud passage should render in styled box."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        story = [ws for ws in worksheets if ws.worksheet_title == "Story Time"]
        assert len(story) == 1
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(story[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_render_all_worksheets(self) -> None:
        """All multi-worksheets should render successfully."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        theme = load_theme("space")
        for i, ws in enumerate(worksheets):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                pdf_path = f.name
            render_worksheet(ws, theme, pdf_path)
            assert Path(pdf_path).stat().st_size > 0
            # Verify print quality
            result = validate_print_quality(pdf_path)
            assert result.passed, f"Worksheet {i+1} failed print quality: {result.violations}"
            Path(pdf_path).unlink()

    def test_render_with_roblox_obby_theme(self) -> None:
        """Roblox Obby theme should load and render correctly."""
        theme = load_theme("roblox_obby")
        assert theme.multi_worksheet is True
        assert theme.avatar_position == "integrated"
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(worksheets[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_break_prompt_renders(self) -> None:
        """Brain break prompt should render without error."""
        worksheets = adapt_lesson(_ufli_59_skill(), _profile())
        # First worksheet should have a break prompt
        assert worksheets[0].break_prompt is not None
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(worksheets[0], theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_backward_compat_single_worksheet(self) -> None:
        """Original single-worksheet rendering still works unchanged."""
        adapted = adapt_activity(_phonics_skill(), _profile())
        theme = load_theme("space")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(adapted, theme, pdf_path)
        assert Path(pdf_path).stat().st_size > 0
        Path(pdf_path).unlink()

    def test_chunk_starts_on_new_page_before_bottom_clip(self) -> None:
        """Integrated-scene layouts should move the next chunk to a new page before clipping."""
        worksheets = adapt_lesson(_lesson74_home_skill(), _profile(), theme_id="roblox_obby")
        # Section cap enforcement may split into multiple parts
        discovery = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert len(discovery) >= 1

        theme = load_theme("roblox_obby")
        scene_path = str(Path("assets/characters/rainbow_roblox.png"))
        manifest = AssetManifest(
            scene_paths={1: scene_path, 2: scene_path, 3: scene_path},
            word_picture_paths={},
            cache_dir="assets/characters",
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        render_worksheet(discovery[0], theme, pdf_path, asset_manifest=manifest)

        doc = fitz.open(pdf_path)
        assert doc.page_count >= 2
        first_page = doc.load_page(0).get_text()
        # Trace chunk should appear on a subsequent page (not necessarily page 2
        # since a phonemic awareness warm-up may also precede it)
        later_pages_text = "".join(doc.load_page(p).get_text() for p in range(1, doc.page_count))
        doc.close()

        # Default profile has no "trace" in prefs, so discovery uses "write"
        assert "Write 4 words" not in first_page
        assert "Write 4 words" in later_pages_text
        Path(pdf_path).unlink()

    def test_word_picture_prompts_key_shuffled_picture_word(self) -> None:
        """Match pictures are looked up by the shuffled picture word."""
        worksheets = adapt_lesson(_lesson74_home_skill(), _profile(), theme_id="roblox_obby")
        # Section cap enforcement may split into multiple parts
        word_practice_parts = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert word_practice_parts, "Expected at least one Word Practice worksheet"
        word_practice = word_practice_parts[0]

        prompts = plan_word_pictures(word_practice)
        match_items = [
            item
            for chunk in word_practice.chunks
            for item in chunk.items
            if item.response_format == "match"
        ]
        picture_words = {item.options[0] for item in match_items if item.options}

        assert picture_words
        assert picture_words.issubset(prompts.keys())

    def test_local_asset_fallback_embeds_images_without_api_key(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Offline generation should still produce printable raster assets."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        worksheets = adapt_lesson(_lesson74_home_skill(), _profile(), theme_id="roblox_obby")
        # Section cap enforcement may split into multiple parts
        word_practice_parts = [
            ws
            for ws in worksheets
            if ws.worksheet_title and ws.worksheet_title.startswith("Word Practice")
        ]
        assert word_practice_parts, "Expected at least one Word Practice worksheet"
        word_practice = word_practice_parts[0]
        theme = load_theme("roblox_obby")
        manifest = generate_worksheet_assets(
            plan_scenes(word_practice, character_spec=theme.character_spec),
            plan_word_pictures(word_practice),
            "test_local_fallback",
            character_spec=theme.character_spec,
        )

        assert manifest is not None
        assert manifest.scene_paths
        assert manifest.word_picture_paths

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        render_worksheet(word_practice, theme, pdf_path, asset_manifest=manifest)

        doc = fitz.open(pdf_path)
        image_count = sum(len(page.get_images(full=True)) for page in doc)
        doc.close()
        Path(pdf_path).unlink()

        assert image_count > 0

    def test_worksheet_hash_changes_with_identity_version(self) -> None:
        base = compute_worksheet_hash("source", 1, "roblox_obby")
        first_identity = compute_worksheet_hash(
            "source",
            1,
            "roblox_obby",
            identity_version="identity_v1_plain",
        )
        equipped_identity = compute_worksheet_hash(
            "source",
            1,
            "roblox_obby",
            identity_version="identity_v1_brown_backpack",
        )

        assert base != first_identity
        assert first_identity != equipped_identity

    def test_scene_cache_path_changes_when_pose_reference_changes(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        ref_dir = tmp_path / "refs"
        ref_dir.mkdir()
        (ref_dir / "ref_front_character_crop.png").write_bytes(b"canonical")
        pose_ref = ref_dir / "pose_pointing.png"
        pose_ref.write_bytes(b"pointing v1")
        profile = LearnerProfile(
            name="Ian",
            grade_level="1",
            avatar=AvatarConfig(
                base_character="ian_learning_buddy",
                style_sheet=CharacterStyleSheet(
                    character_block="Ian has rainbow spiky hair.",
                    reference_image_dir=str(ref_dir),
                ),
            ),
        )
        theme = load_theme("roblox_obby")
        scenes = [ScenePlan(1, "pointing at picture cards", "pointing", "sunny")]

        first = generate_worksheet_assets(
            scenes,
            {},
            "pose_reference_cache_test",
            profile=profile,
            theme_id="roblox_obby",
            character_spec=theme.character_spec,
        )
        pose_ref.write_bytes(b"pointing v2")
        second = generate_worksheet_assets(
            scenes,
            {},
            "pose_reference_cache_test",
            profile=profile,
            theme_id="roblox_obby",
            character_spec=theme.character_spec,
        )

        assert first is not None
        assert second is not None
        assert first.cache_dir != second.cache_dir
        assert first.scene_paths[1] != second.scene_paths[1]

    def test_scene_generation_prompt_uses_identity_guidelines_and_equipped_items(self) -> None:
        theme = load_theme("roblox_obby")
        identity = CharacterIdentity(
            base_character="ian_learning_buddy",
            base_image_path="assets/characters/ian_learning_buddy.png",
            reference_image_dir="assets/style_sheets/ian_roblox_buddy",
            canonical_reference_path="assets/style_sheets/ian_roblox_buddy/ref_front_character_crop.png",
            pose_reference_path="assets/style_sheets/ian_roblox_buddy/pose_pointing.png",
            character_block="Ian has rainbow spiky hair and a blue lightning shirt.",
            scene_guidelines="Use calm printable learning panels.",
            item_style_notes="Accessories must not hide Ian's hair or shirt.",
            equipped_items={"backpack": "brown_backpack"},
            identity_version="identity_v1_brown_backpack",
        )

        prompt = _build_scene_generation_prompt(
            "pointing at picture cards",
            identity,
            theme.character_spec,
        )

        assert "Ian has rainbow spiky hair" in prompt
        assert "calm printable learning panels" in prompt
        assert "backpack=brown_backpack" in prompt
        assert "Calm printable Roblox/obby learning environment" in prompt

    def test_cover_prompt_uses_identity_without_pixar_style_conflict(self) -> None:
        theme = load_theme("roblox_obby")
        identity = CharacterIdentity(
            base_character="ian_learning_buddy",
            base_image_path="assets/characters/ian_learning_buddy.png",
            reference_image_dir="assets/style_sheets/ian_roblox_buddy",
            canonical_reference_path="assets/style_sheets/ian_roblox_buddy/ref_front_character_crop.png",
            pose_reference_path=None,
            character_block="Ian has rainbow spiky hair and a blue lightning shirt.",
            scene_guidelines="Use calm printable learning panels.",
            item_style_notes="Accessories must not hide Ian's hair or shirt.",
            equipped_items={},
            identity_version="identity_v1_plain",
        )

        prompt = _build_cover_prompt(
            "phonics: cvce_pattern",
            ["grade", "slide"],
            theme.character_spec,
            identity,
        )

        assert "Ian has rainbow spiky hair" in prompt
        assert "calm printable learning panels" in prompt
        assert "Calm printable Roblox/obby learning environment" in prompt
        assert "Pixar-like" not in prompt

    def test_scene_generation_invokes_judge_with_reference_and_generated_bytes(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from render import asset_gen

        ref_path = tmp_path / "pose_pointing.png"
        ref_path.write_bytes(b"reference bytes")
        generated_bytes = b"approved ai scene"
        observed: dict[str, bytes] = {}
        monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def fake_generate_scene(
            prompt: str,
            output_path: str,
            ref_bytes: bytes | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(generated_bytes)
            return output_path

        def fake_judge(
            reference_bytes: bytes,
            image_bytes: bytes,
            criteria: list[str],
        ) -> CharacterJudgeResult:
            observed["reference"] = reference_bytes
            observed["generated"] = image_bytes
            return CharacterJudgeResult(available=True, approved=True, score=9, issues=[])

        monkeypatch.setattr(asset_gen, "_generate_scene", fake_generate_scene)
        monkeypatch.setattr(asset_gen, "judge_character_consistency", fake_judge)

        manifest = generate_worksheet_assets(
            [ScenePlan(1, "pointing at picture cards", "pointing", "sunny")],
            {},
            "scene_judge_accepts",
            identity=CharacterIdentity(
                base_character="ian_learning_buddy",
                base_image_path=None,
                reference_image_dir=str(tmp_path),
                canonical_reference_path=str(ref_path),
                pose_reference_path=str(ref_path),
                character_block="Ian has rainbow spiky hair.",
                scene_guidelines="Keep Ian consistent.",
                item_style_notes="",
                equipped_items={},
                identity_version="identity_v1_scene_judge_accepts",
            ),
        )

        assert manifest is not None
        assert observed["reference"] == ref_path.read_bytes()
        assert observed["generated"] == generated_bytes
        assert Path(manifest.scene_paths[1]).read_bytes() == generated_bytes

    def test_rejected_scene_falls_back_without_caching_rejected_ai_bytes(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from render import asset_gen

        ref_path = tmp_path / "pose_pointing.png"
        ref_path.write_bytes(b"reference bytes")
        monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def fake_generate_scene(
            prompt: str,
            output_path: str,
            ref_bytes: bytes | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(b"rejected ai bytes")
            return output_path

        def fake_local_scene(
            plan: ScenePlan,
            output_path: str,
            character_spec: object | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(b"approved local pose bytes")
            return output_path

        monkeypatch.setattr(asset_gen, "_generate_scene", fake_generate_scene)
        monkeypatch.setattr(asset_gen, "_generate_local_scene", fake_local_scene)
        monkeypatch.setattr(
            asset_gen,
            "judge_character_consistency",
            lambda reference_bytes, image_bytes, criteria: CharacterJudgeResult(
                available=True,
                approved=False,
                score=3,
                issues=["hair changed"],
            ),
        )

        manifest = generate_worksheet_assets(
            [ScenePlan(1, "pointing at picture cards", "pointing", "sunny")],
            {},
            "scene_judge_rejects",
            identity=CharacterIdentity(
                base_character="ian_learning_buddy",
                base_image_path=str(ref_path),
                reference_image_dir=str(tmp_path),
                canonical_reference_path=None,
                pose_reference_path=None,
                character_block="Ian has rainbow spiky hair.",
                scene_guidelines="Keep Ian consistent.",
                item_style_notes="",
                equipped_items={},
                identity_version="identity_v1_scene_judge_rejects",
            ),
        )

        assert manifest is not None
        scene_path = Path(manifest.scene_paths[1])
        assert scene_path.read_bytes() == b"approved local pose bytes"
        assert scene_path.read_bytes() != b"rejected ai bytes"
        assert (scene_path.parent / "scene_1_rejected.json").exists()

    def test_unavailable_scene_judge_prefers_local_fallback_over_unverified_ai(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from render import asset_gen

        ref_path = tmp_path / "pose_pointing.png"
        ref_path.write_bytes(b"reference bytes")
        monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def fake_generate_scene(
            prompt: str,
            output_path: str,
            ref_bytes: bytes | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(b"unverified ai bytes")
            return output_path

        def fake_local_scene(
            plan: ScenePlan,
            output_path: str,
            character_spec: object | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(b"canonical local pose bytes")
            return output_path

        monkeypatch.setattr(asset_gen, "_generate_scene", fake_generate_scene)
        monkeypatch.setattr(asset_gen, "_generate_local_scene", fake_local_scene)
        monkeypatch.setattr(
            asset_gen,
            "judge_character_consistency",
            lambda reference_bytes, image_bytes, criteria: CharacterJudgeResult(
                available=False,
                approved=False,
                score=0,
                issues=["no judge available"],
            ),
        )

        manifest = generate_worksheet_assets(
            [ScenePlan(1, "pointing at picture cards", "pointing", "sunny")],
            {},
            "scene_judge_unavailable",
            identity=CharacterIdentity(
                base_character="ian_learning_buddy",
                base_image_path=str(ref_path),
                reference_image_dir=str(tmp_path),
                canonical_reference_path=None,
                pose_reference_path=None,
                character_block="Ian has rainbow spiky hair.",
                scene_guidelines="Keep Ian consistent.",
                item_style_notes="",
                equipped_items={},
                identity_version="identity_v1_scene_judge_unavailable",
            ),
        )

        assert manifest is not None
        assert Path(manifest.scene_paths[1]).read_bytes() == b"canonical local pose bytes"

    def test_rejected_scene_uses_resolved_pose_reference_without_generic_drawing(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from PIL import Image

        from render import asset_gen

        pose_ref = tmp_path / "pose_pointing.png"
        Image.new("RGBA", (4, 4), "#123456").save(pose_ref)
        pose_bytes = pose_ref.read_bytes()
        monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def fake_generate_scene(
            prompt: str,
            output_path: str,
            ref_bytes: bytes | None,
            **kwargs: object,
        ) -> str:
            Path(output_path).write_bytes(b"rejected ai bytes")
            return output_path

        monkeypatch.setattr(asset_gen, "_generate_scene", fake_generate_scene)
        monkeypatch.setattr(
            asset_gen,
            "judge_character_consistency",
            lambda reference_bytes, image_bytes, criteria: CharacterJudgeResult(
                available=True,
                approved=False,
                score=2,
                issues=["identity changed"],
            ),
        )

        manifest = generate_worksheet_assets(
            [ScenePlan(1, "pointing at picture cards", "pointing", "sunny")],
            {},
            "scene_pose_reference_fallback",
            identity=CharacterIdentity(
                base_character="ian_learning_buddy",
                base_image_path=None,
                reference_image_dir=str(tmp_path),
                canonical_reference_path=None,
                pose_reference_path=str(pose_ref),
                character_block="Ian has rainbow spiky hair.",
                scene_guidelines="Keep Ian consistent.",
                item_style_notes="",
                equipped_items={},
                identity_version="identity_v1_scene_pose_reference_fallback",
            ),
        )

        assert manifest is not None
        scene_path = Path(manifest.scene_paths[1])
        assert scene_path.read_bytes() == pose_bytes
        assert scene_path.read_bytes() != b"rejected ai bytes"
        assert (scene_path.parent / "scene_1_rejected.json").exists()
