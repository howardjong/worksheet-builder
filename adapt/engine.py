"""ADHD activity adaptation engine — transforms LiteracySkillModel into AdaptedActivityModel."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from adapt.rules import (
    BRAIN_BREAK_PROMPTS,
    AccommodationRules,
    build_rules,
    get_substitute_format,
)
from adapt.schema import (
    ActivityChunk,
    ActivityItem,
    AdaptedActivityModel,
    Example,
    ScaffoldConfig,
    Step,
)
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CurriculumWordBank:
    """Retrieved curriculum references normalized for deterministic word checks."""

    lesson_ids: tuple[str, ...]
    concepts: tuple[str, ...]
    documents: tuple[str, ...]


def adapt_activity(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_prior_adaptations: list[dict[str, object]] | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> AdaptedActivityModel:
    """Transform a skill model into ADHD-optimized activity chunks.

    1. Build rules from profile (or use provided rules)
    2. Split source_items into chunks respecting size limits
    3. Generate instructions per chunk (numbered, bold verbs, grade-appropriate)
    4. Add worked example to first chunk
    5. Set response format per chunk
    6. Calculate time estimates
    7. Build self-assessment checklist
    8. Define decoration zones
    """
    if rules is None:
        rules = build_rules(profile)

    curriculum = _build_curriculum_word_bank(rag_curriculum_references)
    if curriculum:
        _, matched_targets = _prioritize_words_by_curriculum(skill.target_words, curriculum)
        if matched_targets:
            logger.info(
                "Curriculum context influencing single adaptation: lessons=%s matched_targets=%s",
                ",".join(curriculum.lesson_ids) or "unknown",
                ",".join(sorted(matched_targets)),
            )

    # Split items into chunks
    chunks = _build_chunks(skill, rules, curriculum=curriculum)

    # Apply scaffolding (worked example fades after first chunk)
    scaffolding = ScaffoldConfig(
        show_worked_example=True,
        fade_after_chunk=1,
        hint_level="full" if skill.grade_level in ("K", "1") else "partial",
    )

    # Build self-assessment items
    self_assessment = _build_self_assessment(skill)

    # Define decoration zones (safe areas that won't overlap content)
    decoration_zones = _define_decoration_zones()

    return AdaptedActivityModel(
        source_hash=_hash_str(skill.template_type + str(skill.target_words)),
        skill_model_hash=_hash_str(skill.model_dump_json()),
        learner_profile_hash=_hash_str(profile.model_dump_json()),
        grade_level=skill.grade_level,
        domain=skill.domain,
        specific_skill=skill.specific_skill,
        chunks=chunks,
        scaffolding=scaffolding,
        theme_id=theme_id,
        decoration_zones=decoration_zones,
        avatar_prompts=None,  # MVP: no companion layer
        self_assessment=self_assessment,
    )


def adapt_lesson(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_prior_adaptations: list[dict[str, object]] | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> list[AdaptedActivityModel]:
    """Transform a skill model into 2-3 ADHD-optimized mini-worksheets.

    Each mini-worksheet focuses on a different activity type for multi-sensory variety:
    1. Word Discovery — word-picture matching, trace, circle
    2. Word Builder — word chains, fill-blank, sight words
    3. Story Time — sentence completion, read-aloud passage, comprehension

    Returns a list of 1-3 AdaptedActivityModels, one per mini-worksheet.
    """
    if rules is None:
        rules = build_rules(profile)

    prior_adaptations = rag_prior_adaptations or []
    distractor_blacklist = _extract_distractor_blacklist(prior_adaptations)
    discovery_formats = _suggest_format_mix(prior_adaptations, ["match", "trace", "circle"])
    curriculum = _build_curriculum_word_bank(rag_curriculum_references)
    if prior_adaptations:
        prior_sources = [
            str(adapt.get("source_hash", "unknown"))
            for adapt in prior_adaptations[:3]
        ]
        logger.info(
            "RAG context influencing adaptation: prior_adaptations=%s sources=%s",
            len(prior_adaptations),
            ",".join(prior_sources),
        )

    # Categorize source items by type
    word_items: list[str] = []
    chain_items: list[str] = []
    sight_words: list[str] = []
    sentences: list[str] = []
    passages: list[str] = []

    for si in skill.source_items:
        if si.item_type == "word_list":
            raw = si.content.replace(",", " ").split()
            words = [
                w.strip() for w in raw
                if w.strip() and w.strip().isalpha()
            ]
            word_items.extend(words)
        elif si.item_type == "word_chain":
            chains = _split_word_chains(si.content)
            chain_items.extend(chains)
        elif si.item_type == "sight_words":
            raw = si.content.replace(",", " ").split()
            words = [
                w.strip("*\u2665\u2764") for w in raw if w.strip()
            ]
            sight_words.extend([w for w in words if w.isalpha()])
        elif si.item_type == "sentence":
            sents = _split_sentences(si.content)
            sentences.extend(sents)
        elif si.item_type == "passage":
            passages.append(si.content)

    prioritized_targets, matched_targets = _prioritize_words_by_curriculum(
        skill.target_words,
        curriculum,
    )
    word_items, matched_word_items = _prioritize_words_by_curriculum(word_items, curriculum)
    sight_words, matched_sight_words = _prioritize_words_by_curriculum(sight_words, curriculum)
    curriculum_supported_words = matched_targets | matched_word_items | matched_sight_words
    if curriculum and curriculum_supported_words:
        logger.info(
            "Curriculum context influencing lesson adaptation: lessons=%s matched_words=%s",
            ",".join(curriculum.lesson_ids) or "unknown",
            ",".join(sorted(curriculum_supported_words)),
        )

    worksheets: list[AdaptedActivityModel] = []
    base_hash = _hash_str(skill.template_type + str(skill.target_words))
    skill_hash = _hash_str(skill.model_dump_json())
    profile_hash = _hash_str(profile.model_dump_json())

    # Worksheet 1: Word Discovery (if we have word items or target words)
    discovery_words = word_items or prioritized_targets[:6]
    if discovery_words:
        chunks = _build_discovery_chunks(
            discovery_words,
            skill,
            rules,
            distractor_blacklist=distractor_blacklist,
            format_order=discovery_formats,
            curriculum_supported_words=curriculum_supported_words,
            curriculum_lesson_ids=curriculum.lesson_ids if curriculum else (),
        )
        worksheets.append(AdaptedActivityModel(
            source_hash=base_hash,
            skill_model_hash=skill_hash,
            learner_profile_hash=profile_hash,
            grade_level=skill.grade_level,
            domain=skill.domain,
            specific_skill=skill.specific_skill,
            chunks=chunks,
            scaffolding=ScaffoldConfig(
                show_worked_example=True, fade_after_chunk=1,
                hint_level="full" if skill.grade_level in ("K", "1") else "partial",
            ),
            theme_id=theme_id,
            decoration_zones=_define_decoration_zones(),
            self_assessment=_build_self_assessment(skill),
            worksheet_number=1,
            worksheet_title="Word Discovery",
            break_prompt=BRAIN_BREAK_PROMPTS[0],
        ))

    # Worksheet 2: Word Builder (chains + fill_blank + sight words)
    if chain_items or word_items or sight_words:
        chunks = _build_builder_chunks(
            chain_items, word_items or prioritized_targets[:6],
            sight_words, skill, rules,
            curriculum_supported_words=curriculum_supported_words,
            curriculum_lesson_ids=curriculum.lesson_ids if curriculum else (),
        )
        worksheets.append(AdaptedActivityModel(
            source_hash=base_hash,
            skill_model_hash=skill_hash,
            learner_profile_hash=profile_hash,
            grade_level=skill.grade_level,
            domain=skill.domain,
            specific_skill=skill.specific_skill,
            chunks=chunks,
            scaffolding=ScaffoldConfig(
                show_worked_example=True, fade_after_chunk=1,
                hint_level="full" if skill.grade_level in ("K", "1") else "partial",
            ),
            theme_id=theme_id,
            decoration_zones=_define_decoration_zones(),
            self_assessment=None,
            worksheet_number=len(worksheets) + 1,
            worksheet_title="Word Builder",
            break_prompt=BRAIN_BREAK_PROMPTS[1 % len(BRAIN_BREAK_PROMPTS)],
        ))

    # Worksheet 3: Story Time (sentences + passage + comprehension)
    if sentences or passages:
        chunks = _build_story_chunks(
            sentences,
            passages,
            prioritized_targets,
            skill,
            rules,
            curriculum_supported_words=curriculum_supported_words,
            curriculum_lesson_ids=curriculum.lesson_ids if curriculum else (),
        )
        worksheets.append(AdaptedActivityModel(
            source_hash=base_hash,
            skill_model_hash=skill_hash,
            learner_profile_hash=profile_hash,
            grade_level=skill.grade_level,
            domain=skill.domain,
            specific_skill=skill.specific_skill,
            chunks=chunks,
            scaffolding=ScaffoldConfig(
                show_worked_example=False, fade_after_chunk=0,
                hint_level="full" if skill.grade_level in ("K", "1") else "partial",
            ),
            theme_id=theme_id,
            decoration_zones=_define_decoration_zones(),
            self_assessment=_build_self_assessment(skill),
            worksheet_number=len(worksheets) + 1,
            worksheet_title="Story Time",
            break_prompt=None,  # Last worksheet — no break needed
        ))

    # Set worksheet_count on all worksheets
    count = len(worksheets)
    for ws in worksheets:
        ws.worksheet_count = count

    # Fallback: if nothing produced, return single worksheet via existing path
    if not worksheets:
        single = adapt_activity(
            skill,
            profile,
            theme_id=theme_id,
            rules=rules,
            rag_prior_adaptations=rag_prior_adaptations,
            rag_curriculum_references=rag_curriculum_references,
        )
        return [single]

    return worksheets


def _build_discovery_chunks(
    words: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    distractor_blacklist: set[str] | None = None,
    format_order: list[str] | None = None,
    curriculum_supported_words: set[str] | None = None,
    curriculum_lesson_ids: tuple[str, ...] = (),
) -> list[ActivityChunk]:
    """Build Word Discovery chunks: match + trace + circle activities."""
    chunks: list[ActivityChunk] = []
    item_id = 0

    default_order = ["match", "trace", "circle"]
    ordered_formats: list[str] = []
    seen_formats: set[str] = set()
    for fmt in format_order or default_order:
        if fmt in default_order and fmt not in seen_formats:
            ordered_formats.append(fmt)
            seen_formats.add(fmt)
    for fmt in default_order:
        if fmt not in seen_formats:
            ordered_formats.append(fmt)

    for fmt in ordered_formats:
        chunk_id = len(chunks) + 1
        if fmt == "match":
            match_words = words[:4]
            if not match_words:
                continue
            items: list[ActivityItem] = []
            for word in match_words:
                item_id += 1
                items.append(ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format="match",
                    metadata=_curriculum_item_metadata(
                        word,
                        curriculum_supported_words,
                        curriculum_lesson_ids,
                    ),
                    picture_prompt=_word_to_picture_prompt(word),
                    options=[word],  # renderer will add picture tiles
                ))
            chunks.append(ActivityChunk(
                chunk_id=chunk_id,
                micro_goal=f"Match {len(match_words)} words to their pictures",
                instructions=[
                    Step(number=1, text="Look at each picture."),
                    Step(number=2, text="Draw a line to the matching word."),
                ],
                worked_example=Example(
                    instruction="Watch how I do the first one:",
                    content=(
                        f'The picture of a '
                        f'{_word_to_picture_prompt(match_words[0]).split(",")[0].replace("a ", "")}'
                        f' matches "{match_words[0]}"!'
                    ),
                ),
                items=items,
                response_format="match",
                time_estimate="About 2 minutes",
            ))

        if fmt == "trace":
            trace_words = words[:4]
            if not trace_words:
                continue
            items = []
            for word in trace_words:
                item_id += 1
                items.append(ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format="trace",
                    metadata=_curriculum_item_metadata(
                        word,
                        curriculum_supported_words,
                        curriculum_lesson_ids,
                    ),
                ))
            chunks.append(ActivityChunk(
                chunk_id=chunk_id,
                micro_goal=f"Trace {len(trace_words)} words",
                instructions=[
                    Step(number=1, text="Say each word out loud."),
                    Step(number=2, text="Trace the dotted letters."),
                ],
                worked_example=None,
                items=items,
                response_format="trace",
                time_estimate="About 2 minutes",
            ))

        if fmt == "circle":
            if not words:
                continue
            distractors = _generate_distractors(
                words,
                min(4, len(words)),
                blacklist=distractor_blacklist,
            )
            all_options = words[:4] + distractors
            item_id += 1
            item = ActivityItem(
                item_id=item_id,
                content="Circle all the words that follow the pattern.",
                response_format="circle",
                options=all_options,
                answer=",".join(words[:4]),
            )
            chunks.append(ActivityChunk(
                chunk_id=chunk_id,
                micro_goal="Find the pattern words",
                instructions=[
                    Step(number=1, text="Look at each word."),
                    Step(number=2, text="Circle the words that match the pattern."),
                ],
                worked_example=None,
                items=[item],
                response_format="circle",
                time_estimate="About 1 minute",
            ))

    return chunks


def _build_builder_chunks(
    chains: list[str],
    words: list[str],
    sight_words_list: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    curriculum_supported_words: set[str] | None = None,
    curriculum_lesson_ids: tuple[str, ...] = (),
) -> list[ActivityChunk]:
    """Build Word Builder chunks: chains + fill-blank + sight words."""
    chunks: list[ActivityChunk] = []
    item_id = 0

    # Chunk 1: Word chains (write format, keep existing behavior)
    if chains:
        items: list[ActivityItem] = []
        for chain in chains:
            item_id += 1
            items.append(ActivityItem(
                item_id=item_id,
                content=chain,
                response_format="write",
                metadata={"display": "chain"},
            ))
        chunks.append(ActivityChunk(
            chunk_id=1,
            micro_goal=f"Follow {len(chains)} word chains",
            instructions=[
                Step(number=1, text="Read the chain of words."),
                Step(number=2, text="Write each word on the line."),
            ],
            worked_example=Example(
                instruction="Watch how the letters change:",
                content=f'In "{chains[0]}" — one letter changes each time!',
            ) if chains else None,
            items=items,
            response_format="write",
            time_estimate="About 2 minutes",
        ))

    # Chunk 2: Fill in the missing letter
    fill_words = words[:4]
    if fill_words:
        items = []
        for w in fill_words:
            blank_content, answer_letter = _generate_fill_blank(w)
            if blank_content:
                item_id += 1
                items.append(ActivityItem(
                    item_id=item_id,
                    content=blank_content,
                    response_format="fill_blank",
                    metadata=_curriculum_item_metadata(
                        w,
                        curriculum_supported_words,
                        curriculum_lesson_ids,
                    ),
                    answer=answer_letter,
                    options=["a", "e", "i", "o", "u"],
                ))
        if items:
            chunks.append(ActivityChunk(
                chunk_id=len(chunks) + 1,
                micro_goal=f"Fill in {len(items)} missing letters",
                instructions=[
                    Step(number=1, text="Look at the word with a missing letter."),
                    Step(number=2, text="Write the missing letter on the line."),
                ],
                worked_example=None,
                items=items,
                response_format="fill_blank",
                time_estimate="About 2 minutes",
            ))

    # Chunk 3: Sight word flash (write format)
    if sight_words_list:
        items = []
        for sw in sight_words_list:
            item_id += 1
            items.append(ActivityItem(
                item_id=item_id,
                content=sw,
                response_format="write",
                metadata={
                    "sight_word": True,
                    **_curriculum_item_metadata(
                        sw,
                        curriculum_supported_words,
                        curriculum_lesson_ids,
                    ),
                },
            ))
        chunks.append(ActivityChunk(
            chunk_id=len(chunks) + 1,
            micro_goal=f"Practice {len(sight_words_list)} sight words",
            instructions=[
                Step(number=1, text="Read each sight word."),
                Step(number=2, text="Write each word on the line."),
            ],
            worked_example=None,
            items=items,
            response_format="write",
            time_estimate="About 1 minute",
        ))

    return chunks


def _build_story_chunks(
    sentences: list[str],
    passages: list[str],
    target_words: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    curriculum_supported_words: set[str] | None = None,
    curriculum_lesson_ids: tuple[str, ...] = (),
) -> list[ActivityChunk]:
    """Build Story Time chunks: sentence completion + read-aloud + comprehension."""
    chunks: list[ActivityChunk] = []
    item_id = 0

    # Chunk 1: Sentence completion with word bank
    if sentences:
        items: list[ActivityItem] = []
        for sent in sentences:
            item_id += 1
            blank_sent, removed_word = _sentence_to_fill_blank(sent, target_words)
            if blank_sent and removed_word:
                # Create word bank from target words + the answer
                bank = list(set([removed_word] + target_words[:3]))
                items.append(ActivityItem(
                    item_id=item_id,
                    content=blank_sent,
                    response_format="fill_blank",
                    metadata=_curriculum_item_metadata(
                        removed_word,
                        curriculum_supported_words,
                        curriculum_lesson_ids,
                    ),
                    answer=removed_word,
                    options=bank,
                ))
            else:
                items.append(ActivityItem(
                    item_id=item_id,
                    content=sent,
                    response_format="write",
                ))
        if items:
            chunks.append(ActivityChunk(
                chunk_id=1,
                micro_goal=f"Complete {len(items)} sentences",
                instructions=[
                    Step(number=1, text="Read the sentence."),
                    Step(number=2, text="Fill in the missing word."),
                ],
                worked_example=None,
                items=items,
                response_format=(
                    "fill_blank"
                    if any(i.response_format == "fill_blank" for i in items)
                    else "write"
                ),
                time_estimate="About 2 minutes",
            ))

    # Chunk 2: Read the story (passage)
    if passages:
        items = []
        for passage in passages:
            item_id += 1
            items.append(ActivityItem(
                item_id=item_id,
                content=passage,
                response_format="read_aloud",
            ))
        chunks.append(ActivityChunk(
            chunk_id=len(chunks) + 1,
            micro_goal="Read the story",
            instructions=[
                Step(number=1, text="Read the story out loud."),
                Step(number=2, text="Point to each word as you read."),
            ],
            worked_example=None,
            items=items,
            response_format="read_aloud",
            time_estimate="About 3 minutes",
        ))

    # Chunk 3: Story comprehension (circle format)
    if passages:
        comp_questions = _generate_comprehension_questions(passages, target_words)
        if comp_questions:
            items = []
            for q, opts, ans in comp_questions:
                item_id += 1
                items.append(ActivityItem(
                    item_id=item_id,
                    content=q,
                    response_format="circle",
                    options=opts,
                    answer=ans,
                ))
            chunks.append(ActivityChunk(
                chunk_id=len(chunks) + 1,
                micro_goal="Check your understanding",
                instructions=[
                    Step(number=1, text="Think about the story."),
                    Step(number=2, text="Circle the best answer."),
                ],
                worked_example=None,
                items=items,
                response_format="circle",
                time_estimate="About 2 minutes",
            ))

    return chunks


def _generate_distractors(
    target_words: list[str],
    count: int,
    blacklist: set[str] | None = None,
) -> list[str]:
    """Generate plausible non-pattern words as distractors for circle activities."""
    common_distractors = [
        "the", "and", "cat", "dog", "big", "run", "sit", "hat",
        "pen", "cup", "red", "hop", "fun", "bus", "map", "net",
    ]
    exclude = {word.lower() for word in target_words}
    if blacklist:
        exclude |= {word.lower() for word in blacklist}
    available = [d for d in common_distractors if d.lower() not in exclude]
    return available[:count]


def _extract_distractor_blacklist(
    prior_adaptations: list[dict[str, object]],
) -> set[str]:
    """Extract distractor words used in prior adaptations for blacklist reuse."""
    blacklist: set[str] = set()
    for adaptation in prior_adaptations:
        raw = adaptation.get("distractor_words")
        if not raw:
            continue
        if isinstance(raw, str):
            words = [word.strip().lower() for word in raw.split(",") if word.strip()]
            blacklist.update(words)
    return blacklist


def _suggest_format_mix(
    prior_adaptations: list[dict[str, object]],
    default_formats: list[str],
) -> list[str]:
    """Suggest response formats that differ from prior runs for the same skill."""
    if not prior_adaptations:
        return default_formats

    recent_formats: set[str] | None = None
    for adaptation in prior_adaptations:
        raw_formats = adaptation.get("response_formats")
        if isinstance(raw_formats, str) and raw_formats.strip():
            recent_formats = {fmt.strip() for fmt in raw_formats.split(",") if fmt.strip()}
            break

    if not recent_formats:
        return default_formats

    default_set = {fmt.strip() for fmt in default_formats if fmt.strip()}
    if default_set == recent_formats and len(default_formats) >= 2:
        rotated = default_formats.copy()
        rotated[0], rotated[1] = rotated[1], rotated[0]
        return rotated

    return default_formats


def _generate_fill_blank(word: str) -> tuple[str, str]:
    """Remove a vowel from a word to create a fill-in-the-blank item.

    Returns (blanked_word, removed_vowel). E.g., "grade" -> ("gr_de", "a")
    """
    vowels = "aeiou"
    # Find the first vowel that's not at position 0 or last position
    for i, ch in enumerate(word):
        if ch.lower() in vowels and 0 < i < len(word) - 1:
            blanked = word[:i] + "_" + word[i + 1:]
            return blanked, ch.lower()
    # Fallback: blank the first vowel
    for i, ch in enumerate(word):
        if ch.lower() in vowels:
            blanked = word[:i] + "_" + word[i + 1:]
            return blanked, ch.lower()
    return "", ""


def _sentence_to_fill_blank(
    sentence: str, target_words: list[str],
) -> tuple[str, str]:
    """Convert a sentence to fill-blank by removing a target word.

    Returns (blanked_sentence, removed_word).
    """
    lower_targets = {w.lower() for w in target_words}
    words = sentence.split()
    for i, w in enumerate(words):
        cleaned = w.strip(".,!?;:").lower()
        if cleaned in lower_targets:
            # Replace this word with a blank
            original_word = w.strip(".,!?;:")
            blank = "________"
            # Preserve trailing punctuation
            trailing = ""
            if w and not w[-1].isalpha():
                trailing = w[-1]
            words[i] = blank + trailing
            return " ".join(words), original_word
    return "", ""


def _generate_comprehension_questions(
    passages: list[str], target_words: list[str],
) -> list[tuple[str, list[str], str]]:
    """Generate simple comprehension questions from passage text.

    Returns list of (question, options, answer).
    """
    questions: list[tuple[str, list[str], str]] = []
    full_text = " ".join(passages).lower()

    # Question 1: What word appears in the story?
    found_words = [w for w in target_words if w.lower() in full_text]
    if found_words:
        correct = found_words[0]
        distractors = _generate_distractors(found_words, 2)
        options = [correct] + distractors
        questions.append((
            "Which word from the pattern is in the story?",
            options,
            correct,
        ))

    # Question 2: Simple yes/no about a word presence
    if len(target_words) >= 2:
        not_found = [w for w in target_words if w.lower() not in full_text]
        if not_found:
            questions.append((
                f'Is the word "{not_found[0]}" in the story?',
                ["Yes", "No"],
                "No",
            ))
        elif found_words and len(found_words) >= 2:
            questions.append((
                f'Is the word "{found_words[1]}" in the story?',
                ["Yes", "No"],
                "Yes",
            ))

    return questions[:3]  # Max 3 questions


def _word_to_picture_prompt(word: str) -> str:
    """Generate a simple picture description for a word.

    Returns a description suitable for AI image generation.
    """
    # Simple word-to-picture mapping for common phonics words
    picture_map: dict[str, str] = {
        "cake": "a birthday cake with frosting",
        "grade": "a school report card with a gold star",
        "chase": "a playful dog running",
        "slide": "a playground slide",
        "quite": "a child with finger on lips saying shh",
        "froze": "a snowflake and ice cube",
        "these": "a hand pointing at objects",
        "tune": "musical notes floating in the air",
        "tone": "a bell ringing",
        "cone": "an ice cream cone",
        "cane": "a candy cane",
        "tame": "a gentle pet animal",
        "time": "a clock showing the time",
        "dime": "a shiny coin",
        "dome": "a round dome building",
        "tall": "a tall giraffe",
        "call": "a telephone ringing",
        "wall": "a brick wall",
        "fall": "autumn leaves falling",
        "mall": "a shopping mall building",
        "doll": "a cute doll toy",
        "roll": "a bread roll",
        "poll": "a clipboard with checkmarks",
    }
    return picture_map.get(word.lower(), f"a simple cartoon representing {word}")


def _build_chunks(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    curriculum: _CurriculumWordBank | None = None,
) -> list[ActivityChunk]:
    """Split source items into ADHD-friendly chunks."""
    # Gather all practice items from source
    raw_items = _source_items_to_activity_items(skill, rules, curriculum=curriculum)

    if not raw_items:
        # If no source items, create items from target words
        raw_items = _words_to_activity_items(skill, rules, curriculum=curriculum)

    # Split into chunks
    max_per_chunk = rules.max_items_per_chunk
    chunks: list[ActivityChunk] = []
    chunk_id = 0

    for start in range(0, len(raw_items), max_per_chunk):
        batch = raw_items[start : start + max_per_chunk]
        chunk_id += 1

        # Worked example only in first chunk (scaffolding fade)
        worked_example = None
        if chunk_id == 1:
            worked_example = _generate_worked_example(skill, batch)

        # Instructions
        instructions = _generate_instructions(skill, rules, chunk_id, len(batch))

        # Time estimate
        time_est = (
            f"About {rules.time_estimate_minutes} minutes"
            if rules.require_time_estimate
            else ""
        )

        # Determine dominant response format for this chunk
        formats = [item.response_format for item in batch]
        response_format = max(set(formats), key=formats.count) if formats else "write"

        # Micro goal
        micro_goal = _generate_micro_goal(skill, chunk_id, len(batch))

        chunks.append(
            ActivityChunk(
                chunk_id=chunk_id,
                micro_goal=micro_goal,
                instructions=instructions,
                worked_example=worked_example,
                items=batch,
                response_format=response_format,
                time_estimate=time_est,
                reward_event=None,  # MVP: no reward system
            )
        )

    # Ensure at least one chunk even if no items
    if not chunks:
        chunks.append(
            ActivityChunk(
                chunk_id=1,
                micro_goal=f"Practice {skill.domain} skills",
                instructions=[Step(number=1, text="Try your best!")],
                worked_example=None,
                items=[],
                response_format="write",
                time_estimate=f"About {rules.time_estimate_minutes} minutes",
            )
        )

    return chunks


def _source_items_to_activity_items(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    curriculum: _CurriculumWordBank | None = None,
) -> list[ActivityItem]:
    """Convert SourceItems to ActivityItems with appropriate response formats."""
    items: list[ActivityItem] = []
    item_id = 0

    for source_item in skill.source_items:
        # Determine response format based on item type and profile prefs
        default_format = _default_format_for_type(source_item.item_type)
        response_format = get_substitute_format(
            default_format, rules.allowed_response_formats
        )

        if source_item.item_type == "word_list":
            # Split word lists into individual items
            words = [w.strip() for w in source_item.content.replace(",", " ").split() if w.strip()]
            words, supported_words = _prioritize_words_by_curriculum(words, curriculum)
            for word in words:
                if not word.isalpha():
                    continue
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=word,
                        response_format=response_format,
                        metadata=_curriculum_item_metadata(
                            word,
                            supported_words,
                            curriculum.lesson_ids if curriculum else (),
                        ),
                    )
                )

        elif source_item.item_type == "sentence":
            # Split multi-sentence blocks into individual sentences
            sentences = _split_sentences(source_item.content)
            for sentence in sentences:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=sentence,
                        response_format=response_format,
                    )
                )

        elif source_item.item_type == "word_chain":
            # Split chains into individual transformation steps
            chains = _split_word_chains(source_item.content)
            for chain in chains:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=chain,
                        response_format="write",
                        metadata={"display": "chain"},
                    )
                )

        elif source_item.item_type == "chain_script":
            # Chain scripts are teacher instructions — skip as student items
            pass

        elif source_item.item_type == "passage":
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=source_item.content,
                    response_format="read_aloud",
                )
            )

        elif source_item.item_type == "sight_words":
            words = [w.strip() for w in source_item.content.replace(",", " ").split() if w.strip()]
            words, supported_words = _prioritize_words_by_curriculum(words, curriculum)
            for word in words:
                cleaned = word.strip("*♥❤")
                if not cleaned.isalpha():
                    continue
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=cleaned,
                        response_format=response_format,
                        metadata={
                            "sight_word": True,
                            **_curriculum_item_metadata(
                                cleaned,
                                supported_words,
                                curriculum.lesson_ids if curriculum else (),
                            ),
                        },
                    )
                )

    return items


def _words_to_activity_items(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    curriculum: _CurriculumWordBank | None = None,
) -> list[ActivityItem]:
    """Create activity items from target words when no source items available."""
    items: list[ActivityItem] = []
    default_format = "write"
    if skill.domain == "fluency":
        default_format = "read_aloud"

    response_format = get_substitute_format(
        default_format, rules.allowed_response_formats
    )

    target_words, supported_words = _prioritize_words_by_curriculum(
        skill.target_words,
        curriculum,
    )

    for i, word in enumerate(target_words, start=1):
        items.append(
            ActivityItem(
                item_id=i,
                content=word,
                response_format=response_format,
                metadata=_curriculum_item_metadata(
                    word,
                    supported_words,
                    curriculum.lesson_ids if curriculum else (),
                ),
            )
        )

    return items


def _split_sentences(text: str) -> list[str]:
    """Split a multi-sentence block into individual sentences."""
    import re

    # Split on numbered prefixes like "1. " or "2. "
    numbered = re.split(r"(?:^|\s)(\d+)\.\s+", text.strip())
    if len(numbered) > 2:
        # numbered splits as ['', '1', 'sentence1', '2', 'sentence2', ...]
        sentences = []
        for j in range(1, len(numbered), 2):
            if j + 1 < len(numbered):
                s = numbered[j + 1].strip()
                if s:
                    sentences.append(s)
        if sentences:
            return sentences

    # Fallback: split on sentence-ending punctuation
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _build_curriculum_word_bank(
    curriculum_references: list[dict[str, object]] | None,
) -> _CurriculumWordBank | None:
    """Normalize retrieved curriculum references into a searchable text corpus."""
    if not curriculum_references:
        return None

    lesson_ids: list[str] = []
    concepts: list[str] = []
    documents: list[str] = []

    for ref in curriculum_references:
        lesson_id = str(ref.get("lesson_id", "")).strip()
        concept = str(ref.get("concept", "")).strip()
        document = str(
            ref.get("_rag_document")
            or ref.get("document")
            or "",
        ).strip()

        if lesson_id and lesson_id not in lesson_ids:
            lesson_ids.append(lesson_id)
        if concept and concept not in concepts:
            concepts.append(concept)
        if document:
            documents.append(document.lower())

    if not lesson_ids and not concepts and not documents:
        return None

    return _CurriculumWordBank(
        lesson_ids=tuple(lesson_ids),
        concepts=tuple(concepts),
        documents=tuple(documents),
    )


def _prioritize_words_by_curriculum(
    words: list[str],
    curriculum: _CurriculumWordBank | None,
) -> tuple[list[str], set[str]]:
    """Prefer curriculum-backed words when multiple exact matches are available."""
    deduped = _dedupe_words(words)
    if not deduped or curriculum is None:
        return deduped, set()

    matched: list[str] = []
    remaining: list[str] = []
    matched_normalized: set[str] = set()
    search_spaces = [*curriculum.documents, *[concept.lower() for concept in curriculum.concepts]]

    for word in deduped:
        normalized = _normalize_word(word)
        if not normalized:
            continue
        if any(_text_contains_word(space, normalized) for space in search_spaces):
            matched.append(word)
            matched_normalized.add(normalized)
        else:
            remaining.append(word)

    minimum_matches = min(2, len(deduped))
    if len(matched) < minimum_matches:
        return deduped, matched_normalized

    return matched + remaining, matched_normalized


def _curriculum_item_metadata(
    word: str,
    supported_words: set[str] | None,
    lesson_ids: tuple[str, ...],
) -> dict[str, str | int | float | bool]:
    """Annotate items that are directly supported by retrieved curriculum text."""
    normalized = _normalize_word(word)
    if not normalized or not supported_words or normalized not in supported_words:
        return {}

    metadata: dict[str, str | int | float | bool] = {"curriculum_supported": True}
    if lesson_ids:
        metadata["curriculum_lesson_ids"] = ",".join(lesson_ids)
    return metadata


def _dedupe_words(words: list[str]) -> list[str]:
    """Deduplicate candidate words while preserving order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for word in words:
        normalized = _normalize_word(word)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(word)
    return deduped


