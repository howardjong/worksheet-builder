"""Data models for the ADHD activity adaptation stage."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Step(BaseModel):
    """A single instruction step."""

    number: int
    text: str  # e.g., "Read each word out loud."


class Example(BaseModel):
    """A worked example shown before independent practice items."""

    instruction: str  # e.g., "Watch how I do the first one:"
    content: str  # e.g., "sh → ship (I hear 'sh' at the start!)"


class ActivityItem(BaseModel):
    """A single practice item within a chunk."""

    item_id: int
    content: str  # the actual question/word/prompt
    response_format: str  # "circle"/"write"/"match"/"verbal"/"read_aloud"/"trace"/"fill_blank"
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    options: list[str] | None = None  # choices for circle/match/fill_blank activities
    answer: str | None = None  # correct answer for fill_blank/circle
    picture_prompt: str | None = None  # description for AI to generate a matching illustration


class ActivityChunk(BaseModel):
    """A chunk of practice items — the core unit of ADHD-adapted delivery."""

    chunk_id: int
    micro_goal: str  # e.g., "Find the 'sh' words (4 items)"
    instructions: list[Step]
    worked_example: Example | None = None
    items: list[ActivityItem]
    response_format: str  # dominant format for this chunk
    time_estimate: str  # e.g., "About 3 minutes"
    reward_event: dict[str, str | int] | None = None  # None for MVP


class ScaffoldConfig(BaseModel):
    """Controls how scaffolding fades across chunks."""

    show_worked_example: bool = True  # first chunk always has example
    fade_after_chunk: int = 1  # stop showing examples after this chunk
    hint_level: str = "full"  # "full" | "partial" | "none"


class AdaptedActivityModel(BaseModel):
    """Stage 5 output: ADHD-optimized activity ready for theming and rendering."""

    source_hash: str  # links back to source worksheet
    skill_model_hash: str  # links back to skill extraction
    learner_profile_hash: str  # links back to profile used
    grade_level: str  # "K" | "1" | "2" | "3"
    domain: str  # from skill model
    specific_skill: str  # from skill model
    chunks: list[ActivityChunk]
    scaffolding: ScaffoldConfig
    theme_id: str
    decoration_zones: list[tuple[float, float, float, float]]  # safe areas for illustrations
    avatar_prompts: list[str] | None = None  # None for MVP
    self_assessment: list[str] | None = None  # "I can..." checklist items
    worksheet_number: int = 1  # which mini-worksheet this is (1, 2, or 3)
    worksheet_count: int = 1  # total mini-worksheets for this lesson
    worksheet_title: str | None = None  # e.g., "Word Discovery", "Word Builder"
    break_prompt: str | None = None  # brain break message after this worksheet
