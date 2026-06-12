"""LLM-assisted adaptation — Gemini plans worksheet structure from source content.

Instead of rigid rule-based templates, Gemini reasons about the pedagogical
intent of the source worksheet and plans activities that reinforce the
specific concept being taught.

The LLM outputs a simplified LessonPlan which is then translated into
AdaptedActivityModel objects by deterministic code. This keeps the LLM
focused on pedagogical decisions while the code handles mechanical details
(item IDs, scaffolding config, decoration zones, Pydantic validation).

Falls back to the deterministic engine if Gemini is unavailable or fails.
"""

from __future__ import annotations

import json
import logging
import os

from pydantic import BaseModel, Field

from adapt.rules import AccommodationRules, build_rules
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


# --- Intermediate plan schema (simpler than AdaptedActivityModel) ---


class PlannedItem(BaseModel):
    """A single practice item authored directly by the LLM."""

    content: str
    response_format: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    picture_prompt: str | None = None


class ActivityPlan(BaseModel):
    """A single activity within a worksheet, as planned by the LLM."""

    activity_type: str  # word_chain, match, write, fill_blank, etc.
    micro_goal: str  # e.g. "Build 5 new words by changing one letter"
    words: list[str] = Field(default_factory=list)
    items: list[PlannedItem] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    worked_example: str | None = None
    response_format: str = "write"
    time_estimate_minutes: int = 2
    rationale: str = ""


class WorksheetPlan(BaseModel):
    """A single worksheet within a lesson plan."""

    title: str
    activities: list[ActivityPlan]


class LessonPlan(BaseModel):
    """Full lesson plan produced by the LLM."""

    worksheets: list[WorksheetPlan]
    pedagogical_rationale: str = ""
    concept_focus: str = ""


# --- Prompt construction ---


def _build_adapt_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    theme_id: str,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> str:
    """Build the prompt that asks Gemini to plan the worksheet structure."""

    # Source content summary
    source_sections: list[str] = []
    for si in skill.source_items:
        source_sections.append(f"  - [{si.item_type}]: {si.content}")
    source_text = "\n".join(source_sections) if source_sections else "  (no source items)"

    # Curriculum references
    curriculum_text = ""
    if rag_curriculum_references:
        refs = []
        for ref in rag_curriculum_references[:3]:
            lesson = ref.get("lesson_id", "?")
            concept = ref.get("concept", "?")
            refs.append(f"  - Lesson {lesson}: {concept}")
        curriculum_text = "\nCurriculum references:\n" + "\n".join(refs)

    return f"""You are an expert literacy curriculum designer specializing in ADHD-optimized worksheets for children ages 5-8.

## Source Worksheet Content

Template: {skill.template_type}
Domain: {skill.domain}
Concept: {skill.specific_skill}
Grade level: {skill.grade_level}
Target words: {", ".join(skill.target_words)}

Source sections:
{source_text}
{curriculum_text}

## Learner Profile

Name: {profile.name}
Grade: {profile.grade_level}
Response format preferences: {profile.accommodations.response_format_prefs}

## ADHD Design Constraints

- Maximum {rules.max_items_per_chunk} items per activity chunk
- Maximum {rules.instruction_max_steps} instruction steps per chunk
- Maximum {rules.instruction_max_words} words per instruction step
- Time estimate per chunk: about {rules.time_estimate_minutes} minutes
- Allowed response formats: {rules.allowed_response_formats}
- First activity MUST have a worked example
- Use brain breaks between worksheets

## Your Task

Design 2-3 mini-worksheets that teach the "{skill.specific_skill}" concept effectively.

CRITICAL RULES:
1. Preserve ALL source content — every word chain, sample word, sight word, and sentence from the source MUST appear somewhere in the output.
2. Choose activity types that REINFORCE the specific concept. For example:
   - If the concept is "-le" syllable pattern, do NOT use Elkonin sound boxes (they break the -le unit apart)
   - If the source has word chains, those should be a PRIMARY activity (they're the core UFLI practice)
   - Match activities should connect to the concept, not just test vocabulary
3. Order worksheets so the most concept-focused activity comes FIRST
4. Use ALL sample words across the worksheets, not just the first few
5. Each activity needs a clear rationale for WHY it teaches this concept

## Output Format

Respond with ONLY this JSON (no markdown fences):
{{
  "concept_focus": "What this lesson is trying to teach",
  "pedagogical_rationale": "Why you structured the worksheets this way",
  "worksheets": [
    {{
      "title": "Worksheet title",
      "activities": [
        {{
          "activity_type": "word_chain|match|write|fill_blank|circle|read_aloud|sound_box|sentence_completion",
          "micro_goal": "Short goal description",
          "words": ["word1", "word2"],
          "instructions": ["Step 1 text", "Step 2 text"],
          "worked_example": "Example text or null",
          "response_format": "write|match|circle|fill_blank|read_aloud|trace|sound_box",
          "time_estimate_minutes": 2,
          "rationale": "Why this activity for this concept"
        }}
      ]
    }}
  ]
}}"""


