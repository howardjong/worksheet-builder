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
from typing import Literal

from pydantic import BaseModel, Field

from adapt.objective_ledger import EvidenceItem, ObjectiveLedger, build_objective_ledger
from adapt.schema import AdaptedActivityModel
from skill.schema import LiteracySkillModel
from validate.blocking_gates import BlockingGateResult, run_blocking_gates
from validate.objective_coverage import (
    ObjectiveCoverageResult,
    build_evidence_index,
    evaluate_objective_coverage,
)

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
    # ADHD supports (numbered steps, time estimates, brain breaks, feedback panel)
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
        if ws.feedback:
            ws_lines.append(f"    Feedback panel: {ws.feedback.goal_statement}")
            ws_lines.append(f"      {ws.feedback.parent_log_title}")
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


DEFAULT_OPENAI_TEXT_MODEL = "gpt-5.4"


def openai_text_model() -> str:
    """OpenAI model for judge + planner text calls (WORKSHEET_OPENAI_TEXT_MODEL).

    One knob for both call sites so a poorly-performing or overpriced model can
    be swapped without a code change.
    """
    return os.environ.get("WORKSHEET_OPENAI_TEXT_MODEL", DEFAULT_OPENAI_TEXT_MODEL)


def _call_openai(prompt: str, max_completion_tokens: int = 1024) -> str | None:
    """Call the configured OpenAI text model and return the response text."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model = openai_text_model()
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=max_completion_tokens,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI %s call failed: %s", model, e)
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


# =========================================================================== #
# Objective-sufficiency judge input contract (T7)
#
# A NEW judge surface that lives alongside the OLD judge above. It is built but
# NOT wired into production until T9 (flag-gated WORKSHEET_OBJECTIVE_COVERAGE).
#
# Division of labour (no double-counting): the deterministic validator (T6) is
# AUTHORITATIVE for counts, required-form presence, and distinctness — these are
# handed to the judge as FACTS. The judge scores only QUALITY ("good?"), never
# "enough?". The prompt below makes that boundary explicit.
# =========================================================================== #

JUDGE_CONTRACT_VERSION = "objective_sufficiency_judge_v1"

# Typed severe-defect veto (Session 50). Per essential cell the judge may emit,
# WITH cited evidence, zero or more of these typed severe defects. These — not a
# fuzzy numeric floor — are the judge's hard veto on an essential cell. Defined
# once here so the T8 output schema can reuse the same enum.
SevereDefectType = Literal[
    "wrong_cognitive_task",
    "misleading_or_wrong_instruction",
    "generic_activity_not_exercising_objective",
    "child_cannot_reasonably_answer",
    "overwhelming_or_adhd_unsafe",
]

SEVERE_DEFECT_TYPES: tuple[str, ...] = (
    "wrong_cognitive_task",
    "misleading_or_wrong_instruction",
    "generic_activity_not_exercising_objective",
    "child_cannot_reasonably_answer",
    "overwhelming_or_adhd_unsafe",
)

# Human-readable gloss for each severe defect, rendered into the prompt so the
# judge knows exactly what each enum value means.
_SEVERE_DEFECT_GLOSS: dict[str, str] = {
    "wrong_cognitive_task": (
        "the activity makes the child do a different cognitive task than the "
        "objective names (e.g. a copying/tracing task where the objective is "
        "decoding)"
    ),
    "misleading_or_wrong_instruction": (
        "the instruction is wrong, contradictory, or would mislead the child"
    ),
    "generic_activity_not_exercising_objective": (
        "generic busywork that does not genuinely exercise THIS objective's pattern/skill"
    ),
    "child_cannot_reasonably_answer": (
        "a child ages 5-8 cannot reasonably complete the item as written "
        "(missing info, impossible, mis-keyed)"
    ),
    "overwhelming_or_adhd_unsafe": (
        "the item is overwhelming or ADHD-unsafe (too dense, too many steps, no scaffold)"
    ),
}


def _render_objectives(ledger: ObjectiveLedger) -> str:
    """Render the ledger objective cells the judge must score (handed facts)."""
    lines: list[str] = []
    for cell in ledger.objectives:
        forms = ", ".join(cell.required_forms) if cell.required_forms else "(none)"
        lines.append(
            f"  - {cell.objective_id} [{cell.importance}] {cell.objective_type}: "
            f'"{cell.display_name}" — concept={cell.concept!r}, '
            f"target_pattern={cell.target_pattern!r}, required_forms=[{forms}], "
            f"sufficiency_rule={cell.sufficiency_rule!r}"
        )
    return "\n".join(lines) if lines else "  (none)"


def _render_blocking_gates(gates: BlockingGateResult) -> str:
    """Render the deterministic blocking-gate facts (passed + any violations)."""
    if gates.passed:
        return "  passed=true (no deterministic blockers fired)"
    lines = ["  passed=false — the package FAILED deterministic blockers:"]
    for v in gates.violations:
        if v.severity != "blocker":
            continue
        loc = v.item_id or v.activity_id or "?"
        lines.append(f"    - [{v.gate}] at {loc}: {v.message}")
    return "\n".join(lines)


def _render_deterministic_coverage(coverage: ObjectiveCoverageResult) -> str:
    """Render the AUTHORITATIVE deterministic coverage facts (counts/forms)."""
    lines: list[str] = [
        f"  definition={coverage.definition}",
        f"  overall_status={coverage.status} (passed={coverage.passed})",
        f"  role_counts={coverage.role_counts}",
        "  objective_results (counts/required-form/distinctness are FINAL — do not re-derive):",
    ]
    for r in coverage.objective_results:
        missing = ", ".join(r.missing_required_forms) if r.missing_required_forms else "(none)"
        lines.append(
            f"    - {r.objective_id} [{r.importance}]: status={r.status}, "
            f"distinct_high_confidence={r.distinct_high_confidence_count}/"
            f"{r.min_practice_count}, advisory_low_confidence="
            f"{r.advisory_low_confidence_count}, required_forms_present="
            f"{r.required_forms_present}, missing_required_forms=[{missing}]"
        )
    if coverage.package_bounds.breaches:
        lines.append(f"  package_bound_breaches={coverage.package_bounds.breaches}")
    return "\n".join(lines)


def _render_adapted_activity(worksheets: list[AdaptedActivityModel]) -> str:
    """Render the adapted package (full text — the judge gates what ships)."""
    ws_sections: list[str] = []
    for ws in worksheets:
        chunk_lines: list[str] = []
        for chunk in ws.chunks:
            lines = [f"    Section {chunk.chunk_id}: {chunk.micro_goal}"]
            lines.append(
                "      Instructions: "
                + " | ".join(f"{s.number}. {s.text}" for s in chunk.instructions)
            )
            if chunk.worked_example is not None:
                lines.append(f"      Worked example: {chunk.worked_example.content}")
            for item in chunk.items:
                item_line = f'      - "{item.content}" ({item.response_format})'
                if item.options:
                    item_line += f" options={item.options}"
                if item.answer is not None:
                    item_line += f" answer={item.answer!r}"
                lines.append(item_line)
            chunk_lines.append("\n".join(lines))
        title = ws.worksheet_title or f"Worksheet {ws.worksheet_number}"
        ws_sections.append(f"  Worksheet {ws.worksheet_number}: {title}\n" + "\n".join(chunk_lines))
    return "\n\n".join(ws_sections) if ws_sections else "  (none)"


def _render_evidence_index(evidence: list[EvidenceItem]) -> str:
    """Render the typed evidence index (each item cite-able by evidence_item_id)."""
    lines: list[str] = []
    for ev in evidence:
        ids = ", ".join(ev.objective_ids) if ev.objective_ids else "(none)"
        text = ev.visible_text if ev.visible_text else (ev.answer_key_text or "")
        lines.append(
            f"  - id={ev.evidence_item_id} role={ev.practice_role} "
            f"format={ev.response_format} student_production={ev.is_student_production} "
            f"objective_ids=[{ids}] text={text!r}"
        )
    return "\n".join(lines) if lines else "  (none)"


def _build_objective_judge_prompt(
    ledger: ObjectiveLedger,
    blocking_gates: BlockingGateResult,
    deterministic_coverage: ObjectiveCoverageResult,
    adapted_activity: list[AdaptedActivityModel],
    evidence_index: list[EvidenceItem],
) -> str:
    """Build the objective-sufficiency judge prompt (judge scores handed ledger).

    Assembles the judge input parts per the spec's "Judge Input And Output
    Contract" — ``objective_ledger`` + ``blocking_gates`` +
    ``deterministic_coverage`` + ``adapted_activity`` + ``evidence_index`` — into a
    readable prompt. The judge scores QUALITY only (0-1); counts, required-form
    presence, and distinctness are handed in as FINAL facts.
    """
    severe_defect_lines = "\n".join(
        f"  - {name}: {_SEVERE_DEFECT_GLOSS[name]}" for name in SEVERE_DEFECT_TYPES
    )
    severe_defect_enum = " / ".join(SEVERE_DEFECT_TYPES)

    objectives = ", ".join(c.objective_id for c in ledger.objectives) or "(none)"

    return f"""You are a pediatric literacy specialist and ADHD learning expert reviewing an \
