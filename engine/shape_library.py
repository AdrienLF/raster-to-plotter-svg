"""Custom dither-shape package validation and filesystem-backed library.

A "package" is a JSON manifest (name, state_count, bounds) plus 1..32 raw SVG
"states": state 0 is the light/highlight artwork, the last state the dark/
shadow artwork. A direct upload is a 1-state package (tone is carried by
scaling alone); the Cavalry bridge bakes 32 real states. This module turns
that untrusted bundle into a normalized ``DitherShape`` -- flattening curves
to polylines, keeping per-path stroke/fill colours, rejecting active/external
SVG content -- then persists validated packages atomically so they survive
restarts. Points are normalized centered in [-0.5, 0.5]^2 with a uniform
scale (max of bounds width/height) so multi-state artwork stays registered
and aspect is preserved.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import svgelements as se
from PIL import Image, ImageDraw

from .tessellation_library import (
    ALLOWED_SHAPES,
    MAX_PATHS,
    MAX_POINTS,
    MAX_SVG_BYTES,
    MAX_TOTAL_BYTES,
    PREVIEW_SIZE,
    PatternValidationError,
    _flatten_segments,
    _reject_forbidden_content,
    _validate_bounds,
    slugify_pattern_name,
    _write_flushed,
)

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
MAX_STATES = 32
# RDP tolerance in normalized shape units ([-0.5, 0.5]^2 span). Every cell
# stamps a full copy of the shape, so an over-flattened source curve (the
# tessellation FLATTEN_STEP is absolute source units, blind to shape size)
# multiplies into millions of output points. 0.002 of the span is under a
# third of a pixel even on the largest plausible stamp.
SIMPLIFY_TOLERANCE = 0.002

ShapeValidationError = PatternValidationError

Point = tuple[float, float]


@dataclass(frozen=True)
class ShapePath:
    """One polyline of a shape state, normalized centered in [-0.5, 0.5]^2."""

    points: tuple[Point, ...]
    closed: bool = False
    stroke: str | None = None   # "#rrggbb" or None
    fill: str | None = None


@dataclass(frozen=True)
class ShapeState:
    paths: tuple[ShapePath, ...]


@dataclass(frozen=True)
class DitherShape:
    id: str                     # "shape_dither_custom_<slug>"
    name: str
    source: str                 # "upload" | "cavalry"
    states: tuple[ShapeState, ...]   # index 0 = light/highlight .. last = dark/shadow

    def __post_init__(self) -> None:
        if not (1 <= len(self.states) <= MAX_STATES):
            raise ValueError(f"A shape needs 1..{MAX_STATES} states")


def slugify_shape_name(name: str) -> str:
    """Normalize an arbitrary shape name into a stable custom-shape ID."""
    tail = slugify_pattern_name(name).removeprefix("tessellation_custom_")
    return f"shape_dither_custom_{tail}"


# --------------------------------------------------------------------------
# SVG parsing (colour-preserving)
# --------------------------------------------------------------------------

def _colour_hex(colour) -> str | None:
    """svgelements Color -> "#rrggbb", or None when unset/'none'."""
    try:
        if colour is None or colour.value is None:
            return None
        return str(colour.hexrgb).lower()
    except Exception:
        return None


def parse_shape_state_svg(svg: str) -> list[tuple[list[Point], bool, str | None, str | None]]:
    """Parse and flatten one raw SVG state into raw (unnormalized) paths.

    Returns ``[(points, closed, stroke, fill), ...]`` in source coordinates;
    normalization happens later, once the package bounds are known.
    """
    _reject_forbidden_content(svg)
    try:
        parsed = se.SVG.parse(io.StringIO(svg))
    except Exception as exc:  # svgelements can raise a variety of errors
        raise ShapeValidationError(f"Could not parse SVG: {exc}") from exc

    raw_paths: list[tuple[list[Point], bool, str | None, str | None]] = []
    total_points = 0
    for element in parsed.elements():
        if not isinstance(element, ALLOWED_SHAPES):
            continue
        stroke = _colour_hex(getattr(element, "stroke", None))
        fill = _colour_hex(getattr(element, "fill", None))
        try:
            segments = element.segments(transformed=True)
        except Exception as exc:
            raise ShapeValidationError(f"Could not flatten SVG shape: {exc}") from exc
        for points, closed in _flatten_segments(segments):
            if len(points) < 2:
                continue
            raw_paths.append((points, closed, stroke, fill))
            total_points += len(points)
            if len(raw_paths) > MAX_PATHS:
                raise ShapeValidationError(f"State exceeds {MAX_PATHS} paths")
            if total_points > MAX_POINTS:
                raise ShapeValidationError(f"State exceeds {MAX_POINTS} points")

    if not raw_paths:
        raise ShapeValidationError("State SVG contains no drawable paths")
    return raw_paths


def _simplify_points(points, tol: float = SIMPLIFY_TOLERANCE):
    """Ramer-Douglas-Peucker on a normalized polyline (iterative)."""
    n = len(points)
    if n <= 2 or tol <= 0:
        return list(points)
    pts = np.asarray(points, dtype=float)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[a + 1:b]
        dx, dy = pts[b] - pts[a]
        norm = math.hypot(dx, dy)
        if norm < 1e-12:
            # Degenerate chord (e.g. a closed ring whose ends coincide):
            # fall back to distance from the shared endpoint.
            dist = np.hypot(seg[:, 0] - pts[a][0], seg[:, 1] - pts[a][1])
        else:
            dist = np.abs((seg[:, 0] - pts[a][0]) * dy
                          - (seg[:, 1] - pts[a][1]) * dx) / norm
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack.append((a, m))
            stack.append((m, b))
    return [tuple(p) for p, k in zip(points, keep) if k]


def _make_shape_path(points, closed: bool, stroke: str | None,
                     fill: str | None) -> ShapePath:
    return ShapePath(tuple(_simplify_points(points)),
                     closed=closed, stroke=stroke, fill=fill)


# --------------------------------------------------------------------------
# Package validation
# --------------------------------------------------------------------------

def validate_shape_package(manifest: dict, states: list[str],
                           source: str = "upload") -> DitherShape:
    """Validate a manifest + raw SVG states and return a normalized
    DitherShape, or raise ShapeValidationError."""
    if not isinstance(manifest, dict):
        raise ShapeValidationError("manifest must be an object")

    format_version = manifest.get("format_version")
    if isinstance(format_version, bool) or format_version != FORMAT_VERSION:
        raise ShapeValidationError(f"Unsupported format_version {format_version!r}")

    name = manifest.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
        raise ShapeValidationError("Shape name must be 1-80 visible characters")
    name = name.strip()
    shape_id = slugify_shape_name(name)

    state_count = manifest.get("state_count")
    if isinstance(state_count, bool) or not isinstance(state_count, int) \
            or not (1 <= state_count <= MAX_STATES):
        raise ShapeValidationError(f"state_count must be an integer in 1..{MAX_STATES}")
    if len(states) != state_count:
        raise ShapeValidationError(
            f"Exactly {state_count} states are required, got {len(states)}")

    parsed_states = []
    total_bytes = 0
    for index, svg_text in enumerate(states):
        raw_bytes = svg_text.encode("utf-8") if isinstance(svg_text, str) else bytes(svg_text)
        if len(raw_bytes) > MAX_SVG_BYTES:
            raise ShapeValidationError(f"State {index} exceeds {MAX_SVG_BYTES} bytes")
        total_bytes += len(raw_bytes)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ShapeValidationError(f"Package exceeds {MAX_TOTAL_BYTES} total bytes")
        parsed_states.append(parse_shape_state_svg(
            svg_text if isinstance(svg_text, str) else raw_bytes.decode("utf-8")))

    raw_bounds = manifest.get("bounds")
    if raw_bounds is not None:
        minx, miny, maxx, maxy = _validate_bounds(raw_bounds)
    else:
        xs = [x for state in parsed_states for pts, *_ in state for x, _ in pts]
        ys = [y for state in parsed_states for pts, *_ in state for _, y in pts]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)

    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    span = max(maxx - minx, maxy - miny)
    if not math.isfinite(span) or span <= 0:
        raise ShapeValidationError("Shape bounds must be finite with positive extent")

    shape_states = tuple(
        ShapeState(tuple(
            _make_shape_path([((x - cx) / span, (y - cy) / span) for x, y in points],
                             closed, stroke, fill)
            for points, closed, stroke, fill in state
        ))
        for state in parsed_states
    )

    try:
        return DitherShape(id=shape_id, name=name, source=source, states=shape_states)
    except ValueError as exc:
        raise ShapeValidationError(str(exc)) from exc


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def _shape_to_json(shape: DitherShape, updated_at: str) -> dict:
    return {
        "id": shape.id,
        "name": shape.name,
        "source": shape.source,
        "states": [
            {"paths": [{"points": [list(p) for p in path.points],
                        "closed": path.closed,
                        "stroke": path.stroke,
                        "fill": path.fill}
                       for path in state.paths]}
            for state in shape.states
        ],
        "updated_at": updated_at,
    }


def _shape_from_json(data: dict) -> DitherShape:
    # Re-simplify on load so packages persisted before SIMPLIFY_TOLERANCE
    # existed are repaired transparently (a no-op for already-simple shapes).
    states = tuple(
        ShapeState(tuple(
            _make_shape_path([(float(x), float(y)) for x, y in path["points"]],
                             bool(path["closed"]),
                             path.get("stroke"), path.get("fill"))
            for path in state["paths"]
        ))
        for state in data["states"]
    )
    return DitherShape(id=str(data["id"]), name=str(data["name"]),
                       source=str(data["source"]), states=states)


def _render_preview(shape: DitherShape) -> Image.Image:
    """105x148 preview: the shape stamped over a vertical light-to-dark
    tone ramp -- growing (and stepping through states) top to bottom."""
    width, height = PREVIEW_SIZE
    canvas = Image.new("RGB", PREVIEW_SIZE, "white")
    draw = ImageDraw.Draw(canvas)
    cols, rows = 5, 7
    cell = width / cols
    y0 = (height - rows * cell) / 2
    n_states = len(shape.states)
    for row in range(rows):
        tone = row / (rows - 1)                     # 0 = light .. 1 = dark
        scale = (0.15 + 0.8 * tone) * cell
        state = shape.states[round(tone * (n_states - 1))]
        for col in range(cols):
            ox, oy = (col + 0.5) * cell, y0 + (row + 0.5) * cell
            for path in state.paths:
                pts = [(ox + x * scale, oy + y * scale) for x, y in path.points]
                if len(pts) < 2:
                    continue
                if path.closed:
                    pts.append(pts[0])
                    if path.fill:
                        draw.polygon(pts, fill=path.fill)
                outline = path.stroke or (None if path.fill else "black")
                if outline:
                    draw.line(pts, fill=outline, width=1)
    return canvas


class ShapeLibrary:
    """Filesystem-backed store of validated custom dither shapes.

    Each entry lives in ``root/<shape_id>/`` holding ``shape.json`` and
    ``preview.png``. Installation stages the new entry in a sibling directory
    and swaps it in atomically, so an existing package is never left
    half-replaced.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def install(self, manifest: dict, states: list[str],
                source: str = "upload") -> DitherShape:
        shape = validate_shape_package(manifest, states, source=source)
        updated_at = datetime.now(timezone.utc).isoformat()
        staging = self.root / f"{shape.id}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            payload = json.dumps(_shape_to_json(shape, updated_at),
                                 separators=(",", ":")).encode("utf-8")
            _write_flushed(staging / "shape.json", payload)
            preview_buffer = io.BytesIO()
            _render_preview(shape).save(preview_buffer, format="PNG")
            _write_flushed(staging / "preview.png", preview_buffer.getvalue())
            self._atomic_replace(staging, self.root / shape.id)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return shape

    def _atomic_replace(self, staging: Path, target: Path) -> None:
        backup = target.with_name(target.name + ".backup")
        if backup.exists():
            shutil.rmtree(backup)
        had_previous = target.exists()
        if had_previous:
            target.rename(backup)
        try:
            staging.rename(target)
        except BaseException:
            if had_previous:
                backup.rename(target)
            raise
        if had_previous:
            shutil.rmtree(backup, ignore_errors=True)

    def _entry_dirs(self) -> list[Path]:
        return sorted(
            entry for entry in self.root.iterdir()
            if entry.is_dir() and (entry / "shape.json").is_file()
        )

    def _load_entry(self, entry: Path) -> DitherShape:
        data = json.loads((entry / "shape.json").read_text("utf-8"))
        if data.get("id") != entry.name:
            raise ShapeValidationError(
                f"Entry {entry.name!r} declares mismatched id {data.get('id')!r}")
        return _shape_from_json(data)

    def get(self, shape_id: str) -> DitherShape:
        entry = self.root / shape_id
        if not (entry / "shape.json").is_file():
            raise KeyError(f"Unknown dither shape {shape_id!r}")
        return self._load_entry(entry)

    def load_all(self) -> list[DitherShape]:
        shapes = []
        for entry in self._entry_dirs():
            try:
                shapes.append(self._load_entry(entry))
            except Exception:
                logger.exception("Skipping invalid shape package %s", entry)
        return shapes

    def list(self) -> list[dict]:
        records = []
        for entry in self._entry_dirs():
            try:
                data = json.loads((entry / "shape.json").read_text("utf-8"))
                if data.get("id") != entry.name:
                    raise ShapeValidationError("mismatched id")
                records.append({"id": data["id"], "name": data["name"],
                                "source": data["source"],
                                "states": len(data["states"]),
                                "updated_at": data["updated_at"]})
            except Exception:
                logger.exception("Skipping invalid shape package %s", entry)
        return sorted(records, key=lambda record: record["id"])