def _normalize_word(word: str) -> str:
    """Normalize a candidate word for exact curriculum matching."""
    return "".join(ch for ch in word.lower() if ch.isalpha())


def _text_contains_word(text: str, word: str) -> bool:
    """Check whole-word presence inside retrieved curriculum text."""
    return bool(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text))


def _split_word_chains(text: str) -> list[str]:
    """Split word chain content into individual chain sequences.

    Input like: "1. tune → tone → cone → cane 2. tame → time → dime → dome"
    Output: ["tune → tone → cone → cane", "tame → time → dime → dome"]
    """
    import re

    # Try splitting on numbered prefixes
    numbered = re.split(r"(?:^|\s)(\d+)\.\s+", text.strip())
    if len(numbered) > 2:
        chains = []
        for j in range(1, len(numbered), 2):
            if j + 1 < len(numbered):
                chain = numbered[j + 1].strip()
                if chain:
                    chains.append(chain)
        if chains:
            return chains

    # Single chain — return as-is
    return [text.strip()] if text.strip() else []


def _default_format_for_type(item_type: str) -> str:
    """Return default response format for a source item type."""
    return {
        "word_list": "write",
        "word_chain": "write",
        "chain_script": "write",
        "sentence": "write",
        "passage": "read_aloud",
        "sight_words": "write",
    }.get(item_type, "write")


