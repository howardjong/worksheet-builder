"""Full-page worksheet image prompt assembly.

Everything in this module is model-agnostic: it builds prompt text only.
Provider-specific details (reference-image conditioning, sizes, API calls)
live in render/image_providers.py. ADHD constraints from VisualBudget are
expressed here as damping language ("start rich, damp to ADHD-safe"), not
as code-enforced prohibitions.
"""

from __future__ import annotations

from render.design_spec import SectionSpec, WorksheetDesignSpec

# Bump when prompt structure changes — part of the page cache key.
# v2: match sections demand one picture per row in a single right-hand column
# (owner UAT: two adjacent pictures confused the connect-the-dots task). Bump
# invalidates the page cache so fixed prompts actually regenerate pages.
PROMPT_VERSION = "page_prompt_v2"

_FORMAT_AFFORDANCES: dict[str, str] = {
    "write": "a blank handwriting line wide enough for a child to print the answer",
    "fill_blank": "the text with a clearly visible blank plus a handwriting line below",
    "trace": "the word in light dotted outline letters ready to trace",
    "circle": ("the option words spread out with space around each so a child can circle them"),
    "match": (
        "two columns with clear horizontal separation: words in a single column "
        "on the left, small simple pictures in a single column on the right — "
        "exactly one picture per row, never two pictures adjacent to each other, "
        "with open white space between the columns to draw connecting lines"
    ),
    "read_aloud": "the text inside a soft reading box with a small read-aloud icon",
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
) -> str:
    """Build the full-page generation prompt from the design spec."""

    parts: list[str] = [
        (
            "Create ONE complete, print-ready children's literacy worksheet page "
            "as a single image."
        ),
        ("Portrait orientation, US Letter proportions (8.5 x 11), " "plain white page background."),
        f'Worksheet title banner text: "{spec.worksheet_title}"',
        f"Theme: {spec.theme_name}. Skill focus: {spec.specific_skill} ({spec.domain}).",
        (f"This is worksheet {spec.worksheet_number} of {spec.worksheet_count}" " for the lesson."),
        "## Visual style",
    ]
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

    parts.append("## Activity sections (render in this order)")
    for section in spec.sections:
        parts.append(_section_text(section))

    if spec.self_assessment:
        checks = "; ".join(spec.self_assessment)
        parts.append(
            "Final section: a short 'How did I do?' checklist with one empty "
            f"checkbox per line, exact text: {checks}"
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
            "Overall mood: calm and tidy. Saturate the banners gently; keep large " "areas white."
        )
    elif budget.intensity == "medium":
        rules.append(
            "Overall mood: lively but tidy; banners may be bolder, backgrounds " "stay quiet."
        )
    elif budget.intensity == "high":
        rules.append(
            "Overall mood: bold and energetic chrome, but text areas and answer "
            "spaces stay plain, white, and uncluttered."
        )
    return "\n".join(f"- {rule}" for rule in rules)
