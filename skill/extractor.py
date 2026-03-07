"""Rule-based skill extraction from SourceWorksheetModel → LiteracySkillModel."""

from __future__ import annotations

import re

from extract.schema import SourceWorksheetModel
from skill.schema import LiteracySkillModel, SourceItem
from skill.taxonomy import match_phonics_pattern

_LESSON_PATTERN = re.compile(r"lesson\s+(\d+)", re.IGNORECASE)


def extract_skill(source: SourceWorksheetModel) -> LiteracySkillModel:
    """Extract the targeted literacy skill from a source worksheet.

    Dispatches based on source.template_type:
    - ufli_word_work → phonics extraction
    - ufli_decodable_story → fluency extraction
    - unknown → generic fallback
    """
    if source.template_type == "ufli_word_work":
        return _extract_word_work(source)
    elif source.template_type == "ufli_decodable_story":
        return _extract_decodable_story(source)
    else:
        return _extract_generic(source)


def _extract_word_work(source: SourceWorksheetModel) -> LiteracySkillModel:
    """Extract skill from UFLI Word Work page.

    Rich skill signals:
    1. concept_label gives explicit pattern (e.g., "-all, -oll, -ull")
    2. sample_words gives target word list
    3. word_chain gives manipulation sequence
    4. Domain is almost always "phonics"
    5. Grade level inferred from lesson number and word complexity
    """
    concept_text = ""
    target_words: list[str] = []
    source_items: list[SourceItem] = []
    confidences: list[float] = []
    lesson_number: int | None = None

    for i, region in enumerate(source.regions):
        confidences.append(region.confidence)

        if region.type == "concept_label":
            concept_text = region.content

        elif region.type == "sample_words":
            words = _extract_words(region.content)
            target_words.extend(words)
            source_items.append(
                SourceItem(
                    item_type="word_list",
                    content=region.content,
                    source_region_index=i,
                )
            )

        elif region.type == "word_chain":
            source_items.append(
                SourceItem(
                    item_type="word_chain",
                    content=region.content,
                    source_region_index=i,
                )
            )
            # Extract words from chains (split on arrows)
            chain_words = _extract_chain_words(region.content)
            target_words.extend(chain_words)

        elif region.type == "chain_script":
            source_items.append(
                SourceItem(
                    item_type="word_chain",
                    content=region.content,
                    source_region_index=i,
                )
            )

        elif region.type == "sight_word_list":
            words = _extract_words(region.content)
            target_words.extend(words)
            source_items.append(
                SourceItem(
                    item_type="sight_words",
                    content=region.content,
                    source_region_index=i,
                )
            )

        elif region.type == "practice_sentences":
            source_items.append(
                SourceItem(
                    item_type="sentence",
                    content=region.content,
                    source_region_index=i,
                )
            )

        elif region.type == "title":
            m = _LESSON_PATTERN.search(region.content)
            if m:
                lesson_number = int(m.group(1))

    # Determine specific phonics skill from concept label
    specific_skill = "phonics_pattern"
    if concept_text:
        matched = match_phonics_pattern(concept_text)
        if matched:
            specific_skill = matched
        else:
            # Use the concept text itself as the skill description
            specific_skill = _normalize_concept(concept_text)

    # Infer grade level from lesson number
    grade_level = _grade_from_lesson(lesson_number)

    # Build learning objectives
    objectives = _build_word_work_objectives(specific_skill, concept_text, target_words)

    # Response types for word work
    response_types = ["write", "read_aloud"]
    if any(r.type == "practice_sentences" for r in source.regions):
        response_types.append("trace")

    # Deduplicate target words preserving order
    target_words = _dedupe_preserve_order(target_words)

    # Confidence: average of region confidences, weighted down if concept label missing
    extraction_confidence = _compute_confidence(confidences, has_concept=bool(concept_text))

    return LiteracySkillModel(
        grade_level=grade_level,
        domain="phonics",
        specific_skill=specific_skill,
        learning_objectives=objectives,
        target_words=target_words,
        response_types=response_types,
        source_items=source_items,
        extraction_confidence=extraction_confidence,
        template_type=source.template_type,
    )


