"""Full-page worksheet image prompt assembly.

Everything in this module is model-agnostic: it builds prompt text only.
Provider-specific details (reference-image conditioning, sizes, API calls)
live in render/image_providers.py. ADHD constraints from VisualBudget are
expressed here as damping language ("start rich, damp to ADHD-safe"), not
as code-enforced prohibitions.
"""

from __future__ import annotations

from adapt.feedback import DECISION_HINT
from render.design_spec import SectionSpec, WorksheetDesignSpec

# Bump when prompt structure changes — part of the page cache key.
# v2: match sections demand one picture per row in a single right-hand column
# (owner UAT: two adjacent pictures confused the connect-the-dots task). Bump
# invalidates the page cache so fixed prompts actually regenerate pages.
# v3: goal ribbon replaces the skill-focus badge, typography rules constrain
# text sizes, per-page buddy action, structured feedback strip + grown-up log.
# v4: circle-format fill-blanks, per-row match pictures, chunked passages,
# quick-log-only feedback (spec 2026-07-13)
PROMPT_VERSION = "page_prompt_v4"

_FORMAT_AFFORDANCES: dict[str, str] = {
    "write": "a blank handwriting line wide enough for a child to print the answer",
    "fill_blank": (
        "the text with a clearly visible blank; print the option letters beside it "
        "as large, well-spaced letters a child can circle — no handwriting line"
    ),
    "trace": "the word in light dotted outline letters ready to trace",
    "circle": ("the option words spread out with space around each so a child can circle them"),
    "match": (
        "two columns with clear horizontal separation: words in a single column "
        "on the left, small simple pictures in a single column on the right — "
        "exactly one picture per row, never two pictures adjacent to each other, "
        "with open white space between the columns to draw connecting lines"
    ),
    "read_aloud": (
        "the passage inside a soft reading box with a small read-aloud icon; each "
        "paragraph is its own visually separated block with a blank line between "
        "paragraphs and a small dot marker at each paragraph start"
    ),
    "sound_box": "one empty square box per sound (Elkonin boxes) under the word",
    "verbal": "a small speech icon next to the prompt",
}


def build_page_prompt(
    spec: WorksheetDesignSpec,
    *,
    character_block: str = "",
    scene_guidelines: str = "",
    theme_environment: str = "",
    theme_palette: str = "",
    art_style: str = "",
    buddy_action: str = "",
) -> str:
    """Build the full-page generation prompt from the design spec."""

    parts: list[str] = [
        ("Create ONE complete, print-ready children's literacy worksheet page as a single image."),
        ("Portrait orientation, US Letter proportions (8.5 x 11), plain white page background."),
        f'Worksheet title banner text: "{spec.worksheet_title}"',
        f"Theme: {spec.theme_name}.",
        (f"This is worksheet {spec.worksheet_number} of {spec.worksheet_count} for the lesson."),
    ]
    if spec.worksheet_number == 1:
        parts.append(
            "Directly under the title banner, a goal ribbon with exact text: "
            f'"{spec.learning_goal}"'
        )
    else:
        parts.append(
            f'A small running goal line in the header area, exact text: "{spec.learning_goal}"'
        )
    parts.append("## Visual style")
    if art_style:
        parts.append(f"Art style: {art_style}.")
    if theme_environment:
        parts.append(f"Environment styling for headers and accents: {theme_environment}")
    if theme_palette:
        parts.append(f"Palette guidance: {theme_palette}")
    parts.append(
        "Design the page like a polished, cohesive game-UI worksheet: a themed "
        "title banner, one numbered banner per activity section, and a small "
        "progress strip. Section chrome supports the learning content and never "
        "competes with it."
    )

    if character_block:
        parts.append("## Learning Buddy")
        parts.append(
            "Include the Learning Buddy exactly once, matching the attached "
            f"reference image: {character_block}"
        )
        if scene_guidelines:
            parts.append(scene_guidelines)
        if buddy_action:
            parts.append(
                f"In this page's scene the Learning Buddy is {buddy_action}. Keep "
                "the identity exactly as described; only the pose and action "
                "change from other pages."
            )

    parts.append("## Activity sections (render in this order)")
    for section in spec.sections:
        parts.append(_section_text(section))

    if spec.feedback:
        fb = spec.feedback
        section_rows = ", ".join(f"Part {s.chunk_id}" for s in spec.sections)
        parts.append(
            f'Final section: a compact feedback strip titled with exact text: "{fb.child_prompt}" '
            f"with one row per activity section ({section_rows}); each row shows the part "
            "number and three small circles colored green, yellow, and red for the child "
            "to circle one."
        )
        log_lines = "\n".join(
            f'Log row exact text: "Part {s.chunk_id}: ___ of {len(s.items)} correct   '
            'smooth / choppy   help: none / some / lots"'
            for s in spec.sections
        )
        hint = (
            f'\nLast line in smaller text, exact text: "{DECISION_HINT}"'
            if fb.show_decision_hint
            else ""
        )
        parts.append(
            "Below the feedback strip, a thin outlined box titled with exact text: "
            f'"{fb.parent_log_title}" containing one log row per section:\n{log_lines}{hint}'
        )
    if spec.break_prompt:
        parts.append(
            "After the last activity, a small calm 'Take a Break!' box that "
            f'says: "{spec.break_prompt}"'
        )

    parts.append("## Exact text rules")
    parts.append(
        "Render every quoted string above EXACTLY as written: same spelling, "
        "same words, same punctuation. Do not add, remove, rewrite, or decorate "
        "any instructional text. All text must be dark, legible, high contrast, "
        "and inside safe page margins."
    )

    parts.append("## Typography rules (required)")
    parts.append(
        "- Use exactly THREE text sizes on the page: (1) title and section "
        "banners, (2) practice words and answer items — the largest body text, "
        "and (3) ONE consistent smaller size shared by all instructions, time "
        "cues, and labels.\n"
        "- No text on the page may be smaller than 60% of the practice-word "
        "height.\n"
        "- Use one plain, evenly spaced font family throughout, like a "
        "children's school workbook; no decorative or stylized lettering "
        "outside the title banner.\n"
        "- Story and passage sentences use size (2), the practice-word size "
        "— never the smaller instruction size."
    )

    parts.append("## Calm-focus rules (required)")
    parts.append(_damping_block(spec, has_character=bool(character_block)))

    return "\n\n".join(parts)


