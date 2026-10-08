"""Bounded, ordered concurrency for independent network work, never PDF drawing."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import TypeVar

_T = TypeVar("_T")
_R = TypeVar("_R")


def image_workers() -> int:
    try:
        return min(4, max(1, int(os.environ.get("WORKSHEET_IMAGE_CONCURRENCY", "3"))))
    except ValueError:
        return 3


def ordered_parallel_map(function: Callable[[_T], _R], values: Sequence[_T]) -> list[_R]:
    """Propagate run telemetry; preserve source order regardless of completion order."""
    if len(values) < 2 or image_workers() == 1:
        return [function(value) for value in values]
    with ThreadPoolExecutor(max_workers=min(image_workers(), len(values))) as executor:
        futures = [executor.submit(copy_context().run, function, value) for value in values]
        return [future.result() for future in futures]
