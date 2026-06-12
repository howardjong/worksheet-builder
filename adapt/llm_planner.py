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

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from adapt.llm_adapt import _call_gemini, _parse_lesson_plan, _translate_plan
from adapt.llm_judge import JudgeVerdict, _call_openai, judge_adaptation
from adapt.rules import AccommodationRules, build_rules
from adapt.schema import AdaptedActivityModel
from adapt.section_cap import enforce_section_cap
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


class PlannerLogEntry(BaseModel):
    """One row in llm_adaptation_log.jsonl (planner-v2 schema)."""

    timestamp: str
    skill_domain: str
    specific_skill: str
    template_type: str
    outcome: str
    planning_model: str
    judge_verdicts: list[dict[str, object]] = Field(default_factory=list)
    final_score: float | None = None
    final_output_judged: bool = True
    planner_version: int = 2


def plan_lesson_llm(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
    artifacts_dir: str | None = None,
) -> list[AdaptedActivityModel] | None:
    """One planning call → clamp → judge → one regen → deterministic fallback.

    Returns worksheets on success, or None when the deterministic engine
    should take over (no keys, parse failure, or judge rejected twice).
    """
    if not os.environ.get("WORKSHEET_LLM_ADAPT"):
        return None

    if rules is None:
        rules = build_rules(profile)

    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        logger.info("  LLM planner: no API keys, falling back to deterministic")
        return None

    base_prompt = _build_planner_prompt(skill, profile, rules, theme_id, rag_curriculum_references)

    verdicts: list[JudgeVerdict] = []
    model_label = "none"
    prompt = base_prompt

    for attempt in range(2):  # one call + one regeneration with feedback
        if attempt == 1:
            prompt = base_prompt + "\n\n" + _feedback_suffix(verdicts[-1])
            logger.info("  LLM planner: regenerating once with judge feedback")

        response_text, model_label = _call_planner(prompt)
        if response_text is None:
            break
        plan = _parse_lesson_plan(response_text)
        if plan is None:
            logger.warning("  LLM planner: failed to parse plan (attempt %d)", attempt + 1)
            break
        worksheets = enforce_section_cap(
            _translate_plan(plan, skill, profile, theme_id, rules), rules
        )
        if not worksheets:
            logger.warning("  LLM planner: translation produced no worksheets")
            break

        verdict = judge_adaptation(skill, worksheets)
        if verdict is None:
            outcome = "planned_unjudged"
            _write_verdict_artifact(_unjudged_payload(outcome), artifacts_dir)
            _log_performance(
                _entry(skill, outcome, verdicts, None, model_label, judged=False),
                artifacts_dir,
            )
            logger.warning("  LLM planner: judge unavailable, shipping unjudged")
            return worksheets

        verdicts.append(verdict)
        if verdict.approved:
            outcome = "planned_approved" if attempt == 0 else "planned_regen_approved"
            _write_verdict_artifact(_verdict_payload(verdict, outcome), artifacts_dir)
            _log_performance(
                _entry(skill, outcome, verdicts, verdict.overall_score, model_label),
                artifacts_dir,
            )
            logger.info("  LLM planner: %s (score=%.2f)", outcome, verdict.overall_score)
            return worksheets

        logger.warning(
            "  LLM planner: judge rejected attempt %d (score=%.2f)",
            attempt + 1,
            verdict.overall_score,
        )

    if verdicts:
        outcome = "planned_rejected_fallback"
    elif model_label != "none":
        outcome = "parse_failure_fallback"
    else:
        outcome = "llm_unavailable"
    _write_planner_attempts(outcome, verdicts, artifacts_dir)
    _log_performance(
        _entry(skill, outcome, verdicts, None, model_label, judged=False),
        artifacts_dir,
    )
    logger.info("  LLM planner: %s — deterministic engine takes over", outcome)
    return None


def _feedback_suffix(verdict: JudgeVerdict) -> str:
    """Judge feedback appended to the prompt for the single regeneration."""
    feedback_lines = "\n".join(f"- {fb}" for fb in verdict.feedback)
    return f"""## Previous Attempt Feedback

Your previous plan was REJECTED by the pedagogical reviewer. You MUST fix all issues below.

Scores:
- Concept alignment: {verdict.concept_alignment:.2f}
- Content coverage: {verdict.content_coverage:.2f}
- Lesson flow: {verdict.lesson_flow:.2f}
- ADHD compliance: {verdict.adhd_compliance:.2f}
- Overall: {verdict.overall_score:.2f}

Specific feedback:
{feedback_lines}

Rationale: {verdict.rationale}

IMPORTANT: Address ALL feedback items above. Ensure EVERY source word, chain, and \
sentence appears in your revised plan. Do not drop any content."""


def _verdict_payload(verdict: JudgeVerdict, outcome: str) -> dict[str, object]:
    payload: dict[str, object] = dict(verdict.model_dump())
    payload["outcome"] = outcome
    payload["planner_version"] = 2
    return payload


def _unjudged_payload(outcome: str) -> dict[str, object]:
    return {
        "approved": None,
        "overall_score": None,
        "outcome": outcome,
        "unjudged": True,
        "pedagogical_judge_ran": False,
        "planner_version": 2,
        "rationale": "Judge unavailable; planner output shipped without a verdict.",
    }


def _write_verdict_artifact(payload: dict[str, object], artifacts_dir: str | None) -> None:
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "judge_verdict.json").write_text(json.dumps(payload, indent=2))


def _write_planner_attempts(
    outcome: str,
    verdicts: list[JudgeVerdict],
    artifacts_dir: str | None,
) -> None:
    """Record rejected attempts WITHOUT claiming a verdict for what ships.

    Deliberately not judge_verdict.json: when the planner falls back, the
    deterministic output is what ships, and transform.py runs the advisory
    judge on it (judge-everything policy).
    """
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "planner_attempts.json").write_text(
        json.dumps(
            {
                "outcome": outcome,
                "planner_version": 2,
                "verdicts": [v.model_dump() for v in verdicts],
            },
            indent=2,
        )
    )


def _entry(
    skill: LiteracySkillModel,
    outcome: str,
    verdicts: list[JudgeVerdict],
    final_score: float | None,
    planning_model: str,
    judged: bool = True,
) -> PlannerLogEntry:
    return PlannerLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        skill_domain=skill.domain,
        specific_skill=skill.specific_skill,
        template_type=skill.template_type,
        outcome=outcome,
        planning_model=planning_model,
        judge_verdicts=[v.model_dump() for v in verdicts],
        final_score=final_score,
        final_output_judged=judged,
    )


def _log_performance(entry: PlannerLogEntry, artifacts_dir: str | None) -> None:
    line = entry.model_dump_json() + "\n"
    if artifacts_dir:
        path = Path(artifacts_dir)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)
    # The global cross-run log is live telemetry — never write it from tests.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        global_log = Path("logs")
        global_log.mkdir(parents=True, exist_ok=True)
        with open(global_log / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)
    logger.info(
        "  LLM planner log: outcome=%s model=%s score=%s",
        entry.outcome,
        entry.planning_model,
        f"{entry.final_score:.2f}" if entry.final_score is not None else "N/A",
    )
