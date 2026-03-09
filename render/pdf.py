"""ReportLab PDF renderer — produces print-ready worksheets from themed adapted models."""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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
    "char_space_body": 0.4,     # extra char spacing for body text (pts)
    "char_space_heading": 0.7,  # extra char spacing for headings (pts)
    "word_space": 1.5,          # extra word spacing (pts)
}

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

    # Apply ADHD-optimized spacing
    _apply_adhd_spacing(c, "body")

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
            y = _draw_chunk(
                c, chunk, adapted, theme, sizes, colors, y,
                asset_manifest=asset_manifest,
            )

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
    content_left: float | None = None,
    content_right: float | None = None,
    asset_manifest: AssetManifest | None = None,
) -> float:
    """Draw a single activity chunk.

    content_left/content_right constrain text to a column
    (used by _draw_chunk_with_scene to avoid image overlap).
    """
    theme_colors = theme.colors
    left = content_left if content_left is not None else MARGIN
    right = content_right if content_right is not None else (PAGE_WIDTH - MARGIN)
    col_width = right - left

    # Micro-goal header
    _apply_adhd_spacing(c, "heading")
    c.setFont(theme.fonts.heading, sizes["body"])
    c.setFillColor(HexColor(theme_colors.key_words))
    c.drawString(left, y - sizes["body"], chunk.micro_goal)
    y -= _line_spacing(sizes["body"])

    # Time estimate (if present)
    _apply_adhd_spacing(c, "body")
    if chunk.time_estimate:
        c.setFont(theme.fonts.primary, sizes["small"])
        c.setFillColor(HexColor(theme_colors.directions))
        c.drawString(left + 10, y - sizes["small"], chunk.time_estimate)
        y -= _line_spacing(sizes["small"])

    # Instructions
    c.setFillColor(HexColor(theme_colors.directions))
    c.setFont(theme.fonts.primary, sizes["body"])
    for step in chunk.instructions:
        text = f"{step.number}. {step.text}"
        c.drawString(left + 10, y - sizes["body"], text)
        y -= _line_spacing(sizes["body"])

    y -= 4

    # Worked example (shaded box)
    if chunk.worked_example:
        box_height = sizes["body"] * 2 + 16
        c.setFillColor(HexColor("#F0FDF4"))
        c.rect(
            left + 5, y - box_height,
            col_width - 10, box_height,
            fill=True, stroke=False,
        )

        c.setFillColor(HexColor(theme_colors.examples))
        c.setFont(theme.fonts.primary, sizes["small"])
        ex_text = chunk.worked_example.instruction
        c.drawString(left + 15, y - sizes["small"] - 4, ex_text)
        y -= sizes["small"] + 8

        c.setFont(theme.fonts.primary, sizes["body"])
        ex_content = chunk.worked_example.content
        # Wrap example content to column width
        ex_max = int(col_width / (sizes["body"] * 0.5))
        for ln in _wrap_text(ex_content, ex_max):
            c.drawString(left + 15, y - sizes["body"] - 4, ln)
            y -= sizes["body"] + 4
        y -= 4

    # Activity items
    c.setFillColor(HexColor(theme_colors.text))
    c.setFont(theme.fonts.primary, sizes["body"])
    max_chars = int(col_width / (sizes["body"] * 0.5))

    for item in chunk.items:
        is_chain = item.metadata.get("display") == "chain"

        if is_chain:
            label = f"  {item.item_id}. "
            chain_text = label + item.content
            for ln in _wrap_text(chain_text, max_chars):
                c.drawString(left + 10, y - sizes["body"], ln)
                y -= sizes["body"] + 4
            c.drawString(
                left + 30, y - sizes["body"],
                "Write: ____________________",
            )
            y -= sizes["body"] + 6
        elif item.response_format == "match":
            y = _draw_match_item(
                c, item, theme, sizes, y,
                left, right, asset_manifest,
            )
        elif item.response_format == "trace":
            y = _draw_trace_item(c, item, theme, sizes, y, left)
        elif item.response_format == "circle" and item.options:
            y = _draw_circle_item(
                c, item, theme, sizes, y, left, right,
            )
        elif item.response_format == "fill_blank":
            y = _draw_fill_blank_item(
                c, item, theme, sizes, y, left, col_width,
            )
        elif item.response_format == "read_aloud":
            y = _draw_read_aloud_item(
                c, item, theme, sizes, y, left, col_width,
            )
        else:
            text = f"  {item.item_id}. {item.content}"
            lines = _wrap_text(text, max_chars)

            for ln in lines:
                c.drawString(left + 10, y - sizes["body"], ln)
                y -= sizes["body"] + 4

            if item.response_format == "write":
                c.drawString(
                    left + 30, y - sizes["body"],
                    "____________________",
                )
                y -= sizes["body"] + 4
            elif item.response_format == "circle":
                c.drawString(
                    left + 30, y - sizes["body"], "(circle one)",
                )
                y -= sizes["body"] + 4

            y += 4
            y -= 6

    # Chunk divider
    y -= 8
    c.setStrokeColor(HexColor(theme_colors.chunk_border))
    c.setLineWidth(0.5)
    c.line(left + 20, y, right - 20, y)
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
    left: float | None = None,
    right: float | None = None,
    asset_manifest: AssetManifest | None = None,
) -> float:
    """Draw a word-picture matching item: word on left, picture on right."""
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    rx = right if right is not None else (PAGE_WIDTH - MARGIN)
    col_width = rx - lx
    pic_size = 50  # square picture tile

    # Word label on the left (large, bold)
    c.setFont(theme.fonts.heading, body + 4)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(lx + 15, y - body - 8, item.content)

    # Picture tile on the right
    pic_x = lx + col_width - pic_size - 10
    pic_y = y - pic_size - 4

    # Try to draw actual word picture from asset manifest
    word_drawn = False
    if asset_manifest:
        pic_path = asset_manifest.word_picture_paths.get(item.content)
        if pic_path and Path(pic_path).exists():
            try:
                c.drawImage(
                    pic_path, pic_x, pic_y,
                    width=pic_size, height=pic_size,
                    preserveAspectRatio=True, mask="auto",
                )
                word_drawn = True
            except Exception as e:
                logger.warning(f"Failed to draw word pic: {e}")

    if not word_drawn:
        # Fallback: dashed placeholder box
        c.setStrokeColor(HexColor(theme.colors.chunk_border))
        c.setDash(3, 3)
        c.rect(pic_x, pic_y, pic_size, pic_size, fill=False, stroke=True)
        c.setDash()
        c.setFont(theme.fonts.primary, 7)
        c.setFillColor(HexColor(theme.colors.directions))
        label = (item.picture_prompt or item.content)[:10]
        c.drawString(pic_x + 3, pic_y + 4, f"[{label}]")

    # Connecting line (dotted) from word to picture
    word_end = lx + 15 + len(item.content) * (body * 0.65) + 10
    line_y = y - pic_size / 2 - 4
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setDash(2, 4)
    c.line(
        min(word_end, pic_x - 25), line_y,
        pic_x - 5, line_y,
    )
    c.setDash()

    y -= pic_size + 12
    c.setFont(theme.fonts.primary, body)
    return y


