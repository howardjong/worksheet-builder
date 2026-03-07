"""Tests for capture/preprocess.py and capture/store.py."""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from capture.preprocess import preprocess_page
from capture.store import derive_archival_pdf, store_master

Image = np.ndarray[Any, Any]


# --- Fixtures ---


def _make_worksheet_image(
    width: int = 2550,
    height: int = 3300,
    skew_degrees: float = 0.0,
    add_perspective: bool = False,
    add_noise: bool = False,
    add_background: bool = False,
) -> Image:
    """Generate a synthetic worksheet image for testing.

    Creates a white page with text-like black rectangles, optional skew,
    perspective distortion, noise, and desk background.
    """
    # White page with content
    page: Image = np.ones((height, width, 3), dtype=np.uint8) * 255

    # Title bar
    cv2.rectangle(page, (200, 100), (width - 200, 200), (0, 0, 0), -1)

    # Simulated text lines
    for i in range(10):
        y = 350 + i * 120
        cv2.rectangle(page, (200, y), (width - 300, y + 20), (40, 40, 40), -1)
        cv2.rectangle(page, (200, y + 40), (width - 500, y + 60), (60, 60, 60), -1)

    # Word list box
    cv2.rectangle(page, (200, 1800), (1000, 2400), (0, 0, 0), 3)
    for i in range(5):
        y = 1850 + i * 100
        cv2.rectangle(page, (250, y), (900, y + 30), (50, 50, 50), -1)

    # Apply skew
    if abs(skew_degrees) > 0.01:
        center = (width // 2, height // 2)
        matrix = cv2.getRotationMatrix2D(center, skew_degrees, 1.0)
        page = cv2.warpAffine(page, matrix, (width, height), borderValue=(255, 255, 255))

    # Apply perspective distortion
    if add_perspective:
        src_pts = np.array(
            [[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32
        )
        # Simulate phone at slight angle
        dst_pts = np.array(
            [
                [width * 0.05, height * 0.03],
                [width * 0.92, height * 0.01],
                [width * 0.95, height * 0.97],
                [width * 0.02, height * 0.99],
            ],
            dtype=np.float32,
        )
        m = cv2.getPerspectiveTransform(src_pts, dst_pts)
        page = cv2.warpPerspective(page, m, (width, height), borderValue=(200, 200, 200))

    # Add desk background
    if add_background:
        bg: Image = np.ones((height + 400, width + 400, 3), dtype=np.uint8) * 160
        # Add some texture to background
        rng = np.random.RandomState(42)
        noise_bg = np.asarray(rng.randint(0, 30, bg.shape), dtype=np.uint8)
        bg = cv2.add(bg, noise_bg)
        # Place page on background
        y_off, x_off = 200, 200
        bg[y_off : y_off + height, x_off : x_off + width] = page
        page = bg

    # Add noise
    if add_noise:
        rng2 = np.random.RandomState(42)
        noise = np.asarray(rng2.randint(0, 15, page.shape), dtype=np.uint8)
        page = cv2.add(page, noise)

    return page


@pytest.fixture
def tmp_dir() -> Generator[str, None, None]:
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def clean_scan(tmp_dir: str) -> str:
    """A clean flatbed scan (no skew, no perspective)."""
    path = os.path.join(tmp_dir, "clean_scan.png")
    img = _make_worksheet_image()
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def skewed_photo(tmp_dir: str) -> str:
    """A phone photo with 5-degree skew and slight noise."""
    path = os.path.join(tmp_dir, "skewed.png")
    img = _make_worksheet_image(skew_degrees=5.0, add_noise=True)
    cv2.imwrite(path, img)
    return path


@pytest.fixture
def perspective_photo(tmp_dir: str) -> str:
    """A phone photo with perspective distortion and background."""
    path = os.path.join(tmp_dir, "perspective.png")
    img = _make_worksheet_image(add_perspective=True, add_background=True, add_noise=True)
    cv2.imwrite(path, img)
    return path


# --- Preprocessing Tests ---


class TestPreprocessPage:
    def test_clean_scan(self, clean_scan: str, tmp_dir: str) -> None:
        """Clean flatbed scan produces normalized output."""
        out = os.path.join(tmp_dir, "out", "clean.png")
        result = preprocess_page(clean_scan, out)

        assert os.path.exists(out)
        assert result.width > 0
        assert result.height > 0
        assert len(result.image_hash) == 64  # SHA-256 hex
        assert abs(result.skew_angle) < 1.0

    def test_skewed_photo(self, skewed_photo: str, tmp_dir: str) -> None:
        """Skewed phone photo is deskewed."""
        out = os.path.join(tmp_dir, "out", "deskewed.png")
        result = preprocess_page(skewed_photo, out)

        assert os.path.exists(out)
        assert result.width > 0
        assert result.height > 0
        # The detected skew should be roughly 5 degrees
        assert abs(result.skew_angle) > 1.0

    def test_perspective_photo(self, perspective_photo: str, tmp_dir: str) -> None:
        """Photo with perspective distortion and background is corrected."""
        out = os.path.join(tmp_dir, "out", "warped.png")
        result = preprocess_page(perspective_photo, out)

        assert os.path.exists(out)
        assert result.width > 0
        assert result.height > 0

    def test_deterministic(self, clean_scan: str, tmp_dir: str) -> None:
        """Same input produces same output."""
        out1 = os.path.join(tmp_dir, "out1.png")
        out2 = os.path.join(tmp_dir, "out2.png")

        r1 = preprocess_page(clean_scan, out1)
        r2 = preprocess_page(clean_scan, out2)

        assert r1.image_hash == r2.image_hash
        assert r1.width == r2.width
        assert r1.height == r2.height
        assert r1.skew_angle == r2.skew_angle

        # Output images should be identical
        img1 = cv2.imread(out1)
        img2 = cv2.imread(out2)
        assert img1 is not None
        assert img2 is not None
        assert np.array_equal(img1, img2)

    def test_missing_file_raises(self, tmp_dir: str) -> None:
        """Missing input file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            preprocess_page("/nonexistent/image.png", os.path.join(tmp_dir, "out.png"))

    def test_creates_output_directory(self, clean_scan: str, tmp_dir: str) -> None:
        """Output directory is created if it doesn't exist."""
        out = os.path.join(tmp_dir, "nested", "deep", "output.png")
        result = preprocess_page(clean_scan, out)
        assert os.path.exists(out)
        assert result.output_path == out


# --- Store Tests ---


class TestStoreMaster:
    def test_store_creates_hash_named_copy(self, clean_scan: str, tmp_dir: str) -> None:
        """Master is stored with hash-based filename."""
        masters = os.path.join(tmp_dir, "masters")
        record = store_master(clean_scan, masters)

        assert os.path.exists(record.master_path)
        assert record.image_hash in record.master_path
        assert record.width > 0
        assert record.height > 0

    def test_store_idempotent(self, clean_scan: str, tmp_dir: str) -> None:
        """Storing the same image twice produces same result, no duplicate."""
        masters = os.path.join(tmp_dir, "masters")
        r1 = store_master(clean_scan, masters)
        r2 = store_master(clean_scan, masters)

        assert r1.image_hash == r2.image_hash
        assert r1.master_path == r2.master_path
        # Only one file in masters dir
        files = [f for f in os.listdir(masters) if not f.startswith(".")]
        assert len(files) == 1

    def test_store_missing_file_raises(self, tmp_dir: str) -> None:
        """Missing input file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            store_master("/nonexistent/image.png", os.path.join(tmp_dir, "masters"))


class TestArchivalPdf:
    def test_creates_pdf(self, clean_scan: str, tmp_dir: str) -> None:
        """Archival PDF is created from master image."""
        masters = os.path.join(tmp_dir, "masters")
        record = store_master(clean_scan, masters)

        pdf_path = os.path.join(tmp_dir, "archival.pdf")
        result = derive_archival_pdf(record.master_path, pdf_path)

        assert os.path.exists(result)
        assert Path(result).stat().st_size > 0

    def test_pdf_missing_master_raises(self, tmp_dir: str) -> None:
        """Missing master image raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            derive_archival_pdf("/nonexistent/master.png", os.path.join(tmp_dir, "out.pdf"))