def _generate_instructions(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    chunk_id: int,
    item_count: int,
) -> list[Step]:
    """Generate numbered instructions appropriate for grade level."""
    steps: list[Step] = []

    if skill.domain == "phonics":
        if chunk_id == 1:
            steps.append(Step(number=1, text="Look at each word carefully."))
            steps.append(Step(number=2, text=f"Read each word out loud. ({item_count} words)"))
        else:
            steps.append(Step(number=1, text=f"Read these {item_count} words out loud."))
            steps.append(Step(number=2, text="Write each word on the line."))

    elif skill.domain == "fluency":
        steps.append(Step(number=1, text="Read the passage out loud."))
        steps.append(Step(number=2, text="Point to each word as you read."))

    else:
        steps.append(Step(number=1, text=f"Complete the {item_count} items below."))

    # Trim to max steps
    steps = steps[: rules.instruction_max_steps]

    # Enforce word limit per step
    trimmed: list[Step] = []
    for step in steps:
        words = step.text.split()
        if len(words) > rules.instruction_max_words:
            step = Step(
                number=step.number,
                text=" ".join(words[: rules.instruction_max_words]),
            )
        trimmed.append(step)

    return trimmed


def _generate_worked_example(
    skill: LiteracySkillModel,
    items: list[ActivityItem],
) -> Example | None:
    """Generate a worked example for the first chunk."""
    if not items:
        return None

    first_item = items[0]

    if skill.domain == "phonics":
        return Example(
            instruction="Watch how I do the first one:",
            content=f'"{first_item.content}" — I can read this word!',
        )
    elif skill.domain == "fluency":
        return Example(
            instruction="Listen first, then you try:",
            content=(
                f'I read: "{first_item.content[:50]}..."'
                if len(first_item.content) > 50
                else f'I read: "{first_item.content}"'
            ),
        )
    else:
        return Example(
            instruction="Here is an example:",
            content=f'"{first_item.content}"',
        )


