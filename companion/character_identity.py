"""Resolve Learning Buddy identity inputs for avatar and worksheet art."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from companion.schema import CharacterStyleSheet, LearnerProfile
from theme.schema import CharacterSpec

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _REPO_ROOT / "assets"
_CHARACTERS_DIR = _ASSETS_DIR / "characters"

_CANONICAL_REFERENCE_NAMES = (
    "ref_front_character_crop.png",
    "ref_front.png",
    "local_fallback_sprite.png",
)

_POSE_REFERENCE_NAMES: dict[str, tuple[str, ...]] = {
    "pointing": ("pose_pointing.png",),
    "match": ("pose_pointing.png",),
    "writing": ("pose_working.png",),
    "building": ("pose_working.png",),
    "working": ("pose_working.png",),
    "reading": ("pose_front.png",),
    "read_aloud": ("pose_front.png",),
    "thinking": ("pose_front.png",),
    "listening": ("pose_front.png",),
    "front": ("pose_front.png", "ref_front_character_crop.png", "ref_front.png"),
    "celebrating": ("pose_celebration.png", "ref_celebration_pose.png"),
    "celebration": ("pose_celebration.png", "ref_celebration_pose.png"),
    "backpack": ("pose_backpack.png", "ref_backpack_pose.png"),
}


class CharacterIdentity(BaseModel):
    """Resolved character inputs shared by avatar, scene, and cover generation."""

    base_character: str
    base_image_path: str | None
    reference_image_dir: str | None
    canonical_reference_path: str | None
    pose_reference_path: str | None
    character_block: str
    scene_guidelines: str
    item_style_notes: str
    equipped_items: dict[str, str]
    identity_version: str


def resolve_character_identity(
    profile: LearnerProfile,
    theme_id: str,
    pose: str | None = None,
    character_spec: CharacterSpec | None = None,
) -> CharacterIdentity:
    """Resolve local character identity inputs from profile, style pack, and theme."""

    avatar = profile.avatar
    base_character = avatar.base_character if avatar else "rainbow_roblox"
    style_sheet = avatar.style_sheet if avatar and avatar.style_sheet else None
    equipped_items = dict(sorted((avatar.equipped_items if avatar else {}).items()))

    base_image_path = _existing_relative_path(_CHARACTERS_DIR / f"{base_character}.png")
    reference_image_dir = _reference_dir(style_sheet)
    canonical_reference_path = _canonical_reference_path(style_sheet, reference_image_dir)
    pose_reference_path = _pose_reference_path(style_sheet, reference_image_dir, pose)

    character_block = _character_block(style_sheet, character_spec)
    scene_guidelines = _scene_guidelines(style_sheet, character_spec)
    item_style_notes = _item_style_notes(style_sheet, character_spec)

    identity_version = _identity_version(
        theme_id=theme_id,
        base_character=base_character,
        character_block=character_block,
        reference_image_dir=reference_image_dir,
        canonical_reference_path=canonical_reference_path,
        pose_reference_path=pose_reference_path,
        equipped_items=equipped_items,
        style_sheet=style_sheet,
    )

    return CharacterIdentity(
        base_character=base_character,
        base_image_path=base_image_path,
        reference_image_dir=reference_image_dir,
        canonical_reference_path=canonical_reference_path,
        pose_reference_path=pose_reference_path,
        character_block=character_block,
        scene_guidelines=scene_guidelines,
        item_style_notes=item_style_notes,
        equipped_items=equipped_items,
        identity_version=identity_version,
    )


def _reference_dir(style_sheet: CharacterStyleSheet | None) -> str | None:
    if not style_sheet or not style_sheet.reference_image_dir:
        return None
    ref_dir = Path(style_sheet.reference_image_dir)
    if ref_dir.is_absolute():
        return str(ref_dir) if ref_dir.exists() else None
    full_path = _REPO_ROOT / ref_dir
    return style_sheet.reference_image_dir if full_path.exists() else None


def _canonical_reference_path(
    style_sheet: CharacterStyleSheet | None,
    reference_image_dir: str | None,
) -> str | None:
    if not reference_image_dir:
        return None

    if style_sheet and style_sheet.canonical_reference_path:
        explicit = _resolve_pack_path(reference_image_dir, style_sheet.canonical_reference_path)
        if explicit.exists():
            return _display_path(explicit)

    ref_dir = _repo_path(reference_image_dir)
    for filename in _CANONICAL_REFERENCE_NAMES:
        candidate = ref_dir / filename
        if candidate.exists():
            return _display_path(candidate)
    return None


def _pose_reference_path(
    style_sheet: CharacterStyleSheet | None,
    reference_image_dir: str | None,
    pose: str | None,
) -> str | None:
    if not reference_image_dir or not pose:
        return None

    normalized_pose = pose.lower()
    if style_sheet and normalized_pose in style_sheet.pose_references:
        explicit = _resolve_pack_path(
            reference_image_dir,
            style_sheet.pose_references[normalized_pose],
        )
        if explicit.exists():
            return _display_path(explicit)

    ref_dir = _repo_path(reference_image_dir)
    for filename in _POSE_REFERENCE_NAMES.get(normalized_pose, (f"pose_{normalized_pose}.png",)):
        candidate = ref_dir / filename
        if candidate.exists():
            return _display_path(candidate)
    return None


def _character_block(
    style_sheet: CharacterStyleSheet | None,
    character_spec: CharacterSpec | None,
) -> str:
    if style_sheet and style_sheet.character_block:
        return style_sheet.character_block
    if character_spec:
        parts = [
            character_spec.style_description,
            character_spec.body_description,
            character_spec.face_description,
            character_spec.color_palette,
        ]
        return " ".join(part.strip() for part in parts if part.strip())
    return "A friendly cartoon learning buddy."


def _scene_guidelines(
    style_sheet: CharacterStyleSheet | None,
    character_spec: CharacterSpec | None,
) -> str:
    if style_sheet and style_sheet.scene_guidelines:
        return style_sheet.scene_guidelines
    if not character_spec:
        return ""
    parts = []
    if character_spec.scene_environment:
        parts.append(character_spec.scene_environment.strip())
    if character_spec.scene_elements:
        parts.append("Scene elements: " + ", ".join(character_spec.scene_elements))
    return " ".join(parts)


def _item_style_notes(
    style_sheet: CharacterStyleSheet | None,
    character_spec: CharacterSpec | None,
) -> str:
    if style_sheet and style_sheet.item_style_notes:
        return style_sheet.item_style_notes
    if character_spec and character_spec.art_style:
        return f"Render accessories in the {character_spec.art_style} style."
    return ""


def _identity_version(
    *,
    theme_id: str,
    base_character: str,
    character_block: str,
    reference_image_dir: str | None,
    canonical_reference_path: str | None,
    pose_reference_path: str | None,
    equipped_items: dict[str, str],
    style_sheet: CharacterStyleSheet | None,
) -> str:
    payload = {
        "version": "identity_v1",
        "theme_id": theme_id,
        "base_character": base_character,
        "character_block": character_block,
        "reference_image_dir": reference_image_dir,
        "canonical_reference": (
            Path(canonical_reference_path).name if canonical_reference_path else None
        ),
        "canonical_reference_fingerprint": _file_fingerprint(canonical_reference_path),
        "pose_reference": Path(pose_reference_path).name if pose_reference_path else None,
        "pose_reference_fingerprint": _file_fingerprint(pose_reference_path),
        "equipped_items": equipped_items,
        "style_sheet_identity_version": style_sheet.identity_version if style_sheet else None,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()[:16]
    return f"identity_v1_{digest}"


def _existing_relative_path(path: Path) -> str | None:
    return _display_path(path) if path.exists() else None


def _file_fingerprint(path: str | None) -> str | None:
    if not path:
        return None
    resolved = _repo_path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    stat = resolved.stat()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()[:16]
    return f"{digest}:{stat.st_size}"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else _REPO_ROOT / candidate


def _resolve_pack_path(reference_image_dir: str, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    repo_candidate = _REPO_ROOT / candidate
    if repo_candidate.exists():
        return repo_candidate
    return _repo_path(reference_image_dir) / candidate
