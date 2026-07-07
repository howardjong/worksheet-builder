"""Shared pacing bands for UFLI audio companion clip families.

Single source of truth consumed by the judge, audit, and fallback modules.
"""

from __future__ import annotations

from experiments.corpus_ufli.audio_companion_schema import AudioClipKind

# Conservative child-directed pacing bands for ages 5-8, set below the 150 WPM
# TTS research baseline reported for older students and aligned to explicit,
# decoding-first instruction where slower segmented delivery is preferable.
# Each entry maps a clip family to (target_wpm, min_wpm, max_wpm).
PACING_PROFILES: dict[AudioClipKind, tuple[float, float, float]] = {
    "lesson_instruction": (92.0, 78.0, 108.0),
    "phoneme_model": (58.0, 35.0, 75.0),
    "word_model": (78.0, 45.0, 92.0),
    "passage_sentence": (108.0, 92.0, 122.0),
    "passage_full": (115.0, 100.0, 128.0),
    "review": (92.0, 78.0, 108.0),
}

SANE_SINGLE_WORD_MIN_MS = 600
SANE_SINGLE_WORD_MAX_MS = 2500

# Flat fallback range used by the audit when segment type is unknown.
FLAT_AUDIT_WPM_RANGE: tuple[float, float] = (80.0, 220.0)
