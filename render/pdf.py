"""ReportLab PDF renderer — produces print-ready worksheets from themed adapted models."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from adapt.feedback import DECISION_HINT
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

# ADHD-optimized font directory
_FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

# Font sizes by grade (evidence-based: K-1 16-20pt, 2-3 12-14pt)
GRADE_FONT_SIZES: dict[str, dict[str, int]] = {
    "K": {"heading": 22, "body": 18, "small": 14},
    "1": {"heading": 20, "body": 16, "small": 13},
    "2": {"heading": 16, "body": 13, "small": 11},
    "3": {"heading": 16, "body": 13, "small": 11},
}

# ADHD-optimized spacing (evidence: 1.7x line height, generous char/word spacing)
ADHD_SPACING: dict[str, float] = {
    "line_height_factor": 1.7,  # line spacing = font_size * 1.7
    "char_space_body": 0.4,  # extra char spacing for body text (pts)
    "char_space_heading": 0.7,  # extra char spacing for headings (pts)
    "word_space": 1.5,  # extra word spacing (pts)
}

LAYOUT_SPACING: dict[str, float] = {
    "section_gap": 18.0,
    "item_gap": 16.0,
    "box_gap": 32.0,
    "divider_gap": 22.0,
}

# Avatar clearance: pts above MARGIN to clear avatar (70pt) + speech bubble (18pt) + gap
AVATAR_CLEARANCE = 90

PAGE_BREAK_BUFFER = 20

_TRAFFIC_LIGHT_COLORS = ("#2E9E44", "#E5B800", "#D64545")  # green / yellow / red

_fonts_registered = False


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

    # Avatar-aware content floor: raise effective bottom when avatar is in a bottom corner
    content_bottom = CONTENT_BOTTOM
    if avatar_image and theme.avatar_position in ("bottom-right", "bottom-left"):
        content_bottom = MARGIN + AVATAR_CLEARANCE

    # Page background
    c.setFillColor(HexColor(theme.colors.background))
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=True, stroke=False)

    # Apply ADHD-optimized spacing
    _apply_adhd_spacing(c, "body")

    # Page header
    y = _draw_header(c, adapted, theme, sizes, y)

    # Draw decorations and avatar on first page
    _draw_decorations(c, theme, adapted.theme_id)
    if avatar_image:
        _draw_avatar(c, avatar_image, theme)

    def start_new_page() -> None:
        nonlocal y, page_num

        _draw_footer(c, theme, adapted)
        c.showPage()
        page_num += 1
        y = CONTENT_TOP
        # Page background
        c.setFillColor(HexColor(theme.colors.background))
        c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=True, stroke=False)
        _apply_adhd_spacing(c, "body")
        _draw_decorations(c, theme, adapted.theme_id)
        if avatar_image:
            _draw_avatar(c, avatar_image, theme)

    # Render each chunk
    use_scenes = asset_manifest is not None and theme.avatar_position == "integrated"
    for chunk_idx, chunk in enumerate(adapted.chunks):
        # Estimate with scenes first; fall back to full-width if too tall
        chunk_use_scene = use_scenes
        # Passage/read_aloud chunks always use full-width for readability
        has_passage = any(
            it.response_format == "read_aloud" and it.metadata.get("display") != "roll_and_read"
            for it in chunk.items
        )
        if has_passage:
            chunk_use_scene = False
        required_height = _estimate_chunk_height(
            chunk,
            theme,
            sizes,
            asset_manifest=asset_manifest,
            chunk_idx=chunk_idx,
            use_scene=chunk_use_scene,
        )
        available_space = y - content_bottom - PAGE_BREAK_BUFFER
        if chunk_use_scene and required_height > available_space:
            # Scene layout won't fit in the remaining space — try full-width
            # before resorting to a page break (avoids blank pages)
            full_height = _estimate_chunk_height(
                chunk,
                theme,
                sizes,
                asset_manifest=asset_manifest,
                chunk_idx=chunk_idx,
                use_scene=False,
            )
            if full_height <= available_space:
                chunk_use_scene = False
                required_height = full_height
            else:
                # Neither fits — still fall back to full-width for the new page
                chunk_use_scene = False
                required_height = full_height

        # Only page-break when the chunk header + first item won't fit.
        # Per-item breaks inside _draw_chunk handle overflow for the rest,
        # which avoids stranding headers on blank pages and reduces wasted space.
        chunk_header_height = _estimate_chunk_header_height(chunk, sizes)
        if chunk.items:
            first_item = chunk.items[0]
            col_w = CONTENT_WIDTH
            chunk_header_height += _estimate_item_height(
                first_item,
                theme,
                sizes,
                MARGIN,
                PAGE_WIDTH - MARGIN,
                col_w,
            )
        if chunk_idx > 0 and y - chunk_header_height < content_bottom + PAGE_BREAK_BUFFER:
            start_new_page()

        if chunk_use_scene and asset_manifest is not None:
            y = _draw_chunk_with_scene(
                c,
                chunk,
                adapted,
                theme,
                sizes,
                colors,
                y,
                asset_manifest,
                chunk_idx,
            )
        else:
            y = _draw_chunk(
                c,
                chunk,
                adapted,
                theme,
                sizes,
                colors,
                y,
                asset_manifest=asset_manifest,
                page_break_fn=start_new_page,
                effective_bottom=content_bottom,
            )

    # Brain break + feedback panel: treat as a combined block to avoid
    # each getting its own mostly-blank page
    tail_height = 0.0
    if adapted.break_prompt:
        tail_height += _estimate_break_prompt_height(sizes) + 12
    if adapted.feedback:
        tail_height += _estimate_feedback_panel_height(adapted, sizes)

    if tail_height > 0 and y - tail_height < content_bottom + PAGE_BREAK_BUFFER:
        start_new_page()

    if adapted.break_prompt:
        y = _draw_break_prompt(
            c,
            adapted.break_prompt,
            theme,
            sizes,
            y,
            effective_bottom=content_bottom,
        )

    if adapted.feedback:
        y = _draw_feedback_panel(
            c,
            adapted,
            theme,
            sizes,
            y,
            effective_bottom=content_bottom,
        )

    # Footer with theme name
    _draw_footer(c, theme, adapted)

    c.save()
    return str(path)


def _register_fonts(theme: ThemeConfig) -> None:
    """Register ADHD-optimized fonts (Lexend body, Fredoka headings).

    Falls back to built-in Helvetica if TTF files aren't found.
    Fonts: Lexend (ADHD-optimized spacing, clear letter differentiation)
           Fredoka (rounded, fun, kid-friendly headings)
    """
    global _fonts_registered  # noqa: PLW0603
    if _fonts_registered:
        return

    font_map = {
        "Lexend": "Lexend-VariableFont.ttf",
        "Fredoka": "Fredoka-VariableFont.ttf",
    }

    for font_name, filename in font_map.items():
        font_path = _FONTS_DIR / filename
        if font_path.exists():
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
                logger.debug(f"Registered font: {font_name}")
            except Exception as e:
                logger.warning(f"Failed to register {font_name}: {e}")
        else:
            logger.debug(f"Font not found: {font_path}")

    _fonts_registered = True


def _apply_adhd_spacing(c: Canvas, mode: str = "body") -> None:
    """Set ADHD-optimized character and word spacing on canvas.

    mode: "body" for content text, "heading" for headings.
    Uses Canvas internal state (_charSpace, _wordSpace) since
    setCharSpace/setWordSpace are only on TextObject.
    """
    if mode == "heading":
        c._charSpace = ADHD_SPACING["char_space_heading"]
    else:
        c._charSpace = ADHD_SPACING["char_space_body"]
    c._wordSpace = ADHD_SPACING["word_space"]


def _line_spacing(font_size: int) -> float:
    """Compute ADHD-optimized line spacing for a given font size."""
    return font_size * ADHD_SPACING["line_height_factor"]


def _draw_writing_line(
    c: Canvas,
    x: float,
    y: float,
    color: str,
    max_width: float = 300,
    col_width: float = CONTENT_WIDTH,
) -> None:
    """Draw a writing line with start marker tick.

    Thicker (1pt), darker gray, with an 8pt vertical tick at the start.
    """
    line_end = x + min(col_width - 60, max_width)
    c.setStrokeColor(HexColor(color))
    c.setLineWidth(1.0)
    # Start marker tick
    c.line(x, y - 4, x, y + 4)
    # Horizontal writing line
    c.line(x, y, line_end, y)


def _estimate_chunk_header_height(
    chunk: ActivityChunk,
    sizes: dict[str, int],
) -> float:
    """Estimate vertical space for a chunk's header (before items)."""
    body = sizes["body"]
    small = sizes["small"]
    height = _line_spacing(body)  # micro_goal
    if chunk.time_estimate:
        height += _line_spacing(small) + 8
    height += len(chunk.instructions) * _line_spacing(body)
    height += LAYOUT_SPACING["section_gap"]
    if chunk.worked_example:
        shaded_box_height = body * 2 + 36
        height += shaded_box_height + LAYOUT_SPACING["box_gap"]
    height += 4  # micro-goal pill extra
    return height


