"""Tests for shared pacing bands in corpus.ufli.pacing."""

from __future__ import annotations

from typing import get_args

from corpus.ufli.audio_companion_schema import AudioClipKind
from corpus.ufli.pacing import FLAT_AUDIT_WPM_RANGE, PACING_PROFILES


def test_all_clip_kinds_have_pacing_profiles() -> None:
    all_kinds = set(get_args(AudioClipKind))
    profiled_kinds = set(PACING_PROFILES.keys())
    assert profiled_kinds == all_kinds, f"Missing profiles for: {all_kinds - profiled_kinds}"


def test_pacing_profiles_return_correct_tuples() -> None:
    for kind, band in PACING_PROFILES.items():
        target, min_wpm, max_wpm = band
        assert isinstance(target, float), f"{kind} target is not float"
        assert isinstance(min_wpm, float), f"{kind} min is not float"
        assert isinstance(max_wpm, float), f"{kind} max is not float"
        assert min_wpm < target < max_wpm, f"{kind} band order is wrong: {band}"


def test_flat_audit_wpm_range_is_valid() -> None:
    assert len(FLAT_AUDIT_WPM_RANGE) == 2
    assert FLAT_AUDIT_WPM_RANGE[0] < FLAT_AUDIT_WPM_RANGE[1]
