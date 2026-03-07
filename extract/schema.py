"""Data models for the extraction stage."""

from pydantic import BaseModel

PIPELINE_VERSION = "0.1.0"
LOW_CONFIDENCE_THRESHOLD = 0.7


class SourceRegion(BaseModel):
    """A single text region extracted from the worksheet."""

    type: str
    """Region type. Generic: "title", "instruction", "question", "answer_blank",
    "word_list", "illustration", "table", "divider".
    UFLI Word Work: "concept_label", "sample_words", "word_chain",
    "chain_script", "sight_word_list", "practice_sentences".
    UFLI Decodable: "story_title", "illustration_box", "decodable_passage"."""

    content: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    confidence: float  # OCR confidence 0-1
    metadata: dict[str, str | int | float | bool]


class SourceWorksheetModel(BaseModel):
    """Complete extraction result for one worksheet page."""

    source_image_hash: str
    pipeline_version: str
    template_type: str  # "ufli_word_work" | "ufli_decodable_story" | "unknown"
    regions: list[SourceRegion]
    raw_text: str
    ocr_engine: str  # "paddleocr" | "tesseract"
    low_confidence_flags: list[int]  # indices of regions below threshold


class OCRBlock(BaseModel):
    """Raw OCR output block before heuristic classification."""

    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    confidence: float


class OCRResult(BaseModel):
    """Raw OCR output from an engine."""

    blocks: list[OCRBlock]
    engine: str
    raw_text: str


def flag_low_confidence(regions: list[SourceRegion]) -> list[int]:
    """Return indices of regions below confidence threshold for human review."""
    return [i for i, r in enumerate(regions) if r.confidence < LOW_CONFIDENCE_THRESHOLD]