def _estimate_chunk_height(
    chunk: ActivityChunk,
    theme: ThemeConfig,
    sizes: dict[str, int],
    *,
    asset_manifest: AssetManifest | None,
    chunk_idx: int,
    use_scene: bool,
) -> float:
    """Estimate how much vertical space a chunk needs before drawing it."""
    col_width = CONTENT_WIDTH
    scene_height = 0.0

    if use_scene and asset_manifest is not None:
        scene_path = asset_manifest.scene_paths.get(chunk.chunk_id)
        if scene_path and Path(scene_path).exists():
            scene_height = 158.0
            gap = 10.0
            scene_width = CONTENT_WIDTH * 0.38
            col_width = CONTENT_WIDTH - scene_width - gap

    body = sizes["body"]
    small = sizes["small"]
    height = _line_spacing(body)

    if chunk.time_estimate:
        height += _line_spacing(small) + 8

    height += len(chunk.instructions) * _line_spacing(body)
    height += LAYOUT_SPACING["section_gap"]

    if chunk.worked_example:
        ex_max = max(1, int(col_width / (body * 0.5)))
        ex_lines = len(_wrap_text(chunk.worked_example.content, ex_max))
        content_height = sizes["small"] + 12 + ex_lines * (body + 6) + 8
        shaded_box_height = body * 2 + 36
        height += max(content_height, shaded_box_height)
        height += LAYOUT_SPACING["box_gap"]

    left = MARGIN
    right = MARGIN + col_width
    for item in chunk.items:
        height += _estimate_item_height(item, theme, sizes, left, right, col_width)

    height += LAYOUT_SPACING["divider_gap"] + 12
    return max(height, scene_height)


