"""Tests for character-consistent cover generation (offline; stubs only).

The cover (page 1) must hold the Learning Buddy identity the same way the
worksheet pages do: reference-conditioned generation, the character judge as a
fail-closed gate, bounded retries, provider fall-through, and the deterministic
local cover as the final fallback. Rejected AI covers are never cached.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from companion.character_identity import CharacterIdentity
from companion.character_judge import CharacterJudgeResult


def _png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (32, 48), "#FFFFFF")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


def _identity(ref_path: Path) -> CharacterIdentity:
    return CharacterIdentity(
        base_character="ian_learning_buddy",
        base_image_path=None,
        reference_image_dir=str(ref_path.parent),
        canonical_reference_path=str(ref_path),
        pose_reference_path=str(ref_path),
        character_block="Ian has rainbow spiky hair and a blue lightning shirt.",
        scene_guidelines="Calm printable learning panels.",
        item_style_notes="",
        equipped_items={},
        identity_version="identity_v_cover_test",
    )


def _ref(tmp_path: Path) -> Path:
    ref_path = tmp_path / "pose_celebration.png"
    ref_path.write_bytes(_png_bytes())
    return ref_path


def _verdict(approved: bool) -> CharacterJudgeResult:
    return CharacterJudgeResult(available=True, approved=approved, score=9 if approved else 3)


def _call_cover(tmp_path: Path, worksheet_hash: str = "coverhash") -> str | None:
    from render.asset_gen import generate_cover_image

    return generate_cover_image(
        skill_description="phonics: vowel teams",
        target_words=["rain", "play"],
        theme_spec=None,
        worksheet_hash=worksheet_hash,
        identity=_identity(_ref(tmp_path)),
    )


def test_cover_approved_on_first_attempt_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    ai_bytes = _png_bytes()
    provider = _StubProvider("stub", [ai_bytes])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [provider])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: _verdict(True))

    result = _call_cover(tmp_path)

    assert result is not None
    assert Path(result).exists()
    assert Path(result).read_bytes() == ai_bytes
    assert provider.calls == 1
    # The gate report is written before the cached image (torn-entry safety).
    assert (Path(result).parent / "cover_gates.json").exists()


def test_cover_regenerates_after_rejected_then_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    verdicts = iter([_verdict(False), _verdict(True)])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [provider])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: next(verdicts))

    result = _call_cover(tmp_path)

    assert result is not None
    assert provider.calls == 2


def test_cover_falls_through_to_next_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    working_bytes = _png_bytes()
    broken = _StubProvider("broken", [None])
    working = _StubProvider("working", [working_bytes])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [broken, working])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: _verdict(True))

    result = _call_cover(tmp_path)

    assert result is not None
    assert Path(result).read_bytes() == working_bytes
    assert broken.calls == 1
    assert working.calls == 1


def test_cover_total_failure_uses_local_fallback_and_does_not_cache_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    ai_bytes = _png_bytes()
    provider = _StubProvider("stub", [ai_bytes, ai_bytes, ai_bytes])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [provider])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: _verdict(False))

    result = _call_cover(tmp_path)

    assert result is not None
    assert Path(result).exists()
    # Quality-first budget: 3 attempts on the one provider before giving up.
    assert provider.calls == 3
    # The rejected AI bytes are never cached; the local deterministic cover is used.
    assert Path(result).read_bytes() != ai_bytes


def test_cover_no_providers_uses_local_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [])

    result = _call_cover(tmp_path)

    assert result is not None
    assert Path(result).exists()


def test_cover_cache_hit_skips_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from render import asset_gen

    monkeypatch.delenv("WORKSHEET_SKIP_ASSET_GEN", raising=False)
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    provider = _StubProvider("stub", [_png_bytes(), _png_bytes()])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [provider])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: _verdict(True))

    _call_cover(tmp_path)
    assert provider.calls == 1

    _call_cover(tmp_path)
    assert provider.calls == 1  # second render served from cache


def test_cover_skip_env_returns_none_without_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from render import asset_gen

    monkeypatch.setenv("WORKSHEET_SKIP_ASSET_GEN", "1")
    monkeypatch.setattr(asset_gen, "_CACHE_DIR", tmp_path / "cache")
    provider = _StubProvider("stub", [_png_bytes()])
    monkeypatch.setattr(asset_gen, "resolve_provider_chain", lambda: [provider])
    monkeypatch.setattr(asset_gen, "judge_character_consistency", lambda r, g, c: _verdict(True))

    result = _call_cover(tmp_path)

    assert result is None
    assert provider.calls == 0
