"""ReportLab PDF renderer — produces print-ready worksheets from themed adapted models."""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from adapt.schema import ActivityChunk, AdaptedActivityModel
from theme.assets import resolve_decoration
from theme.schema import ThemeConfig

logger = logging.getLogger(__name__)

# Page geometry
PAGE_WIDTH, PAGE_HEIGHT = letter  # 612 x 792 points
MARGIN = 0.75 * inch  # 54 points
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
CONTENT_TOP = PAGE_HEIGHT - MARGIN
CONTENT_BOTTOM = MARGIN

# Font sizes by grade
GRADE_FONT_SIZES: dict[str, dict[str, int]] = {
    "K": {"heading": 18, "body": 16, "small": 14},
    "1": {"heading": 16, "body": 14, "small": 12},
    "2": {"heading": 14, "body": 12, "small": 10},
    "3": {"heading": 14, "body": 12, "small": 10},
}


def render_worksheet(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    output_path: str,
    avatar_image: str | None = None,
) -> str:
    """Render an adapted activity to a print-ready PDF.

    Returns the output file path.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    c = Canvas(str(path), pagesize=letter)
    _register_fonts(theme)

    sizes = GRADE_FONT_SIZES.get(adapted.grade_level, GRADE_FONT_SIZES["1"])
    colors = theme.colors
    y = CONTENT_TOP
    page_num = 1

    # Page header
    y = _draw_header(c, adapted, theme, sizes, y)

    # Draw decorations and avatar on first page
    _draw_decorations(c, theme, adapted.theme_id)
    if avatar_image:
        _draw_avatar(c, avatar_image, theme)

    # Render each chunk
    for chunk in adapted.chunks:
        y = _draw_chunk(c, chunk, adapted, theme, sizes, colors, y)

        # Check if we need a new page
        if y < CONTENT_BOTTOM + 100:
            _draw_footer(c, theme, adapted)
            c.showPage()
            page_num += 1
            y = CONTENT_TOP
            # Draw decorations on new pages too
            _draw_decorations(c, theme, adapted.theme_id)
            if avatar_image:
                _draw_avatar(c, avatar_image, theme)

    # Self-assessment at the bottom
    if adapted.self_assessment:
        y = _draw_self_assessment(c, adapted.self_assessment, theme, sizes, y)

    # Footer with theme name
    _draw_footer(c, theme, adapted)

    c.save()
    return str(path)


def _register_fonts(theme: ThemeConfig) -> None:
    """Register theme fonts if available, otherwise use built-in Helvetica."""
    # For MVP, use ReportLab's built-in fonts (Helvetica, Times, Courier)
    # Custom fonts (Nunito, etc.) require TTF files — deferred to post-MVP
    pass


def _draw_header(
    c: Canvas,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw the worksheet header."""
    # Title
    c.setFont(theme.fonts.heading, sizes["heading"])
    c.setFillColor(HexColor(theme.colors.text))

    title = f"{adapted.specific_skill.replace('_', ' ').title()} Practice"
    c.drawString(MARGIN, y - sizes["heading"], title)
    y -= sizes["heading"] + 8

    # Subtitle with domain
    c.setFont(theme.fonts.primary, sizes["small"])
    c.setFillColor(HexColor(theme.colors.directions))
    subtitle = f"Domain: {adapted.domain.replace('_', ' ').title()} | Grade {adapted.grade_level}"
    c.drawString(MARGIN, y - sizes["small"], subtitle)
    y -= sizes["small"] + 16

    # Divider line
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setLineWidth(1)
    c.line(MARGIN, y, PAGE_WIDTH - MARGIN, y)
    y -= 12

    return y


