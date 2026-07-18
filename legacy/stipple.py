"""Stippling algorithms — all return list of (cx, cy, radius) in pixel coordinates."""

import numpy as np
from PIL import Image


def _luminance(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Return (gray float32 0-1, alpha float32 0-1) arrays from any PIL image."""
    gray = np.array(img.convert("L"), dtype=np.float32) / 255.0
    if img.mode in ("RGBA", "LA"):
        alpha = np.array(img.split()[-1], dtype=np.float32) / 255.0
    else:
        alpha = np.ones_like(gray)
    return gray, alpha


def grid_halftone(
    img: Image.Image,
    grid_spacing: int,
    min_radius: float,
    max_radius: float,
) -> list[tuple[float, float, float]]:
    """Regular grid: dot radius scales with darkness. Transparent areas are skipped."""
    gray, alpha = _luminance(img)
    h, w = gray.shape
    dots: list[tuple[float, float, float]] = []

    for row in range(0, h, grid_spacing):
        for col in range(0, w, grid_spacing):
            r2 = min(row + grid_spacing, h)
            c2 = min(col + grid_spacing, w)
            cell_gray = gray[row:r2, col:c2]
            cell_alpha = alpha[row:r2, col:c2]

            avg_alpha = float(cell_alpha.mean())
            if avg_alpha < 0.15:
                continue

            avg_brightness = float(cell_gray.mean())
            t = 1.0 - avg_brightness  # dark=1, light=0, weighted by alpha
            t *= avg_alpha

            radius = min_radius + t * (max_radius - min_radius)
            if radius <= 0:
                continue

            cx = col + (c2 - col) / 2.0
            cy = row + (r2 - row) / 2.0
            dots.append((cx, cy, radius))

    return dots


def random_stipple(
    img: Image.Image,
    dot_count: int,
    dot_radius: float,
    jitter: float = 0.0,
) -> list[tuple[float, float, float]]:
    """
    Density-based stipple: darker areas receive more dots, all dots are the same
    radius (matching a fixed pen tip). Optional jitter adds ±jitter*spacing noise.
    """
    gray, alpha = _luminance(img)
    h, w = gray.shape

    # Probability map: dark opaque pixels attract dots
    prob = (1.0 - gray) * alpha
    prob_sum = prob.sum()
    if prob_sum == 0:
        return []

    prob_flat = prob.ravel()
    prob_flat = prob_flat / prob_flat.sum()

    # Clamp dot_count to available non-zero pixels
    nonzero = int((prob_flat > 0).sum())
    dot_count = min(dot_count, nonzero)

    indices = np.random.choice(h * w, size=dot_count, replace=False, p=prob_flat)
    rows, cols = np.divmod(indices, w)

    dots: list[tuple[float, float, float]] = []
    rng = np.random.default_rng()
    for px, py in zip(cols.astype(float), rows.astype(float)):
        if jitter > 0:
            px += rng.uniform(-jitter, jitter)
            py += rng.uniform(-jitter, jitter)
        dots.append((px, py, dot_radius))

    return dots
