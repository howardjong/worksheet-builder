"""Bind pedagogical approval to the exact effective activity package."""

import hashlib
import json

from adapt.schema import AdaptedActivityModel


def package_hash(worksheets: list[AdaptedActivityModel]) -> str:
    serialized = json.dumps([ws.model_dump(mode="json") for ws in worksheets], sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()
