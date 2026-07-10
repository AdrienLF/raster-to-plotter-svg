"""End-to-end pipeline workloads over the real server and engine interfaces.

Every workload here calls production code paths (``web.server.svg_to_polylines``,
``_reorder``, ``_estimate_polylines``, ``engine.composition.compose_visible_svg``,
``engine.svg_io.split_svg_by_pen``) so a regression in any of them shows up.
"""
from __future__ import annotations

from ..workload import Workload, WorkloadCase, WorkloadOutput, register, stable_checksum

DENSE_CIRCLE_COUNT = 8000
PAGE_MM = (420.0, 297.0)
_FLATTEN_SETTINGS = {"curve_step_mm": 0.5, "reordering": "none"}


def _dense_circle_svg() -> str:
    """One <g> of exactly 8000 deterministic circles, > 400 KiB of markup."""
    width, height = PAGE_MM
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" '
        f'height="{height}mm" viewBox="0 0 {width} {height}">',
        '<g stroke="#000000" fill="none" stroke-width="0.3">',
    ]
    cols = 100
    for i in range(DENSE_CIRCLE_COUNT):
        col, row = i % cols, i // cols
        cx = 5.0 + col * (width - 10.0) / cols
        cy = 5.0 + row * 3.5
        r = 1.0 + (i % 7) * 0.25
        parts.append(f'<circle cx="{cx:.6f}" cy="{cy:.6f}" r="{r:.6f}"/>')
    parts.append("</g></svg>")
    return "".join(parts)


# -- shared fixtures ---------------------------------------------------------

def _svg_case() -> WorkloadCase:
    svg = _dense_circle_svg()
    return WorkloadCase(value=svg, fixture_checksum=stable_checksum(svg))


def _polyline_case() -> WorkloadCase:
    from web.server import svg_to_polylines

    svg = _dense_circle_svg()
    polylines = svg_to_polylines(svg.encode(), _FLATTEN_SETTINGS, respect_stop=False)
    return WorkloadCase(value=polylines, fixture_checksum=stable_checksum(len(polylines)))


# -- svg flatten -------------------------------------------------------------

def _svg_run(case: WorkloadCase) -> WorkloadOutput:
    from web.server import svg_to_polylines

    svg = case.value
    polylines = svg_to_polylines(svg.encode(), _FLATTEN_SETTINGS, respect_stop=False)
    return WorkloadOutput(
        {"paths": len(polylines), "svg_bytes": len(svg.encode())},
        stable_checksum(len(polylines)),
    )


def _svg_validate(output: WorkloadOutput) -> None:
    if output.metrics["paths"] != DENSE_CIRCLE_COUNT:
        raise ValueError(f"expected {DENSE_CIRCLE_COUNT} paths, got {output.metrics['paths']}")
    if output.metrics["svg_bytes"] <= 400_000:
        raise ValueError(f"fixture SVG too small: {output.metrics['svg_bytes']} bytes")


# -- reorder -----------------------------------------------------------------

def _reorder_run(case: WorkloadCase) -> WorkloadOutput:
    from web.server import _reorder

    ordered = _reorder(case.value, "nearest")
    return WorkloadOutput(
        {"paths": len(ordered)},
        stable_checksum([len(ordered), len(ordered[0]) if ordered else 0]),
    )


def _reorder_validate(output: WorkloadOutput) -> None:
    if output.metrics["paths"] != DENSE_CIRCLE_COUNT:
        raise ValueError(f"reorder dropped paths: {output.metrics['paths']}")


# -- estimate ----------------------------------------------------------------

def _estimate_run(case: WorkloadCase) -> WorkloadOutput:
    from web.server import _estimate_polylines

    estimate = _estimate_polylines(case.value, {"copies": 1})
    seconds = float(estimate.get("seconds", estimate.get("duration", 0.0)) or 0.0)
    return WorkloadOutput(
        {"paths": len(case.value), "estimate_keys": len(estimate)},
        stable_checksum([len(case.value), round(seconds, 3)]),
    )


def _estimate_validate(output: WorkloadOutput) -> None:
    if output.metrics["paths"] != DENSE_CIRCLE_COUNT:
        raise ValueError("estimate saw wrong path count")


# -- compose + split ---------------------------------------------------------