def _estimate_item_height(
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    left: float,
    right: float,
    col_width: float,
) -> float:
    """Estimate the vertical footprint for a single item renderer."""
    body = sizes["body"]
    max_chars = max(1, int(col_width / (body * 0.5)))

    write_line_height = max(int(body * 2.5), 40)

    if item.metadata.get("display") == "chain":
        line_count = len(_wrap_text(f"  {item.item_id}. {item.content}", max_chars))
        return line_count * (body + 6) + write_line_height + 10

    if item.metadata.get("display") == "chain_step":
        line_count = len(_wrap_text(f"  {item.item_id}. {item.content}", max_chars))
        return line_count * (body + 6) + write_line_height + 12

    if item.response_format == "match":
        return 76

    if item.response_format == "trace":
        trace_size = sizes["heading"] + 6
        return trace_size + 22

    if item.response_format == "circle" and item.options:
        word_size = body + 2
        rows = _estimate_option_rows(item.options, sizes, left, right)
        return body + 14 + max(rows - 1, 0) * (word_size + 22) + word_size + 20

    if item.response_format == "fill_blank":
        display_size = body + 4
        fill_max = max(1, int(col_width / (display_size * 0.55)))
        line_count = len(_wrap_text(f"{item.item_id}. {item.content}", fill_max))
        height = line_count * (display_size + 8) + write_line_height + 8
        if item.options:
            height += body + 24
        return height

    if item.response_format == "read_aloud" and item.metadata.get("display") == "roll_and_read":
        # Fluency word: large word + bottom padding
        return sizes["heading"] + 16

    if item.response_format == "read_aloud":
        read_aloud_chars = max(1, int((col_width - 40) / (body * 0.5)))
        line_count = len(_wrap_text(item.content, read_aloud_chars))
        return line_count * (body + 6) + 32

    if item.response_format == "sound_box":
        # Word label + boxes row + bottom padding
        box_size = 58  # ~0.8 inch
        return sizes["heading"] + 12 + box_size + 16

    line_count = len(_wrap_text(f"  {item.item_id}. {item.content}", max_chars))
    height = line_count * (body + 6) + 4
    if item.response_format == "write":
        height += write_line_height + 10
    elif item.response_format == "circle":
        height += body + 8
    return height


def _estimate_option_rows(
    options: list[str],
    sizes: dict[str, int],
    left: float,
    right: float,
) -> int:
    """Estimate how many visual rows a bubble-option item will occupy."""
    body = sizes["body"]
    x = left + 25
    rows = 1

    for word in options:
        word_width = len(word) * body * 0.55 + 24
        x += word_width + 8
        if x > right - 30:
            rows += 1
            x = left + 25 + word_width + 8

    return rows


def _estimate_break_prompt_height(sizes: dict[str, int]) -> float:
    """Estimate the movement-break box height."""
    body = sizes["body"]
    return body * 2 + 36


def _estimate_feedback_panel_height(adapted: AdaptedActivityModel, sizes: dict[str, int]) -> float:
    """Estimate the feedback panel block height (child strip + grown-up log)."""
    body = sizes["body"]
    small = sizes["small"]
    rows = len(adapted.chunks)
    child = body + 10 + rows * (body + 6)
    parent = body + 10 + rows * (small + 6)
    hint = 0.0
    if adapted.feedback and adapted.feedback.show_decision_hint:
        max_chars = max(1, int((CONTENT_WIDTH - 10) / (small * 0.5)))
        hint = len(_wrap_text(DECISION_HINT, max_chars)) * (small + 6)
    return child + parent + hint + 20


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
    _apply_adhd_spacing(c, "heading")
    if adapted.worksheet_title and adapted.worksheet_count > 1:
        title = f"{adapted.worksheet_title}"
        c.drawString(MARGIN, y - sizes["heading"], title)
        y -= _line_spacing(sizes["heading"])
        # Sub-title with worksheet number
        _apply_adhd_spacing(c, "body")
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        subtitle = (
            f"{adapted.specific_skill.replace('_', ' ').title()} "
            f"| Part {adapted.worksheet_number} of {adapted.worksheet_count}"
        )
        c.drawString(MARGIN, y - sizes["small"], subtitle)
        y -= _line_spacing(sizes["small"])
    else:
        title = f"{adapted.specific_skill.replace('_', ' ').title()} Practice"
        c.drawString(MARGIN, y - sizes["heading"], title)
        y -= _line_spacing(sizes["heading"])
        # Subtitle with domain
        _apply_adhd_spacing(c, "body")
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        domain_label = adapted.domain.replace("_", " ").title()
        subtitle = f"Domain: {domain_label} | Grade {adapted.grade_level}"
        c.drawString(MARGIN, y - sizes["small"], subtitle)
        y -= _line_spacing(sizes["small"]) + 4

    if adapted.feedback:
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme.colors.directions))
        c.drawString(MARGIN, y - sizes["small"], adapted.feedback.goal_statement)
        y -= _line_spacing(sizes["small"])

    # Header accent underline (short, colored)
    c.setStrokeColor(HexColor(theme.colors.directions))
    c.setLineWidth(1.5)
    c.line(MARGIN, y, MARGIN + 80, y)
    c.setLineWidth(1)
    y -= 24

    return y


