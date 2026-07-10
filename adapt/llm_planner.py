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

from adapt.coverage_ledger import (
    CoverageLedgerEntry,
    build_coverage_ledger,
    repair_coverage,
    verify_coverage,
)
from adapt.llm_adapt import LessonPlan, _call_gemini, _parse_lesson_plan, _translate_plan
from adapt.llm_judge import (
    JudgeVerdict,
    ObjectiveJudgeVerdict,
    _call_openai,
    aggregate_objective_verdicts,
    derive_objective_approval,
    judge_adaptation_samples,
    judge_objective_adaptation_samples,
    openai_text_model,
)
from adapt.objective_ledger import (
    ObjectiveCell,
    ObjectiveLedger,
    RequiredForm,
    build_objective_ledger,
)
from adapt.rules import AccommodationRules, build_rules, llm_adapt_enabled
from adapt.schema import AdaptedActivityModel
from adapt.section_cap import enforce_section_cap
from companion.schema import LearnerProfile
from corpus.ufli.lookup import lookup_lesson
from skill.schema import LiteracySkillModel
from validate.blocking_gates import run_blocking_gates
from validate.objective_coverage import build_evidence_index, evaluate_objective_coverage

logger = logging.getLogger(__name__)

DEFAULT_PLANNER_PROVIDERS = "openai,gemini"
DEFAULT_PLANNER_GEMINI_MODEL = "gemini-3.5-flash"
PLANNER_MAX_COMPLETION_TOKENS = 8192
_CORPUS_FIELD_CHAR_CAP = 2000


def _judge_samples() -> int:
    """How many times to judge each plan (median-of-N). Default 1 (production)."""
    try:
        return max(1, int(os.environ.get("WORKSHEET_JUDGE_SAMPLES", "1")))
    except ValueError:
        return 1


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
                return text, openai_text_model()
        elif provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
            model = os.environ.get("WORKSHEET_PLANNER_GEMINI_MODEL", DEFAULT_PLANNER_GEMINI_MODEL)
            text = _call_gemini(prompt, model=model)
            if text:
                return text, model
    return None, "none"


def _slot_contract_enabled() -> bool:
    """Whether the deterministic coverage contract is active (default OFF)."""
    return bool(os.environ.get("WORKSHEET_PLANNER_SLOT_CONTRACT"))


def _coverage_contract_block(skill: LiteracySkillModel) -> str:
    """Render the required ledger entries as an explicit coverage contract.

    Empty string when the flag is off so the prompt is byte-identical to today.
    """
    if not _slot_contract_enabled():
        return ""
    required = [e for e in build_coverage_ledger(skill) if e.priority == "required"]
    if not required:
        return ""
    lines = [_contract_line(e) for e in required]
    listing = "\n".join(lines)
    return f"""
## Coverage contract (REQUIRED — every id below MUST be covered)

Each row is `id | type | exact_text`. Every required id MUST be exercised by at
least one practice item, and each item MUST list the ids it covers in its
"covered_source_item_ids" field, reproducing the exact_text verbatim in the
item's content, options, or answer. Coverage is verified deterministically —
a claimed id whose exact_text is absent does NOT count.

{listing}
"""


def _contract_line(entry: CoverageLedgerEntry) -> str:
    return f"- {entry.source_item_id} | {entry.item_type} | {entry.exact_text}"


def _covered_ids_schema_line() -> str:
    """The extra item-schema key, only when the contract is active."""
    if not _slot_contract_enabled():
        return ""
    return ',\n              "covered_source_item_ids": ["id1", "id2"]'


def _objective_coverage_enabled() -> bool:
    """Whether objective-sufficiency authoring guidance is active (default OFF)."""
    return bool(os.environ.get("WORKSHEET_OBJECTIVE_COVERAGE"))


def _allow_unjudged_objective_plan() -> bool:
    """Whether to ship an objective plan unjudged when the judge is down (default OFF).

    Safe default: the objective path abstains to the deterministic fallback when the
    judge is unavailable. Set this flag to opt back into the old ship-unjudged behavior.
    """
    return bool(os.environ.get("WORKSHEET_ALLOW_UNJUDGED_OBJECTIVE_PLAN"))


