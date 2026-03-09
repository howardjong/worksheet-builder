"""ReportLab PDF renderer — produces print-ready worksheets from themed adapted models."""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel
from theme.assets import resolve_decoration
from theme.schema import AssetManifest, ThemeConfig

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
    asset_manifest: AssetManifest | None = None,
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
    use_scenes = (
        asset_manifest is not None
        and theme.avatar_position == "integrated"
    )
    for chunk_idx, chunk in enumerate(adapted.chunks):
        if use_scenes and asset_manifest is not None:
            y = _draw_chunk_with_scene(
                c, chunk, adapted, theme, sizes, colors, y,
                asset_manifest, chunk_idx,
            )
        else:
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

    # Brain break prompt (if multi-worksheet)
    if adapted.break_prompt:
        y = _draw_break_prompt(c, adapted.break_prompt, theme, sizes, y)

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

    # Title: include worksheet title if multi-worksheet
    if adapted.worksheet_title and adapted.worksheet_count > 1:
        title = f"{adapted.worksheet_title}"
        c.drawString(MARGIN, y - sizes["heading"], title)
        y -= sizes["heading"] + 4
        # Sub-title with worksheet number
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        subtitle = (
            f"{adapted.specific_skill.replace('_', ' ').title()} "
            f"| Part {adapted.worksheet_number} of {adapted.worksheet_count}"
        )
        c.drawString(MARGIN, y - sizes["small"], subtitle)
        y -= sizes["small"] + 12
    else:
        title = f"{adapted.specific_skill.replace('_', ' ').title()} Practice"
        c.drawString(MARGIN, y - sizes["heading"], title)
        y -= sizes["heading"] + 8
        # Subtitle with domain
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        domain_label = adapted.domain.replace("_", " ").title()
        subtitle = f"Domain: {domain_label} | Grade {adapted.grade_level}"
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
        elif item.response_format == "match":
            y = _draw_match_item(c, item, theme, sizes, y)
        elif item.response_format == "trace":
            y = _draw_trace_item(c, item, theme, sizes, y)
        elif item.response_format == "circle" and item.options:
            y = _draw_circle_item(c, item, theme, sizes, y)
        elif item.response_format == "fill_blank":
            y = _draw_fill_blank_item(c, item, theme, sizes, y)
        elif item.response_format == "read_aloud":
            y = _draw_read_aloud_item(c, item, theme, sizes, y)
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


def _draw_match_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a word-picture matching item: word on left, picture zone on right."""
    body = sizes["body"]
    # Word label on the left
    c.setFont(theme.fonts.heading, body + 2)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(MARGIN + 15, y - body - 2, item.content)

    # Picture zone placeholder on the right (dashed box)
    pic_x = MARGIN + CONTENT_WIDTH * 0.5
    pic_size = body + 16
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setDash(3, 3)
    c.rect(pic_x, y - pic_size, pic_size, pic_size, fill=False, stroke=True)
    c.setDash()

    # Picture label inside box
    c.setFont(theme.fonts.primary, sizes["small"] - 2)
    c.setFillColor(HexColor(theme.colors.directions))
    prompt_text = (item.picture_prompt or item.content)[:12]
    c.drawString(pic_x + 3, y - pic_size + 4, f"[{prompt_text}]")

    # Connecting line stub (dotted)
    line_start_x = MARGIN + 15 + len(item.content) * (body * 0.6)
    line_end_x = pic_x - 5
    line_y = y - body / 2 - 4
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setDash(2, 4)
    c.line(min(line_start_x, line_end_x - 20), line_y, line_end_x, line_y)
    c.setDash()

    y -= pic_size + 8
    c.setFont(theme.fonts.primary, body)
    return y


def _draw_trace_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a word in large dotted/gray outline letters for tracing."""
    trace_size = sizes["heading"] + 6  # Larger for tracing
    c.setFont(theme.fonts.heading, trace_size)
    c.setFillColor(HexColor("#D1D5DB"))  # Light gray for tracing
    c.drawString(MARGIN + 20, y - trace_size, item.content)

    # Add a solid write line below
    line_y = y - trace_size - 6
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setLineWidth(0.5)
    line_width = len(item.content) * trace_size * 0.6
    c.line(MARGIN + 20, line_y, MARGIN + 20 + max(line_width, 100), line_y)

    y -= trace_size + 14
    c.setFont(theme.fonts.primary, sizes["body"])
    return y


def _draw_circle_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a row of words in bubbles for circling."""
    body = sizes["body"]

    # Instruction text
    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(MARGIN + 10, y - body, f"  {item.item_id}. {item.content}")
    y -= body + 8

    # Draw word bubbles in a row
    if item.options:
        x = MARGIN + 25
        bubble_padding = 12
        for word in item.options:
            word_width = len(word) * body * 0.55 + bubble_padding * 2
            # Draw rounded rectangle bubble
            c.setStrokeColor(HexColor(theme.colors.text))
            c.setFillColor(HexColor("#FFFFFF"))
            c.setLineWidth(1)
            c.roundRect(x, y - body - 4, word_width, body + 8, 6, fill=True, stroke=True)
            # Word text inside bubble
            c.setFillColor(HexColor(theme.colors.text))
            c.setFont(theme.fonts.primary, body)
            c.drawString(x + bubble_padding, y - body + 1, word)
            x += word_width + 8
            # Wrap to next line if needed
            if x > PAGE_WIDTH - MARGIN - 30:
                x = MARGIN + 25
                y -= body + 14

        y -= body + 12

    return y


def _draw_fill_blank_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a word/sentence with blank and optional word bank."""
    body = sizes["body"]

    # Content with blank
    c.setFont(theme.fonts.primary, body + 2)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(MARGIN + 15, y - body - 2, f"{item.item_id}. {item.content}")
    y -= body + 10

    # Word bank (options) in a shaded box
    if item.options:
        bank_height = body + 12
        bx = MARGIN + 25
        bw = CONTENT_WIDTH - 50
        c.setFillColor(HexColor("#F9FAFB"))
        c.rect(bx, y - bank_height, bw, bank_height, fill=True, stroke=False)
        c.setStrokeColor(HexColor(theme.colors.chunk_border))
        c.rect(bx, y - bank_height, bw, bank_height, fill=False, stroke=True)

        c.setFillColor(HexColor(theme.colors.directions))
        c.setFont(theme.fonts.primary, sizes["small"])
        bank_text = "Word bank: " + "   ".join(item.options)
        c.drawString(MARGIN + 35, y - body - 2, bank_text)
        y -= bank_height + 6

    c.setFont(theme.fonts.primary, body)
    return y


