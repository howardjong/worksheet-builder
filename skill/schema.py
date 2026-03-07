"""Data models for the skill extraction stage."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """A single extracted question or activity from the source worksheet."""

    item_type: str  # "word_chain", "sentence", "word_list", "passage", "sight_words"
    content: str
    source_region_index: int  # index into SourceWorksheetModel.regions
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class LiteracySkillModel(BaseModel):
    """Stage 4 output: the targeted literacy skill extracted from a worksheet."""

    grade_level: str  # "K" | "1" | "2" | "3"
    domain: str  # "phonemic_awareness" | "phonics" | "fluency" |
    #              "vocabulary" | "comprehension" | "writing"
    specific_skill: str  # e.g., "CVC blending", "digraph sh/ch/th", "CVCe pattern"
    learning_objectives: list[str]
    target_words: list[str]  # word lists, sight words, spelling patterns
    response_types: list[str]  # "circle", "write", "match", "read_aloud", "trace"
    source_items: list[SourceItem]  # extracted questions/activities
    extraction_confidence: float  # overall confidence in skill extraction 0-1
    template_type: str  # from SourceWorksheetModel, passed through
