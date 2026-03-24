"""Tests for OCR runtime helpers."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from extract import ocr


class _FakePaddleOCR:
    instances = 0

    def __init__(self, lang: str) -> None:
        type(self).instances += 1
        self.lang = lang


def test_get_paddle_ocr_reuses_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paddleocr_module = ModuleType("paddleocr")
    setattr(paddleocr_module, "PaddleOCR", _FakePaddleOCR)

    monkeypatch.setitem(sys.modules, "paddleocr", paddleocr_module)
    ocr._get_paddle_ocr.cache_clear()
    _FakePaddleOCR.instances = 0

    first = ocr._get_paddle_ocr()
    second = ocr._get_paddle_ocr()

    assert first is second
    assert _FakePaddleOCR.instances == 1