def _generate_micro_goal(
    skill: LiteracySkillModel,
    chunk_id: int,
    item_count: int,
) -> str:
    """Generate a micro goal description for a chunk."""
    if skill.domain == "phonics":
        return f"Read and practice {item_count} words (Part {chunk_id})"
    elif skill.domain == "fluency":
        return f"Read the story (Part {chunk_id})"
    else:
        return f"Complete {item_count} items (Part {chunk_id})"


def _build_self_assessment(skill: LiteracySkillModel) -> list[str]:
    """Build self-assessment checklist items."""
    items = []

    if skill.domain == "phonics":
        items.append(f"I can read words with the {skill.specific_skill} pattern")
        items.append("I can sound out new words")
    elif skill.domain == "fluency":
        items.append("I can read the story smoothly")
        items.append("I can point to words as I read")
    else:
        items.append(f"I can practice {skill.domain} skills")

    items.append("I'm still learning (and that's okay!)")

    return items


def _define_decoration_zones() -> list[tuple[float, float, float, float]]:
    """Define safe areas for theme decorations that won't overlap content.

    Returns bounding boxes in normalized coordinates (0-1).
    Two zones: top-right corner and bottom-left corner.
    """
    return [
        (0.85, 0.0, 1.0, 0.12),  # top-right: small theme accent
        (0.0, 0.88, 0.15, 1.0),  # bottom-left: avatar/companion zone
    ]


def _hash_str(data: str) -> str:
    """Generate a short hash for linking models."""
    return hashlib.sha256(data.encode()).hexdigest()[:16]
