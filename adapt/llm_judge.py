"""GPT 5.4 pedagogical judge — validates adapted worksheets before rendering.

Evaluates whether the LLM-planned adaptation preserves the teaching objective,
uses appropriate activities for the concept, and maintains ADHD accommodations.

This is separate from validate/ai_review.py which checks structural quality
(spelling, truncation, formatting artifacts). The judge checks pedagogical
soundness — does this worksheet actually teach what it's supposed to?
"""

from __future__ import annotations

import json
import logging
import os
import statistics

from pydantic import BaseModel

from adapt.schema import AdaptedActivityModel
from skill.schema import LiteracySkillModel

logger = logging.getLogger(__name__)


class JudgeVerdict(BaseModel):
    """Result of the pedagogical judge evaluation."""

    approved: bool
    overall_score: float  # 0.0 to 1.0
    concept_alignment: float  # Do activities reinforce the target concept?
    content_coverage: float  # Are all source words/chains/sentences included?
    lesson_flow: float  # Is the progression pedagogically sound?
    adhd_compliance: float  # Are ADHD accommodations properly applied?
    feedback: list[str]  # Specific feedback items
    rationale: str  # Overall assessment


def _build_judge_prompt(
    skill: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
) -> str:
    """Build the prompt for GPT 5.4 pedagogical evaluation."""

    # Source content summary
    source_sections = []
    for si in skill.source_items:
        source_sections.append(f"  - [{si.item_type}]: {si.content}")
    source_text = "\n".join(source_sections) if source_sections else "  (none)"

    # Adapted worksheets — FULL text, the judge gates what ships. Render the
    # ADHD supports (numbered steps, time estimates, brain breaks, self-check)
    # so the adhd_compliance score reflects what the worksheet actually carries.
    ws_sections = []
    for ws in worksheets:
        chunks_desc = []
        for chunk in ws.chunks:
            lines = [f"    Section {chunk.chunk_id}: {chunk.micro_goal}"]
            lines.append(
                "      Instructions: "
                + " | ".join(f"{s.number}. {s.text}" for s in chunk.instructions)
            )
            if chunk.time_estimate:
                lines.append(f"      Time estimate: {chunk.time_estimate}")
            if chunk.worked_example is not None:
                lines.append(f"      Worked example: {chunk.worked_example.content}")
            for item in chunk.items:
                item_line = f'      - "{item.content}" ({item.response_format})'
                if item.options:
                    item_line += f" options={item.options}"
                if item.answer is not None:
                    item_line += f" answer={item.answer!r}"
                lines.append(item_line)
            chunks_desc.append("\n".join(lines))
        ws_lines = [
            f"  Worksheet {ws.worksheet_number}: {ws.worksheet_title}",
            "\n".join(chunks_desc),
        ]
        if ws.break_prompt:
            ws_lines.append(f"    Brain break: {ws.break_prompt}")
        if ws.self_assessment:
            ws_lines.append("    Self-check: " + ", ".join(ws.self_assessment))
        ws_sections.append("\n".join(ws_lines))
    adapted_text = "\n\n".join(ws_sections)

    return f"""You are a pediatric literacy specialist and ADHD learning expert reviewing adapted worksheets for a child ages 5-8.

## Original Source Content

Template: {skill.template_type}
Concept being taught: {skill.specific_skill}
Domain: {skill.domain}
Grade level: {skill.grade_level}
Target words: {", ".join(skill.target_words)}

Source sections from the original worksheet:
{source_text}

## Adapted Worksheets (to evaluate)

{adapted_text}

## Evaluation Criteria

Score each criterion 0.0-1.0:

1. **concept_alignment**: Do the activities reinforce the specific concept ("{skill.specific_skill}")? Activities should make the child practice and internalize this pattern, not just do generic phonics work.

2. **content_coverage**: Are ALL source words, word chains, sight words, and sentences from the original worksheet represented somewhere in the adapted output? Nothing should be dropped.

3. **lesson_flow**: Is the worksheet ordering pedagogically sound? Core practice activities should come before reinforcement. The progression should build understanding.

4. **adhd_compliance**: Are ADHD accommodations properly applied? Chunked content, numbered instructions, worked examples, time estimates, brain breaks, not too many items per chunk.

5. **Structural quality (fold into your scores and approval)**: Every item must be real, correctly spelled, complete text. If any item is truncated (e.g., ends mid-sentence or in "..."), garbled, misspelled, or a formatting artifact (raw markup, teacher-only instructions), set approved=false and name the exact item in feedback.

## Output Format

Respond with ONLY this JSON (no markdown fences):
{{
  "approved": true or false,
  "overall_score": 0.0-1.0,
  "concept_alignment": 0.0-1.0,
  "content_coverage": 0.0-1.0,
  "lesson_flow": 0.0-1.0,
  "adhd_compliance": 0.0-1.0,
  "feedback": ["specific feedback item 1", "specific feedback item 2"],
  "rationale": "Overall assessment in 2-3 sentences"
}}

Approve if overall_score >= 0.7 and no criterion is below 0.5.
Be rigorous but fair — the worksheets should teach the concept effectively."""