def _section_text(section: SectionSpec) -> str:
    lines: list[str] = [f'Section {section.chunk_id} banner text: "{section.micro_goal}"']
    if section.time_estimate:
        lines.append(f'Small time cue next to the banner: "{section.time_estimate}"')
    for number, instruction in enumerate(section.instructions, start=1):
        lines.append(f'Numbered instruction {number}: "{instruction}"')
    if section.worked_example_content:
        intro = section.worked_example_instruction or "Watch how I do the first one:"
        lines.append(
            f'Worked example in a soft tinted box: "{intro}" then '
            f'"{section.worked_example_content}"'
        )
    for item in section.items:
        affordance = _FORMAT_AFFORDANCES.get(
            item.response_format, "clear space for the child's answer"
        )
        item_line = f'Item {item.item_id}: "{item.content}" with {affordance}'
        # Only these formats present options for the child to choose among.
        if item.options and item.response_format in {"circle", "fill_blank", "match"}:
            item_line += f" (options, exact text: {', '.join(item.options)})"
        lines.append(item_line)
    return "\n".join(lines)


def _damping_block(spec: WorksheetDesignSpec, *, has_character: bool = False) -> str:
    budget = spec.visual_budget
    if budget.max_decorative_elements > 0:
        decoration_rule = (
            f"Exactly {budget.max_decorative_elements} small purely decorative "
            "accents on the whole page, placed only in the header or footer "
            "corners — never between activities."
        )
    else:
        decoration_rule = "No purely decorative elements; only the section chrome described above."

    rules = [
        (
            "Plain white or near-white behind ALL instructional text and ALL answer "
            "areas; never put patterns, gradients, or scene art behind text or "
            "writing lines."
        ),
        (
            f"Use at most {budget.max_colors} accent colors (plus black text on "
            "white) and keep them consistent: one color for section banners, one "
            "for example boxes, one for rewards."
        ),
        decoration_rule,
        "One clearly boxed activity per section with generous white space between sections.",
        *(
            [
                "The Learning Buddy appears at most once and stays visually subordinate "
                "to the activities."
            ]
            if has_character
            else []
        ),
        (
            "No flashing effects, no crowding, no dense text blocks, no score "
            "displays or leaderboards."
        ),
    ]
    if budget.intensity == "low":
        rules.append(
            "Overall mood: calm and tidy. Saturate the banners gently; keep large areas white."
        )
    elif budget.intensity == "medium":
        rules.append(
            "Overall mood: lively but tidy; banners may be bolder, backgrounds stay quiet."
        )
    elif budget.intensity == "high":
        rules.append(
            "Overall mood: bold and energetic chrome, but text areas and answer "
            "spaces stay plain, white, and uncluttered."
        )
    return "\n".join(f"- {rule}" for rule in rules)