def _draw_chunk(
    c: Canvas,
    chunk: ActivityChunk,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    colors: object,
    y: float,
    content_left: float | None = None,
    content_right: float | None = None,
    asset_manifest: AssetManifest | None = None,
    page_break_fn: Callable[[], None] | None = None,
    effective_bottom: float = CONTENT_BOTTOM,
) -> float:
    """Draw a single activity chunk.

    content_left/content_right constrain text to a column
    (used by _draw_chunk_with_scene to avoid image overlap).
    """
    theme_colors = theme.colors
    left = content_left if content_left is not None else MARGIN
    right = content_right if content_right is not None else (PAGE_WIDTH - MARGIN)
    col_width = right - left

    # Micro-goal header with background pill
    _apply_adhd_spacing(c, "heading")
    body = sizes["body"]
    pill_h = body + 8
    pill_w = len(chunk.micro_goal) * body * 0.55 + 24
    pill_r = pill_h / 2
    c.setFillColor(HexColor(theme_colors.micro_goal_bg))
    c.roundRect(left, y - pill_h, pill_w, pill_h, pill_r, fill=True, stroke=False)
    c.setFont(theme.fonts.heading, body)
    c.setFillColor(HexColor(theme_colors.key_words))
    c.drawString(left + 12, y - body - 2, chunk.micro_goal)
    y -= _line_spacing(body) + 4

    # Time estimate (if present)
    _apply_adhd_spacing(c, "body")
    if chunk.time_estimate:
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme_colors.directions))
        c.drawString(left + 10, y - sizes["small"], chunk.time_estimate)
        y -= _line_spacing(sizes["small"])
        y -= 8  # Breathing room before instructions

    # Instructions (bold step numbers for scannable anchors)
    c.setFillColor(HexColor(theme_colors.directions))
    for step in chunk.instructions:
        # Bold step number
        c.setFont(theme.fonts.heading, sizes["body"])
        num_text = f"{step.number}."
        c.drawString(left + 10, y - sizes["body"], num_text)
        num_w = len(num_text) * sizes["body"] * 0.55 + 4
        # Regular step text
        c.setFont(theme.fonts.primary, sizes["body"])
        c.drawString(left + 10 + num_w, y - sizes["body"], f" {step.text}")
        y -= _line_spacing(sizes["body"])

    y -= LAYOUT_SPACING["section_gap"]

    # Worked example (shaded box with rounded corners + border)
    if chunk.worked_example:
        box_height = sizes["body"] * 2 + 36
        c.setFillColor(HexColor(theme_colors.example_bg))
        c.roundRect(
            left + 5,
            y - box_height,
            col_width - 10,
            box_height,
            8,
            fill=True,
            stroke=False,
        )
        c.setStrokeColor(HexColor(theme_colors.example_border))
        c.setLineWidth(0.75)
        c.roundRect(
            left + 5,
            y - box_height,
            col_width - 10,
            box_height,
            8,
            fill=False,
            stroke=True,
        )

        c.setFillColor(HexColor(theme_colors.examples))
        c.setFont(theme.fonts.primary, sizes["small"])
        ex_text = chunk.worked_example.instruction
        c.drawString(left + 20, y - sizes["small"] - 10, ex_text)
        y -= sizes["small"] + 12

        c.setFont(theme.fonts.primary, sizes["body"])
        ex_content = chunk.worked_example.content
        # Wrap example content to column width
        ex_max = int(col_width / (sizes["body"] * 0.5))
        for ln in _wrap_text(ex_content, ex_max):
            c.drawString(left + 20, y - sizes["body"] - 4, ln)
            y -= sizes["body"] + 6
        y -= LAYOUT_SPACING["box_gap"]

    # Activity items
    c.setFillColor(HexColor(theme_colors.text))
    c.setFont(theme.fonts.primary, sizes["body"])
    max_chars = int(col_width / (sizes["body"] * 0.5))

    # Child-print write line height: generous for young writers (ages 5-8)
    write_line_height = max(int(sizes["body"] * 2.5), 40)

    # Collect consecutive match items into groups for two-column rendering
    match_group: list[ActivityItem] = []
    items_to_render: list[ActivityItem | list[ActivityItem]] = []
    for item in chunk.items:
        if item.response_format == "match":
            match_group.append(item)
        else:
            if match_group:
                items_to_render.append(match_group)
                match_group = []
            items_to_render.append(item)
    if match_group:
        items_to_render.append(match_group)

    for entry in items_to_render:
        # Handle match groups as a batch
        if isinstance(entry, list):
            group_h = _estimate_match_group_height(entry, sizes)
            if page_break_fn is not None and y - group_h < effective_bottom + PAGE_BREAK_BUFFER:
                page_break_fn()
                y = CONTENT_TOP
                _apply_adhd_spacing(c, "body")
                c.setFillColor(HexColor(theme_colors.text))
                c.setFont(theme.fonts.primary, sizes["body"])
            y = _draw_match_group(
                c,
                entry,
                theme,
                sizes,
                y,
                left,
                right,
                asset_manifest,
            )
            continue

        item = entry

        # Per-item page break: if this item won't fit, start a new page
        if page_break_fn is not None:
            item_h = _estimate_item_height(item, theme, sizes, left, right, col_width)
            if y - item_h < effective_bottom + PAGE_BREAK_BUFFER:
                page_break_fn()
                y = CONTENT_TOP
                _apply_adhd_spacing(c, "body")
                c.setFillColor(HexColor(theme_colors.text))
                c.setFont(theme.fonts.primary, sizes["body"])

        is_chain = item.metadata.get("display") == "chain"
        is_chain_step = item.metadata.get("display") == "chain_step"

        if is_chain:
            label = f"  {item.item_id}. "
            chain_text = label + item.content
            for ln in _wrap_text(chain_text, max_chars):
                c.drawString(left + 10, y - sizes["body"], ln)
                y -= sizes["body"] + 6
            # Writing line with ample space for child to print
            write_y = y - write_line_height + 6
            line_color = theme_colors.writing_line
            _draw_writing_line(c, left + 30, write_y, line_color, col_width=col_width)
            y = write_y - 10
        elif is_chain_step:
            y = _draw_chain_step_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                col_width,
                write_line_height,
            )
        elif item.response_format == "trace":
            y = _draw_trace_item(c, item, theme, sizes, y, left)
        elif item.response_format == "circle" and item.options:
            y = _draw_circle_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                right,
            )
        elif item.response_format == "fill_blank":
            y = _draw_fill_blank_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                col_width,
            )
        elif (
            item.response_format == "read_aloud" and item.metadata.get("display") == "roll_and_read"
        ):
            y = _draw_fluency_word_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                col_width,
            )
        elif item.response_format == "read_aloud":
            y = _draw_read_aloud_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                col_width,
            )
        elif item.response_format == "sound_box":
            y = _draw_sound_box_item(
                c,
                item,
                theme,
                sizes,
                y,
                left,
                col_width,
            )
        else:
            text = f"  {item.item_id}. {item.content}"
            lines = _wrap_text(text, max_chars)

            for ln in lines:
                c.drawString(left + 10, y - sizes["body"], ln)
                y -= sizes["body"] + 6

            if item.response_format == "write":
                # Writing line with ample space for child to print
                write_y = y - write_line_height + 6
                line_color = theme_colors.writing_line
                _draw_writing_line(
                    c,
                    left + 30,
                    write_y,
                    line_color,
                    col_width=col_width,
                )
                y = write_y - 10
            elif item.response_format == "circle":
                c.drawString(
                    left + 30,
                    y - sizes["body"],
                    "(circle one)",
                )
                y -= sizes["body"] + 8

            y -= LAYOUT_SPACING["item_gap"]

    # Chunk divider: three centered dots
    y -= LAYOUT_SPACING["divider_gap"]
    c.setFillColor(HexColor(theme_colors.chunk_border))
    center_x = (left + right) / 2
    for dx in (-12, 0, 12):
        c.circle(center_x + dx, y, 2, fill=True, stroke=False)
    y -= LAYOUT_SPACING["divider_gap"]

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