# Maps each required pedagogical form to concrete "author IN this form" guidance.
# Keyed on RequiredForm Literal values; the load-bearing phrases (e.g. "ordered
# build/transformation") are pinned by tests/test_llm_planner.py.
_FORM_GUIDANCE: dict[RequiredForm, str] = {
    "word_chain": (
        "author an ordered build/transformation sequence — each step changes ONE "
        "letter/sound from the previous word, with explicit step language (e.g. "
        '"Make `tune`. Change the `u` to `o`. What word? ...`tone`"). Do NOT scatter '
        "the chain's words across separate write items."
    ),
    "chain_script": (
        "author an ordered build/transformation sequence — each step changes ONE "
        "letter/sound from the previous word, with explicit step language (e.g. "
        '"Make `tune`. Change the `u` to `o`. What word?"). Do NOT scatter the '
        "chain's words across separate write items."
    ),
    "decodable_passage": (
        "author real CONNECTED TEXT (a short passage), not a title or a lone sentence."
    ),
    "encoding_or_spelling": (
        "author WRITTEN PRODUCTION (the child writes/spells the word), not reading."
    ),
    "decodable_sentence": (
        "author PRODUCTION (the child writes the sentence), not just reading it."
    ),
    "irregular_word_practice": ("practice the irregular/heart words as whole words."),
    "contrast_sort_or_discrimination": (
        "author a deliberate sort / discrimination task that separates the target "
        "pattern from the contrast words."
    ),
}


def _objective_cell_block(cell: ObjectiveCell, content_by_id: dict[str, str]) -> str:
    """Render one objective cell: its identity, words, threshold, and form guidance."""
    lines = [
        f"### {cell.objective_id} — {cell.display_name} ({cell.importance})",
        f"- Required forms: {', '.join(cell.required_forms) or '(none)'}",
        f"- Target-pattern words (these exercise the pattern): "
        f"{', '.join(cell.target_words) or '(see source items below)'}",
        f"- Practice threshold (min): {cell.min_practice_count}",
    ]
    if cell.contrast_words:
        lines.append(
            f"- Contrast words (do NOT count toward this cell): {', '.join(cell.contrast_words)}"
        )
    if cell.irregular_words:
        lines.append(
            f"- Irregular words (do NOT count toward this cell): {', '.join(cell.irregular_words)}"
        )
    for fid in cell.source_item_ids:
        content = content_by_id.get(fid)
        if content:
            lines.append(f"- Source ({fid}): {content}")
    for form in cell.required_forms:
        lines.append(f"- For `{form}`: {_FORM_GUIDANCE[form]}")
    return "\n".join(lines)


def _objective_authoring_block(
    skill: LiteracySkillModel, ledger: ObjectiveLedger | None = None
) -> str:
    """Render per-objective authoring guidance: author each objective IN its form.

    Empty string when the flag is off (guarded FIRST, so no ledger is built) — the
    prompt stays byte-identical to today. When on, the ledger's objective cells +
    required forms + sampling/dilution rules are rendered for the planner. A caller
    may pass a prebuilt ``ledger`` to guarantee the prompt-ledger and the
    validation-ledger share identical facts; if None, it is built internally.
    """
    if not _objective_coverage_enabled():
        return ""
    if ledger is None:
        ledger = build_objective_ledger(skill)
    content_by_id = {si.source_item_id: si.content for si in ledger.source_items}
    cell_blocks = "\n\n".join(_objective_cell_block(c, content_by_id) for c in ledger.objectives)
    return f"""
## Objective coverage (author each objective IN its required form)

Each objective below MUST be exercised IN its required pedagogical form (not merely
mentioned). Follow these three rules:

1. AUTHOR EACH REQUIRED FORM IN ITS FORM. A word chain is an ordered \
build/transformation sequence (change one letter/sound per step, with explicit step \
language) — NOT the chain's words scattered across separate write items. A passage is \
connected text. An encode/spell objective is written production. A sentence-write \
objective is production (the child writes it).
2. SAMPLE samplable pools to the threshold, not exhaustively. For large pools \
(Roll-and-Read lists, long word lists) practice a representative sample up to the \
cell's threshold — do not include every pool word; you need not include all of them.
3. Do NOT dilute a target-pattern cell with contrast/review/irregular words. A \
target-pattern objective's practice MUST use the pattern's own words; contrast, \
review, and irregular words do not count toward it and must not pad it.

{cell_blocks}
"""


