"""K-3 literacy skill taxonomy — 6 domains with grade-appropriate specific skills."""

from __future__ import annotations

from typing import Any

LITERACY_DOMAINS: dict[str, dict[str, Any]] = {
    "phonemic_awareness": {
        "skills": [
            "rhyme_identification",
            "syllable_counting",
            "phoneme_segmentation",
            "phoneme_blending",
            "phoneme_manipulation",
        ],
        "grade_range": ["K", "1"],
    },
    "phonics": {
        "skills": [
            "letter_sound",
            "cvc_blending",
            "cvce",
            "digraphs",
            "blends",
            "vowel_teams",
            "r_controlled",
            "multisyllable",
        ],
        "grade_range": ["K", "1", "2", "3"],
    },
    "fluency": {
        "skills": [
            "decodable_text",
            "sight_words",
            "passage_reading",
            "timed_reading",
        ],
        "grade_range": ["1", "2", "3"],
    },
    "vocabulary": {
        "skills": [
            "context_clues",
            "word_parts",
            "academic_vocabulary",
        ],
        "grade_range": ["2", "3"],
    },
    "comprehension": {
        "skills": [
            "literal_questions",
            "inference",
            "main_idea",
            "text_evidence",
            "summarizing",
            "comparing_texts",
        ],
        "grade_range": ["1", "2", "3"],
    },
    "writing": {
        "skills": [
            "letter_formation",
            "sentence_writing",
            "paragraph_organization",
        ],
        "grade_range": ["K", "1", "2", "3"],
    },
}


def get_domain_skills(domain: str) -> list[str]:
    """Return list of specific skills for a domain."""
    entry = LITERACY_DOMAINS.get(domain)
    if entry is None:
        return []
    return list(entry["skills"])


def get_domain_grade_range(domain: str) -> list[str]:
    """Return valid grade range for a domain."""
    entry = LITERACY_DOMAINS.get(domain)
    if entry is None:
        return []
    return list(entry["grade_range"])


def is_valid_skill(domain: str, skill: str) -> bool:
    """Check if a specific skill belongs to the given domain."""
    return skill in get_domain_skills(domain)


def all_domains() -> list[str]:
    """Return all domain names."""
    return list(LITERACY_DOMAINS.keys())


# Common phonics patterns for UFLI concept label matching
PHONICS_PATTERNS: dict[str, str] = {
    # CVC
    "cvc": "cvc_blending",
    "short": "cvc_blending",
    # CVCe / silent-e
    "a_e": "cvce",
    "i_e": "cvce",
    "o_e": "cvce",
    "u_e": "cvce",
    "e_e": "cvce",
    "silent e": "cvce",
    "magic e": "cvce",
    "cvce": "cvce",
    # Digraphs
    "sh": "digraphs",
    "ch": "digraphs",
    "th": "digraphs",
    "wh": "digraphs",
    "ck": "digraphs",
    "ph": "digraphs",
    # Blends
    "bl": "blends",
    "cl": "blends",
    "fl": "blends",
    "gl": "blends",
    "pl": "blends",
    "sl": "blends",
    "br": "blends",
    "cr": "blends",
    "dr": "blends",
    "fr": "blends",
    "gr": "blends",
    "pr": "blends",
    "tr": "blends",
    "sc": "blends",
    "sk": "blends",
    "sm": "blends",
    "sn": "blends",
    "sp": "blends",
    "st": "blends",
    "sw": "blends",
    # Vowel teams
    "ai": "vowel_teams",
    "ay": "vowel_teams",
    "ea": "vowel_teams",
    "ee": "vowel_teams",
    "oa": "vowel_teams",
    "ow": "vowel_teams",
    "oo": "vowel_teams",
    "ou": "vowel_teams",
    "oi": "vowel_teams",
    "oy": "vowel_teams",
    # R-controlled
    "ar": "r_controlled",
    "er": "r_controlled",
    "ir": "r_controlled",
    "or": "r_controlled",
    "ur": "r_controlled",
    # Word families (map to phonics subcategories)
    "-all": "cvc_blending",
    "-oll": "cvc_blending",
    "-ull": "cvc_blending",
    "-ill": "cvc_blending",
    "-ell": "cvc_blending",
    "-ack": "cvc_blending",
    "-ick": "cvc_blending",
    "-ock": "cvc_blending",
    "-uck": "cvc_blending",
    "-ank": "cvc_blending",
    "-ink": "cvc_blending",
    "-unk": "cvc_blending",
    "-ang": "cvc_blending",
    "-ing": "cvc_blending",
    "-ung": "cvc_blending",
}


def match_phonics_pattern(concept_text: str) -> str | None:
    """Match a concept label to a specific phonics skill.

    Tries longer patterns first to avoid partial matches.
    Short patterns (2 chars) require word boundaries or explicit separators
    to avoid false positives (e.g., "st" in "just").
    """
    import re

    text_lower = concept_text.lower()

    # Sort patterns by length descending so longer matches win
    sorted_patterns = sorted(PHONICS_PATTERNS.keys(), key=len, reverse=True)

    for pattern in sorted_patterns:
        if len(pattern) <= 2:
            # Short patterns need word boundary or separator context
            escaped = re.escape(pattern)
            if re.search(rf"(?:^|[\s,/\-])({escaped})(?:[\s,/\-]|$)", text_lower):
                return PHONICS_PATTERNS[pattern]
        else:
            if pattern in text_lower:
                return PHONICS_PATTERNS[pattern]

    return None
