"""AI-in-the-loop quality review — evaluates adapted worksheets before rendering."""

from __future__ import annotations

import json
import logging

from adapt.schema import AdaptedActivityModel
from ai.telemetry import in_stage

logger = logging.getLogger(__name__)

# Quality criteria the AI evaluates
QUALITY_CRITERIA = [
    "content_accuracy: All words and sentences are real, correctly spelled, and age-appropriate",
    "skill_preservation: The adapted activity still teaches the original literacy skill",
    "adhd_compliance: Content is chunked, instructions are numbered and short, no clutter",
    "age_appropriateness: Language and difficulty match the grade level (K-3)",
    "completeness: No truncated text, missing items, or placeholder content",
    "chain_structure: Word chains show valid letter-by-letter transformations",
    "sentence_quality: Practice sentences are complete and grammatically correct",
]

MAX_REVIEW_ITERATIONS = 3


class ReviewResult:
    """Result of an AI quality review."""

    def __init__(
        self,
        passed: bool,
        issues: list[dict[str, str]],
        suggestions: list[dict[str, str]],
        skipped_no_api_key: bool = False,
    ) -> None:
        self.passed = passed
        self.issues = issues  # [{"criterion": ..., "description": ...}]
        self.suggestions = suggestions  # [{"chunk_id": ..., "item_id": ..., "fix": ...}]
        self.skipped_no_api_key = skipped_no_api_key

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "passed": self.passed,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }
        if self.skipped_no_api_key:
            data["skipped_no_api_key"] = True
        return data


@in_stage("review")
def review_adapted_worksheet(
    adapted: AdaptedActivityModel,
    max_iterations: int = MAX_REVIEW_ITERATIONS,
) -> tuple[AdaptedActivityModel, list[ReviewResult]]:
    """Review and iteratively fix an adapted worksheet using AI.

    Sends the adapted model to AI for quality evaluation. If issues are found,
    applies suggested fixes and re-reviews until quality passes or max iterations.

    Returns (possibly-fixed adapted model, list of review results).
    """
    reviews: list[ReviewResult] = []

    for iteration in range(1, max_iterations + 1):
        logger.info(f"  AI review iteration {iteration}/{max_iterations}...")

        result = _run_review(adapted)
        reviews.append(result)

        if result.passed:
            logger.info(f"  AI review passed on iteration {iteration}")
            return adapted, reviews

        logger.info(f"  Found {len(result.issues)} issues, {len(result.suggestions)} suggestions")

        # Apply suggestions
        if result.suggestions and iteration < max_iterations:
            adapted = _apply_suggestions(adapted, result.suggestions)
        else:
            # No actionable suggestions — stop iterating
            logger.info("  No actionable suggestions — accepting current output")
            break

    return adapted, reviews


def _run_review(adapted: AdaptedActivityModel) -> ReviewResult:
    """Send adapted model to AI for quality review."""
    from ai import openrouter

    if not openrouter.available():
        return ReviewResult(passed=True, issues=[], suggestions=[], skipped_no_api_key=True)
    raw = openrouter.complete_json(
        _build_review_prompt(adapted),
        model_ids=openrouter.stage_models("review"),
        validate=lambda value: (
            isinstance(value.get("passed"), bool)
            and isinstance(value.get("issues"), list)
            and isinstance(value.get("suggestions"), list)
        ),
    )
    parsed = _parse_review_response(json.dumps(raw)) if raw is not None else None
    return parsed or ReviewResult(
        passed=False,
        issues=[
            {
                "criterion": "review_unavailable",
                "description": "OpenRouter review unavailable",
            }
        ],
        suggestions=[],
    )


