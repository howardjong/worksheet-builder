"""Image preprocessing pipeline for worksheet photos and scans."""

import hashlib
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from capture.schema import PreprocessResult

# Use Any for numpy array types to avoid strict dtype mismatches with OpenCV
Image = np.ndarray[Any, Any]


def preprocess_page(image_path: str, output_path: str) -> PreprocessResult:
    """Full preprocessing pipeline.

    Load, detect page, warp, deskew, denoise, normalize, save.
    """
    img = _load_image(image_path)
    original_hash = _hash_image(img)

    page, perspective_corrected = _detect_and_warp_page(img)
    page, skew_angle = _deskew(page)
    page = _denoise(page)
    page = _normalize_contrast(page)
    page = _trim_borders(page)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, page)

    h, w = page.shape[:2]
    return PreprocessResult(
        image_hash=original_hash,
        original_path=image_path,
        output_path=output_path,
        width=w,
        height=h,
        skew_angle=skew_angle,
        perspective_corrected=perspective_corrected,
    )


def _load_image(path: str) -> Image:
    """Load image from disk. Raises FileNotFoundError if missing."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return img


def _hash_image(img: Image) -> str:
    """SHA-256 hash of raw image bytes."""
    return hashlib.sha256(img.tobytes()).hexdigest()


def _detect_and_warp_page(img: Image) -> tuple[Image, bool]:
    """Detect the page quadrilateral and perspective-warp to rectangular.

    Returns (warped_image, True) if a page was detected and warped,
    or (original_image, False) if no clear page boundary was found.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # Dilate to close gaps in edge contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img, False

    # Find the largest contour that approximates a quadrilateral
    img_area = img.shape[0] * img.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contour)
        if area < img_area * 0.2:
            break

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

        if len(approx) == 4:
            return _four_point_warp(img, approx.reshape(4, 2)), True

    return img, False


def _four_point_warp(img: Image, pts: Image) -> Image:
    """Perspective-warp a quadrilateral to a rectangle."""
    rect = _order_points(pts.astype(np.float32))
    tl, tr, br, bl = rect

    width_top = float(np.linalg.norm(tr - tl))
    width_bot = float(np.linalg.norm(br - bl))
    max_width = int(max(width_top, width_bot))

    height_left = float(np.linalg.norm(bl - tl))
    height_right = float(np.linalg.norm(br - tr))
    max_height = int(max(height_left, height_right))

    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped: Image = cv2.warpPerspective(img, matrix, (max_width, max_height))
    return warped


def _order_points(pts: Image) -> Image:
    """Order points as: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def _deskew(img: Image) -> tuple[Image, float]:
    """Detect and correct skew using Hough line transform.

    Returns (deskewed_image, skew_angle_degrees).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)

    if lines is None:
        return img, 0.0

    # Collect angles of near-horizontal lines
    angles: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) < 15:  # Only near-horizontal lines
            angles.append(angle)

    if not angles:
        return img, 0.0

    median_angle = float(np.median(angles))

    if abs(median_angle) < 0.1:
        return img, 0.0

    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated: Image = cv2.warpAffine(
        img, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, median_angle


def _denoise(img: Image) -> Image:
    """Apply non-local means denoising."""
    result: Image = cv2.fastNlMeansDenoisingColored(img, None, 7, 7, 7, 21)
    return result


def _normalize_contrast(img: Image) -> Image:
    """Apply CLAHE contrast normalization to the L channel."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_normalized = clahe.apply(l_channel)

    merged = cv2.merge([l_normalized, a_channel, b_channel])
    result: Image = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    return result


def _trim_borders(img: Image, threshold: int = 240) -> Image:
    """Trim near-white borders from the page image."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)

    coords = cv2.findNonZero(binary)
    if coords is None:
        return img

    x, y, w, h = cv2.boundingRect(coords)

    # Add small padding
    pad = 10
    x = max(0, x - pad)
    y = max(0, y - pad)
    w = min(img.shape[1] - x, w + 2 * pad)
    h = min(img.shape[0] - y, h + 2 * pad)

    return img[y : y + h, x : x + w]
