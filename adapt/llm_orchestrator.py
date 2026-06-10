"""LLM adaptation orchestrator — retry loop with GPT takeover and performance logging.

Flow:
1. Gemini plans → GPT 5.4 judges → Approved? Done
2. Rejected → Gemini retries with feedback → GPT judges → Approved? Done
3. Rejected again → GPT 5.4 takes over planning (no self-judging)
4. Only if both LLMs unavailable → return None (deterministic fallback)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from adapt.llm_adapt import (
    LessonPlan,
    _build_adapt_prompt,
    _call_gemini,
    _parse_lesson_plan,
    _translate_plan,
)
from adapt.llm_judge import (
    JudgeVerdict,
    _call_openai,
    judge_adaptation,
)
from adapt.rules import AccommodationRules, build_rules
from adapt.schema import AdaptedActivityModel
from companion.schema import LearnerProfile
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)

MAX_GEMINI_ATTEMPTS = 2


class AdaptationLogEntry(BaseModel):
    """One row in llm_adaptation_log.jsonl."""

    timestamp: str
    skill_domain: str
    specific_skill: str
    template_type: str
    outcome: str
    gemini_attempts: int
    judge_verdicts: list[dict[str, object]] = Field(default_factory=list)
    final_score: float | None = None
    final_output_judged: bool = True
    final_judge_status: str = "approved"
    planning_model: str  # gemini-3-flash-preview | gpt-5.4 | deterministic
    error_details: str | None = None


def orchestrate_llm_adaptation(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str = "default",
    rules: AccommodationRules | None = None,
    rag_curriculum_references: list[dict[str, object]] | None = None,
    artifacts_dir: str | None = None,
) -> list[AdaptedActivityModel] | None:
    """Orchestrate LLM adaptation with retry loop and GPT takeover.

    Requires WORKSHEET_LLM_ADAPT=1 environment variable.
    Returns worksheets on success, or None if both LLMs are unavailable
    (caller should fall back to deterministic engine).
    """
    if not os.environ.get("WORKSHEET_LLM_ADAPT"):
        return None

    if rules is None:
        rules = build_rules(profile)

    gemini_available = bool(os.environ.get("GEMINI_API_KEY"))
    gpt_available = bool(os.environ.get("OPENAI_API_KEY"))

    if not gemini_available and not gpt_available:
        logger.info("  LLM orchestrator: no API keys available, falling back to deterministic")
        return None

    verdicts: list[JudgeVerdict] = []
    gemini_attempts = 0

    # --- Gemini rounds (up to MAX_GEMINI_ATTEMPTS) ---
    if gemini_available:
        for attempt in range(MAX_GEMINI_ATTEMPTS):
            gemini_attempts += 1

            if attempt == 0 or not verdicts:
                logger.info(
                    "  LLM orchestrator: Gemini attempt %d/%d", attempt + 1, MAX_GEMINI_ATTEMPTS
                )
                plan, worksheets = _gemini_plan(
                    skill, profile, theme_id, rules, rag_curriculum_references
                )
            else:
                logger.info(
                    "  LLM orchestrator: Gemini retry %d/%d with judge feedback",
                    attempt + 1,
                    MAX_GEMINI_ATTEMPTS,
                )
                plan, worksheets = _gemini_plan_with_feedback(
                    skill,
                    profile,
                    theme_id,
                    rules,
                    verdicts[-1],
                    rag_curriculum_references,
                )

            if plan is None or worksheets is None:
                logger.warning(
                    "  LLM orchestrator: Gemini attempt %d failed to produce a plan", attempt + 1
                )
                continue

            # Judge the plan (only if GPT is available)
            if gpt_available:
                verdict = judge_adaptation(skill, worksheets)
                if verdict is not None:
                    verdicts.append(verdict)
                    _write_judge_verdict(verdict, artifacts_dir)

                    if verdict.approved:
                        outcome = "gemini_first_try" if attempt == 0 else "gemini_retry"
                        logger.info(
                            "  LLM orchestrator: %s (score=%.2f)", outcome, verdict.overall_score
                        )
                        _log_performance(
                            _build_log_entry(
                                skill,
                                outcome,
                                gemini_attempts,
                                verdicts,
                                verdict.overall_score,
                                "gemini-3-flash-preview",
                            ),
                            artifacts_dir,
                        )
                        return worksheets
                    else:
                        logger.warning(
                            "  LLM orchestrator: Gemini attempt %d rejected (score=%.2f)",
                            attempt + 1,
                            verdict.overall_score,
                        )
                else:
                    # Judge call itself failed — accept Gemini's plan
                    logger.warning("  LLM orchestrator: judge unavailable, accepting Gemini plan")
                    _log_performance(
                        _build_log_entry(
                            skill,
                            "gemini_unjudged",
                            gemini_attempts,
                            verdicts,
                            None,
                            "gemini-3-flash-preview",
                            final_output_judged=False,
                            final_judge_status="unjudged",
                        ),
                        artifacts_dir,
                    )
                    return worksheets
            else:
                # No judge available — accept Gemini's plan
                logger.info("  LLM orchestrator: no judge available, accepting Gemini plan")
                _log_performance(
                    _build_log_entry(
                        skill,
                        "gemini_unjudged",
                        gemini_attempts,
                        verdicts,
                        None,
                        "gemini-3-flash-preview",
                        final_output_judged=False,
                        final_judge_status="unjudged",
                    ),
                    artifacts_dir,
                )
                return worksheets

    # --- GPT takeover ---
    if gpt_available:
        logger.info("  LLM orchestrator: GPT 5.4 taking over planning")
        worksheets = _gpt_plan(skill, profile, theme_id, rules, verdicts, rag_curriculum_references)
        if worksheets:
            outcome = "gpt_takeover_unjudged"
            _write_unjudged_verdict(outcome, verdicts, artifacts_dir)
            _log_performance(
                _build_log_entry(
                    skill,
                    outcome,
                    gemini_attempts,
                    verdicts,
                    None,
                    "gpt-5.4",
                    final_output_judged=False,
                    final_judge_status="unjudged",
                ),
                artifacts_dir,
            )
            return worksheets
        else:
            logger.warning("  LLM orchestrator: GPT takeover also failed")

    # Both LLM paths exhausted
    _log_performance(
        _build_log_entry(
            skill,
            "llm_failure",
            gemini_attempts,
            verdicts,
            None,
            "none",
            "Both LLM paths exhausted",
        ),
        artifacts_dir,
    )
    return None


# --- Gemini planning ---


def _gemini_plan(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    rules: AccommodationRules,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> tuple[LessonPlan | None, list[AdaptedActivityModel] | None]:
    """Call Gemini to plan worksheets. Returns (plan, worksheets) or (None, None)."""
    prompt = _build_adapt_prompt(skill, profile, rules, theme_id, rag_curriculum_references)
    response_text = _call_gemini(prompt)
    if response_text is None:
        return None, None

    plan = _parse_lesson_plan(response_text)
    if plan is None:
        return None, None

    logger.info("  Gemini planned %d worksheets — %s", len(plan.worksheets), plan.concept_focus)

    worksheets = _translate_plan(plan, skill, profile, theme_id, rules)
    if not worksheets:
        return plan, None

    return plan, worksheets


def _gemini_plan_with_feedback(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    rules: AccommodationRules,
    verdict: JudgeVerdict,
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> tuple[LessonPlan | None, list[AdaptedActivityModel] | None]:
    """Call Gemini with judge feedback appended to the prompt."""
    base_prompt = _build_adapt_prompt(skill, profile, rules, theme_id, rag_curriculum_references)
    feedback_suffix = _build_retry_prompt_suffix(verdict)
    prompt = base_prompt + "\n\n" + feedback_suffix

    response_text = _call_gemini(prompt)
    if response_text is None:
        return None, None

    plan = _parse_lesson_plan(response_text)
    if plan is None:
        return None, None

    logger.info(
        "  Gemini retry planned %d worksheets — %s", len(plan.worksheets), plan.concept_focus
    )

    worksheets = _translate_plan(plan, skill, profile, theme_id, rules)
    if not worksheets:
        return plan, None

    return plan, worksheets


def _build_retry_prompt_suffix(verdict: JudgeVerdict) -> str:
    """Construct feedback text from a JudgeVerdict for Gemini retry."""
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

IMPORTANT: Address ALL feedback items above. Ensure EVERY source word, chain, and sentence appears in your revised plan. Do not drop any content."""