def _extract_decodable_story(source: SourceWorksheetModel) -> LiteracySkillModel:
    """Extract skill from UFLI Decodable Story page.

    Primary domain is "fluency" (decodable_text).
    Target pattern extracted from story title or passage word frequency.
    """
    story_title = ""
    passage_text = ""
    source_items: list[SourceItem] = []
    confidences: list[float] = []
    lesson_number: int | None = None

    for i, region in enumerate(source.regions):
        confidences.append(region.confidence)

        if region.type == "story_title":
            story_title = region.content
            source_items.append(
                SourceItem(
                    item_type="passage",
                    content=region.content,
                    source_region_index=i,
                    metadata={"role": "title"},
                )
            )

        elif region.type == "decodable_passage":
            passage_text += " " + region.content
            source_items.append(
                SourceItem(
                    item_type="passage",
                    content=region.content,
                    source_region_index=i,
                )
            )

        elif region.type == "title":
            m = _LESSON_PATTERN.search(region.content)
            if m:
                lesson_number = int(m.group(1))

    passage_text = passage_text.strip()

    # Try to identify the target phonics pattern from the passage
    target_pattern = _identify_passage_pattern(story_title, passage_text)
    specific_skill = "decodable_text"
    if target_pattern:
        specific_skill = f"decodable_text_{target_pattern}"

    # Extract high-frequency pattern words from passage
    target_words = _extract_passage_target_words(passage_text, target_pattern)

    grade_level = _grade_from_lesson(lesson_number)

    objectives = [
        "Read a decodable passage with fluency and accuracy",
    ]
    if target_pattern:
        objectives.append(f"Apply {target_pattern} pattern knowledge in connected text")

    response_types = ["read_aloud"]

    extraction_confidence = _compute_confidence(
        confidences, has_concept=bool(target_pattern)
    )

    return LiteracySkillModel(
        grade_level=grade_level,
        domain="fluency",
        specific_skill=specific_skill,
        learning_objectives=objectives,
        target_words=target_words,
        response_types=response_types,
        source_items=source_items,
        extraction_confidence=extraction_confidence,
        template_type=source.template_type,
    )


def _extract_generic(source: SourceWorksheetModel) -> LiteracySkillModel:
    """Fallback extraction for unknown layouts."""
    source_items: list[SourceItem] = []
    target_words: list[str] = []
    confidences: list[float] = []

    for i, region in enumerate(source.regions):
        confidences.append(region.confidence)

        if region.type == "word_list":
            words = _extract_words(region.content)
            target_words.extend(words)
            source_items.append(
                SourceItem(
                    item_type="word_list",
                    content=region.content,
                    source_region_index=i,
                )
            )
        elif region.type == "question":
            source_items.append(
                SourceItem(
                    item_type="sentence",
                    content=region.content,
                    source_region_index=i,
                )
            )

    # Try to identify domain from title/instructions
    domain = "phonics"  # default
    specific_skill = "unknown"
    response_types = ["write"]

    for region in source.regions:
        text_lower = region.content.lower()
        if "read" in text_lower or "story" in text_lower:
            domain = "fluency"
            specific_skill = "passage_reading"
            response_types = ["read_aloud"]
            break
        if "write" in text_lower or "sentence" in text_lower:
            domain = "writing"
            specific_skill = "sentence_writing"
            response_types = ["write"]
            break

    target_words = _dedupe_preserve_order(target_words)

    extraction_confidence = _compute_confidence(confidences, has_concept=False) * 0.7

    return LiteracySkillModel(
        grade_level="1",
        domain=domain,
        specific_skill=specific_skill,
        learning_objectives=[f"Practice {domain} skills"],
        target_words=target_words,
        response_types=response_types,
        source_items=source_items,
        extraction_confidence=extraction_confidence,
        template_type=source.template_type,
    )


# --- Helpers ---


def _extract_words(text: str) -> list[str]:
    """Extract individual words from a region, cleaning punctuation."""
    # Remove common markers
    cleaned = text.replace("*", "").replace("♥", "").replace("❤", "")
    # Split on commas, spaces, slashes
    parts = re.split(r"[,/\s]+", cleaned)
    words = [w.strip().lower() for w in parts if w.strip() and w.strip().isalpha()]
    return words


def _extract_chain_words(text: str) -> list[str]:
    """Extract words from a chain like 'all → fall → mall → small'."""
    # Remove leading numbers/dots
    cleaned = re.sub(r"^\d+\.\s*", "", text)
    # Split on arrows
    parts = re.split(r"[→\->]+", cleaned)
    words = [w.strip().lower() for w in parts if w.strip() and w.strip().isalpha()]
    return words