def _build_planner_prompt(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    theme_id: str,
    rag_curriculum_references: list[dict[str, object]] | None,
    objective_ledger: ObjectiveLedger | None = None,
) -> str:
    """Build the single planning prompt: full source, corpus truth, ADHD limits."""
    source_sections: list[str] = []
    for si in skill.source_items:
        source_sections.append(f"- [{si.item_type}]: {si.content}")
    source_text = "\n".join(source_sections) if source_sections else "(no source items)"

    corpus_text = _corpus_block(skill)
    contract_block = _coverage_contract_block(skill)
    objective_block = _objective_authoring_block(skill, objective_ledger)
    covered_ids_schema = _covered_ids_schema_line()

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
{contract_block}{objective_block}
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
- The FIRST section of the first worksheet MUST have a worked example. A worked
  example MUST model the CORRECT answer and end on a real word, correctly
  spelled (e.g. "c__ke -> cake"). NEVER show a wrong attempt, a non-word, or a
  self-refuting question like "Write cate? No." — only demonstrate what is right.
- One main task per section; keep each mini-worksheet to one page of focus

## Your Task

Design 2-3 mini-worksheets that teach "{skill.specific_skill}" effectively.

CRITICAL RULES:
1. Preserve ALL source content as INDIVIDUAL practice. Every source word, every
   word-chain step, and every source sentence MUST appear as its OWN separate
   item that the child actually works (read, write, build, or circle). Coverage
   is judged on individual practice, not mere presence:
   - Do NOT bundle multiple source words into one item, and do NOT dump a long
     word list into a single item's "content" or as one giant "option" — use
     one item per word.
   - A word chain (e.g. "mule -> mute -> cute") MUST be its own build/word-work
     activity with each step as an item, not only as a worked example.
   - Preserve each source sentence's full text in at least one item (a read item,
     or if you remove one letter/word keep the rest of the sentence intact).
   - For circle/fill_blank items, each item targets ONE answer with 2-4 short,
     real, single-word options; never use a phrase or a list of words as one
     option.
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
              "answer": "correct answer or null"{covered_ids_schema}
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


def _apply_coverage_contract(
    plan: LessonPlan,
    skill: LiteracySkillModel,
    rules: AccommodationRules,
) -> LessonPlan:
    """Verify the authored plan against the ledger and deterministically repair gaps.

    Removes content-coverage as a generation-variance source: any required source
    item the planner dropped is appended as deterministic catch-up practice before
    the plan is translated and judged. Only invoked when the slot contract is on.
    """
    ledger = build_coverage_ledger(skill)
    report = verify_coverage(plan, ledger)
    required = sum(1 for e in ledger if e.priority == "required")
    missing = len(report.missing)
    if report.missing:
        plan = repair_coverage(plan, report.missing, rules)
    logger.info(
        "  LLM planner coverage: required=%d covered=%d repaired=%d unknown_claims=%d",
        required,
        required - missing,
        missing,
        len(report.unknown_claims),
    )
    return plan


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
    if not llm_adapt_enabled():
        return None

    # Flag mutual-exclusion: never run both coverage systems at once. No-op unless
    # BOTH flags are set, so every existing path stays byte-identical.
    if _objective_coverage_enabled() and _slot_contract_enabled():
        raise RuntimeError(
            "WORKSHEET_OBJECTIVE_COVERAGE and WORKSHEET_PLANNER_SLOT_CONTRACT are "
            "mutually exclusive; enable at most one coverage system at a time"
        )

    if rules is None:
        rules = build_rules(profile)

    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        logger.info("  LLM planner: no API keys, falling back to deterministic")
        return None

    if _objective_coverage_enabled():
        return _plan_lesson_objective(
            skill, profile, rules, theme_id, rag_curriculum_references, artifacts_dir
        )

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
        if _slot_contract_enabled():
            plan = _apply_coverage_contract(plan, skill, rules)
        worksheets = enforce_section_cap(
            _translate_plan(plan, skill, profile, theme_id, rules), rules
        )
        if not worksheets:
            logger.warning("  LLM planner: translation produced no worksheets")
            break

        verdict = judge_adaptation_samples(skill, worksheets, _judge_samples())
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


