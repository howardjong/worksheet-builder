"""Single-call LLM lesson planner — replaces the retry/takeover orchestration loop.

One strong planning call (provider chain: gpt-5.4 → gemini-3.5-flash) receives
the FULL source items plus canonical corpus lesson content and authors
worksheet items directly. Deterministic code clamps the result to ADHD rules
(adapt/rules.py) and the section cap (adapt/section_cap.py). The GPT judge
evaluates the full item text: approve → ship; reject → ONE regeneration with
feedback; reject again → deterministic engine. Everything that ships carries
a judge verdict.
"""

from __future__ import annotations

import logging
import os

from adapt.llm_adapt import _call_gemini
from adapt.llm_judge import _call_openai
from adapt.rules import AccommodationRules
from companion.schema import LearnerProfile
from corpus.ufli.lookup import lookup_lesson
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)

DEFAULT_PLANNER_PROVIDERS = "openai,gemini"
DEFAULT_PLANNER_GEMINI_MODEL = "gemini-3.5-flash"
PLANNER_MAX_COMPLETION_TOKENS = 8192
_CORPUS_FIELD_CHAR_CAP = 2000


def _corpus_block(skill: LiteracySkillModel) -> str:
    """Canonical UFLI lesson content via the deterministic corpus lookup."""
    if skill.lesson_number is None:
        return ""
    result = lookup_lesson(skill.lesson_number)
    if result is None:
        return ""
    parts = [f"## Canonical UFLI Lesson {result.lesson_id} Content (ground truth)"]
    if result.concept.strip():
        parts.append(f"Concept: {result.concept.strip()}")
    for label, text in (
        ("Home practice text", result.home_practice_text),
        ("Decodable text", result.decodable_text),
        ("Additional practice (Roll and Read)", result.additional_text),
    ):
        cleaned = text.strip()
        if cleaned:
            parts.append(f"{label}:\n{cleaned[:_CORPUS_FIELD_CHAR_CAP]}")
    return "\n\n".join(parts)


def _planner_providers() -> list[str]:
    order = os.environ.get("WORKSHEET_PLANNER_PROVIDERS", DEFAULT_PLANNER_PROVIDERS)
    return [p.strip() for p in order.split(",") if p.strip()]


def _call_planner(prompt: str) -> tuple[str | None, str]:
    """Walk the provider chain; return (response_text, model_label)."""
    for provider in _planner_providers():
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            text = _call_openai(prompt, max_completion_tokens=PLANNER_MAX_COMPLETION_TOKENS)
            if text:
                return text, "gpt-5.4"
        elif provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
            model = os.environ.get("WORKSHEET_PLANNER_GEMINI_MODEL", DEFAULT_PLANNER_GEMINI_MODEL)
            text = _call_gemini(prompt, model=model)
            if text:
                return text, model
    return None, "none"


def _build_planner_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    theme_id: str,
    rag_curriculum_references: list[dict[str, object]] | None,
) -> str:
    """Build the single planning prompt: full source, corpus truth, ADHD limits."""
    source_sections: list[str] = []
    for si in skill.source_items:
        source_sections.append(f"- [{si.item_type}]: {si.content}")
    source_text = "\n".join(source_sections) if source_sections else "(no source items)"

    corpus_text = _corpus_block(skill)

    curriculum_text = ""
    if rag_curriculum_references:
        refs = []
        for ref in rag_curriculum_references[:3]:
            lesson = ref.get("lesson_id", "?")
            concept = ref.get("concept", "?")
            refs.append(f"- Lesson {lesson}: {concept}")
        curriculum_text = "\nCurriculum references:\n" + "\n".join(refs)

    return f"""You are an expert literacy curriculum designer specializing in \
ADHD-optimized worksheets for children ages 5-8.

## Source Worksheet Content (COMPLETE — preserve everything below)

Template: {skill.template_type}
Domain: {skill.domain}
Concept: {skill.specific_skill}
Grade level: {skill.grade_level}
Target words: {", ".join(skill.target_words)}

Source sections:
{source_text}

{corpus_text}
{curriculum_text}

## Learner Profile

Name: {profile.name}
Grade: {profile.grade_level}
Response format preferences: {profile.accommodations.response_format_prefs}

## ADHD Design Constraints (hard limits — deterministic validators reject violations)

- Maximum {rules.max_sections_per_worksheet} sections (activities) per mini-worksheet
- Maximum {rules.max_items_per_chunk} items per section
- Maximum {rules.instruction_max_steps} instruction steps per section
- Maximum {rules.instruction_max_words} words per instruction step
- Time estimate per section: about {rules.time_estimate_minutes} minutes
- Allowed response formats: {rules.allowed_response_formats}
- The FIRST section of the first worksheet MUST have a worked example
- One main task per section; keep each mini-worksheet to one page of focus

## Your Task

Design 2-3 mini-worksheets that teach "{skill.specific_skill}" effectively.

CRITICAL RULES:
1. Preserve ALL source content — every word chain, sample word, sight word,
   and sentence from the source MUST appear somewhere in your output items.
2. YOU author the actual practice items: write the exact student-facing text,
   the "answer" options, and the correct answer for each item. Use real,
   correctly spelled, grade-appropriate words. Never truncate a sentence.
3. Choose activity types that REINFORCE the specific concept (e.g., do NOT
   break "-le" units apart with sound boxes; word chains from the source are
   PRIMARY activities).
4. Order worksheets so the most concept-focused activity comes FIRST.
5. For "match" and "sound_box" activities, list the words in "words" and leave
   "items" empty — the rendering system constructs those mechanically.
6. Each activity needs a rationale for WHY it teaches this concept.

## Output Format

Respond with ONLY this JSON (no markdown fences):
{{
  "concept_focus": "What this lesson teaches",
  "pedagogical_rationale": "Why you structured the worksheets this way",
  "worksheets": [
    {{
      "title": "Worksheet title",
      "activities": [
        {{
          "activity_type": "word_chain|match|write|fill_blank|circle|read_aloud|\
sound_box|sentence_completion",
          "micro_goal": "Short goal description",
          "words": ["only for match/sound_box or as backup"],
          "items": [
            {{
              "content": "Exact student-facing item text",
              "response_format": "write|circle|fill_blank|read_aloud|trace",
              "options": ["choice1", "choice2"],
              "answer": "correct answer or null"
            }}
          ],
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