def _normalize_concept(text: str) -> str:
    """Normalize a concept label to a skill identifier."""
    # Extract patterns like "-all, -oll, -ull" or "a_e" from concept text
    cleaned = text.lower().strip()
    # Remove common prefixes
    for prefix in ["new concept and sample words", "new concept", "sample words"]:
        cleaned = cleaned.replace(prefix, "").strip()
    # Clean up
    cleaned = re.sub(r"[^a-z0-9_\-,\s]", "", cleaned).strip()
    if not cleaned:
        return "phonics_pattern"
    return cleaned


def _grade_from_lesson(lesson_number: int | None) -> str:
    """Infer grade level from UFLI lesson number.

    UFLI Foundations rough mapping:
    - Lessons 1-30: K (letter sounds, basic CVC)
    - Lessons 31-70: Grade 1 (digraphs, blends, CVCe)
    - Lessons 71-100: Grade 2 (vowel teams, r-controlled)
    - Lessons 101+: Grade 3 (multisyllable, morphology)
    """
    if lesson_number is None:
        return "1"  # default
    if lesson_number <= 30:
        return "K"
    if lesson_number <= 70:
        return "1"
    if lesson_number <= 100:
        return "2"
    return "3"


def _build_word_work_objectives(
    specific_skill: str, concept_text: str, target_words: list[str]
) -> list[str]:
    """Build learning objectives for a word work page."""
    objectives: list[str] = []

    if concept_text:
        objectives.append(f"Identify and read words with the {concept_text.strip()} pattern")

    skill_labels: dict[str, str] = {
        "cvc_blending": "Blend CVC words",
        "cvce": "Read and spell CVCe (silent-e) words",
        "digraphs": "Read words with consonant digraphs",
        "blends": "Read words with consonant blends",
        "vowel_teams": "Read words with vowel teams",
        "r_controlled": "Read words with r-controlled vowels",
        "multisyllable": "Decode multisyllable words",
        "letter_sound": "Match letters to their sounds",
    }

    label = skill_labels.get(specific_skill)
    if label and label not in objectives:
        objectives.append(label)

    if target_words:
        objectives.append("Build and manipulate words using target patterns")

    if not objectives:
        objectives.append("Practice phonics skills")

    return objectives


def _identify_passage_pattern(title: str, passage: str) -> str | None:
    """Try to identify the target phonics pattern in a decodable passage."""
    # Check title for pattern hints
    if title:
        matched = match_phonics_pattern(title)
        if matched:
            return matched

    # Look for high-frequency patterns in passage words
    if not passage:
        return None

    words = re.findall(r"[a-zA-Z]+", passage.lower())
    if not words:
        return None

    # Check for CVCe pattern (words ending in consonant+e with internal vowel)
    cvce_pattern = re.compile(r"^[a-z]*[aeiou][a-z]e$")
    cvce_count = sum(1 for w in words if cvce_pattern.match(w) and len(w) >= 3)
    if cvce_count >= 3:
        return "cvce"

    return None


def _extract_passage_target_words(passage: str, pattern: str | None) -> list[str]:
    """Extract target words from a passage based on the identified pattern."""
    if not passage:
        return []

    words = re.findall(r"[a-zA-Z]+", passage.lower())
    if not words:
        return []

    if pattern == "cvce":
        cvce_re = re.compile(r"^[a-z]*[aeiou][a-z]e$")
        targets = [w for w in words if cvce_re.match(w) and len(w) >= 3]
        return _dedupe_preserve_order(targets)

    # Default: return content words (skip very short/common words)
    stop_words = {
        "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
        "has", "had", "have", "do", "did", "does", "to", "of", "in", "on",
        "at", "by", "for", "and", "but", "or", "not", "no", "so", "if",
        "it", "its", "he", "she", "we", "they", "i", "me", "my", "his",
        "her", "our", "us", "them", "this", "that",
    }
    content_words = [w for w in words if w not in stop_words and len(w) >= 3]
    return _dedupe_preserve_order(content_words)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _compute_confidence(
    region_confidences: list[float], has_concept: bool
) -> float:
    """Compute overall extraction confidence."""
    if not region_confidences:
        return 0.0

    avg = sum(region_confidences) / len(region_confidences)

    # Boost if we found a concept label (strong skill signal)
    if has_concept:
        return min(avg * 1.05, 1.0)

    # Penalize if no concept label found
    return avg * 0.85