# --- GPT takeover planning ---


def _gpt_plan(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    theme_id: str,
    rules: AccommodationRules,
    accumulated_verdicts: list[JudgeVerdict],
    rag_curriculum_references: list[dict[str, object]] | None = None,
) -> list[AdaptedActivityModel] | None:
    """GPT 5.4 takes over planning after Gemini failures."""
    base_prompt = _build_adapt_prompt(skill, profile, rules, theme_id, rag_curriculum_references)

    # Append all accumulated feedback so GPT knows what went wrong
    feedback_parts: list[str] = []
    for i, verdict in enumerate(accumulated_verdicts, 1):
        feedback_parts.append(f"### Attempt {i} Feedback (score: {verdict.overall_score:.2f})")
        for fb in verdict.feedback:
            feedback_parts.append(f"- {fb}")
        feedback_parts.append(f"Rationale: {verdict.rationale}")

    if feedback_parts:
        feedback_text = "\n".join(feedback_parts)
        prompt = (
            base_prompt
            + f"\n\n## Previous Failed Attempts\n\nA different model attempted this task {len(accumulated_verdicts)} time(s) and was rejected each time. Learn from these failures:\n\n{feedback_text}\n\nYou MUST produce a plan that addresses ALL the feedback above. Ensure complete content coverage."
        )
    else:
        prompt = base_prompt

    response_text = _call_openai(prompt, max_completion_tokens=4096)
    if response_text is None:
        return None

    plan = _parse_lesson_plan(response_text)
    if plan is None:
        logger.warning("  GPT takeover: failed to parse plan")
        return None

    logger.info(
        "  GPT takeover planned %d worksheets — %s", len(plan.worksheets), plan.concept_focus
    )

    worksheets = _translate_plan(plan, skill, profile, theme_id, rules)
    if not worksheets:
        logger.warning("  GPT takeover: translation produced no worksheets")
        return None

    return worksheets