def _call_openai(prompt: str, max_completion_tokens: int = 1024) -> str | None:
    """Call GPT 5.4 and return the response text."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=max_completion_tokens,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("GPT 5.4 judge call failed: %s", e)
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


def _parse_verdict(text: str) -> JudgeVerdict | None:
    """Parse GPT 5.4 response into a JudgeVerdict."""
    try:
        data = json.loads(_extract_json(text))
        return JudgeVerdict.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to parse judge verdict: %s", e)
        return None


def judge_adaptation(
    skill: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
) -> JudgeVerdict | None:
    """Evaluate adapted worksheets using GPT 5.4 as pedagogical judge.

    Returns a JudgeVerdict on success, or None if the judge is unavailable.
    The caller decides what to do with a failing verdict (retry, fallback, etc.).
    """
    if not os.environ.get("OPENAI_API_KEY"):
        logger.info("  Pedagogical judge: no OPENAI_API_KEY, skipping")
        return None

    prompt = _build_judge_prompt(skill, worksheets)

    logger.info("  Pedagogical judge: calling GPT 5.4...")
    response_text = _call_openai(prompt)
    if response_text is None:
        return None

    verdict = _parse_verdict(response_text)
    if verdict is None:
        return None

    status = "APPROVED" if verdict.approved else "REJECTED"
    logger.info(
        "  Pedagogical judge: %s (score=%.2f, concept=%.2f, coverage=%.2f, flow=%.2f, adhd=%.2f)",
        status,
        verdict.overall_score,
        verdict.concept_alignment,
        verdict.content_coverage,
        verdict.lesson_flow,
        verdict.adhd_compliance,
    )
    for fb in verdict.feedback:
        logger.info("    - %s", fb)

    return verdict


# Documented approval rule (mirrors the judge prompt): approve iff the overall
# score clears 0.70 and no individual criterion drops below 0.50.
_APPROVE_OVERALL_MIN = 0.70
_APPROVE_CRITERION_MIN = 0.50


def _aggregate_verdicts(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """Combine repeated judge samples into one median verdict.

    A single sample is returned unchanged (production default). With multiple
    samples, each score is the median across samples and ``approved`` is
    recomputed from those medians per the documented rule — this removes
    per-call sampling noise from the gate. The prose (feedback/rationale) comes
    from the sample whose overall score is closest to the median.
    """
    if len(verdicts) == 1:
        return verdicts[0]

    concept = statistics.median(v.concept_alignment for v in verdicts)
    coverage = statistics.median(v.content_coverage for v in verdicts)
    flow = statistics.median(v.lesson_flow for v in verdicts)
    adhd = statistics.median(v.adhd_compliance for v in verdicts)
    overall = statistics.median(v.overall_score for v in verdicts)
    approved = (
        overall >= _APPROVE_OVERALL_MIN
        and min(concept, coverage, flow, adhd) >= _APPROVE_CRITERION_MIN
    )
    representative = min(verdicts, key=lambda v: abs(v.overall_score - overall))
    return JudgeVerdict(
        approved=approved,
        overall_score=overall,
        concept_alignment=concept,
        content_coverage=coverage,
        lesson_flow=flow,
        adhd_compliance=adhd,
        feedback=representative.feedback,
        rationale=representative.rationale,
    )


def judge_adaptation_samples(
    skill: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
    samples: int,
) -> JudgeVerdict | None:
    """Judge the adaptation ``samples`` times and return the median verdict.

    Failed calls are dropped; returns ``None`` only if every call failed.
    ``samples <= 1`` is exactly one judge call (production default).
    """
    collected: list[JudgeVerdict] = []
    for _ in range(max(1, samples)):
        verdict = judge_adaptation(skill, worksheets)
        if verdict is not None:
            collected.append(verdict)
    if not collected:
        return None
    return _aggregate_verdicts(collected)
