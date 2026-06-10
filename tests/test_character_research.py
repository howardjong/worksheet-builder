"""Tests for companion/character_research.py and theme-aware avatar pipeline."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image
from pytest import MonkeyPatch

from companion.character_research import (
    _compose_character_block,
    _compose_item_style_notes,
    _compose_scene_guidelines,
    _spec_needs_research,
    research_character_style,
)
from companion.schema import (
    AvatarConfig,
    CharacterStyleSheet,
    LearnerProfile,
    Preferences,
)
from theme.engine import load_theme
from theme.schema import CharacterSpec


class TestCharacterSpec:
    def test_roblox_obby_has_character_spec(self) -> None:
        theme = load_theme("roblox_obby")
        assert theme.character_spec.art_style == "roblox_2d_comic_avatar"
        assert "blocky" in theme.character_spec.body_description.lower()
        assert "lightning bolt" in theme.character_spec.body_description
        assert len(theme.character_spec.judge_criteria) >= 5
        assert len(theme.character_spec.scene_elements) >= 3

    def test_space_theme_has_character_spec(self) -> None:
        theme = load_theme("space")
        assert theme.character_spec.art_style == "space_cartoon"
        assert theme.character_spec.style_description != ""

    def test_spec_needs_research_empty(self) -> None:
        assert _spec_needs_research(CharacterSpec())

    def test_spec_needs_research_populated(self) -> None:
        spec = CharacterSpec(
            style_description="blocky 3D",
            body_description="large head",
        )
        assert not _spec_needs_research(spec)


class TestComposeCharacterBlock:
    def test_uses_spec_descriptions(self) -> None:
        spec = CharacterSpec(
            style_description="Roblox-style 3D cartoon",
            body_description="blocky R15 rig",
            face_description="2D decal smiley face",
            color_palette="bright saturated colors",
        )
        prefs = Preferences()
        profile = LearnerProfile(name="Test", grade_level="1")
        block = _compose_character_block(spec, prefs, profile)
        assert "Roblox-style 3D cartoon" in block
        assert "blocky R15 rig" in block
        assert "2D decal smiley face" in block
        assert "bright saturated colors" in block

    def test_includes_avatar_colors(self) -> None:
        spec = CharacterSpec(style_description="test style")
        prefs = Preferences()
        profile = LearnerProfile(
            name="Test",
            grade_level="1",
            avatar=AvatarConfig(
                base_colors={"primary": "#FF0000", "secondary": "#00FF00"},
            ),
        )
        block = _compose_character_block(spec, prefs, profile)
        assert "#FF0000" in block
        assert "#00FF00" in block

    def test_fallback_for_empty_spec(self) -> None:
        block = _compose_character_block(
            CharacterSpec(),
            Preferences(),
            LearnerProfile(name="Test", grade_level="1"),
        )
        assert "cartoon" in block.lower()


class TestComposeSceneGuidelines:
    def test_includes_environment_and_elements(self) -> None:
        spec = CharacterSpec(
            scene_environment="floating platforms over lava",
            scene_elements=["neon blocks", "spinning coins"],
        )
        guidelines = _compose_scene_guidelines(spec)
        assert "floating platforms" in guidelines
        assert "neon blocks" in guidelines
        assert "spinning coins" in guidelines

    def test_empty_for_no_spec(self) -> None:
        assert _compose_scene_guidelines(CharacterSpec()) == ""


class TestComposeItemStyleNotes:
    def test_includes_art_style(self) -> None:
        spec = CharacterSpec(art_style="roblox_3d_cartoon")
        notes = _compose_item_style_notes(spec)
        assert "roblox_3d_cartoon" in notes

    def test_empty_for_no_style(self) -> None:
        assert _compose_item_style_notes(CharacterSpec()) == ""


class TestCharacterStyleSheet:
    def test_style_sheet_on_avatar_config(self) -> None:
        sheet = CharacterStyleSheet(
            character_block="test block",
            theme_id="roblox_obby",
        )
        config = AvatarConfig(style_sheet=sheet)
        assert config.style_sheet is not None
        assert config.style_sheet.character_block == "test block"

    def test_avatar_config_none_style_sheet_default(self) -> None:
        config = AvatarConfig()
        assert config.style_sheet is None

    def test_style_sheet_serialization(self) -> None:
        sheet = CharacterStyleSheet(
            character_block="blocky character",
            theme_id="roblox_obby",
            scene_guidelines="obby environment",
            item_style_notes="match roblox style",
            generated_at="2026-03-18T00:00:00",
        )
        data = sheet.model_dump()
        restored = CharacterStyleSheet.model_validate(data)
        assert restored.character_block == "blocky character"
        assert restored.theme_id == "roblox_obby"

    def test_optional_identity_reference_fields_round_trip(self) -> None:
        sheet = CharacterStyleSheet(
            character_block="blocky character",
            theme_id="roblox_obby",
            reference_image_dir="assets/style_sheets/ian_roblox_buddy",
            canonical_reference_path="assets/style_sheets/ian_roblox_buddy/ref_front_character_crop.png",
            pose_references={"pointing": "assets/style_sheets/ian_roblox_buddy/pose_pointing.png"},
            identity_version="identity_v1_static",
        )

        restored = CharacterStyleSheet.model_validate(sheet.model_dump())

        assert restored.canonical_reference_path == sheet.canonical_reference_path
        assert restored.pose_references == sheet.pose_references
        assert restored.identity_version == "identity_v1_static"

    def test_variant_generation_and_judge_share_canonical_reference(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        from companion import generate_overlays

        with tempfile.TemporaryDirectory() as tmpdir:
            ref_path = Path(tmpdir) / "ref_front_character_crop.png"
            Image.new("RGBA", (4, 4), "#123456").save(ref_path)
            generated = io.BytesIO()
            Image.new("RGBA", (4, 4), "#654321").save(generated, format="PNG")
            generated_bytes = generated.getvalue()
            observed: dict[str, bytes] = {}

            def fake_generate(
                equipped_items: dict[str, str],
                style_sheet: CharacterStyleSheet | None,
                reference_bytes: bytes,
            ) -> bytes:
                observed["generation"] = reference_bytes
                return generated_bytes

            def fake_judge(
                ref_bytes: bytes,
                image_bytes: bytes,
                equipped_items: dict[str, str],
                character_spec: object | None = None,
            ) -> dict[str, object]:
                observed["judge"] = ref_bytes
                return {"passed": True, "score": 10, "issues": []}

            monkeypatch.setattr(generate_overlays, "_generate_single_variant", fake_generate)
            monkeypatch.setattr(generate_overlays, "_judge_variant", fake_judge)

            output_path = Path(tmpdir) / "variant.png"
            result = generate_overlays.generate_variant(
                {"backpack": "brown_backpack"},
                output_path,
                style_sheet=CharacterStyleSheet(reference_image_dir=tmpdir),
            )

            assert result == output_path
            assert observed["generation"] == ref_path.read_bytes()
            assert observed["judge"] == ref_path.read_bytes()


class TestResearchCharacterStyle:
    def test_produces_style_sheet_from_static_spec(self) -> None:
        """With skip_research + skip_images, uses only static theme spec."""
        theme = load_theme("roblox_obby")
        profile = LearnerProfile(
            name="TestKid",
            grade_level="1",
            avatar=AvatarConfig(),
            preferences=Preferences(
                favorite_themes=["roblox_obby"],
            ),
        )
        sheet = research_character_style(
            profile,
            theme,
            "roblox_obby",
            skip_images=True,
            skip_research=True,
        )
        assert sheet.theme_id == "roblox_obby"
        assert "blocky" in sheet.character_block.lower() or "R15" in sheet.character_block
        assert sheet.scene_guidelines != ""
        assert sheet.item_style_notes != ""
        assert sheet.generated_at != ""

    def test_empty_theme_produces_fallback(self) -> None:
        from theme.schema import ThemeConfig

        theme = ThemeConfig(name="empty")
        profile = LearnerProfile(name="Test", grade_level="1")
        sheet = research_character_style(
            profile,
            theme,
            "empty",
            skip_images=True,
            skip_research=True,
        )
        assert sheet.theme_id == "empty"
        assert "cartoon" in sheet.character_block.lower()