# --- Logging and artifacts ---


def _build_log_entry(
    skill: LiteracySkillModel,
    outcome: str,
    gemini_attempts: int,
    verdicts: list[JudgeVerdict],
    final_score: float | None,
    planning_model: str,
    error_details: str | None = None,
    final_output_judged: bool = True,
    final_judge_status: str = "approved",
) -> AdaptationLogEntry:
    """Build a log entry for the JSONL performance log."""
    return AdaptationLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        skill_domain=skill.domain,
        specific_skill=skill.specific_skill,
        template_type=skill.template_type,
        outcome=outcome,
        gemini_attempts=gemini_attempts,
        judge_verdicts=[v.model_dump() for v in verdicts],
        final_score=final_score,
        final_output_judged=final_output_judged,
        final_judge_status=final_judge_status,
        planning_model=planning_model,
        error_details=error_details,
    )


def _write_judge_verdict(verdict: JudgeVerdict, artifacts_dir: str | None) -> None:
    """Write judge_verdict.json to artifacts directory."""
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    verdict_path = path / "judge_verdict.json"
    verdict_path.write_text(json.dumps(verdict.model_dump(), indent=2))


def _write_unjudged_verdict(
    outcome: str,
    prior_verdicts: list[JudgeVerdict],
    artifacts_dir: str | None,
) -> None:
    """Write a marker when the final LLM output was not independently judged."""
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    verdict_path = path / "judge_verdict.json"
    verdict_path.write_text(
        json.dumps(
            {
                "approved": None,
                "overall_score": None,
                "outcome": outcome,
                "unjudged": True,
                "pedagogical_judge_ran": False,
                "rationale": "Final LLM-planned output was not independently judged.",
                "prior_judge_verdicts": [verdict.model_dump() for verdict in prior_verdicts],
            },
            indent=2,
        )
    )


def _log_performance(entry: AdaptationLogEntry, artifacts_dir: str | None) -> None:
    """Append a log entry to the JSONL performance log."""
    line = entry.model_dump_json() + "\n"

    # Write to artifacts dir (per-run)
    if artifacts_dir:
        path = Path(artifacts_dir)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "llm_adaptation_log.jsonl", "a") as f:
            f.write(line)

    # Write to global log (cross-run visibility)
    global_log = Path("logs")
    global_log.mkdir(parents=True, exist_ok=True)
    with open(global_log / "llm_adaptation_log.jsonl", "a") as f:
        f.write(line)

    logger.info(
        "  LLM orchestrator log: outcome=%s model=%s gemini_attempts=%d score=%s",
        entry.outcome,
        entry.planning_model,
        entry.gemini_attempts,
        f"{entry.final_score:.2f}" if entry.final_score is not None else "N/A",
    )