def _compose_case() -> WorkloadCase:
    from engine.composition import Composition, CompositionLayer

    svg = _dense_circle_svg()
    comp = Composition()
    comp.layers.append(CompositionLayer(
        id="dense", name="Dense", kind="svg", visible=True,
        width=PAGE_MM[0], height=PAGE_MM[1], svg=svg,
    ))
    return WorkloadCase(value=comp, fixture_checksum=stable_checksum(svg))


def _compose_run(case: WorkloadCase) -> WorkloadOutput:
    from engine.composition import compose_visible_svg

    composed = compose_visible_svg(case.value)
    return WorkloadOutput(
        {"svg_bytes": len(composed.encode())},
        stable_checksum(len(composed)),
    )


def _compose_validate(output: WorkloadOutput) -> None:
    if output.metrics["svg_bytes"] <= 0:
        raise ValueError("composed SVG is empty")


def _split_case() -> WorkloadCase:
    from engine.composition import Composition, CompositionLayer, compose_visible_svg

    svg = _dense_circle_svg()
    comp = Composition()
    comp.layers.append(CompositionLayer(
        id="dense", name="Dense", kind="svg", visible=True,
        width=PAGE_MM[0], height=PAGE_MM[1], svg=svg,
    ))
    composed = compose_visible_svg(comp)
    return WorkloadCase(value=composed, fixture_checksum=stable_checksum(len(composed)))


def _split_run(case: WorkloadCase) -> WorkloadOutput:
    from engine.svg_io import split_svg_by_pen

    pens = split_svg_by_pen(case.value.encode(), [("Black", "#000000")])
    return WorkloadOutput(
        {"pens": len(pens), "shapes": int(sum(p.get("shapes", 0) for p in pens))},
        stable_checksum([len(pens), sum(p.get("shapes", 0) for p in pens)]),
    )


def _split_validate(output: WorkloadOutput) -> None:
    if output.metrics["pens"] < 1:
        raise ValueError("split produced no pens")


def register_pipeline() -> None:
    register(Workload(
        id="pipeline.svg_dense_circles", version=1, category="pipeline",
        fixture_id="dense-circles", quick=True, backends=("cpu",),
        warning_floor_ms=5.0,
        metadata={"dtype": "none", "problem_size": f"circles={DENSE_CIRCLE_COUNT}",
                  "tile": 0, "cold_group": ""},
        prepare=_svg_case, run=_svg_run, validate=_svg_validate,
    ))
    register(Workload(
        id="pipeline.reorder_nearest", version=1, category="pipeline",
        fixture_id="dense-circles", quick=True, backends=("cpu",),
        warning_floor_ms=5.0,
        metadata={"dtype": "none", "problem_size": f"paths={DENSE_CIRCLE_COUNT}",
                  "tile": 0, "cold_group": ""},
        prepare=_polyline_case, run=_reorder_run, validate=_reorder_validate,
    ))
    register(Workload(
        id="pipeline.estimate_plot", version=1, category="pipeline",
        fixture_id="dense-circles", quick=True, backends=("cpu",),
        warning_floor_ms=2.0,
        metadata={"dtype": "none", "problem_size": f"paths={DENSE_CIRCLE_COUNT}",
                  "tile": 0, "cold_group": ""},
        prepare=_polyline_case, run=_estimate_run, validate=_estimate_validate,
    ))
    register(Workload(
        id="pipeline.compose_visible", version=1, category="pipeline",
        fixture_id="dense-circles", quick=True, backends=("cpu",),
        warning_floor_ms=5.0,
        metadata={"dtype": "none", "problem_size": f"circles={DENSE_CIRCLE_COUNT}",
                  "tile": 0, "cold_group": ""},
        prepare=_compose_case, run=_compose_run, validate=_compose_validate,
    ))
    register(Workload(
        id="pipeline.split_by_pen", version=1, category="pipeline",
        fixture_id="dense-circles", quick=True, backends=("cpu",),
        warning_floor_ms=5.0,
        metadata={"dtype": "none", "problem_size": f"circles={DENSE_CIRCLE_COUNT}",
                  "tile": 0, "cold_group": ""},
        prepare=_split_case, run=_split_run, validate=_split_validate,
    ))