def _draw_chain_step_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    col_width: float | None = None,
    write_line_height: float = 40,
) -> float:
    """Draw a chain-step item: instruction text + writing line for the answer."""
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    cw = col_width if col_width is not None else CONTENT_WIDTH
    max_ch = max(1, int(cw / (body * 0.5)))

    # Item number + instruction text
    c.setFillColor(HexColor(theme.colors.text))
    c.setFont(theme.fonts.primary, body)
    item_text = f"  {item.item_id}. {item.content}"
    for ln in _wrap_text(item_text, max_ch):
        c.drawString(lx + 10, y - body, ln)
        y -= body + 6

    # Writing line with generous space for child to print the answer
    write_y = y - write_line_height + 6
    _draw_writing_line(c, lx + 30, write_y, theme.colors.writing_line, max_width=160, col_width=cw)
    y = write_y - 12

    return y


def _estimate_match_group_height(
    items: list[ActivityItem],
    sizes: dict[str, int],
) -> float:
    """Estimate total height for a two-column match group."""
    row_height = 88  # pic_size(72) + gap(16)
    return row_height * len(items) + 20


def _draw_match_group(
    c: Canvas,
    items: list[ActivityItem],
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    right: float | None = None,
    asset_manifest: AssetManifest | None = None,
) -> float:
    """Draw match items as a two-column layout: words left, pictures right (shuffled).

    Words are listed top-to-bottom on the left. Pictures are listed in their
    shuffled order (from item.options[0]) on the right. The child draws lines
    to connect each word to the correct picture.
    """
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    rx = right if right is not None else (PAGE_WIDTH - MARGIN)
    col_width = rx - lx
    pic_size = 72
    row_height = pic_size + 16

    # Build picture list from shuffled options
    pic_words = [(item.options[0] if item.options else item.content) for item in items]

    # Draw each row
    for row_idx, item in enumerate(items):
        row_y = y - row_idx * row_height

        # Word label on the left (vertically centered in row)
        c.setFont(theme.fonts.heading, body + 4)
        c.setFillColor(HexColor(theme.colors.text))
        word_y = row_y - pic_size / 2 - (body + 4) / 3
        c.drawString(lx + 15, word_y, item.content)

        # Picture on the right (from the shuffled list, NOT this item's word)
        pic_word = pic_words[row_idx]
        pic_x = lx + col_width - pic_size - 10
        pic_y = row_y - pic_size - 4

        word_drawn = False
        if asset_manifest:
            pic_path = asset_manifest.word_picture_paths.get(pic_word)
            if pic_path and Path(pic_path).exists():
                try:
                    c.drawImage(
                        pic_path,
                        pic_x,
                        pic_y,
                        width=pic_size,
                        height=pic_size,
                        preserveAspectRatio=True,
                        mask="auto",
                    )
                    word_drawn = True
                except Exception as e:
                    logger.warning(f"Failed to draw word pic: {e}")

        if not word_drawn:
            c.setStrokeColor(HexColor(theme.colors.chunk_border))
            c.setDash(3, 3)
            c.rect(pic_x, pic_y, pic_size, pic_size, fill=False, stroke=True)
            c.setDash()
            c.setFont(theme.fonts.primary, 7)
            c.setFillColor(HexColor(theme.colors.directions))
            # Show the picture word label so the child knows what the picture is
            prompt = _word_to_picture_label(pic_word)
            c.drawString(pic_x + 3, pic_y + pic_size / 2, prompt)

    # Draw dotted connecting area between word and picture columns
    # (light dotted lines from each word row to give the child space to draw)
    mid_left = lx + 15 + max(len(item.content) for item in items) * (body * 0.65) + 15
    mid_right = lx + col_width - pic_size - 20
    if mid_left < mid_right:
        for row_idx in range(len(items)):
            row_y = y - row_idx * row_height
            line_y = row_y - pic_size / 2 - 4
            c.setStrokeColor(HexColor(theme.colors.chunk_border))
            c.setDash(2, 6)
            c.setLineWidth(0.5)
            c.line(mid_left, line_y, mid_right, line_y)
            c.setDash()
            c.setLineWidth(1)

    y -= len(items) * row_height + 10
    c.setFont(theme.fonts.primary, body)
    return y