def _build_review_prompt(adapted: AdaptedActivityModel) -> str:
    """Build the prompt for AI quality review."""
    # Serialize the adapted model to a readable format
    chunks_desc = []
    for chunk in adapted.chunks:
        items_desc = []
        for item in chunk.items:
            options = f", options={item.options}" if item.options else ""
            answer = f", answer={item.answer!r}" if item.answer else ""
            items_desc.append(
                f'    - Item {item.item_id}: "{item.content}" '
                f"(format: {item.response_format}{options}{answer})"
            )
        chunks_desc.append(
            f"  Chunk {chunk.chunk_id}: {chunk.micro_goal}\n"
            f"    Instructions: {[s.text for s in chunk.instructions]}\n" + "\n".join(items_desc)
        )

    worksheet_text = (
        f"Grade: {adapted.grade_level}\n"
        f"Domain: {adapted.domain}\n"
        f"Skill: {adapted.specific_skill}\n"
        f"Theme: {adapted.theme_id}\n\n" + "\n\n".join(chunks_desc)
    )

    if adapted.feedback:
        worksheet_text += "\nFeedback panel:\n"
        worksheet_text += f"  - Goal: {adapted.feedback.goal_statement}\n"
        worksheet_text += f"  - {adapted.feedback.parent_log_title}"

    criteria_text = "\n".join(f"- {c}" for c in QUALITY_CRITERIA)

    return (
        "You are reviewing an ADHD-adapted literacy worksheet for a child "
        "ages 5-8. Check it against these quality criteria:\n\n"
        f"{criteria_text}\n\n"
        "CRITICAL RULES:\n"
        "- Do NOT change or substitute the actual words/content. "
        "The words come from the original UFLI worksheet and MUST be preserved.\n"
        "- Do NOT suggest replacing words with different words. "
        "The specific words are the learning targets.\n"
        "- Only flag STRUCTURAL issues: truncated text (ending in '...'), "
        "garbled/nonsensical content, items that are clearly formatting "
        "artifacts rather than real content, or ADHD anti-patterns.\n"
        "- Use 'remove_item' for items that are formatting artifacts "
        "(e.g., raw markup, teacher instructions that leaked through).\n"
        "- Use 'fix_content' ONLY to fix truncated text or obvious "
        "OCR errors — never to substitute different words.\n"
        "- For every sentence with a word bank: does EXACTLY ONE option fit "
        "the sentence? If more than one fits, emit suggestion "
        '{"action": "remove_option", "item_id": N, "option": "word"} '
        "for each extra plausible option.\n\n"
        "Here is the worksheet content:\n\n"
        f"{worksheet_text}\n\n"
        "Respond with ONLY this JSON (no markdown fences):\n"
        "{\n"
        '  "passed": true or false,\n'
        '  "issues": [\n'
        '    {"criterion": "...", "description": "..."}\n'
        "  ],\n"
        '  "suggestions": [\n'
        "    {\n"
        '      "chunk_id": 1,\n'
        '      "item_id": 1,\n'
        '      "action": "fix_content" or "remove_item" or "remove_option",\n'
        '      "fixed_content": "corrected text (only if fix_content)",\n'
        '      "option": "word to remove (only if remove_option)"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If the worksheet looks good, set passed=true with empty arrays. "
        "Be conservative — only flag real problems, not preferences."
    )


def _parse_review_response(text: str) -> ReviewResult | None:
    """Parse AI review response into ReviewResult."""
    text = text.strip()

    # Extract JSON from markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            if line.strip() == "```" and in_block:
                break
            if in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    try:
        data = json.loads(text)
        return ReviewResult(
            passed=bool(data.get("passed", True)),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse AI review response: {e}")
        return None


def _apply_suggestions(
    adapted: AdaptedActivityModel,
    suggestions: list[dict[str, str]],
) -> AdaptedActivityModel:
    """Apply AI suggestions to fix the adapted model.

    Creates a new model with fixes applied. Non-destructive — only modifies
    items that match suggestion chunk_id and item_id.
    """
    # Build a lookup of fixes: (chunk_id, item_id) -> suggestion
    fixes: dict[tuple[int, int], dict[str, str]] = {}
    removals: set[tuple[int, int]] = set()
    option_removals: dict[tuple[int, int], list[str]] = {}

    for s in suggestions:
        try:
            chunk_id = int(s.get("chunk_id", 0))
            item_id = int(s.get("item_id", 0))
            action = s.get("action", "fix_content")

            if action == "remove_item":
                removals.add((chunk_id, item_id))
            elif action == "fix_content" and s.get("fixed_content"):
                fixes[(chunk_id, item_id)] = s
            elif action == "remove_option" and s.get("option"):
                option_removals.setdefault((chunk_id, item_id), []).append(str(s["option"]))
        except (ValueError, TypeError):
            continue

    if not fixes and not removals and not option_removals:
        return adapted

    # Rebuild chunks with fixes applied
    from adapt.schema import ActivityChunk

    new_chunks = []
    for chunk in adapted.chunks:
        new_items = []
        for item in chunk.items:
            key = (chunk.chunk_id, item.item_id)

            if key in removals:
                logger.info(f"  Removing item {item.item_id} from chunk {chunk.chunk_id}")
                continue

            if key in fixes:
                fixed = fixes[key].get("fixed_content", item.content)
                logger.info(
                    f"  Fixing chunk {chunk.chunk_id} item {item.item_id}: "
                    f'"{item.content[:30]}" -> "{fixed[:30]}"'
                )
                item = item.model_copy(update={"content": str(fixed)})

            if key in option_removals and item.options:
                options = list(item.options)
                for option in option_removals[key]:
                    # Guardrails: never remove the answer, never drop below
                    # 2 remaining options.
                    if option == item.answer:
                        continue
                    if option not in options:
                        continue
                    if len(options) <= 2:
                        continue
                    options.remove(option)
                    logger.info(
                        f"  Removing ambiguous option '{option}' from "
                        f"chunk {chunk.chunk_id} item {item.item_id}"
                    )
                if options != item.options:
                    item = item.model_copy(update={"options": options})

            new_items.append(item)

        if not new_items:
            # A mutation may remove a bad item, but it must never leave task
            # instructions and scoring chrome with nothing for the child to do.
            logger.warning(
                "  Refusing suggestions that would empty chunk %s; preserving original items",
                chunk.chunk_id,
            )
            new_items = list(chunk.items)

        new_chunks.append(
            ActivityChunk(
                chunk_id=chunk.chunk_id,
                micro_goal=chunk.micro_goal,
                instructions=chunk.instructions,
                worked_example=chunk.worked_example,
                items=new_items,
                response_format=chunk.response_format,
                time_estimate=chunk.time_estimate,
                reward_event=chunk.reward_event,
            )
        )

    return adapted.model_copy(update={"chunks": new_chunks})
