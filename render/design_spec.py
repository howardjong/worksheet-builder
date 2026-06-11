"""Renderer-neutral worksheet design specification.

This module turns validated adapted worksheet data into a stable contract that
different renderers can consume without re-deciding pedagogy or ADHD constraints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from adapt.schema import ActivityItem, AdaptedActivityModel
from companion.schema import LearnerProfile
from theme.schema import ThemeConfig

RenderMode = Literal["pdf_classic", "hybrid_shell", "image_prompt"]
VisualIntensity = Literal["low", "medium", "high"]

LETTER_WIDTH_PT = 612
LETTER_HEIGHT_PT = 792
LETTER_MARGIN_PT = 54


class PageSpec(BaseModel):
    """Print page geometry in PDF points."""

    width_pt: int = Field(description="Page width in points.")
    height_pt: int = Field(description="Page height in points.")
    margin_pt: int = Field(description="Safe margin in points.")

    @model_validator(mode="after")
    def _validate_letter_page(self) -> PageSpec:
        if self.width_pt != LETTER_WIDTH_PT or self.height_pt != LETTER_HEIGHT_PT:
            raise ValueError("worksheet design specs must target US Letter pages")
        if self.margin_pt < 50:
            raise ValueError("worksheet design specs must preserve print-safe margins")
        return self


class VisualBudget(BaseModel):
    """ADHD-safe visual budget for a renderer."""

    style: str = Field(description="Theme style label, such as calm.")
    intensity: VisualIntensity = Field(description="Allowed visual intensity.")
    max_decorative_elements: int = Field(description="Maximum decorative-only elements.")
    max_colors: int = Field(description="Maximum functional color count.")

    @field_validator("max_decorative_elements")
    @classmethod
    def _validate_decorations(cls, value: int) -> int:
        if value < 0 or value > 2:
            raise ValueError("ADHD-safe worksheets allow 0-2 decorative elements")
        return value

    @field_validator("max_colors")
    @classmethod
    def _validate_colors(cls, value: int) -> int:
        if value < 1 or value > 4:
            raise ValueError("ADHD-safe worksheets allow 1-4 functional colors")
        return value


class AnswerZoneSpec(BaseModel):
    """A renderer-independent answer affordance for one worksheet item."""

    chunk_id: int = Field(description="Activity chunk identifier.")
    item_id: int = Field(description="Activity item identifier.")
    response_format: str = Field(description="Expected response format.")
    prompt_text: str = Field(description="Student-facing prompt text.")
    expected_answer: str | None = Field(default=None, description="Answer when known.")
    x0: float = Field(description="Relative left coordinate.")
    y0: float = Field(description="Relative bottom coordinate.")
    x1: float = Field(description="Relative right coordinate.")
    y1: float = Field(description="Relative top coordinate.")

    @model_validator(mode="after")
    def _validate_relative_bounds(self) -> AnswerZoneSpec:
        values = (self.x0, self.y0, self.x1, self.y1)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("answer zone coordinates must be relative values from 0 to 1")
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("answer zone bounds must have positive area")
        return self


class WorksheetDesignSpec(BaseModel):
    """Renderer-neutral worksheet contract."""

    spec_version: str = Field(default="worksheet_design_spec_v1")
    render_mode: RenderMode
    source_hash: str
    skill_model_hash: str
    learner_profile_hash: str
    theme_id: str
    theme_name: str
    learner_name: str
    learner_grade_level: str
    learner_theme_preferences: list[str] = Field(default_factory=list)
    worksheet_title: str
    worksheet_number: int
    worksheet_count: int
    domain: str
    specific_skill: str
    page: PageSpec
    visual_budget: VisualBudget
    required_text: list[str] = Field(description="Exact text renderers must preserve.")
    answer_zones: list[AnswerZoneSpec] = Field(default_factory=list)

    @field_validator("required_text")
    @classmethod
    def _validate_required_text(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("worksheet design specs require at least one text entry")
        if any(not text.strip() for text in value):
            raise ValueError("required text entries must not be blank")
        return value


def compile_worksheet_design_spec(
    adapted: AdaptedActivityModel,
    theme: ThemeConfig,
    profile: LearnerProfile,
    *,
    render_mode: RenderMode,
) -> WorksheetDesignSpec:
    """Compile an adapted worksheet into a renderer-neutral design spec."""

    return WorksheetDesignSpec(
        render_mode=render_mode,
        source_hash=adapted.source_hash,
        skill_model_hash=adapted.skill_model_hash,
        learner_profile_hash=adapted.learner_profile_hash,
        theme_id=adapted.theme_id,
        theme_name=theme.name,
        learner_name=profile.name,
        learner_grade_level=profile.grade_level,
        learner_theme_preferences=_theme_preferences(profile),
        worksheet_title=adapted.worksheet_title or adapted.specific_skill,
        worksheet_number=adapted.worksheet_number,
        worksheet_count=adapted.worksheet_count,
        domain=adapted.domain,
        specific_skill=adapted.specific_skill,
        page=PageSpec(
            width_pt=LETTER_WIDTH_PT,
            height_pt=LETTER_HEIGHT_PT,
            margin_pt=LETTER_MARGIN_PT,
        ),
        visual_budget=VisualBudget(
            style=theme.style,
            intensity=_intensity_for_style(theme.style),
            max_decorative_elements=theme.decorative_elements.max_per_page,
            max_colors=4,
        ),
        required_text=_required_text(adapted),
        answer_zones=_answer_zones(adapted),
    )


def _theme_preferences(profile: LearnerProfile) -> list[str]:
    if profile.preferences is None:
        return []
    return list(profile.preferences.favorite_themes)


def _intensity_for_style(style: str) -> VisualIntensity:
    if style == "calm":
        return "low"
    return "medium"


def _required_text(adapted: AdaptedActivityModel) -> list[str]:
    text: list[str] = [
        adapted.worksheet_title or adapted.specific_skill,
        adapted.specific_skill,
    ]
    for chunk in adapted.chunks:
        text.append(chunk.micro_goal)
        text.extend(step.text for step in chunk.instructions)
        if chunk.worked_example is not None:
            text.append(chunk.worked_example.instruction)
            text.append(chunk.worked_example.content)
        for item in chunk.items:
            text.append(item.content)
            if item.answer:
                text.append(item.answer)
            if item.options:
                text.extend(item.options)
    return _dedupe_nonblank(text)


def _answer_zones(adapted: AdaptedActivityModel) -> list[AnswerZoneSpec]:
    zones: list[AnswerZoneSpec] = []
    answer_index = 0
    for chunk in adapted.chunks:
        for item in chunk.items:
            if not _needs_answer_zone(item):
                continue
            answer_index += 1
            y0 = max(0.08, 0.82 - answer_index * 0.1)
            zones.append(
                AnswerZoneSpec(
                    chunk_id=chunk.chunk_id,
                    item_id=item.item_id,
                    response_format=item.response_format,
                    prompt_text=item.content,
                    expected_answer=item.answer,
                    x0=0.12,
                    y0=y0,
                    x1=0.88,
                    y1=min(0.92, y0 + 0.07),
                )
            )
    return zones


def _needs_answer_zone(item: ActivityItem) -> bool:
    return item.response_format in {"write", "fill_blank", "trace", "sound_box"}


def _dedupe_nonblank(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