def _word_to_picture_label(word: str) -> str:
    """Short label for a picture placeholder box."""
    return f"[{word[:10]}]"


def _draw_trace_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
) -> float:
    """Draw a word in dotted outline letters for tracing."""
    lx = left if left is not None else MARGIN
    trace_size = sizes["heading"] + 6

    # Render text as clipping path, then draw dashed strokes (dotted outline)
    text_obj = c.beginText(lx + 20, y - trace_size)
    text_obj.setFont(theme.fonts.heading, trace_size)
    text_obj.setTextRenderMode(1)  # Stroke only (outline, no fill)
    text_obj.textLine(item.content)
    c.setStrokeColor(HexColor("#C0C4CC"))
    c.setLineWidth(0.7)
    c.setDash(1, 2)  # 1pt dot, 2pt gap — dotted effect
    c.drawText(text_obj)
    c.setDash()  # Reset dash

    # Solid write line below
    line_y = y - trace_size - 6
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setLineWidth(0.5)
    line_width = len(item.content) * trace_size * 0.6
    c.line(lx + 20, line_y, lx + 20 + max(line_width, 100), line_y)

    y -= trace_size + 20
    c.setFont(theme.fonts.primary, sizes["body"])
    return y


def _draw_circle_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    right: float | None = None,
) -> float:
    """Draw words spaced out for the child to circle — no pre-drawn bubbles."""
    body = sizes["body"]
    word_size = body + 2
    lx = left if left is not None else MARGIN
    rx = right if right is not None else (PAGE_WIDTH - MARGIN)

    # Instruction text
    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(lx + 10, y - body, f"  {item.item_id}. {item.content}")
    y -= body + 14

    # Draw plain words with generous spacing for circling
    if item.options:
        x = lx + 30
        word_spacing = 28  # space between words for child to circle
        for word in item.options:
            word_width = len(word) * word_size * 0.6
            # Check if word fits on this row
            if x + word_width + word_spacing > rx - 10 and x > lx + 30:
                x = lx + 30
                y -= word_size + 22
            c.setFillColor(HexColor(theme.colors.text))
            c.setFont(theme.fonts.heading, word_size)
            c.drawString(x, y - word_size, word)
            x += word_width + word_spacing

        y -= word_size + 20

    return y