# --- Gemini call ---


def _call_gemini(prompt: str) -> str | None:
    """Call Gemini and return the response text."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        return str(response.text)
    except Exception as e:
        logger.warning("Gemini adaptation call failed: %s", e)
        return None


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            if line.strip() == "```" and in_block:
                break
            if in_block:
                json_lines.append(line)
        return "\n".join(json_lines)
    return text


def _parse_lesson_plan(text: str) -> LessonPlan | None:
    """Parse Gemini response into a LessonPlan."""
    try:
        data = json.loads(_extract_json(text))
        return LessonPlan.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to parse Gemini lesson plan: %s", e)
        return None


# --- Translation: LessonPlan → AdaptedActivityModel ---


def _translate_plan(
    plan: LessonPlan,
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    rules: AccommodationRules,
) -> list[AdaptedActivityModel]:
    """Translate a LessonPlan into AdaptedActivityModel objects."""
    import hashlib

    base_hash = hashlib.sha256(
        (skill.template_type + str(skill.target_words)).encode(),
    ).hexdigest()[:16]
    skill_hash = hashlib.sha256(skill.model_dump_json().encode()).hexdigest()[:16]
    profile_hash = hashlib.sha256(profile.model_dump_json().encode()).hexdigest()[:16]

    worksheets: list[AdaptedActivityModel] = []

    for ws_idx, ws_plan in enumerate(plan.worksheets):
        chunks: list[ActivityChunk] = []
        item_counter = 0

        for act_idx, activity in enumerate(ws_plan.activities):
            chunk_id = act_idx + 1

            # Build instructions
            instructions = [
                Step(number=i + 1, text=text)
                for i, text in enumerate(activity.instructions[: rules.instruction_max_steps])
            ]
            if not instructions:
                instructions = [Step(number=1, text="Complete the activity below.")]

            # Build worked example
            worked_example = None
            if activity.worked_example and chunk_id == 1:
                worked_example = Example(
                    instruction="Watch how I do the first one:",
                    content=activity.worked_example,
                )

            # Build items based on activity type
            items = _items_for_activity(
                activity,
                skill,
                rules,
                item_counter,
            )
            item_counter += len(items)

            if not items:
                continue

            chunks.append(
                ActivityChunk(
                    chunk_id=chunk_id,
                    micro_goal=activity.micro_goal,
                    instructions=instructions,
                    worked_example=worked_example,
                    items=items,
                    response_format=activity.response_format,
                    time_estimate=f"About {activity.time_estimate_minutes} minutes",
                )
            )

        if not chunks:
            continue

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
                decoration_zones=[
                    (0.85, 0.0, 1.0, 0.12),
                    (0.0, 0.88, 0.15, 1.0),
                ],
                self_assessment=_build_self_assessment(skill)
                if ws_idx == len(plan.worksheets) - 1
                else None,
                worksheet_number=ws_idx + 1,
                worksheet_count=len(plan.worksheets),
                worksheet_title=ws_plan.title,
                break_prompt=(
                    _BRAIN_BREAKS[ws_idx % len(_BRAIN_BREAKS)]
                    if ws_idx < len(plan.worksheets) - 1
                    else None
                ),
            )
        )

    return worksheets


_BRAIN_BREAKS = [
    "Stand up and stretch!",
    "Do 5 jumping jacks!",
    "Get a drink of water!",
]


# Formats whose renderer contracts (shuffled picture options, phoneme boxes)
# must stay mechanically constructed even when the model authors items.
_MECHANICAL_FORMATS = {"match", "sound_box"}


def _items_for_activity(
    activity: ActivityPlan,
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    item_start: int,
) -> list[ActivityItem]:
    """Prefer model-authored items; degrade to template expansion."""
    if activity.items and activity.activity_type not in _MECHANICAL_FORMATS:
        authored = _items_from_planned(activity, rules, item_start)
        if authored:
            return authored
    if activity.items and not activity.words:
        # Salvage authored content as inputs for the mechanical builders.
        activity = activity.model_copy(
            update={"words": [planned.content for planned in activity.items]}
        )
    return _build_items_from_activity(activity, skill, rules, item_start)


def _items_from_planned(
    activity: ActivityPlan,
    rules: AccommodationRules,
    item_start: int,
) -> list[ActivityItem]:
    """Clamp model-authored items to ADHD rules; mechanics stay deterministic."""
    from adapt.engine import _limit_options

    items: list[ActivityItem] = []
    item_id = item_start
    for planned in activity.items[: rules.max_items_per_chunk]:
        content = planned.content.strip()
        if not content:
            continue
        options = [opt.strip() for opt in planned.options if opt.strip()]
        if options and planned.answer:
            options = _limit_options(
                options,
                required=planned.answer,
                max_items=rules.max_items_per_chunk,
            )
        else:
            options = options[: rules.max_items_per_chunk]
        item_id += 1
        items.append(
            ActivityItem(
                item_id=item_id,
                content=content,
                response_format=planned.response_format or activity.response_format,
                options=options or None,
                answer=planned.answer,
                picture_prompt=planned.picture_prompt,
            )
        )
    return items


def _build_items_from_activity(
    activity: ActivityPlan,
    skill: LiteracySkillModel,
    rules: AccommodationRules,
    item_start: int,
) -> list[ActivityItem]:
    """Convert an ActivityPlan into ActivityItem objects."""
    items: list[ActivityItem] = []
    item_id = item_start

    max_items = rules.max_items_per_chunk

    if activity.activity_type == "word_chain":
        # Parse word chains into letter-change steps
        from adapt.engine import _parse_chain_steps

        chain_steps = _parse_chain_steps(activity.words)
        for step in chain_steps[:max_items]:
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=(
                        f'Start with "{step["from_word"]}". '
                        f'Change the "{step["old_letter"]}" '
                        f'to "{step["new_letter"]}". '
                        f"Write the new word."
                    ),
                    response_format="write",
                    metadata={"display": "chain_step"},
                    answer=step["to_word"],
                )
            )

    elif activity.activity_type == "match":
        from adapt.engine import _shuffled_mismatch, _word_to_picture_prompt

        # The match renderer lays out two columns cleanly up to four rows.
        words = activity.words[: min(max_items, 4)]
        if words:
            shuffled = _shuffled_mismatch(words)
            for idx, word in enumerate(words):
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=word,
                        response_format="match",
                        picture_prompt=_word_to_picture_prompt(shuffled[idx]),
                        options=[shuffled[idx]],
                        answer=word,
                    )
                )

    elif activity.activity_type == "write":
        for word in activity.words[:max_items]:
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format="write",
                )
            )

    elif activity.activity_type == "fill_blank":
        from adapt.engine import _generate_fill_blank, _limit_options

        for word in activity.words[:max_items]:
            blank, answer = _generate_fill_blank(word)
            if blank:
                item_id += 1
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=blank,
                        response_format="fill_blank",
                        answer=answer,
                        options=_limit_options(
                            ["a", "e", "i", "o", "u"],
                            required=answer,
                            max_items=max_items,
                        ),
                    )
                )

    elif activity.activity_type == "circle":
        from adapt.engine import _generate_distractors

        target_limit = max(1, max_items - 1) if len(activity.words) > 1 else max_items
        target_words = activity.words[:target_limit]
        distractors = _generate_distractors(
            activity.words,
            max(0, max_items - len(target_words)),
        )
        item_id += 1
        items.append(
            ActivityItem(
                item_id=item_id,
                content="Circle all the words that follow the pattern.",
                response_format="circle",
                options=target_words + distractors,
                answer=",".join(target_words),
            )
        )

    elif activity.activity_type == "sentence_completion":
        from adapt.engine import _limit_options, _sentence_to_fill_blank

        for sent in activity.words[:max_items]:  # sentences stored in words field
            item_id += 1
            blank_sent, removed = _sentence_to_fill_blank(sent, skill.target_words)
            if blank_sent and removed:
                bank = _limit_options(
                    [removed, *skill.target_words],
                    required=removed,
                    max_items=max_items,
                )
                items.append(
                    ActivityItem(
                        item_id=item_id,
                        content=blank_sent,
                        response_format="fill_blank",
                        answer=removed,
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

    elif activity.activity_type == "read_aloud":
        for text in activity.words[:max_items]:
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=text,
                    response_format="read_aloud",
                )
            )

    elif activity.activity_type == "sound_box":
        from adapt.engine import _segment_phonemes

        for word in activity.words[:max_items]:
            phonemes = _segment_phonemes(word)
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format="sound_box",
                    metadata={"display": "elkonin", "phoneme_count": len(phonemes)},
                    options=phonemes,
                    answer=word,
                )
            )

    elif activity.activity_type == "sight_word":
        for word in activity.words[:max_items]:
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format="write",
                    metadata={"sight_word": True},
                )
            )

    else:
        # Unknown activity type — treat as write
        for word in activity.words[:max_items]:
            item_id += 1
            items.append(
                ActivityItem(
                    item_id=item_id,
                    content=word,
                    response_format=activity.response_format,
                )
            )

    return items


def _build_self_assessment(skill: LiteracySkillModel) -> list[str]:
    """Build self-assessment checklist."""
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


# --- Public API ---


def llm_adapt_lesson(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> list[AdaptedActivityModel] | None:
    """Plan and build worksheets using Gemini for pedagogical decisions.

    Requires WORKSHEET_LLM_ADAPT=1 environment variable to enable.
    Returns a list of AdaptedActivityModel on success, or None if LLM
    is unavailable or fails (caller should fall back to deterministic engine).
    """
    if not os.environ.get("WORKSHEET_LLM_ADAPT"):
        return None

    if rules is None:
        rules = build_rules(profile)

    # Build prompt
    prompt = _build_adapt_prompt(
        skill,
        profile,
        rules,
        theme_id,
        rag_curriculum_references=rag_curriculum_references,
    )

    # Call Gemini
    logger.info("  LLM adaptation: calling Gemini for lesson planning...")
    response_text = _call_gemini(prompt)
    if response_text is None:
        logger.info("  LLM adaptation: Gemini unavailable, falling back to deterministic")
        return None

    # Parse plan
    plan = _parse_lesson_plan(response_text)
    if plan is None:
        logger.warning("  LLM adaptation: failed to parse Gemini response")
        return None

    logger.info(
        "  LLM adaptation: Gemini planned %s worksheets — %s",
        len(plan.worksheets),
        plan.concept_focus,
    )

    # Translate to AdaptedActivityModel
    worksheets = _translate_plan(plan, skill, profile, theme_id, rules)
    if not worksheets:
        logger.warning("  LLM adaptation: translation produced no worksheets")
        return None

    logger.info(
        "  LLM adaptation: produced %s worksheets with %s total chunks",
        len(worksheets),
        sum(len(ws.chunks) for ws in worksheets),
    )

    return worksheets
