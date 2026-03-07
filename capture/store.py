"""Master image storage and archival PDF generation."""

import hashlib
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from capture.schema import MasterRecord


def store_master(image_path: str, masters_dir: str) -> MasterRecord:
    """Store original image with hash-based filename for permanence.

    Copies the original image to masters_dir with a content-hash filename,
    preserving the original extension. Idempotent — skips if already stored.
    """
    src = Path(image_path)
    if not src.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image_bytes = src.read_bytes()
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    masters = Path(masters_dir)
    masters.mkdir(parents=True, exist_ok=True)

    dest = masters / f"{image_hash}{src.suffix.lower()}"
    if not dest.exists():
        shutil.copy2(str(src), str(dest))

    from PIL import Image

    with Image.open(str(dest)) as img:
        width, height = img.size

    return MasterRecord(
        original_path=str(src),
        master_path=str(dest),
        image_hash=image_hash,
        width=width,
        height=height,
    )


def derive_archival_pdf(master_path: str, output_path: str) -> str:
    """Generate a PDF wrapping the master image for archival storage.

    This is NOT a searchable/OCR PDF — OCR happens later in the extract stage.
    True PDF/A compliance requires ocrmypdf or similar post-OCR tooling
    and is a post-MVP concern.
    """
    src = Path(master_path)
    if not src.exists():
        raise FileNotFoundError(f"Master image not found: {master_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    with Image.open(str(src)) as img:
        img_width, img_height = img.size

    page_width, page_height = letter

    # Scale image to fit letter page with margins
    margin = 36  # 0.5 inch
    available_w = page_width - 2 * margin
    available_h = page_height - 2 * margin

    scale = min(available_w / img_width, available_h / img_height)
    draw_w = img_width * scale
    draw_h = img_height * scale

    x = margin + (available_w - draw_w) / 2
    y = margin + (available_h - draw_h) / 2

    c = canvas.Canvas(output_path, pagesize=letter)
    c.drawImage(str(src), x, y, width=draw_w, height=draw_h)
    c.save()

    return output_path