def _draw_trace_item(
    c: Canvas,
    item: ActivityItem,
    theme: ThemeConfig,
    sizes: dict[str, int],
    y: float,
    left: float | None = None,
) -> float:
    """Draw a word in large dotted/gray outline letters for tracing."""
    lx = left if left is not None else MARGIN
    trace_size = sizes["heading"] + 6
    c.setFont(theme.fonts.heading, trace_size)
    c.setFillColor(HexColor("#D1D5DB"))  # Light gray for tracing
    c.drawString(lx + 20, y - trace_size, item.content)

    # Solid write line below
    line_y = y - trace_size - 6
    c.setStrokeColor(HexColor(theme.colors.chunk_border))
    c.setLineWidth(0.5)
    line_width = len(item.content) * trace_size * 0.6
    c.line(lx + 20, line_y, lx + 20 + max(line_width, 100), line_y)

    y -= trace_size + 14
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
    """Draw a row of words in bubbles for circling."""
    body = sizes["body"]
    lx = left if left is not None else MARGIN
    rx = right if right is not None else (PAGE_WIDTH - MARGIN)

    # Instruction text
    c.setFont(theme.fonts.primary, body)
    c.setFillColor(HexColor(theme.colors.text))
    c.drawString(lx + 10, y - body, f"  {item.item_id}. {item.content}")
    y -= body + 8

    # Draw word bubbles in a row
    if item.options:
        x = lx + 25
        bubble_padding = 12
        for word in item.options:
            word_width = len(word) * body * 0.55 + bubble_padding * 2
            c.setStrokeColor(HexColor(theme.colors.text))
            c.setFillColor(HexColor("#FFFFFF"))
            c.setLineWidth(1)
            c.roundRect(
                x, y - body - 4,
                word_width, body + 8, 6,
                fill=True, stroke=True,
            )
            c.setFillColor(HexColor(theme.colors.text))
            c.setFont(theme.fonts.primary, body)
            c.drawString(x + bubble_padding, y - body + 1, word)
            x += word_width + 8
            if x > rx - 30:
                x = lx + 25
                y -= body + 14

        y -= body + 12

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

    # Content with blank
    c.setFont(theme.fonts.primary, body + 2)
    c.setFillColor(HexColor(theme.colors.text))
    max_ch = int(cw / (body * 0.5))
    item_text = f"{item.item_id}. {item.content}"
    for ln in _wrap_text(item_text, max_ch):
        c.drawString(lx + 15, y - body - 2, ln)
        y -= body + 4
    y -= 4

    # Word bank (options) in a shaded box
    if item.options:
        bank_height = body + 12
        bx = lx + 25
        bw = cw - 50
        c.setFillColor(HexColor("#F9FAFB"))
        c.rect(bx, y - bank_height, bw, bank_height, fill=True, stroke=False)
        c.setStrokeColor(HexColor(theme.colors.chunk_border))
        c.rect(bx, y - bank_height, bw, bank_height, fill=False, stroke=True)

        c.setFillColor(HexColor(theme.colors.directions))
        c.setFont(theme.fonts.primary, sizes["small"])
        bank_text = "Word bank: " + "   ".join(item.options)
        c.drawString(bx + 10, y - body - 2, bank_text)
        y -= bank_height + 6

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

    box_height = len(lines) * (body + 4) + 20
    if y - box_height < CONTENT_BOTTOM:
        box_height = y - CONTENT_BOTTOM - 10

    # Light blue reading box
    rx, rw = lx + 10, cw - 20
    c.setFillColor(HexColor("#EFF6FF"))
    c.roundRect(rx, y - box_height, rw, box_height, 8, fill=True, stroke=False)
    c.setStrokeColor(HexColor("#BFDBFE"))
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
    """Draw chunk with two-column layout: content (60%) + scene (40%).

    Alternates scene position left/right between chunks.
    Text is constrained to the content column so it never overlaps the scene.
    Falls back to standard layout if no scene asset available.
    """
    scene_path = asset_manifest.scene_paths.get(chunk.chunk_id)

    if not scene_path or not Path(scene_path).exists():
        return _draw_chunk(
            c, chunk, adapted, theme, sizes, colors, y,
            asset_manifest=asset_manifest,
        )

    # Layout: even chunks = scene right, odd = scene left
    scene_right = chunk_idx % 2 == 0
    gap = 10  # gap between content and scene columns

    scene_width = CONTENT_WIDTH * 0.32
    scene_height = 120

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
            scene_path, scene_x, y - scene_height,
            width=scene_width, height=scene_height,
            preserveAspectRatio=True, mask="auto",
        )
    except Exception as e:
        logger.warning(
            f"Failed to draw scene for chunk {chunk.chunk_id}: {e}"
        )

    # Draw content constrained to the content column
    y_after = _draw_chunk(
        c, chunk, adapted, theme, sizes, colors, y,
        content_left=content_left,
        content_right=content_right,
        asset_manifest=asset_manifest,
    )

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