def _draw_fill_blank_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    col_width: float | None = None,
) -> float:
    """Draw a word/sentence with blank and optional word bank."""
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    cw = col_width if col_width is not None else CONTENT_WIDTH
    # Child-print line height: generous for young writers
    write_line_height = max(int(body * 2.5), 40)

    # Content with blank — display at large size for readability
    display_size = body + 4
    c.setFont(theme.fonts.heading, display_size)
    c.setFillColor(HexColor(theme.colors.text))
    max_ch = int(cw / (display_size * 0.55))
    item_text = f"{item.item_id}. {item.content}"
    for ln in _wrap_text(item_text, max_ch):
        c.drawString(lx + 15, y - display_size - 2, ln)
        y -= display_size + 8

    # Answer writing line below the prompt
    line_y = y - write_line_height + 8
    _draw_writing_line(c, lx + 30, line_y, theme.colors.writing_line, max_width=220, col_width=cw)
    y = line_y - 8

    # Word bank (options) in a shaded box
    if item.options:
        bank_height = body + 14
        bx = lx + 25
        bw = cw - 50
        c.setFillColor(HexColor("#F9FAFB"))
        c.roundRect(bx, y - bank_height, bw, bank_height, 6, fill=True, stroke=False)
        c.setStrokeColor(HexColor(theme.colors.chunk_border))
        c.roundRect(bx, y - bank_height, bw, bank_height, 6, fill=False, stroke=True)

        c.setFillColor(HexColor(theme.colors.directions))
        c.setFont(theme.fonts.primary, sizes["small"])
        bank_text = "Word bank: " + "   ".join(item.options)
        c.drawString(bx + 10, y - body - 2, bank_text)
        y -= bank_height + 10

    c.setFont(theme.fonts.primary, body)
    return y


def _draw_read_aloud_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    col_width: float | None = None,
) -> float:
    """Draw a passage in a styled reading box with read-aloud icon."""
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    cw = col_width if col_width is not None else CONTENT_WIDTH
    max_chars = int((cw - 40) / (body * 0.5))
    lines = _wrap_text(item.content, max_chars)

    box_height = len(lines) * (body + 6) + 24

    # Light blue reading box
    rx, rw = lx + 10, cw - 20
    c.setFillColor(HexColor(theme.colors.reading_bg))
    c.roundRect(rx, y - box_height, rw, box_height, 8, fill=True, stroke=False)
    c.setStrokeColor(HexColor(theme.colors.reading_border))
    c.roundRect(rx, y - box_height, rw, box_height, 8, fill=False, stroke=True)

    c.setFont(theme.fonts.heading, sizes["small"])
    c.setFillColor(HexColor(theme.colors.directions))
    c.drawString(lx + 20, y - sizes["small"] - 6, "Read Aloud:")
    inner_y = y - sizes["small"] - 14

    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor(theme.colors.text))
    for line in lines:
        if inner_y < y - box_height + 8:
            break
        c.drawString(lx + 20, inner_y - body, line)
        inner_y -= body + 6

    y -= box_height + 12
    return y


def _draw_sound_box_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    col_width: float | None = None,
) -> float:
    """Draw Elkonin sound boxes — target word above, one box per phoneme below."""
    lx = left if left is not None else MARGIN
    cw = col_width if col_width is not None else CONTENT_WIDTH
    phonemes = item.options or list(item.content)
    box_size = 58  # ~0.8 inch
    box_gap = 8

    # Target word label
    heading_size = sizes["heading"]
    c.setFont(theme.fonts.heading, heading_size)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(lx + 20, y - heading_size, item.content)
    y -= heading_size + 12

    # Draw boxes
    total_boxes_width = len(phonemes) * box_size + (len(phonemes) - 1) * box_gap
    start_x = lx + (cw - total_boxes_width) / 2  # center the boxes

    examples_color = getattr(theme.colors, "examples", "#10B981")
    for i in range(len(phonemes)):
        bx = start_x + i * (box_size + box_gap)
        # Subtle fill to make boxes feel like inviting slots
        c.setFillColor(HexColor(theme.colors.example_bg))
        c.roundRect(bx, y - box_size, box_size, box_size, 6, fill=True, stroke=False)
        c.setStrokeColor(HexColor(examples_color))
        c.setLineWidth(1.5)
        c.roundRect(bx, y - box_size, box_size, box_size, 6, fill=False, stroke=True)

    y -= box_size + 16
    return y


def _draw_fluency_word_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
    col_width: float | None = None,
) -> float:
    """Draw a single fluency word in large, clear type for rapid reading."""
    lx = left if left is not None else MARGIN
    heading_size = sizes["heading"]

    c.setFont(theme.fonts.heading, heading_size + 4)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(lx + 30, y - heading_size - 2, item.content)
    y -= heading_size + 16
    return y