def _plan_lesson_objective(
    skill: LiteracySkillModel,
    profile: LearnerProfile,
    rules: AccommodationRules,
    theme_id: str,
    rag_curriculum_references: list[dict[str, object]] | None,
    artifacts_dir: str | None,
) -> list[AdaptedActivityModel] | None:
    """Objective-sufficiency planning path (flag-gated WORKSHEET_OBJECTIVE_COVERAGE).

    One planning call → clamp → deterministic blocking gates → deterministic
    objective coverage → objective judge → tri-state approval. APPROVE ships;
    gate-block / coverage-fail / judge-reject / judge-abstain all route to the
    deterministic fallback (return None), each with a DISTINCT logged outcome.
    A single planning attempt (no regen): regeneration cannot resolve an abstain's
    uncertainty deterministically, so the deterministic engine takes over instead.
    """
    ledger = build_objective_ledger(skill)
    prompt = _build_planner_prompt(
        skill, profile, rules, theme_id, rag_curriculum_references, objective_ledger=ledger
    )

    response_text, model_label = _call_planner(prompt)
    if response_text is None:
        return _objective_fallback(skill, "llm_unavailable", model_label, None, artifacts_dir)

    plan = _parse_lesson_plan(response_text)
    if plan is None:
        logger.warning("  LLM planner (objective): failed to parse plan")
        return _objective_fallback(
            skill, "objective_parse_failure", model_label, None, artifacts_dir
        )

    worksheets = enforce_section_cap(_translate_plan(plan, skill, profile, theme_id, rules), rules)
    if not worksheets:
        logger.warning("  LLM planner (objective): translation produced no worksheets")
        return _objective_fallback(
            skill, "objective_no_worksheets", model_label, None, artifacts_dir
        )

    # 1. Deterministic blocking gates — block → reject, skip the judge entirely.
    gates = run_blocking_gates(worksheets, ledger)
    if not gates.passed:
        summary = "; ".join(
            f"{v.gate} {v.item_id or v.activity_id or '?'}: {v.message}"
            for v in gates.violations[:5]
        )
        logger.warning(
            "  LLM planner (objective): blocking gate failed → reject "
            "(%d violation(s), gates=%s): %s",
            len(gates.violations),
            sorted({v.gate for v in gates.violations}),
            summary,
        )
        return _objective_fallback(
            skill,
            "objective_rejected_gate",
            model_label,
            None,
            artifacts_dir,
            details={"gate_violations": [v.model_dump(mode="json") for v in gates.violations]},
        )

    # 2. Deterministic objective coverage — pass the SAME worksheets to both the
    #    evidence index AND the evaluator (the evaluator silently skips the package
    #    ADHD upper-bound checks if worksheets is omitted). det fail → reject.
    evidence = build_evidence_index(worksheets, ledger)
    coverage = evaluate_objective_coverage(ledger, evidence, worksheets)
    if coverage.status == "fail":
        failing = [
            cell.model_dump(
                mode="json",
                include={"objective_id", "status", "missing_required_forms", "notes"},
            )
            for cell in coverage.objective_results
            if cell.status != "pass"
        ]
        logger.warning(
            "  LLM planner (objective): deterministic coverage failed → reject "
            "(%d failing objective(s): %s)",
            len(failing),
            [f["objective_id"] for f in failing],
        )
        return _objective_fallback(
            skill,
            "objective_rejected_coverage",
            model_label,
            None,
            artifacts_dir,
            details={
                "coverage_failure": {
                    "status": coverage.status,
                    "failing_objectives": failing,
                    "package_bounds": coverage.package_bounds.model_dump(mode="json"),
                }
            },
        )

    # 3. Objective judge (raw per-sample list; [] when unavailable).
    samples = judge_objective_adaptation_samples(
        ledger, gates, coverage, worksheets, evidence, _judge_samples()
    )
    if not samples:
        if not _allow_unjudged_objective_plan():
            # Safe default: the judge is the Phase-2 quality review; gates + coverage
            # do not substitute for it. Abstain to the deterministic fallback so
            # transform.py judges what actually ships.
            logger.warning("  LLM planner (objective): judge unavailable → abstain to fallback")
            return _objective_fallback(
                skill, "objective_abstain_judge_unavailable", model_label, None, artifacts_dir
            )
        # Opt-in (WORKSHEET_ALLOW_UNJUDGED_OBJECTIVE_PLAN): the deterministic gates +
        # coverage already vetted it; ship unjudged.
        outcome = "objective_planned_unjudged"
        _write_verdict_artifact(_unjudged_payload(outcome), artifacts_dir)
        _log_performance(
            _objective_entry(skill, outcome, None, None, model_label, judged=False),
            artifacts_dir,
        )
        logger.warning("  LLM planner (objective): judge unavailable, shipping unjudged")
        return worksheets

    # 4. Aggregate (raises on empty — guarded above) then derive the tri-state. The
    #    AGGREGATED verdict carries the per-cell severe_defect_vote derive() reads.
    aggregated = aggregate_objective_verdicts(samples)
    decision = derive_objective_approval(aggregated, gates, coverage, ledger)

    # 5. Route on the authoritative tri-state decision.
    if decision == "approve":
        outcome = "objective_approved"
        _write_verdict_artifact(_objective_verdict_payload(aggregated, outcome), artifacts_dir)
        _log_performance(
            _objective_entry(skill, outcome, aggregated, aggregated.overall_score, model_label),
            artifacts_dir,
        )
        logger.info(
            "  LLM planner (objective): %s (overall=%.2f)", outcome, aggregated.overall_score
        )
        return worksheets

    outcome = "objective_abstain_fallback" if decision == "abstain" else "objective_rejected_judge"
    logger.info("  LLM planner (objective): judge decision=%s → fallback", decision)
    return _objective_fallback(skill, outcome, model_label, aggregated, artifacts_dir)


