"""ADHD activity adaptation engine — transforms LiteracySkillModel into AdaptedActivityModel."""

from __future__ import annotations

import hashlib

from adapt.rules import AccommodationRules, build_rules, get_substitute_format
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


def adapt_activity(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
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

    # Split items into chunks
    chunks = _build_chunks(skill, rules)

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


def _build_chunks(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> list[ActivityChunk]:
    """Split source items into ADHD-friendly chunks."""
    # Gather all practice items from source
    raw_items = _source_items_to_activity_items(skill, rules)

    if not raw_items:
        # If no source items, create items from target words
        raw_items = _words_to_activity_items(skill, rules)

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
            for word in words:
                if not word.isalpha():
                    continue
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=word,
                        response_format=response_format,
                    )
                )

        elif source_item.item_type == "sentence":
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=source_item.content,
                    response_format=response_format,
                )
            )

        elif source_item.item_type == "word_chain":
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=source_item.content,
                    response_format="write",
                )
            )

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
                        metadata={"sight_word": True},
                    )
                )

    return items


def _words_to_activity_items(
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> list[ActivityItem]:
    """Create activity items from target words when no source items available."""
    items: list[ActivityItem] = []
    default_format = "write"
    if skill.domain == "fluency":
        default_format = "read_aloud"

    response_format = get_substitute_format(
        default_format, rules.allowed_response_formats
    )

    for i, word in enumerate(skill.target_words, start=1):
        items.append(
            ActivityItem(
                item_id=i,
                content=word,
                response_format=response_format,
            )
        )

    return items


def _default_format_for_type(item_type: str) -> str:
    """Return default response format for a source item type."""
    return {
        "word_list": "write",
        "word_chain": "write",
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
