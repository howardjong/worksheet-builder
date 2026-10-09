"""Validate owner-approved generation supplements without replacing judge identity."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field


class ReferenceItem(BaseModel):
    id: str
    group: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimensions: list[int] = Field(min_length=2, max_length=2)
    owner_approved: bool


class ReferenceLibrary(BaseModel):
    schema_version: int
    character_id: str
    items: list[ReferenceItem]

    def item_bytes(self, root: Path, group: str, item_id: str) -> bytes:
        if self.schema_version != 1 or self.character_id != "rainbow_learning_buddy":
            raise ValueError("Unsupported reference library")
        matches = [item for item in self.items if item.group == group and item.id == item_id]
        if len(matches) != 1 or not matches[0].owner_approved:
            raise ValueError("Reference must be uniquely identified and owner approved")
        item = matches[0]
        path = (root / item.path).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Reference path escapes library")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.sha256:
            raise ValueError("Reference hash mismatch")
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format != "PNG" or list(image.size) != item.dimensions:
                raise ValueError("Reference image format or dimensions mismatch")
        return raw


def approved_supplements(manifest: Path, expression: str) -> tuple[bytes, bytes]:
    library = ReferenceLibrary.model_validate_json(manifest.read_text())
    return (
        library.item_bytes(manifest.parent, "expressions", expression),
        library.item_bytes(manifest.parent, "wardrobe", "astronaut"),
    )