def _draw_chunk(
    c: Canvas,
    chunk: ActivityChunk,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    colors: object,
    y: float,
) -> float:
    """Draw a single activity chunk."""
    theme_colors = theme.colors

    # Micro-goal header
    c.setFont(theme.fonts.heading, sizes["body"])
    c.setFillColor(HexColor(theme_colors.key_words))
    c.drawString(MARGIN, y - sizes["body"], chunk.micro_goal)
    y -= sizes["body"] + 6

    # Time estimate (if present)
    if chunk.time_estimate:
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme_colors.directions))
        c.drawString(MARGIN + 10, y - sizes["small"], chunk.time_estimate)
        y -= sizes["small"] + 6

    # Instructions
    c.setFillColor(HexColor(theme_colors.directions))
    c.setFont(theme.fonts.primary, sizes["body"])
    for step in chunk.instructions:
        text = f"{step.number}. {step.text}"
        c.drawString(MARGIN + 10, y - sizes["body"], text)
        y -= sizes["body"] + 4

    y -= 6

    # Worked example (shaded box)
    if chunk.worked_example:
        box_height = sizes["body"] * 2 + 16
        # Green-tinted background box
        c.setFillColor(HexColor("#F0FDF4"))
        c.rect(MARGIN + 5, y - box_height, CONTENT_WIDTH - 10, box_height, fill=True, stroke=False)

        c.setFillColor(HexColor(theme_colors.examples))
        c.setFont(theme.fonts.primary, sizes["small"])
        c.drawString(MARGIN + 15, y - sizes["small"] - 4, chunk.worked_example.instruction)
        y -= sizes["small"] + 8

        c.setFont(theme.fonts.primary, sizes["body"])
        c.drawString(MARGIN + 15, y - sizes["body"] - 4, chunk.worked_example.content)
        y -= sizes["body"] + 12

    # Activity items
    c.setFillColor(HexColor(theme_colors.text))
    c.setFont(theme.fonts.primary, sizes["body"])
    max_chars = int(CONTENT_WIDTH / (sizes["body"] * 0.5))

    for item in chunk.items:
        is_chain = item.metadata.get("display") == "chain"

        if is_chain:
            # Word chain: show chain sequence, then write line below
            label = f"  {item.item_id}. "
            c.drawString(MARGIN + 10, y - sizes["body"], label + item.content)
            y -= sizes["body"] + 4
            # Write line for student to practice
            c.drawString(MARGIN + 30, y - sizes["body"], "Write: ____________________")
            y -= sizes["body"] + 6
        else:
            # Regular item — wrap long text across lines
            text = f"  {item.item_id}. {item.content}"
            lines = _wrap_text(text, max_chars)

            for k, line in enumerate(lines):
                c.drawString(MARGIN + 10, y - sizes["body"], line)
                y -= sizes["body"] + 4

            # Add response format indicator on a new line
            if item.response_format == "write":
                c.drawString(MARGIN + 30, y - sizes["body"], "____________________")
                y -= sizes["body"] + 4
            elif item.response_format == "circle":
                c.drawString(MARGIN + 30, y - sizes["body"], "(circle one)")
                y -= sizes["body"] + 4
            elif item.response_format == "read_aloud":
                c.setFont(theme.fonts.primary, sizes["small"])
                c.drawString(MARGIN + 30, y - sizes["small"], "[read aloud]")
                c.setFont(theme.fonts.primary, sizes["body"])
                y -= sizes["small"] + 4

            y += 4  # offset the last +4, then add spacing
            y -= 6

    # Chunk divider
    y -= 8
    c.setStrokeColor(HexColor(theme_colors.chunk_border))
    c.setLineWidth(0.5)
    c.line(MARGIN + 20, y, PAGE_WIDTH - MARGIN - 20, y)
    y -= 12

    return y


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Wrap text into lines that fit within max_chars."""
    if len(text) <= max_chars:
        return [text]

    lines: list[str] = []
    words = text.split()
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip() if current_line else word
        if len(candidate) <= max_chars:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def _draw_self_assessment(
    c: Canvas,
    items: list[str],
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw self-assessment checklist at the bottom."""
    # Check if enough space, otherwise new page
    needed = len(items) * (sizes["body"] + 6) + sizes["body"] + 20
    if y - needed < CONTENT_BOTTOM:
        c.showPage()
        y = CONTENT_TOP

    # Header
    c.setFont(theme.fonts.heading, sizes["body"])
    c.setFillColor(HexColor(theme.colors.rewards))
    c.drawString(MARGIN, y - sizes["body"], "How did I do?")
    y -= sizes["body"] + 10

    # Checklist items
    c.setFont(theme.fonts.primary, sizes["body"])
    c.setFillColor(HexColor(theme.colors.text))
    for item in items:
        # Draw checkbox
        box_size = sizes["body"] - 2
        c.rect(MARGIN + 10, y - box_size, box_size, box_size, fill=False, stroke=True)
        c.drawString(MARGIN + 10 + box_size + 6, y - sizes["body"] + 2, item)
        y -= sizes["body"] + 6

    return y