def _draw_read_aloud_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a passage in a styled reading box with read-aloud icon."""
    body = sizes["body"]
    max_chars = int((CONTENT_WIDTH - 40) / (body * 0.5))
    lines = _wrap_text(item.content, max_chars)

    box_height = len(lines) * (body + 4) + 20
    # Ensure enough space
    if y - box_height < CONTENT_BOTTOM:
        box_height = y - CONTENT_BOTTOM - 10

    # Light blue reading box
    rx, rw = MARGIN + 10, CONTENT_WIDTH - 20
    c.setFillColor(HexColor("#EFF6FF"))
    c.roundRect(rx, y - box_height, rw, box_height, 8, fill=True, stroke=False)
    c.setStrokeColor(HexColor("#BFDBFE"))
    c.roundRect(rx, y - box_height, rw, box_height, 8, fill=False, stroke=True)

    # Read aloud icon indicator
    c.setFont(theme.fonts.heading, sizes["small"])
    c.setFillColor(HexColor(theme.colors.directions))
    c.drawString(MARGIN + 20, y - sizes["small"] - 6, "Read Aloud:")
    inner_y = y - sizes["small"] - 14

    # Story text
    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor(theme.colors.text))
    for line in lines:
        if inner_y < y - box_height + 8:
            break
        c.drawString(MARGIN + 20, inner_y - body, line)
        inner_y -= body + 4

    y -= box_height + 8
    return y


def _draw_break_prompt(
    c: Canvas,
    prompt: str,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
) -> float:
    """Draw a fun 'Take a Break!' section with movement suggestion."""
    body = sizes["body"]
    box_height = body * 2 + 24

    # Check space
    if y - box_height < CONTENT_BOTTOM:
        c.showPage()
        y = CONTENT_TOP

    # Bright, fun box
    bx, bw = MARGIN + 20, CONTENT_WIDTH - 40
    c.setFillColor(HexColor("#FEF3C7"))  # Warm yellow
    c.roundRect(bx, y - box_height, bw, box_height, 10, fill=True, stroke=False)
    c.setStrokeColor(HexColor("#F59E0B"))
    c.setLineWidth(2)
    c.roundRect(bx, y - box_height, bw, box_height, 10, fill=False, stroke=True)
    c.setLineWidth(1)

    # Title
    c.setFont(theme.fonts.heading, body + 2)
    c.setFillColor(HexColor("#92400E"))
    c.drawCentredString(PAGE_WIDTH / 2, y - body - 6, "Take a Break!")

    # Prompt text
    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor("#78350F"))
    c.drawCentredString(PAGE_WIDTH / 2, y - body * 2 - 12, prompt)

    y -= box_height + 12
    return y


def _draw_chunk_with_scene(
    c: Canvas,
    chunk: ActivityChunk,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    colors: object,
    y: float,
    asset_manifest: AssetManifest,
    chunk_idx: int,
) -> float:
    """Draw chunk with two-column layout: content (60%) + scene illustration (40%).

    Alternates scene position left/right between chunks.
    Falls back to standard layout if no scene asset available.
    """
    scene_path = asset_manifest.scene_paths.get(chunk.chunk_id)

    if not scene_path or not Path(scene_path).exists():
        return _draw_chunk(c, chunk, adapted, theme, sizes, colors, y)

    # Determine layout: even chunks = scene right, odd = scene left
    scene_right = chunk_idx % 2 == 0

    # Scene dimensions
    scene_width = CONTENT_WIDTH * 0.35
    scene_height = 120  # Fixed height for scenes
    content_width = CONTENT_WIDTH * 0.60

    if scene_right:
        scene_x = MARGIN + content_width + 10
    else:
        scene_x = MARGIN

    # Draw scene image
    try:
        c.drawImage(
            scene_path, scene_x, y - scene_height,
            width=scene_width, height=scene_height,
            preserveAspectRatio=True, mask="auto",
        )
    except Exception as e:
        logger.warning(f"Failed to draw scene for chunk {chunk.chunk_id}: {e}")

    # Draw content in the remaining column (using standard chunk drawing
    # but constrained to the content column width)
    # For now, draw standard chunk — the scene is purely additive
    y_after = _draw_chunk(c, chunk, adapted, theme, sizes, colors, y)

    # Ensure we move past the scene height
    y_after = min(y_after, y - scene_height - 8)

    return y_after


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
    if adapted.worksheet_count > 1:
        footer += f" | Part {adapted.worksheet_number} of {adapted.worksheet_count}"
    c.drawString(MARGIN, MARGIN / 2, footer)
