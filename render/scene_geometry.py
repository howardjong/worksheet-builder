"""Shared scene size contract used by the visual gate and PDF composition."""

SCENE_HEIGHT = 224.0
PAGE_AREA = 612.0 * 792.0
CONTENT_WIDTH = 504.0


def scene_size(width: int, height: int) -> tuple[float, float]:
    scale = min(CONTENT_WIDTH / width, SCENE_HEIGHT / height)
    return width * scale, height * scale


def meaningful_page_fraction(
    width: int, height: int, bounds: tuple[float, float, float, float]
) -> float:
    draw_width, draw_height = scene_size(width, height)
    x0, y0, x1, y1 = bounds
    return draw_width * draw_height * (x1 - x0) * (y1 - y0) / PAGE_AREA
