"""AI-in-the-loop quality review — evaluates adapted worksheets before rendering."""

from __future__ import annotations

import json
import logging
import os

from adapt.schema import AdaptedActivityModel

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
    ) -> None:
        self.passed = passed
        self.issues = issues  # [{"criterion": ..., "description": ...}]
        self.suggestions = suggestions  # [{"chunk_id": ..., "item_id": ..., "fix": ...}]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }


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

        logger.info(
            f"  Found {len(result.issues)} issues, "
            f"{len(result.suggestions)} suggestions"
        )

        # Apply suggestions
        if result.suggestions:
            adapted = _apply_suggestions(adapted, result.suggestions)
        else:
            # No actionable suggestions — stop iterating
            logger.info("  No actionable suggestions — accepting current output")
            break

    return adapted, reviews


def _run_review(adapted: AdaptedActivityModel) -> ReviewResult:
    """Send adapted model to AI for quality review."""
    # Try Gemini first, then OpenAI
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        result = _review_with_gemini(adapted, gemini_key)
        if result is not None:
            return result

    if openai_key:
        result = _review_with_openai(adapted, openai_key)
        if result is not None:
            return result

    # No AI available — pass through
    logger.info("  No AI API key available — skipping quality review")
    return ReviewResult(passed=True, issues=[], suggestions=[])


def _build_review_prompt(adapted: AdaptedActivityModel) -> str:
    """Build the prompt for AI quality review."""
    # Serialize the adapted model to a readable format
    chunks_desc = []
    for chunk in adapted.chunks:
        items_desc = []
        for item in chunk.items:
            items_desc.append(
                f"    - Item {item.item_id}: \"{item.content}\" "
                f"(format: {item.response_format})"
            )
        chunks_desc.append(
            f"  Chunk {chunk.chunk_id}: {chunk.micro_goal}\n"
            f"    Instructions: {[s.text for s in chunk.instructions]}\n"
            + "\n".join(items_desc)
        )

    worksheet_text = (
        f"Grade: {adapted.grade_level}\n"
        f"Domain: {adapted.domain}\n"
        f"Skill: {adapted.specific_skill}\n"
        f"Theme: {adapted.theme_id}\n\n"
        + "\n\n".join(chunks_desc)
    )

    if adapted.self_assessment:
        worksheet_text += "\n\nSelf-assessment:\n"
        worksheet_text += "\n".join(f"  - {s}" for s in adapted.self_assessment)

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
        "OCR errors — never to substitute different words.\n\n"
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
        '      "action": "fix_content" or "remove_item",\n'
        '      "fixed_content": "corrected text (only if fix_content)"\n'
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


def _review_with_gemini(
    adapted: AdaptedActivityModel, api_key: str
) -> ReviewResult | None:
    """Run quality review using Gemini."""
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        prompt = _build_review_prompt(adapted)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        return _parse_review_response(str(response.text))

    except Exception as e:
        logger.warning(f"Gemini review failed: {e}")
        return None


def _review_with_openai(
    adapted: AdaptedActivityModel, api_key: str
) -> ReviewResult | None:
    """Run quality review using OpenAI GPT-5.4."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = _build_review_prompt(adapted)

        response = client.chat.completions.create(
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1024,
        )

        text = response.choices[0].message.content or ""
        return _parse_review_response(text)

    except Exception as e:
        logger.warning(f"OpenAI review failed: {e}")
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

    for s in suggestions:
        try:
            chunk_id = int(s.get("chunk_id", 0))
            item_id = int(s.get("item_id", 0))
            action = s.get("action", "fix_content")

            if action == "remove_item":
                removals.add((chunk_id, item_id))
            elif action == "fix_content" and s.get("fixed_content"):
                fixes[(chunk_id, item_id)] = s
        except (ValueError, TypeError):
            continue

    if not fixes and not removals:
        return adapted

    # Rebuild chunks with fixes applied
    from adapt.schema import ActivityChunk, ActivityItem

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
                    f"\"{item.content[:30]}\" -> \"{fixed[:30]}\""
                )
                new_items.append(
                    ActivityItem(
                        item_id=item.item_id,
                        content=str(fixed),
                        response_format=item.response_format,
                        metadata=item.metadata,
                    )
                )
            else:
                new_items.append(item)

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