def _draw_break_prompt(
    c: Canvas,
    prompt: str,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    effective_bottom: float = CONTENT_BOTTOM,
) -> float:
    """Draw a fun 'Take a Break!' section with movement suggestion."""
    body = sizes["body"]
    box_height = body * 2 + 24

    # Check space
    if y - box_height < effective_bottom:
        c.showPage()
        y = CONTENT_TOP

    # Bright, fun box
    bx, bw = MARGIN + 20, CONTENT_WIDTH - 40
    c.setFillColor(HexColor("#FEF3C7"))  # Warm yellow
    c.roundRect(bx, y - box_height, bw, box_height, 8, fill=True, stroke=False)
    c.setStrokeColor(HexColor("#F59E0B"))
    c.setLineWidth(2)
    c.roundRect(bx, y - box_height, bw, box_height, 8, fill=False, stroke=True)
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
    """Draw chunk with two-column layout: content (60%) + scene (40%).

    Alternates scene position left/right between chunks.
    Text is constrained to the content column so it never overlaps the scene.
    Falls back to standard layout if no scene asset available.
    """
    scene_path = asset_manifest.scene_paths.get(chunk.chunk_id)

    if not scene_path or not Path(scene_path).exists():
        return _draw_chunk(
            c,
            chunk,
            adapted,
            theme,
            sizes,
            colors,
            y,
            asset_manifest=asset_manifest,
        )

    # Layout: even chunks = scene right, odd = scene left
    scene_right = chunk_idx % 2 == 0
    gap = 10  # gap between content and scene columns

    scene_width = CONTENT_WIDTH * 0.38
    scene_height = 150

    if scene_right:
        content_left = MARGIN
        content_right = PAGE_WIDTH - MARGIN - scene_width - gap
        scene_x = content_right + gap
    else:
        scene_x = MARGIN
        content_left = MARGIN + scene_width + gap
        content_right = PAGE_WIDTH - MARGIN

    # Draw scene image
    try:
        c.drawImage(
            scene_path,
            scene_x,
            y - scene_height,
            width=scene_width,
            height=scene_height,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception as e:
        logger.warning(f"Failed to draw scene for chunk {chunk.chunk_id}: {e}")

    # Draw content constrained to the content column
    y_after = _draw_chunk(
        c,
        chunk,
        adapted,
        theme,
        sizes,
        colors,
        y,
        content_left=content_left,
        content_right=content_right,
        asset_manifest=asset_manifest,
    )

    # Ensure we move past the scene height
    y_after = min(y_after, y - scene_height - 8)

    return y_after


def _draw_feedback_panel(
    c: Canvas,
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    effective_bottom: float = CONTENT_BOTTOM,
) -> float:
    """Child traffic-light strip + grown-up quick log (spec 2026-07-10)."""
    panel = adapted.feedback
    if panel is None:
        return y
    body = sizes["body"]
    small = sizes["small"]
    if y - _estimate_feedback_panel_height(adapted, sizes) < effective_bottom:
        c.showPage()
        y = CONTENT_TOP

    c.setFont(theme.fonts.heading, body)
    c.setFillColor(HexColor(theme.colors.rewards))
    c.drawString(MARGIN, y - body, panel.child_prompt)
    y -= body + 10
    for chunk in adapted.chunks:
        c.setFont(theme.fonts.primary, body)
        c.setFillColor(HexColor(theme.colors.text))
        c.drawString(MARGIN + 10, y - body + 2, f"Part {chunk.chunk_id}")
        x = MARGIN + 90
        for color in _TRAFFIC_LIGHT_COLORS:
            c.setStrokeColor(HexColor(color))
            c.circle(x, y - body / 2, body / 2.5, fill=0, stroke=1)
            x += body + 12
        y -= body + 6

    c.setFont(theme.fonts.heading, body)
    c.setFillColor(HexColor(theme.colors.directions))
    c.drawString(MARGIN, y - body, panel.parent_log_title)
    y -= body + 10
    c.setFont(theme.fonts.primary, small)
    c.setFillColor(HexColor(theme.colors.text))
    for chunk in adapted.chunks:
        line = (
            f"Part {chunk.chunk_id}: ___ of {len(chunk.items)} correct   "
            "smooth / choppy   help: none / some / lots"
        )
        c.drawString(MARGIN + 10, y - small, line)
        y -= small + 6
    if panel.show_decision_hint:
        max_chars = max(1, int((CONTENT_WIDTH - 10) / (small * 0.5)))
        for ln in _wrap_text(DECISION_HINT, max_chars):
            c.drawString(MARGIN + 10, y - small, ln)
            y -= small + 6
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
            str(avatar_file),
            x,
            y,
            width=avatar_size,
            height=avatar_size,
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
                str(asset_path),
                x,
                y,
                width=size,
                height=size,
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
    """Draw page footer with separator line."""
    footer_y = MARGIN / 2
    # Thin separator line above footer
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setLineWidth(0.5)
    c.line(MARGIN, footer_y + 10, PAGE_WIDTH - MARGIN, footer_y + 10)
    c.setFont(theme.fonts.primary, 8)
    c.setFillColor(HexColor(theme.colors.chunk_border))
    footer = f"{theme.name} | Worksheet Builder v0.1.0"
    if adapted.worksheet_count > 1:
        footer += f" | Part {adapted.worksheet_number} of {adapted.worksheet_count}"
    c.drawString(MARGIN, footer_y, footer)