def _draw_avatar(
    c: Canvas,
    avatar_path: str,
    theme: ThemeConfig,
) -> None:
    """Draw the learning buddy avatar in the configured position.

    ADHD rules: avatar in fixed position, visually subordinate to content,
    with a short encouraging speech bubble.
    """
    avatar_file = Path(avatar_path)
    if not avatar_file.exists():
        return

    # Avatar position from theme config (default: bottom-right)
    position = theme.avatar_position
    avatar_size = 70  # points (~1 inch)

    if position == "bottom-right":
        x = PAGE_WIDTH - MARGIN - avatar_size
        y = MARGIN + 10
    elif position == "bottom-left":
        x = MARGIN
        y = MARGIN + 10
    elif position == "top-right":
        x = PAGE_WIDTH - MARGIN - avatar_size
        y = PAGE_HEIGHT - MARGIN - avatar_size
    else:
        x = PAGE_WIDTH - MARGIN - avatar_size
        y = MARGIN + 10

    try:
        c.drawImage(
            str(avatar_file), x, y,
            width=avatar_size, height=avatar_size,
            preserveAspectRatio=True,
            mask="auto",
        )

        # Speech bubble with encouragement (visually subordinate)
        bubble_x = x - 90
        bubble_y = y + avatar_size - 10
        c.setFillColor(HexColor("#F3F4F6"))
        c.roundRect(bubble_x, bubble_y, 85, 18, 4, fill=True, stroke=False)
        c.setFont(theme.fonts.primary, 7)
        c.setFillColor(HexColor(theme.colors.directions))
        c.drawString(bubble_x + 5, bubble_y + 5, "You can do it!")
    except Exception as e:
        logger.warning(f"Failed to draw avatar: {e}")


def _draw_decorations(
    c: Canvas,
    theme: ThemeConfig,
    theme_id: str,
) -> None:
    """Draw theme decorative elements in safe zones.

    ADHD rules: max 2 per page, in fixed corners only, never between items.
    """
    assets = theme.decorative_elements.assets
    max_elements = theme.decorative_elements.max_per_page

    if not assets:
        return

    # Decoration zones: top-right corner and bottom-left corner
    zones = [
        (PAGE_WIDTH - MARGIN - 45, PAGE_HEIGHT - MARGIN - 45, 40),  # top-right
        (MARGIN + 5, MARGIN + 5, 35),  # bottom-left
    ]

    for i, asset_name in enumerate(assets):
        if i >= max_elements or i >= len(zones):
            break

        asset_path = resolve_decoration(asset_name, theme_id)
        if asset_path is None:
            continue

        x, y, size = zones[i]
        try:
            c.drawImage(
                str(asset_path), x, y,
                width=size, height=size,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception as e:
            logger.warning(f"Failed to draw decoration {asset_name}: {e}")


def _draw_footer(
    c: Canvas,
    theme: ThemeConfig,
    adapted: AdaptedActivityModel,
) -> None:
    """Draw page footer."""
    c.setFont(theme.fonts.primary, 8)
    c.setFillColor(HexColor(theme.colors.chunk_border))
    footer = f"{theme.name} | Worksheet Builder v0.1.0"
    c.drawString(MARGIN, MARGIN / 2, footer)
