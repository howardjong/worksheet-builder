"""Measured vector text and on-demand artwork; no instructional text in images."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import fitz
from PIL import Image as PILImage
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
)

from adapt.schema import ActivityChunk, ActivityItem, AdaptedActivityModel
from ai.telemetry import in_stage
from render.pdf import (
    GRADE_FONT_SIZES,
    RenderContractError,
    _printable_text,
    _register_fonts,
    _validate_render_inputs,
)
from render.scene_geometry import meaningful_page_fraction, scene_size
from theme.schema import ThemeConfig

WIDTH, HEIGHT, MARGIN = 612.0, 792.0, 54.0
CONTENT_WIDTH = WIDTH - 2 * MARGIN


class PracticeParagraph(Paragraph):  # type: ignore[misc]
    """Track pages with actual child practice, including split passages."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.practice_pages: set[int] = set()

    def draw(self) -> None:
        self.practice_pages.add(self.canv.getPageNumber())
        super().draw()

    def split(self, availWidth: float, availHeight: float) -> list[Flowable]:  # noqa: N803
        parts: list[Flowable] = super().split(availWidth, availHeight)
        for part in parts:
            if isinstance(part, PracticeParagraph):
                part.practice_pages = self.practice_pages
        return parts


class LearningIllustration(Image):  # type: ignore[misc]
    """Place a scene once alongside its task, never stamp it on continuation pages."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.scene_pages: set[int] = set()

    def draw(self) -> None:
        self.scene_pages.add(self.canv.getPageNumber())
        super().draw()


class TracePractice(Flowable):  # type: ignore[misc]
    """Visible dotted outline glyphs, measured before drawing."""

    def __init__(self, text: str, font: str, size: float, pages: set[int]) -> None:
        super().__init__()
        self.text, self.font, self.size, self.pages = text, font, size, pages
        self.height = size * 1.6

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # noqa: N803
        if pdfmetrics.stringWidth(self.text, self.font, self.size) > availWidth:
            raise RenderContractError("trace text exceeds its writing area")
        self.width = availWidth
        return self.width, self.height

    def draw(self) -> None:
        self.pages.add(self.canv.getPageNumber())
        self.canv.saveState()
        self.canv.setStrokeColor(HexColor("#94A3B8"))
        self.canv.setLineWidth(0.7)
        self.canv.setDash(1, 2)
        text = self.canv.beginText(0, self.size * 0.25)
        text.setFont(self.font, self.size)
        text.setTextRenderMode(1)
        text.textLine(self.text)
        self.canv.drawText(text)
        self.canv.restoreState()


class ResponseLines(Flowable):  # type: ignore[misc]
    def __init__(self, kind: str, boxes: int = 0) -> None:
        super().__init__()
        self.kind = kind
        self.boxes = boxes
        self.height = 42 if boxes else 30

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # noqa: N803
        self.width = availWidth
        if self.boxes and self.boxes * 30 > availWidth:
            raise RenderContractError("sound boxes would be too small or extend outside the page")
        return self.width, self.height

    def draw(self) -> None:
        self.canv.setStrokeColor(HexColor("#94A3B8"))
        self.canv.setLineWidth(0.8)
        if self.boxes:
            size = min(42.0, (self.width - 8 * (self.boxes - 1)) / self.boxes)
            for index in range(self.boxes):
                self.canv.roundRect(index * (size + 8), 0, size, size, 4, stroke=1, fill=0)
        else:
            self.canv.line(0, 8, min(self.width, 300), 8)
            if self.kind == "trace":
                self.canv.setDash(2, 3)
                self.canv.line(0, 20, min(self.width, 300), 20)


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_printable_text(text)).replace("\n", "<br/>"), style)


def _practice(
    item: ActivityItem,
    number: int,
    body: ParagraphStyle,
    theme: ThemeConfig,
    pages: set[int],
) -> list[Flowable]:
    if item.response_format == "match":
        raise RenderContractError(
            "hybrid_shell requires asset-independent activities before approval"
        )
    if item.response_format not in {
        "write",
        "trace",
        "fill_blank",
        "circle",
        "read_aloud",
        "verbal",
        "sound_box",
    }:
        raise RenderContractError(f"unsupported response format: {item.response_format}")
    style = body
    if item.response_format == "read_aloud":
        style = ParagraphStyle(
            "passage",
            parent=body,
            backColor=HexColor(theme.colors.reading_bg),
            borderPadding=8,
            spaceBefore=6,
            spaceAfter=8,
        )
    if item.response_format == "trace":
        style = ParagraphStyle(
            "trace",
            parent=body,
            fontSize=body.fontSize + 5,
            leading=body.leading + 5,
            textColor=HexColor("#64748B"),
        )
    paragraph = PracticeParagraph(escape(_printable_text(f"{number}. {item.content}")), style)
    paragraph.practice_pages = pages
    result: list[Flowable] = [
        TracePractice(
            _printable_text(f"{number}. {item.content}"), body.fontName, style.fontSize, pages
        )
        if item.response_format == "trace"
        else paragraph
    ]
    if item.options and item.response_format in {"circle", "fill_blank"}:
        label = "Circle one: " if item.response_format == "circle" else "Word bank: "
        result.append(_paragraph(label + "   /   ".join(item.options), body))
    if item.response_format == "sound_box":
        result.append(ResponseLines("sound_box", len(item.options or list(item.content))))
    elif item.response_format in {"write", "trace", "fill_blank"} or item.metadata.get(
        "display"
    ) in {
        "chain",
        "chain_step",
    }:
        result.append(ResponseLines(item.response_format))
    result.append(Spacer(1, 7))
    return result


def _caregiver_rows(chunks: list[ActivityChunk]) -> list[str]:
    """Score displayed tasks by section, never identifiers or a passage as one word."""
    rows: list[str] = []
    for number, chunk in enumerate(chunks, 1):
        prefix = f"Section {number}: "
        written = sum(
            item.response_format in {"write", "trace", "fill_blank", "circle", "sound_box"}
            for item in chunk.items
        )
        reading = [item for item in chunk.items if item.response_format == "read_aloud"]
        words = [
            item
            for item in reading
            if item.content.strip().replace("-", "").replace("'", "").isalpha()
        ]
        if written:
            rows.append(prefix + f"Right: ___ of {written} tasks")
        if words:
            rows.append(prefix + f"Read correctly: ___ of {len(words)} words")
        if len(reading) > len(words):
            rows.append(prefix + "Reading: smooth / choppy")
        if any(item.response_format == "verbal" for item in chunk.items):
            rows.append(prefix + "Oral practice: done / needs help")
    rows.append("Help: none / some / lots")
    return rows


@in_stage("composition")
def render_composed_pdf(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    output: Path,
    artifacts: Path,
    scene_path: str | None,
    learner_name: str,
) -> None:
    """Build serially: ReportLab font state and PyMuPDF never enter worker threads."""
    _validate_render_inputs(adapted, None)
    _register_fonts(theme)
    body_font = "Lexend" if "Lexend" in pdfmetrics.getRegisteredFontNames() else theme.fonts.primary
    sizes = GRADE_FONT_SIZES.get(adapted.grade_level, GRADE_FONT_SIZES["1"])
    child_min_size = {"K": 16, "1": 14, "2": 12, "3": 12}.get(adapted.grade_level, 14)
    if min(sizes["body"], sizes["heading"]) < child_min_size:
        raise RenderContractError("child-facing type is below the grade minimum")
    body = ParagraphStyle(
        "practice",
        fontName=body_font,
        fontSize=sizes["body"],
        leading=sizes["body"] * 1.6,
        textColor=HexColor(theme.colors.text),
        spaceAfter=4,
    )
    heading = ParagraphStyle(
        "section",
        parent=body,
        fontName=theme.fonts.heading,
        fontSize=sizes["heading"],
        leading=sizes["heading"] * 1.3,
        textColor=HexColor(theme.colors.directions),
        spaceBefore=8,
        spaceAfter=5,
    )
    small = ParagraphStyle(
        "caregiver", parent=body, fontSize=sizes["small"], leading=sizes["small"] * 1.4
    )
    story: list[Flowable] = []
    practice_pages: set[int] = set()
    last_practice: list[Flowable] = []
    caregiver_rows = _caregiver_rows(adapted.chunks) if adapted.feedback else []
    display_numbering: list[dict[str, int]] = []
    scene_width = 0.0
    illustration: LearningIllustration | None = None
    scene_section = 1
    if scene_path:
        with PILImage.open(scene_path) as image:
            pixel_width, pixel_height = image.size
            scene_width, scene_height = scene_size(pixel_width, pixel_height)
        receipt = json.loads((artifacts / "learning_scene.json").read_text())
        bounds = receipt["gate"]["bounds"]
        if meaningful_page_fraction(pixel_width, pixel_height, tuple(bounds)) < 0.10:
            raise RenderContractError("learning scene occupies less than 10% of the page")
        scene_section = receipt.get("action_contract", {}).get("section_number", 1)
        if type(scene_section) is not int or not 1 <= scene_section <= len(adapted.chunks):
            raise RenderContractError("learning scene references an absent section")
        illustration = LearningIllustration(scene_path, width=scene_width, height=scene_height)
        illustration.hAlign = "CENTER"
    for section_number, chunk in enumerate(adapted.chunks, 1):
        if not chunk.items:
            raise RenderContractError("empty activity section")
        header: list[Flowable] = [
            _paragraph(f"Section {section_number}: {chunk.micro_goal}", heading)
        ]
        if illustration and section_number == scene_section:
            header.extend([illustration, Spacer(1, 8)])
        display_numbering.extend(
            {"section": section_number, "item_id": item.item_id, "display_number": number}
            for number, item in enumerate(chunk.items, 1)
        )
        if chunk.time_estimate:
            header.append(_paragraph(chunk.time_estimate, body))
        header.extend(
            _paragraph(f"{step.number}. {step.text}", body) for step in chunk.instructions
        )
        if chunk.worked_example:
            header.append(_paragraph(chunk.worked_example.instruction, body))
            header.append(_paragraph(chunk.worked_example.content, body))
        short_practice = adapted.grade_level in {"2", "3"} and all(
            item.response_format in {"write", "fill_blank", "trace", "sound_box"}
            and not item.options
            and len(item.content) <= 28
            and "\n" not in item.content
            for item in chunk.items
        )
        if short_practice:
            # Numbered, left-to-right pairs retain generous writing space without
            # wasting a whole row on a short word. Long text stays full-width.
            for index in range(0, len(chunk.items), 2):
                cells: list[list[Flowable]] = [
                    _practice(item, number, body, theme, practice_pages)
                    for number, item in enumerate(chunk.items[index : index + 2], index + 1)
                ]
                if len(cells) == 1:
                    cells.append([])
                table = Table(
                    [cells],
                    colWidths=[CONTENT_WIDTH / 2] * 2,
                    style=[
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ],
                )
                block = header + [table] if index == 0 else [table]
                story.append(KeepTogether(block))
                last_practice = block
        else:
            for index, item in enumerate(chunk.items):
                practice = _practice(item, index + 1, body, theme, practice_pages)
                block = header + practice if index == 0 else practice
                story.append(KeepTogether(block))
                last_practice = block

    tail: list[Flowable] = []
    if adapted.break_prompt:
        tail.append(_paragraph("Brain break: " + adapted.break_prompt, body))
    if adapted.feedback:
        tail.append(_paragraph(adapted.feedback.parent_log_title, small))
        tail.extend(_paragraph(row, small) for row in caregiver_rows)
        if adapted.feedback.show_decision_hint:
            from adapt.feedback import DECISION_HINT

            tail.append(_paragraph(DECISION_HINT, small))
    if tail:
        # The final practice item travels with its log/break, preventing log-only pages.
        story[-1] = KeepTogether(last_practice + tail)
    if not story:
        raise RenderContractError("worksheet has no practice")

    title = _paragraph(adapted.worksheet_title or "Word practice", heading)
    _, title_height = title.wrap(CONTENT_WIDTH, HEIGHT)
    goal_text = (
        adapted.feedback.goal_statement
        if adapted.feedback
        else adapted.specific_skill.replace("_", " ")
    )
    goal = _paragraph(goal_text, body)
    _, goal_height = goal.wrap(CONTENT_WIDTH, HEIGHT)
    learner = _paragraph("For " + learner_name, body)
    _, learner_height = learner.wrap(CONTENT_WIDTH, HEIGHT)
    header_height = title_height + goal_height + learner_height + 6
    if header_height > 110:
        raise RenderContractError("worksheet title, goal and learner name exceed the header space")
    content_top = HEIGHT - MARGIN - header_height - 12
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building.pdf")

    def page_header(canvas: Canvas, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        title.drawOn(canvas, MARGIN, HEIGHT - MARGIN - title_height)
        goal.drawOn(canvas, MARGIN, HEIGHT - MARGIN - title_height - goal_height - 2)
        learner.drawOn(
            canvas, MARGIN, HEIGHT - MARGIN - title_height - goal_height - learner_height - 4
        )
        canvas.setFont(body_font, sizes["small"])
        canvas.setFillColor(HexColor(theme.colors.text))
        footer = (
            f"{theme.name} | Part {adapted.worksheet_number}/{adapted.worksheet_count} "
            f"| Page {document.page}"
        )
        canvas.drawString(MARGIN, MARGIN, footer)
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(temporary),
        pagesize=(WIDTH, HEIGHT),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=HEIGHT - content_top,
        bottomMargin=MARGIN + 22,
        title=adapted.worksheet_title or "Worksheet",
        author="Worksheet Builder",
    )
    try:
        document.build(story, onFirstPage=page_header, onLaterPages=page_header)
        # This layer contains actual drawn text, never a synthetic invisible copy.
        with fitz.open(temporary) as pdf:
            if practice_pages != set(range(1, len(pdf) + 1)):
                raise RenderContractError("worksheet contains a page without child practice")
            actual = " ".join(" ".join(page.get_text().split()) for page in pdf)
            required_text: list[str] = []
            for chunk in adapted.chunks:
                required_text.extend([chunk.micro_goal, chunk.time_estimate])
                required_text.extend(step.text for step in chunk.instructions)
                if chunk.worked_example:
                    required_text.extend(
                        [chunk.worked_example.instruction, chunk.worked_example.content]
                    )
                for item in chunk.items:
                    required_text.extend(item.options or [])
                    expected = " ".join(_printable_text(item.content).split())
                    if expected not in actual:
                        raise RenderContractError(
                            f"practice item {item.item_id} absent from drawn PDF"
                        )
            for value in required_text:
                if " ".join(_printable_text(value).split()) not in actual:
                    raise RenderContractError(
                        "required instruction, example or option absent from PDF"
                    )
            for row in caregiver_rows:
                if " ".join(_printable_text(row).split()) not in actual:
                    raise RenderContractError("caregiver score or denominator absent from PDF")
            layout_report = {
                "physical_pages": len(pdf),
                "practice_pages": sorted(practice_pages),
                "child_min_font_pt": child_min_size,
                "child_body_font_pt": sizes["body"],
                "caregiver_font_pt": sizes["small"],
                "artwork_effective_ppi": (
                    round(
                        min(pixel_width / (scene_width / 72), pixel_height / (scene_height / 72)), 1
                    )
                    if scene_path
                    else None
                ),
                "raster_text": False,
                "artwork_pages": sorted(illustration.scene_pages) if illustration else [],
                "artwork_section": scene_section if illustration else None,
                "display_numbering": display_numbering,
                "caregiver_rows": caregiver_rows,
                "page_count_requires_human_acceptance": True,
            }
            (artifacts / "layout_report.json").write_text(json.dumps(layout_report, indent=2))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