def _objective_fallback(
    skill: LiteracySkillModel,
    outcome: str,
    model_label: str,
    aggregated: ObjectiveJudgeVerdict | None,
    artifacts_dir: str | None,
    details: dict[str, object] | None = None,
) -> list[AdaptedActivityModel] | None:
    """Route the objective path to the deterministic fallback (return None).

    Mirrors the old fallback artifact policy: write planner_attempts.json, NOT
    judge_verdict.json — the deterministic engine takes over and transform.py
    judges what actually ships. The DISTINCT ``outcome`` keeps abstain, reject,
    gate, and coverage failures separable in the log/attempts; ``details``
    carries the rejection evidence (gate violations, failing coverage cells)
    so a rejection is debuggable from the artifact alone.
    """
    _write_objective_attempts(outcome, aggregated, artifacts_dir, details)
    _log_performance(
        _objective_entry(skill, outcome, aggregated, None, model_label, judged=False),
        artifacts_dir,
    )
    logger.info("  LLM planner (objective): %s — deterministic engine takes over", outcome)
    return None


def _objective_verdict_payload(verdict: ObjectiveJudgeVerdict, outcome: str) -> dict[str, object]:
    payload: dict[str, object] = dict(verdict.model_dump())
    payload["outcome"] = outcome
    payload["planner_version"] = 2
    return payload


def _write_objective_attempts(
    outcome: str,
    aggregated: ObjectiveJudgeVerdict | None,
    artifacts_dir: str | None,
    details: dict[str, object] | None = None,
) -> None:
    """Record a non-approved objective attempt WITHOUT claiming a shipped verdict.

    Deliberately not judge_verdict.json (mirrors ``_write_planner_attempts``): on
    fallback the deterministic output ships and transform.py runs the advisory
    judge on it. The aggregated verdict (when present) is serialized for telemetry.
    """
    if not artifacts_dir:
        return
    path = Path(artifacts_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "outcome": outcome,
        "planner_version": 2,
        "objective_coverage": True,
        "verdicts": [aggregated.model_dump()] if aggregated is not None else [],
    }
    if details:
        payload.update(details)
    (path / "planner_attempts.json").write_text(json.dumps(payload, indent=2))


def _objective_entry(
    skill: LiteracySkillModel,
    outcome: str,
    aggregated: ObjectiveJudgeVerdict | None,
    final_score: float | None,
    planning_model: str,
    judged: bool = True,
) -> PlannerLogEntry:
    """Build a PlannerLogEntry for the objective path (aggregated verdict telemetry)."""
    return PlannerLogEntry(
        timestamp=datetime.now(UTC).isoformat(),
        skill_domain=skill.domain,
        specific_skill=skill.specific_skill,
        template_type=skill.template_type,
        outcome=outcome,
        planning_model=planning_model,
        judge_verdicts=[aggregated.model_dump()] if aggregated is not None else [],
        final_score=final_score,
        final_output_judged=judged,
    )


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
