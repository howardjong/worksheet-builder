"""OCR engine integration — PaddleOCR primary, Tesseract fallback."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from extract.schema import OCRBlock, OCRResult

logger = logging.getLogger(__name__)


def extract_text(image_path: str, engine: str = "paddleocr") -> OCRResult:
    """Run OCR on preprocessed image.

    Returns text blocks with bounding boxes and confidence scores.
    Engine: "paddleocr" (primary) or "tesseract" (fallback).
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    if engine == "paddleocr":
        return _run_paddleocr(image_path)
    elif engine == "tesseract":
        return _run_tesseract(image_path)
    else:
        raise ValueError(f"Unknown OCR engine: {engine}")


def extract_text_with_fallback(image_path: str) -> OCRResult:
    """Try PaddleOCR first, fall back to Tesseract if unavailable."""
    try:
        return extract_text(image_path, engine="paddleocr")
    except ImportError:
        logger.warning("PaddleOCR not available, falling back to Tesseract")
        return extract_text(image_path, engine="tesseract")


def _run_paddleocr(image_path: str) -> OCRResult:
    """Run PaddleOCR and normalize output to OCRResult."""
    # Suppress noisy paddle logging
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    from paddleocr import PaddleOCR

    ocr = PaddleOCR(lang="en")
    raw: list[Any] = ocr.ocr(image_path)

    blocks: list[OCRBlock] = []
    all_text_parts: list[str] = []

    if not raw:
        return OCRResult(blocks=[], engine="paddleocr", raw_text="")

    page = raw[0]

    # PaddleOCR v3 returns a dict with rec_texts, rec_scores, rec_polys
    if isinstance(page, dict):
        texts: list[str] = page.get("rec_texts", [])
        scores: list[float] = page.get("rec_scores", [])
        polys: list[Any] = page.get("rec_polys", [])

        for i in range(len(texts)):
            text = texts[i].strip()
            if not text:
                continue

            score = float(scores[i]) if i < len(scores) else 0.0
            poly = polys[i] if i < len(polys) else None
            bbox = _poly_to_bbox(poly)

            blocks.append(OCRBlock(text=text, bbox=bbox, confidence=score))
            all_text_parts.append(text)

    # PaddleOCR v2 returns list of [bbox, (text, conf)]
    elif isinstance(page, list):
        for line in page:
            if not line or len(line) < 2:
                continue
            poly = line[0]
            text_conf = line[1]
            if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                text = str(text_conf[0]).strip()
                conf = float(text_conf[1])
            else:
                continue

            if not text:
                continue

            bbox = _poly_to_bbox(poly)
            blocks.append(OCRBlock(text=text, bbox=bbox, confidence=conf))
            all_text_parts.append(text)

    # Sort blocks top-to-bottom, left-to-right
    blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

    return OCRResult(
        blocks=blocks,
        engine="paddleocr",
        raw_text="\n".join(all_text_parts),
    )


def _run_tesseract(image_path: str) -> OCRResult:
    """Run Tesseract OCR and normalize output to OCRResult."""
    import pytesseract
    from PIL import Image

    img = Image.open(image_path)
    data: dict[str, list[Any]] = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DICT
    )

    blocks: list[OCRBlock] = []
    all_text_parts: list[str] = []

    n = len(data["text"])
    for i in range(n):
        text = str(data["text"][i]).strip()
        if not text:
            continue

        conf = float(data["conf"][i])
        if conf < 0:
            conf = 0.0
        else:
            conf = conf / 100.0  # Tesseract returns 0-100

        x = float(data["left"][i])
        y = float(data["top"][i])
        w = float(data["width"][i])
        h = float(data["height"][i])
        bbox = (x, y, x + w, y + h)

        blocks.append(OCRBlock(text=text, bbox=bbox, confidence=conf))
        all_text_parts.append(text)

    # Sort blocks top-to-bottom, left-to-right
    blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

    return OCRResult(
        blocks=blocks,
        engine="tesseract",
        raw_text="\n".join(all_text_parts),
    )


def _poly_to_bbox(poly: Any) -> tuple[float, float, float, float]:
    """Convert a 4-point polygon to axis-aligned bounding box (x0, y0, x1, y1)."""
    if poly is None:
        return (0.0, 0.0, 0.0, 0.0)

    arr = np.array(poly, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[0] >= 4:
        x0 = float(arr[:, 0].min())
        y0 = float(arr[:, 1].min())
        x1 = float(arr[:, 0].max())
        y1 = float(arr[:, 1].max())
        return (x0, y0, x1, y1)

    return (0.0, 0.0, 0.0, 0.0)
