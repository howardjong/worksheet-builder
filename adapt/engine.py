"""ADHD activity adaptation engine — transforms LiteracySkillModel into AdaptedActivityModel."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
from adapt.section_cap import enforce_section_cap
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel

if TYPE_CHECKING:
    from companion.character_identity import CharacterIdentity

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
    artifacts_dir: str | None = None,
    character_identity: CharacterIdentity | None = None,
) -> list[AdaptedActivityModel]:
    """Transform a skill model into 2-3 ADHD-optimized mini-worksheets.

    Tries LLM-assisted adaptation first (Gemini plans the worksheet structure),
    then falls back to the deterministic rule-based engine if LLM is unavailable
    or fails validation.

    Returns a list of 1-3 AdaptedActivityModels, one per mini-worksheet.
    """
    if rules is None:
        rules = build_rules(profile)

    if os.environ.get("WORKSHEET_DIRECT_COMPILER") == "1":
        try:
            from adapt.direct_compiler import compile_lesson_direct

            direct_result = compile_lesson_direct(
                skill,
                profile,
                theme_id,
                character_identity=character_identity,
            )
            if direct_result:
                return enforce_section_cap(direct_result, rules)
        except Exception as exc:
            logger.warning("Direct compiler failed, using fallback adaptation: %s", exc)

    if os.environ.get("WORKSHEET_PLANNER_V2") == "1":
        # New single-call planner (A/B flag; becomes the only LLM path after
        # the battery gate — see plans/2026-06-12-planner-simplification-plan.md)
        try:
            from adapt.llm_planner import plan_lesson_llm

            planned = plan_lesson_llm(
                skill,
                profile,
                theme_id=theme_id,
                rules=rules,
                rag_curriculum_references=rag_curriculum_references,
                artifacts_dir=artifacts_dir,
            )
            if planned:
                return enforce_section_cap(planned, rules)
        except Exception as exc:
            logger.warning("LLM planner failed, using deterministic engine: %s", exc)
    else:
        # Legacy loop (Gemini → Judge → retry → GPT takeover)
        try:
            from adapt.llm_orchestrator import orchestrate_llm_adaptation

            llm_result = orchestrate_llm_adaptation(
                skill,
                profile,
                theme_id=theme_id,
                rules=rules,
                rag_curriculum_references=rag_curriculum_references,
                artifacts_dir=artifacts_dir,
            )
            if llm_result:
                return enforce_section_cap(llm_result, rules)
        except Exception as exc:
            logger.warning("LLM orchestration failed, using deterministic engine: %s", exc)

    # Deterministic fallback

    prior_adaptations = rag_prior_adaptations or []
    distractor_blacklist = _extract_distractor_blacklist(prior_adaptations)
    # Respect learner's response format preferences: if "trace" is not in
    # allowed formats, substitute "write" so discovery uses write-the-word
    # instead of dotted tracing (trace is K-level; older learners write).
    discovery_default = ["match", "trace", "circle"]
    if "trace" not in rules.allowed_response_formats:
        discovery_default = ["write" if f == "trace" else f for f in discovery_default]
    discovery_formats = _suggest_format_mix(prior_adaptations, discovery_default)
    curriculum = _build_curriculum_word_bank(rag_curriculum_references)
    if prior_adaptations:
        prior_sources = [
            str(adapt.get("source_hash", "unknown")) for adapt in prior_adaptations[:3]
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
    roll_and_read_words: list[str] = []

    for si in skill.source_items:
        if si.item_type == "word_list":
            raw = si.content.replace(",", " ").split()
            words = [w.strip() for w in raw if w.strip() and w.strip().isalpha()]
            word_items.extend(words)
        elif si.item_type == "word_chain":
            chains = _split_word_chains(si.content)
            chain_items.extend(chains)
        elif si.item_type == "sight_words":
            raw = si.content.replace(",", " ").split()
            words = [w.strip("*\u2665\u2764") for w in raw if w.strip()]
            sight_words.extend([w for w in words if w.isalpha()])
        elif si.item_type == "sentence":
            sents = _split_sentences(si.content)
            sentences.extend(sents)
        elif si.item_type == "passage":
            passages.append(si.content)
        elif si.item_type == "roll_and_read":
            roll_and_read_words.extend(_parse_roll_and_read(si.content))

    # Deduplicate sentences (home practice PDF often has duplicated content)
    seen_sents: set[str] = set()
    unique_sents: list[str] = []
    for s in sentences:
        key = s.strip().lower()
        if key not in seen_sents:
            seen_sents.add(key)
            unique_sents.append(s)
    sentences = unique_sents

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
            preserve_all_words=bool(word_items),
        )
        # Prepend phonemic awareness warm-up for grades K-1
        warmup = _build_warmup_chunk(
            discovery_words,
            skill,
            rules,
            start_chunk_id=0,
        )
        if warmup:
            # Renumber existing chunk IDs
            for ch in chunks:
                ch.chunk_id += 1
            chunks = [warmup] + chunks
        worksheets.append(
            AdaptedActivityModel(
                source_hash=base_hash,
                skill_model_hash=skill_hash,
                learner_profile_hash=profile_hash,
                grade_level=skill.grade_level,
                domain=skill.domain,
                specific_skill=skill.specific_skill,
                chunks=chunks,
                scaffolding=ScaffoldConfig(
                    show_worked_example=True,
                    fade_after_chunk=1,
                    hint_level="full" if skill.grade_level in ("K", "1") else "partial",
                ),
                theme_id=theme_id,
                decoration_zones=_define_decoration_zones(),
                self_assessment=_build_self_assessment(skill),
                worksheet_number=1,
                worksheet_title="Word Discovery",
                break_prompt=BRAIN_BREAK_PROMPTS[0],
            )
        )

    # Worksheet 2: Word Builder (chains + fill_blank + sight words + roll-and-read)
    if chain_items or word_items or sight_words:
        chunks = _build_builder_chunks(
            chain_items,
            word_items or prioritized_targets[:6],
            sight_words,
            skill,
            rules,
            curriculum_supported_words=curriculum_supported_words,
            curriculum_lesson_ids=curriculum.lesson_ids if curriculum else (),
        )
        # Append Roll and Read fluency chunk
        roll_chunk = _build_roll_and_read_chunk(
            roll_and_read_words,
            skill,
            rules,
            start_chunk_id=len(chunks) + 1,
        )
        if roll_chunk:
            chunks.append(roll_chunk)
        worksheets.append(
            AdaptedActivityModel(
                source_hash=base_hash,
                skill_model_hash=skill_hash,
                learner_profile_hash=profile_hash,
                grade_level=skill.grade_level,
                domain=skill.domain,
                specific_skill=skill.specific_skill,
                chunks=chunks,
                scaffolding=ScaffoldConfig(
                    show_worked_example=True,
                    fade_after_chunk=1,
                    hint_level="full" if skill.grade_level in ("K", "1") else "partial",
                ),
                theme_id=theme_id,
                decoration_zones=_define_decoration_zones(),
                self_assessment=None,
                worksheet_number=len(worksheets) + 1,
                worksheet_title="Word Builder",
                break_prompt=BRAIN_BREAK_PROMPTS[1 % len(BRAIN_BREAK_PROMPTS)],
            )
        )

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
        worksheets.append(
            AdaptedActivityModel(
                source_hash=base_hash,
                skill_model_hash=skill_hash,
                learner_profile_hash=profile_hash,
                grade_level=skill.grade_level,
                domain=skill.domain,
                specific_skill=skill.specific_skill,
                chunks=chunks,
                scaffolding=ScaffoldConfig(
                    show_worked_example=False,
                    fade_after_chunk=0,
                    hint_level="full" if skill.grade_level in ("K", "1") else "partial",
                ),
                theme_id=theme_id,
                decoration_zones=_define_decoration_zones(),
                self_assessment=_build_self_assessment(skill),
                worksheet_number=len(worksheets) + 1,
                worksheet_title="Story Time",
                break_prompt=None,  # Last worksheet — no break needed
            )
        )

    # For UFLI word work: reorder so word chains (the core lesson activity)
    # come first, then sample word practice, then sentences. The default
    # order (Discovery → Builder → Story) buries the chains in Worksheet 2
    # behind generic match/write/circle activities that don't teach the
    # UFLI concept.
    if skill.template_type == "ufli_word_work" and len(worksheets) >= 2:
        builder_idx = next(
            (i for i, ws in enumerate(worksheets) if ws.worksheet_title == "Word Builder"),
            None,
        )
        discovery_idx = next(
            (i for i, ws in enumerate(worksheets) if ws.worksheet_title == "Word Discovery"),
            None,
        )
        # Only reorder when Builder actually has word chain content
        has_chains = builder_idx is not None and any(
            item.metadata.get("display") in ("chain_step", "chain")
            for chunk in worksheets[builder_idx].chunks
            for item in chunk.items
        )
        if (
            has_chains
            and builder_idx is not None
            and discovery_idx is not None
            and builder_idx > discovery_idx
        ):
            worksheets[discovery_idx], worksheets[builder_idx] = (
                worksheets[builder_idx],
                worksheets[discovery_idx],
            )
            worksheets[discovery_idx].worksheet_title = "Word Work"
            worksheets[builder_idx].worksheet_title = "Word Practice"

    # Set worksheet_count and worksheet_number on all worksheets
    count = len(worksheets)
    for i, ws in enumerate(worksheets):
        ws.worksheet_count = count
        ws.worksheet_number = i + 1

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
        return enforce_section_cap([single], rules)

    return enforce_section_cap(worksheets, rules)


def _build_discovery_chunks(
    words: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    distractor_blacklist: set[str] | None = None,
    format_order: list[str] | None = None,
    curriculum_supported_words: set[str] | None = None,
    curriculum_lesson_ids: tuple[str, ...] = (),
    preserve_all_words: bool = False,
) -> list[ActivityChunk]:
    """Build Word Discovery chunks: match + trace + circle activities."""
    chunks: list[ActivityChunk] = []
    item_id = 0
    max_items = rules.max_items_per_chunk

    default_order = ["match", "trace", "circle"]
    valid_formats = {"match", "trace", "circle", "write"}
    ordered_formats: list[str] = []
    seen_formats: set[str] = set()
    for fmt in format_order or default_order:
        if fmt in valid_formats and fmt not in seen_formats:
            ordered_formats.append(fmt)
            seen_formats.add(fmt)
            # "write" substitutes for "trace" — prevent trace sneaking back
            if fmt == "write":
                seen_formats.add("trace")
    for fmt in default_order:
        if fmt not in seen_formats:
            ordered_formats.append(fmt)

    for fmt in ordered_formats:
        chunk_id = len(chunks) + 1
        if fmt == "match":
            # The match renderer lays out two columns cleanly up to four rows.
            match_words = words[: min(max_items, 4)]
            if not match_words:
                continue
            # Shuffle the picture order so words and pictures don't align
            shuffled_pictures = _shuffled_mismatch(match_words)
            items: list[ActivityItem] = []
            for idx, word in enumerate(match_words):
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=word,
                        response_format="match",
                        metadata=_curriculum_item_metadata(
                            word,
                            curriculum_supported_words,
                            curriculum_lesson_ids,
                        ),
                        picture_prompt=_word_to_picture_prompt(shuffled_pictures[idx]),
                        options=[shuffled_pictures[idx]],
                        answer=word,
                    )
                )
            chunks.append(
                ActivityChunk(
                    chunk_id=chunk_id,
                    micro_goal=f"Match {len(match_words)} words to their pictures",
                    instructions=[
                        Step(number=1, text="Look at each picture."),
                        Step(number=2, text="Draw a line to the matching word."),
                    ],
                    worked_example=Example(
                        instruction="Watch how I do the first one:",
                        content=_match_example_content(match_words[0]),
                    ),
                    items=items,
                    response_format="match",
                    time_estimate="About 2 minutes",
                )
            )

        if fmt == "trace":
            trace_batches = (
                [words[start : start + max_items] for start in range(0, len(words), max_items)]
                if preserve_all_words
                else [words[:max_items]]
            )
            for batch_index, trace_words in enumerate(trace_batches):
                if not trace_words:
                    continue
                items = []
                for word in trace_words:
                    item_id += 1
                    items.append(
                        ActivityItem(
                            item_id=item_id,
                            content=word,
                            response_format="trace",
                            metadata=_curriculum_item_metadata(
                                word,
                                curriculum_supported_words,
                                curriculum_lesson_ids,
                            ),
                        )
                    )
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal=f"Trace {len(trace_words)} words",
                        instructions=[
                            Step(number=1, text="Say each word out loud."),
                            Step(number=2, text="Trace the dotted letters."),
                        ],
                        worked_example=None,
                        items=items,
                        response_format="trace",
                        time_estimate=("About 1 minute" if batch_index > 0 else "About 2 minutes"),
                    )
                )

        if fmt == "write":
            write_batches = (
                [words[start : start + max_items] for start in range(0, len(words), max_items)]
                if preserve_all_words
                else [words[:max_items]]
            )
            for batch_index, write_words in enumerate(write_batches):
                if not write_words:
                    continue
                items = []
                for word in write_words:
                    item_id += 1
                    items.append(
                        ActivityItem(
                            item_id=item_id,
                            content=word,
                            response_format="write",
                            metadata=_curriculum_item_metadata(
                                word,
                                curriculum_supported_words,
                                curriculum_lesson_ids,
                            ),
                        )
                    )
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal=f"Write {len(write_words)} words",
                        instructions=[
                            Step(number=1, text="Say each word out loud."),
                            Step(number=2, text="Write the word on the line."),
                        ],
                        worked_example=None,
                        items=items,
                        response_format="write",
                        time_estimate=("About 1 minute" if batch_index > 0 else "About 2 minutes"),
                    )
                )

        if fmt == "circle":
            if not words:
                continue
            target_options = words[: max(1, max_items - 1)]
            distractors = _generate_distractors(
                words,
                max(0, max_items - len(target_options)),
                blacklist=distractor_blacklist,
            )
            all_options = target_options + distractors
            item_id += 1
            item = ActivityItem(
                item_id=item_id,
                content="Circle all the words that follow the pattern.",
                response_format="circle",
                options=all_options,
                answer=",".join(target_options),
            )
            chunks.append(
                ActivityChunk(
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
                )
            )

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
    max_items = rules.max_items_per_chunk

    # Chunk 1: Word chains — interactive letter-change steps
    if chains:
        chain_steps = _parse_chain_steps(chains)
        # Deduplicate steps (source PDFs sometimes repeat chains)
        seen_steps: set[tuple[str, str]] = set()
        unique_steps: list[dict[str, str]] = []
        for step in chain_steps:
            key = (step["from_word"], step["to_word"])
            if key not in seen_steps:
                seen_steps.add(key)
                unique_steps.append(step)
        chain_steps = unique_steps

        if chain_steps:
            # Worked example uses the first step; activity uses the rest
            ex_step = chain_steps[0]
            example = Example(
                instruction="Watch how the letters change:",
                content=(
                    f'{ex_step["from_word"]} → {ex_step["to_word"]}  '
                    f'(change the "{ex_step["old_letter"]}" '
                    f'to "{ex_step["new_letter"]}")'
                ),
            )
            activity_steps = chain_steps[1:]
        else:
            # Fallback if parsing fails — show chain read-only
            example = Example(
                instruction="Watch how the letters change:",
                content=f'In "{chains[0]}" — one letter changes each time!',
            )
            activity_steps = []

        if activity_steps:
            for batch_start in range(0, len(activity_steps), max_items):
                batch = activity_steps[batch_start : batch_start + max_items]
                items: list[ActivityItem] = []
                for step in batch:
                    item_id += 1
                    items.append(
                        ActivityItem(
                            item_id=item_id,
                            content=(
                                f'Start with "{step["from_word"]}". '
                                f'Change the "{step["old_letter"]}" '
                                f'to "{step["new_letter"]}". '
                                f'Write the new word.'
                            ),
                            response_format="write",
                            metadata={"display": "chain_step"},
                            answer=step["to_word"],
                        )
                    )
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal=f"Build {len(items)} new words",
                        instructions=[
                            Step(number=1, text="Read the starting word."),
                            Step(number=2, text="Change the letter shown."),
                            Step(number=3, text="Write the new word on the line."),
                        ],
                        worked_example=example if batch_start == 0 else None,
                        items=items,
                        response_format="write",
                        time_estimate="About 1 minute",
                    )
                )
        else:
            # Fallback: plain chain items (skip first chain used in example)
            for batch_start in range(0, len(chains), max_items):
                chain_batch = chains[batch_start : batch_start + max_items]
                items = []
                for chain in chain_batch:
                    item_id += 1
                    items.append(
                        ActivityItem(
                            item_id=item_id,
                            content=chain,
                            response_format="write",
                            metadata={"display": "chain"},
                        )
                    )
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal=f"Build {len(items)} new words",
                        instructions=[
                            Step(number=1, text="Read the starting word."),
                            Step(number=2, text="Change the letter shown."),
                            Step(number=3, text="Write the new word on the line."),
                        ],
                        worked_example=example if batch_start == 0 else None,
                        items=items,
                        response_format="write",
                        time_estimate="About 1 minute",
                    )
                )

    # Chunk 2: Fill in the missing letter
    # Word-list-only lessons rely on these chunks for full target coverage, so
    # split all words by the learner cap instead of silently dropping later words.
    fill_word_batches = (
        [
            words[batch_start : batch_start + max_items]
            for batch_start in range(0, len(words), max_items)
        ]
        if not chains
        else [words[:max_items]]
    )
    for fill_words in fill_word_batches:
        if not fill_words:
            continue
        items = []
        for w in fill_words:
            blank_content, answer_letter = _generate_fill_blank(w)
            if blank_content:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=blank_content,
                        response_format="fill_blank",
                        metadata=_curriculum_item_metadata(
                            w,
                            curriculum_supported_words,
                            curriculum_lesson_ids,
                        ),
                        answer=answer_letter,
                        options=_limit_options(
                            ["a", "e", "i", "o", "u"],
                            required=answer_letter,
                            max_items=max_items,
                        ),
                    )
                )
        if items:
            chunks.append(
                ActivityChunk(
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
                )
            )

    # Chunk 3: Sight word flash (write format)
    if sight_words_list:
        for batch_start in range(0, len(sight_words_list), max_items):
            sight_word_batch = sight_words_list[batch_start : batch_start + max_items]
            items = []
            for sw in sight_word_batch:
                item_id += 1
                items.append(
                    ActivityItem(
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
                    )
                )
            chunks.append(
                ActivityChunk(
                    chunk_id=len(chunks) + 1,
                    micro_goal=f"Practice {len(items)} sight words",
                    instructions=[
                        Step(number=1, text="Read each sight word."),
                        Step(number=2, text="Write each word on the line."),
                    ],
                    worked_example=None,
                    items=items,
                    response_format="write",
                    time_estimate="About 1 minute",
                )
            )

    return chunks


def _build_warmup_chunk(
    words: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    start_chunk_id: int = 0,
) -> ActivityChunk | None:
    """Build a phonemic awareness warm-up chunk with Elkonin sound boxes.

    Only produced for grades K-1. Returns None otherwise.
    """
    if skill.grade_level not in ("K", "1"):
        return None

    # Skip for consonant-le syllable patterns — Elkonin sound-box segmentation
    # breaks the -le unit apart, contradicting the lesson's teaching goal.
    if "-le" in skill.specific_skill.lower():
        return None

    # Pick a short sound-box set without exceeding the learner's chunk cap.
    candidates = [w.lower() for w in words if 2 <= len(w) <= 5 and w.isalpha()]
    if not candidates:
        return None
    selected = candidates[: min(3, rules.max_items_per_chunk)]

    items: list[ActivityItem] = []
    for idx, word in enumerate(selected):
        phonemes = _segment_phonemes(word)
        items.append(
            ActivityItem(
                item_id=idx + 1,
                content=word,
                response_format="sound_box",
                metadata={"display": "elkonin", "phoneme_count": len(phonemes)},
                options=phonemes,
                answer=word,
            )
        )

    return ActivityChunk(
        chunk_id=start_chunk_id + 1,
        micro_goal=f"Tap out the sounds in {len(items)} words",
        instructions=[
            Step(number=1, text="Say the word out loud."),
            Step(number=2, text="Tap each sound you hear."),
            Step(number=3, text="Write one sound in each box."),
        ],
        worked_example=Example(
            instruction="Watch how I tap out the sounds:",
            content=f'"{selected[0]}" has {len(_segment_phonemes(selected[0]))} sounds: '
            + " - ".join(f'"{p}"' for p in _segment_phonemes(selected[0])),
        ),
        items=items,
        response_format="sound_box",
        time_estimate="About 1 minute",
    )


def _segment_phonemes(word: str) -> list[str]:
    """Segment a word into approximate phonemes for Elkonin boxes.

    This is a simplified grapheme-to-phoneme mapping suitable for
    common English phonics patterns taught in UFLI K-2.
    """
    word = word.lower()
    phonemes: list[str] = []
    i = 0
    # Common digraphs and trigraphs to treat as single phonemes
    multi_graphemes = [
        "tch",
        "dge",
        "sh",
        "ch",
        "th",
        "wh",
        "ph",
        "ck",
        "ng",
        "nk",
        "ai",
        "ay",
        "ee",
        "ea",
        "oa",
        "ow",
        "ou",
        "oi",
        "oy",
        "oo",
        "ew",
        "aw",
        "au",
        "igh",
        "eigh",
        "ar",
        "er",
        "ir",
        "or",
        "ur",
    ]
    while i < len(word):
        matched = False
        # Check longest multi-graphemes first
        for mg in multi_graphemes:
            if word[i : i + len(mg)] == mg:
                phonemes.append(mg)
                i += len(mg)
                matched = True
                break
        if not matched:
            # Silent e at end after consonant
            if (
                i == len(word) - 1
                and word[i] == "e"
                and len(phonemes) >= 2
                and word[i - 1] not in "aeiou"
            ):
                break  # skip silent e
            phonemes.append(word[i])
            i += 1
    return phonemes


def _parse_roll_and_read(text: str) -> list[str]:
    """Parse a Roll and Read text block into a clean word list."""
    words: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        # Skip headers, copyright, lesson markers
        if not line:
            continue
        if line.startswith("©") or "University of Florida" in line:
            continue
        if line.lower().startswith("roll and read") or line.lower().startswith("lesson"):
            continue
        # Each remaining line should be a single word
        for token in line.split():
            token = token.strip().lower()
            # Filter: must be real English word (>=2 chars, not an artifact)
            if not token or not token.isalpha() or len(token) < 2:
                continue
            # Skip common OCR/extraction artifacts
            if token in ("la", "le", "re", "de", "el", "al"):
                continue
            words.append(token)
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def _build_roll_and_read_chunk(
    words: list[str],
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    start_chunk_id: int = 1,
) -> ActivityChunk | None:
    """Build a Roll and Read fluency chunk with a mix of base and inflected words."""
    if not words:
        return None

    max_items = rules.max_items_per_chunk
    # Prefer a mix of base and inflected forms within the learner's chunk cap.
    base_words = [w for w in words if not w.endswith("ing") and not w.endswith("ed")]
    inflected = [w for w in words if w.endswith("ing") or w.endswith("ed")]
    selected: list[str] = []
    # Alternate base and inflected
    bi, ii = 0, 0
    while len(selected) < max_items and (bi < len(base_words) or ii < len(inflected)):
        if bi < len(base_words) and len(selected) < max_items:
            selected.append(base_words[bi])
            bi += 1
        if ii < len(inflected) and len(selected) < max_items:
            selected.append(inflected[ii])
            ii += 1

    if not selected:
        return None

    items: list[ActivityItem] = []
    for idx, word in enumerate(selected):
        items.append(
            ActivityItem(
                item_id=idx + 1,
                content=word,
                response_format="read_aloud",
                metadata={"display": "roll_and_read"},
            )
        )

    return ActivityChunk(
        chunk_id=start_chunk_id,
        micro_goal=f"Read {len(items)} words smoothly",
        instructions=[
            Step(number=1, text="Read each word smoothly."),
            Step(number=2, text="Try the list three times."),
            Step(number=3, text="Point to each word as you read."),
        ],
        worked_example=None,
        items=items,
        response_format="read_aloud",
        time_estimate="About 1 minute",
    )


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
    max_items = rules.max_items_per_chunk

    # Chunk 1: Sentence completion with word bank
    if sentences:
        items: list[ActivityItem] = []
        for sent in sentences:
            item_id += 1
            blank_sent, removed_word = _sentence_to_fill_blank(sent, target_words)
            if blank_sent and removed_word:
                # Create word bank from target words + the answer
                bank = _limit_options(
                    [removed_word, *target_words],
                    required=removed_word,
                    max_items=max_items,
                )
                items.append(
                    ActivityItem(
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
                    )
                )
            else:
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=sent,
                        response_format="write",
                    )
                )
        if items:
            for batch_start in range(0, len(items), max_items):
                batch = items[batch_start : batch_start + max_items]
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal=f"Complete {len(batch)} sentences",
                        instructions=[
                            Step(number=1, text="Read the sentence."),
                            Step(number=2, text="Fill in the missing word."),
                        ],
                        worked_example=None,
                        items=batch,
                        response_format=(
                            "fill_blank"
                            if any(i.response_format == "fill_blank" for i in batch)
                            else "write"
                        ),
                        time_estimate="About 2 minutes",
                    )
                )

    # Chunk 2: Read the story (passage)
    if passages:
        for batch_start in range(0, len(passages), max_items):
            passage_batch = passages[batch_start : batch_start + max_items]
            items = []
            for passage in passage_batch:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=passage,
                        response_format="read_aloud",
                    )
                )
            chunks.append(
                ActivityChunk(
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
                )
            )

    # Chunk 3: Story comprehension (circle format)
    if passages:
        comp_questions = _generate_comprehension_questions(passages, target_words)
        if comp_questions:
            items = []
            for q, opts, ans in comp_questions:
                limited_opts = _limit_options(opts, required=ans, max_items=max_items)
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=q,
                        response_format="circle",
                        options=limited_opts,
                        answer=ans,
                    )
                )
            for batch_start in range(0, len(items), max_items):
                batch = items[batch_start : batch_start + max_items]
                chunks.append(
                    ActivityChunk(
                        chunk_id=len(chunks) + 1,
                        micro_goal="Check your understanding",
                        instructions=[
                            Step(number=1, text="Think about the story."),
                            Step(number=2, text="Circle the best answer."),
                        ],
                        worked_example=None,
                        items=batch,
                        response_format="circle",
                        time_estimate="About 2 minutes",
                    )
                )

    return chunks


def _generate_distractors(
    target_words: list[str],
    count: int,
    blacklist: set[str] | None = None,
) -> list[str]:
    """Generate phonetically graduated distractors for circle activities.

    Based on research (PMC8862114, PMC5902514):
    - Near-miss distractors share features with targets but differ in the
      target pattern, training precise phonological discrimination.
    - Mix of difficulty: ~half near-miss (share ending/onset), ~half unrelated
      but grade-appropriate CVC/CCVC words.
    """
    exclude = {word.lower() for word in target_words}
    if blacklist:
        exclude |= {word.lower() for word in blacklist}

    # Near-miss distractors: share visual/phonetic features with targets
    # Organized by common phonics patterns that look similar but sound different
    near_miss_pools: dict[str, list[str]] = {
        # Words ending in y but with short vowel (vs y-as-long-i targets)
        "y_short": ["funny", "happy", "bunny", "puppy", "silly", "jelly"],
        # Words with similar onsets to common targets
        "onset_similar": ["clip", "clam", "trap", "drum", "skip", "slim"],
        # Words sharing rime patterns but different vowels
        "rime_similar": ["bay", "day", "say", "may", "joy", "toy", "boy"],
        # Short-vowel CVC words (common, clearly different)
        "cvc_basic": ["cat", "dog", "big", "run", "sit", "hat", "hop", "cup"],
    }

    # Pick near-miss first (half the count), then fill with basic CVC
    near_count = max(1, count // 2)
    selected: list[str] = []

    # Try near-miss pools in order
    for pool_words in near_miss_pools.values():
        if len(selected) >= near_count:
            break
        for w in pool_words:
            if w.lower() not in exclude and w not in selected:
                selected.append(w)
                if len(selected) >= near_count:
                    break

    # Fill remaining with basic CVC distractors
    for w in near_miss_pools["cvc_basic"]:
        if len(selected) >= count:
            break
        if w.lower() not in exclude and w not in selected:
            selected.append(w)

    return selected[:count]


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
            blanked = word[:i] + "_" + word[i + 1 :]
            return blanked, ch.lower()
    # Fallback: blank the first vowel
    for i, ch in enumerate(word):
        if ch.lower() in vowels:
            blanked = word[:i] + "_" + word[i + 1 :]
            return blanked, ch.lower()
    return "", ""


def _limit_options(
    options: list[str],
    required: str | None,
    max_items: int,
) -> list[str]:
    """Cap choices to the chunk size while keeping the correct answer."""
    deduped: list[str] = []
    for option in options:
        if option not in deduped:
            deduped.append(option)

    limited = deduped[:max_items]
    if required and required not in limited:
        if len(limited) >= max_items:
            limited[-1] = required
        else:
            limited.append(required)
    return limited


def _sentence_to_fill_blank(
    sentence: str,
    target_words: list[str],
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
    passages: list[str],
    target_words: list[str],
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
        questions.append(
            (
                "Which word from the pattern is in the story?",
                options,
                correct,
            )
        )

    # Question 2: Simple yes/no about a word presence
    if len(target_words) >= 2:
        not_found = [w for w in target_words if w.lower() not in full_text]
        if not_found:
            questions.append(
                (
                    f'Is the word "{not_found[0]}" in the story?',
                    ["Yes", "No"],
                    "No",
                )
            )
        elif found_words and len(found_words) >= 2:
            questions.append(
                (
                    f'Is the word "{found_words[1]}" in the story?',
                    ["Yes", "No"],
                    "Yes",
                )
            )

    return questions[:3]  # Max 3 questions


def _match_example_content(word: str) -> str:
    pic = _word_to_picture_prompt(word).split(",")[0].replace("a ", "")
    return f'The picture of a {pic} matches "{word}"!'


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
            f"About {rules.time_estimate_minutes} minutes" if rules.require_time_estimate else ""
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
        response_format = get_substitute_format(default_format, rules.allowed_response_formats)

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

    response_format = get_substitute_format(default_format, rules.allowed_response_formats)

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
            ref.get("_rag_document") or ref.get("document") or "",
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


def _parse_chain_steps(chains: list[str]) -> list[dict[str, str]]:
    """Parse word chains into individual letter-change steps.

    Given ["cry -> try -> dry -> pry", "fry -> fly -> sly -> sky"],
    returns a list of dicts like:
      [{"from_word": "cry", "to_word": "try", "old_letter": "c", "new_letter": "t"}, ...]
    """
    steps: list[dict[str, str]] = []
    for chain in chains:
        words = [w.strip() for w in re.split(r"\s*(?:->|→)\s*", chain) if w.strip()]
        for i in range(len(words) - 1):
            from_w = words[i].lower()
            to_w = words[i + 1].lower()
            old_letter, new_letter = _find_letter_change(from_w, to_w)
            if old_letter and new_letter:
                steps.append(
                    {
                        "from_word": from_w,
                        "to_word": to_w,
                        "old_letter": old_letter,
                        "new_letter": new_letter,
                    }
                )
    return steps


def _shuffled_mismatch(words: list[str]) -> list[str]:
    """Return a shuffled copy where no element stays in its original position.

    This ensures the picture column never lines up with the word column.
    Uses a deterministic seed based on the words for reproducibility.
    """
    import random

    if len(words) <= 1:
        return list(words)

    seed = hash(tuple(words)) & 0xFFFFFFFF
    rng = random.Random(seed)
    shuffled = list(words)
    # Fisher-Yates derangement: keep shuffling until no element is in place
    for _ in range(100):
        rng.shuffle(shuffled)
        if all(s != w for s, w in zip(shuffled, words)):
            return shuffled
    # Fallback: rotate by 1 (always a derangement for len >= 2)
    return words[1:] + words[:1]


def _find_letter_change(word_a: str, word_b: str) -> tuple[str, str]:
    """Find the single letter that changed between two words.

    Returns (old_letter, new_letter) or ("", "") if no single change found.
    """
    if len(word_a) != len(word_b):
        # Length change — find the differing position(s)
        # For simple add/remove, describe broadly
        return "", ""
    diffs = [(a, b) for a, b in zip(word_a, word_b) if a != b]
    if len(diffs) == 1:
        return diffs[0][0], diffs[0][1]
    return "", ""


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