adapted phonics worksheet PACKAGE for a child ages 5-8.

judge_contract_version: {JUDGE_CONTRACT_VERSION}

## What you are scoring (and what you are NOT)

A deterministic validator has ALREADY decided the QUANTITATIVE questions for this \
package. Counts (how many distinct target words are practiced), required-form \
presence, and distinctness are FINAL FACTS handed to you below — they are correct. \
Your job is to score QUALITY: clarity, developmental fit, coherence, and whether \
each practice activity GENUINELY EXERCISES its objective. You answer "good?"; the \
validator already answered "enough?".

You MUST NOT:
  - re-derive, recount, or override the handed counts / required-form presence / \
distinctness — they are authoritative;
  - You MUST NOT create new objectives beyond the ones handed to you \
({objectives});
  - reclassify source items, or re-decide a word's role;
  - count contrast, review, or irregular words toward a target-pattern objective \
(only the target pattern's own words exercise it);
  - require that every source word, or every Roll and Read item, or every word in \
a samplable pool appears — samplable pools NEED NOT be exhausted; practicing a \
representative sample is correct and sufficient;
  - approve a package that FAILED the deterministic blockers below — if \
blocking_gates.passed is false you MUST NOT approve.

(There is no requirement to include every source word. Do not penalize a package \
for omitting pool words it was free to sample from.)

## objective_ledger (the objectives you score — handed facts)

ledger_version: {ledger.ledger_version}
lesson_number: {ledger.lesson_number}
primary_pattern: {ledger.primary_pattern!r}
objectives:
{_render_objectives(ledger)}

## blocking_gates (deterministic hard blocks — authoritative)

{_render_blocking_gates(blocking_gates)}

## deterministic_coverage (counts / required-form / distinctness — FINAL)

{_render_deterministic_coverage(deterministic_coverage)}

## adapted_activity (the package to evaluate — full text)

{_render_adapted_activity(adapted_activity)}

## evidence_index (typed, cite-able by evidence_item_id)

{_render_evidence_index(evidence_index)}

## How to score

For EACH objective cell handed above, give a per-cell quality score in [0.0, 1.0]. \
This per-cell quality score is ADVISORY / DIAGNOSTIC confidence — it is NOT a \
pass/fail threshold and NOT a hard gate. A bare low score with no cited defect is \
diagnostic only, not a block.

The HARD veto on an ESSENTIAL cell is the typed severe-defect list, not a number. \
For each essential cell, emit zero or more typed severe defects from this fixed \
enum, and you MUST CITE the supporting evidence (the evidence_item_id(s) above) \
for every defect you assert:
{severe_defect_lines}

A severe defect with cited evidence on an essential cell is a real block. A low \
score alone is not.

Score each on 0.0-1.0 (do NOT use a 0-5 scale). Be rigorous but fair: the \
worksheet should teach each objective effectively for a child ages 5-8.

## Output Format

Respond with ONLY this JSON (no markdown fences). Give one entry in \
``objective_scores`` for EACH objective cell handed above (matched by \
``objective_id``). ``severe_defects`` is a (possibly empty) list of typed \
defects, each citing its ``evidence`` (the evidence_item_id(s) + why). The five \
criteria and ``overall_score`` are package-level 0.0-1.0 scores.
{{
  "objective_scores": [
    {{
      "objective_id": "obj_decode",
      "quality": 0.0-1.0,
      "severe_defects": [
        {{"defect_type": "one of {severe_defect_enum}", "evidence": "evidence_item_id(s) + why"}}
      ],
      "evidence_item_ids": ["evidence_item_id", "..."],
      "rationale": "1-2 sentence per-cell assessment"
    }}
  ],
  "objective_sufficiency": 0.0-1.0,
  "skill_form_fidelity": 0.0-1.0,
  "structured_literacy_alignment": 0.0-1.0,
  "adhd_cognitive_load_fit": 0.0-1.0,
  "lesson_flow_and_usability": 0.0-1.0,
  "overall_score": 0.0-1.0,
  "approval_recommendation": "approve" | "abstain" | "reject",
  "feedback": ["specific feedback item 1", "specific feedback item 2"]
}}"""


# =========================================================================== #
# Objective-sufficiency judge OUTPUT schema + per-cell aggregation +
# AUTHORITATIVE tri-state derivation (T8)
#
# Lives alongside the OLD judge. The LLM emits per-cell quality (advisory) and a
# typed severe-defect list per essential cell. We aggregate N samples PER cell:
# numeric quality by median, severe defects by a CONSERVATIVE vote (2/3 -> reject
# that cell, 1/3 with cited evidence -> abstain, never silently ignored). The
# authoritative tri-state (approve/abstain/reject) is derived from the AGGREGATED
# verdict plus the deterministic facts (blocking gates + coverage + ledger).
# Built but NOT wired into production until T9 (flag-gated).
# =========================================================================== #


class SevereDefect(BaseModel):
    """One typed severe defect the judge asserts against an essential cell.

    ``evidence`` must cite the supporting evidence_item_id(s) and say why — a
    severe defect without cited evidence is not a real block (see the prompt).
    """

    defect_type: SevereDefectType
    evidence: str


class ObjectiveJudgeCellScore(BaseModel):
    """Per-objective-cell judge output.

    ``quality`` is ADVISORY / diagnostic confidence, NOT a hard gate. The hard
    veto on an essential cell is the typed ``severe_defects`` list.
    ``severe_defect_vote`` is NOT emitted by the LLM — it is derived during
    aggregation (the conservative vote across N samples). The default keeps a
    single-sample parse valid.
    """

    objective_id: str
    quality: float = Field(ge=0.0, le=1.0)
    severe_defects: list[SevereDefect] = Field(default_factory=list)
    evidence_item_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    severe_defect_vote: Literal["none", "abstain", "reject"] = "none"


class ObjectiveJudgeVerdict(BaseModel):
    """Objective-sufficiency judge verdict (per-cell scores + 5 criteria).

    ``objective_sufficiency`` is the transition rename of the OLD judge's
    ``content_coverage``. ``contract_version`` is fixed by us, not the LLM;
    everything else except each cell's ``severe_defect_vote`` is emitted by the
    judge. ``approval_recommendation`` here is DIAGNOSTIC — the authoritative
    tri-state is ``derive_objective_approval``.
    """

    contract_version: Literal["objective_sufficiency_judge_v1"] = "objective_sufficiency_judge_v1"
    objective_scores: list[ObjectiveJudgeCellScore] = Field(default_factory=list)
    objective_sufficiency: float = Field(ge=0.0, le=1.0)
    skill_form_fidelity: float = Field(ge=0.0, le=1.0)
    structured_literacy_alignment: float = Field(ge=0.0, le=1.0)
    adhd_cognitive_load_fit: float = Field(ge=0.0, le=1.0)
    lesson_flow_and_usability: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    approval_recommendation: Literal["approve", "abstain", "reject"] = "abstain"
    feedback: list[str] = Field(default_factory=list)


def _parse_objective_verdict(text: str) -> ObjectiveJudgeVerdict | None:
    """Parse a GPT 5.4 response into an ObjectiveJudgeVerdict (mirror old parse)."""
    try:
        data = json.loads(_extract_json(text))
        return ObjectiveJudgeVerdict.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to parse objective judge verdict: %s", e)
        return None


def judge_objective_adaptation(
    ledger: ObjectiveLedger,
    blocking_gates: BlockingGateResult,
    deterministic_coverage: ObjectiveCoverageResult,
    worksheets: list[AdaptedActivityModel],
    evidence: list[EvidenceItem],
) -> ObjectiveJudgeVerdict | None:
    """Evaluate a package with the objective-sufficiency judge (one call).

    Returns an ObjectiveJudgeVerdict on success, or None if the judge is
    unavailable (no key), the call fails, or the response cannot be parsed.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        logger.info("  Objective judge: no OPENAI_API_KEY, skipping")
        return None

    prompt = _build_objective_judge_prompt(
        ledger, blocking_gates, deterministic_coverage, worksheets, evidence
    )

    logger.info("  Objective judge: calling GPT 5.4...")
    response_text = _call_openai(prompt)
    if response_text is None:
        return None

    verdict = _parse_objective_verdict(response_text)
    if verdict is None:
        return None

    logger.info(
        "  Objective judge: recommendation=%s (overall=%.2f, sufficiency=%.2f, adhd=%.2f, cells=%d)",
        verdict.approval_recommendation,
        verdict.overall_score,
        verdict.objective_sufficiency,
        verdict.adhd_cognitive_load_fit,
        len(verdict.objective_scores),
    )
    for fb in verdict.feedback:
        logger.info("    - %s", fb)

    return verdict


def judge_objective_adaptation_samples(
    ledger: ObjectiveLedger,
    blocking_gates: BlockingGateResult,
    deterministic_coverage: ObjectiveCoverageResult,
    worksheets: list[AdaptedActivityModel],
    evidence: list[EvidenceItem],
    samples: int,
) -> list[ObjectiveJudgeVerdict]:
    """Call the objective judge ``samples`` times; return the RAW per-sample list.

    Failed calls are dropped. Returns ``[]`` if every call failed. Aggregation is
    deliberately separate (``aggregate_objective_verdicts``) — the conservative
    severe-defect vote needs the per-sample data, so this does not aggregate.
    """
    collected: list[ObjectiveJudgeVerdict] = []
    for _ in range(max(1, samples)):
        verdict = judge_objective_adaptation(
            ledger, blocking_gates, deterministic_coverage, worksheets, evidence
        )
        if verdict is not None:
            collected.append(verdict)
    return collected


def _resolve_cell_vote(
    defect_sample_count: int, n_samples: int
) -> Literal["none", "abstain", "reject"]:
    """Conservative per-defect-type vote: 2/3 -> reject, >=1 -> abstain, else none."""
    if defect_sample_count * 3 >= 2 * n_samples:
        return "reject"
    if defect_sample_count >= 1:
        return "abstain"
    return "none"


def _aggregate_cell(
    objective_id: str,
    per_sample_cells: list[ObjectiveJudgeCellScore],
    n_samples: int,
) -> ObjectiveJudgeCellScore:
    """Aggregate one objective cell across the samples that scored it.

    ``quality`` is the median across samples that reported the cell. The
    ``severe_defect_vote`` is the most severe vote across defect types (reject >
    abstain > none), counted per defect_type across the N total samples.
    """
    quality = statistics.median(c.quality for c in per_sample_cells)

    # Count, per defect_type, how many samples carried at least one such defect.
    defect_sample_counts: dict[str, int] = {}
    representative_evidence: dict[str, str] = {}
    for cell in per_sample_cells:
        seen_here: set[str] = set()
        for defect in cell.severe_defects:
            if defect.defect_type in seen_here:
                continue
            seen_here.add(defect.defect_type)
            defect_sample_counts[defect.defect_type] = (
                defect_sample_counts.get(defect.defect_type, 0) + 1
            )
            representative_evidence.setdefault(defect.defect_type, defect.evidence)

    vote: Literal["none", "abstain", "reject"] = "none"
    severe_defects: list[SevereDefect] = []
    _rank = {"none": 0, "abstain": 1, "reject": 2}
    for defect_type in SEVERE_DEFECT_TYPES:
        count = defect_sample_counts.get(defect_type, 0)
        type_vote = _resolve_cell_vote(count, n_samples)
        if type_vote == "none":
            continue
        # Defect reached at least abstain-level — carry it with a representative
        # evidence string from a sample that reported it.
        severe_defects.append(
            SevereDefect(
                defect_type=defect_type,  # type: ignore[arg-type]
                evidence=representative_evidence[defect_type],
            )
        )
        if _rank[type_vote] > _rank[vote]:
            vote = type_vote

    # rationale / evidence_item_ids from a representative sample (the first one
    # that reported the cell, stable across runs).
    representative = per_sample_cells[0]
    return ObjectiveJudgeCellScore(
        objective_id=objective_id,
        quality=quality,
        severe_defects=severe_defects,
        evidence_item_ids=representative.evidence_item_ids,
        rationale=representative.rationale,
        severe_defect_vote=vote,
    )


def aggregate_objective_verdicts(
    verdicts: list[ObjectiveJudgeVerdict],
) -> ObjectiveJudgeVerdict:
    """Combine N objective-judge samples into one aggregated verdict.

    Per objective cell (matched by ``objective_id``): ``quality`` is the median
    across samples; ``severe_defect_vote`` is the conservative vote per
    defect_type (>= 2/3 of samples -> reject, >= 1 sample with cited evidence ->
    abstain, else none). For N=1 a single credible defect on a cell -> reject
    (conservative for safety, by design). The five criteria + ``overall_score``
    are the median across samples; ``feedback`` and ``approval_recommendation``
    come from the representative (closest-to-median overall) sample.

    A single verdict returns a COPY with each cell's ``severe_defect_vote``
    resolved. The authoritative tri-state is ``derive_objective_approval``.
    """
    if not verdicts:
        raise ValueError("aggregate_objective_verdicts requires at least one verdict")

    n_samples = len(verdicts)

    # Gather each cell's per-sample scores, preserving first-seen objective order.
    ordered_ids: list[str] = []
    per_cell: dict[str, list[ObjectiveJudgeCellScore]] = {}
    for verdict in verdicts:
        for cell in verdict.objective_scores:
            if cell.objective_id not in per_cell:
                per_cell[cell.objective_id] = []
                ordered_ids.append(cell.objective_id)
            per_cell[cell.objective_id].append(cell)

    aggregated_cells = [_aggregate_cell(oid, per_cell[oid], n_samples) for oid in ordered_ids]

    objective_sufficiency = statistics.median(v.objective_sufficiency for v in verdicts)
    skill_form = statistics.median(v.skill_form_fidelity for v in verdicts)
    structured = statistics.median(v.structured_literacy_alignment for v in verdicts)
    adhd = statistics.median(v.adhd_cognitive_load_fit for v in verdicts)
    flow = statistics.median(v.lesson_flow_and_usability for v in verdicts)
    overall = statistics.median(v.overall_score for v in verdicts)
    representative = min(verdicts, key=lambda v: abs(v.overall_score - overall))

    return ObjectiveJudgeVerdict(
        objective_scores=aggregated_cells,
        objective_sufficiency=objective_sufficiency,
        skill_form_fidelity=skill_form,
        structured_literacy_alignment=structured,
        adhd_cognitive_load_fit=adhd,
        lesson_flow_and_usability=flow,
        overall_score=overall,
        approval_recommendation=representative.approval_recommendation,
        feedback=representative.feedback,
    )


# Objective-sufficiency tri-state bands (mirror the OLD judge's
# _APPROVE_OVERALL_MIN 0.70 / _APPROVE_CRITERION_MIN 0.50). Named so the policy
# reads without scattered magic numbers.
_OBJ_OVERALL_MIN = 0.70  # overall_score below this -> reject
_OBJ_ADHD_MIN = 0.50  # adhd_cognitive_load_fit below this -> reject
_OBJ_CELL_FAIL = 0.50  # essential-cell quality below this -> reject
_OBJ_CELL_PASS = 0.65  # essential-cell quality in [FAIL, PASS) -> abstain


def derive_objective_approval(
    judge: ObjectiveJudgeVerdict | None,
    blocking: BlockingGateResult,
    coverage: ObjectiveCoverageResult,
    ledger: ObjectiveLedger,
) -> Literal["approve", "abstain", "reject"]:
    """AUTHORITATIVE tri-state approval for the objective-sufficiency path.

    The caller MUST pass the AGGREGATED verdict (the one whose cells carry a
    resolved ``severe_defect_vote``) — the per-cell vote is read here. Policy:
    deterministic / missing-judge rejects short-circuit; then judge-side rejects
    (overall / adhd / essential-cell quality floor / a 2-of-3 severe-defect
    veto); then abstains (coverage needs verification, an essential cell in the
    [0.50, 0.65) quality band, or a 1-of-3 severe-defect on an essential cell);
    else approve.
    """
    if judge is None or not blocking.passed or coverage.status == "fail":
        return "reject"

    essential_ids = {
        cell.objective_id for cell in ledger.objectives if cell.importance == "essential"
    }
    essential_scores = [s for s in judge.objective_scores if s.objective_id in essential_ids]

    # judge-side REJECT
    if judge.overall_score < _OBJ_OVERALL_MIN:
        return "reject"
    if judge.adhd_cognitive_load_fit < _OBJ_ADHD_MIN:
        return "reject"
    if any(s.quality < _OBJ_CELL_FAIL for s in essential_scores):
        return "reject"
    if any(s.severe_defect_vote == "reject" for s in essential_scores):
        return "reject"

    # COMPLETENESS GUARD — never auto-approve unless the judge scored EVERY
    # essential cell. A cell the judge omitted (or an empty objective_scores)
    # carries no quality signal; treating it as a pass is a false approve. The
    # conservative, spec-consistent outcome is abstain (route to fallback). This
    # sits after the reject checks (a genuine reject on a SCORED cell still wins)
    # and before the abstain checks.
    scored_ids = {s.objective_id for s in judge.objective_scores}
    if not essential_ids.issubset(scored_ids):
        return "abstain"

    # ABSTAIN
    if coverage.status == "needs_verification":
        return "abstain"
    if any(_OBJ_CELL_FAIL <= s.quality < _OBJ_CELL_PASS for s in essential_scores):
        return "abstain"
    if any(s.severe_defect_vote == "abstain" for s in essential_scores):
        return "abstain"

    return "approve"


# =========================================================================== #
# Advisory objective judge — fail-before-render policy (P3b)
#
# A single public entry point transform.py Stage 5c calls for the FALLBACK
# (deterministic-engine) package, i.e. when the planner did NOT already write
# judge_verdict.json. Composes exactly what the planner-path objective judging
# does (build_objective_ledger -> run_blocking_gates -> build_evidence_index ->
# evaluate_objective_coverage -> judge_objective_adaptation, which itself calls
# _build_objective_judge_prompt + _call_openai + _parse_objective_verdict) —
# no prompt text is duplicated here. Never raises: any exception anywhere in
# that chain is caught, logged, and turned into None so a judge-side failure
# can never block a package from shipping (transform.py's policy for None is
# "ship with a loud warning").
# =========================================================================== #


def judge_package_objective(
    skill_model: LiteracySkillModel,
    worksheets: list[AdaptedActivityModel],
) -> ObjectiveJudgeVerdict | None:
    """Advisory objective-sufficiency judge for a finished fallback package.

    Returns a single-sample ``ObjectiveJudgeVerdict`` (contract_version
    ``objective_sufficiency_judge_v1``) on success, or ``None`` on ANY
    infra/API failure (no key, provider error, unparseable response) — this
    function must never raise. transform.py Stage 5c decides what to do with
    each outcome per the P3b policy matrix.
    """
    try:
        ledger = build_objective_ledger(skill_model)
        gates = run_blocking_gates(worksheets, ledger)
        evidence = build_evidence_index(worksheets, ledger)
        coverage = evaluate_objective_coverage(ledger, evidence, worksheets)
        return judge_objective_adaptation(ledger, gates, coverage, worksheets, evidence)
    except Exception as exc:
        logger.warning("  Objective judge (advisory): unavailable — %s", exc)
        return None
