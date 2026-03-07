"""Data models for the capture stage."""

from pydantic import BaseModel


class PreprocessResult(BaseModel):
    """Result of preprocessing a page image."""

    image_hash: str
    original_path: str
    output_path: str
    width: int
    height: int
    skew_angle: float
    perspective_corrected: bool


class MasterRecord(BaseModel):
    """Record of a stored master image."""

    original_path: str
    master_path: str
    image_hash: str
    width: int
    height: int
