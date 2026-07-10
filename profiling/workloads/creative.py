"""Dynamically discovered PFM and generator workloads.

Every entry in ``engine.pfm.REGISTRY`` and ``engine.generate.GENERATORS`` becomes
a workload so ``full`` can never silently skip a creative module. Only modules
whose production code dispatches an accelerated primitive are GPU-labeled.
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from PIL import Image

from ..workload import Workload, WorkloadCase, WorkloadOutput, register, stable_checksum

SEED = 20260710
SAMPLE_PNG = Path(__file__).resolve().parents[2] / "frontend" / "e2e" / "assets" / "sample.png"

# Small deterministic overrides where a default is unsuitable for repeatable,
# bounded profiling (unbounded iteration counts, huge line caps).
PFM_OVERRIDES = {
    "differential_growth": {"iterations": 20},
    "sketch_lines": {"line_max_limit": 500},
    "sketch_curves": {"line_max_limit": 500},
    "sketch_squares": {"line_max_limit": 500},
    "circle_packing": {"attempts": 1000},
}

# Families that call engine.accel's accelerated nearest-site primitive.
_GPU_FAMILIES = ("voronoi", "lbg")


def _load_image() -> Image.Image:
    return Image.open(SAMPLE_PNG).convert("RGB")


def _pfm_defaults(pfm) -> dict:
    values = {param.name: param.default for param in pfm.params}
    values.update(PFM_OVERRIDES.get(pfm.id, {}))
    return values


def _pfm_case(pfm_id: str) -> WorkloadCase:
    from engine.pfm import get

    pfm = get(pfm_id)
    image = _load_image()
    values = _pfm_defaults(pfm)
    return WorkloadCase(value=(image, values), fixture_checksum=stable_checksum(
        [pfm_id, SAMPLE_PNG.name, sorted((k, str(v)) for k, v in values.items())]))


def _pfm_run(pfm_id: str, case: WorkloadCase) -> WorkloadOutput:
    from engine.canvas import DrawingArea
    from engine.pens import DrawingSet
    from engine.pfm import get
    from engine.svg_io import to_svg

    pfm = get(pfm_id)
    image, values = case.value
    drawing = pfm.run(image, DrawingArea(), DrawingSet(), values, seed=SEED)
    svg = to_svg(drawing)
    return WorkloadOutput(
        {"drawing_total": int(drawing.total()), "svg_bytes": len(svg.encode())},
        stable_checksum([int(drawing.total()), len(svg)]),
    )


def _pfm_validate(pfm_id: str, output: WorkloadOutput) -> None:
    if output.metrics["svg_bytes"] <= 0:
        raise ValueError(f"{pfm_id} produced empty SVG")


def _generator_case(gen_id: str) -> WorkloadCase:
    from engine.generate import GENERATORS
    from engine.params import validate

    gen = GENERATORS[gen_id]
    values = {param.name: param.default for param in gen["params"]}
    values.update(gen.get("defaults", {}))
    if "normalize" in gen:
        values = gen["normalize"](values)
    else:
        values = validate(gen["params"], values)
    values["seed"] = SEED
    return WorkloadCase(value=values, fixture_checksum=stable_checksum(
        [gen_id, sorted((k, str(v)) for k, v in values.items())]))


def _generator_run(gen_id: str, case: WorkloadCase) -> WorkloadOutput:
    from engine.generate import GENERATORS

    gen = GENERATORS[gen_id]
    result = gen["fn"](dict(case.value), seed=SEED)
    lines = result[0] if isinstance(result, tuple) else result
    points = sum(len(line) for line in lines)
    return WorkloadOutput(
        {"lines": len(lines), "points": int(points)},
        stable_checksum([len(lines), int(points)]),
    )


def _generator_validate(gen_id: str, output: WorkloadOutput) -> None:
    if output.metrics["lines"] < 0:
        raise ValueError(f"{gen_id} produced a negative line count")


def _pfm_backends(pfm) -> tuple[str, ...]:
    if pfm.family in _GPU_FAMILIES:
        return ("cpu", "gpu")
    return ("cpu",)


def register_creative() -> None:
    from engine.generate import GENERATORS
    from engine.pfm import REGISTRY, get

    for pfm_id in sorted(REGISTRY):
        pfm = get(pfm_id)
        register(Workload(
            id=f"pfm.{pfm_id}", version=1, category="pfm",
            fixture_id="sample-png", quick=False, backends=_pfm_backends(pfm),
            warning_floor_ms=5.0,
            metadata={"dtype": "uint8", "problem_size": "sample-png",
                      "tile": 1 << 16, "cold_group": "", "family": pfm.family},
            prepare=partial(_pfm_case, pfm_id),
            run=partial(_pfm_run, pfm_id),
            validate=partial(_pfm_validate, pfm_id),
        ))

    for gen_id in sorted(GENERATORS):
        register(Workload(
            id=f"generator.{gen_id}", version=1, category="generator",
            fixture_id=f"generator-{gen_id}", quick=False, backends=("cpu",),
            warning_floor_ms=5.0,
            metadata={"dtype": "none", "problem_size": gen_id, "tile": 0,
                      "cold_group": ""},
            prepare=partial(_generator_case, gen_id),
            run=partial(_generator_run, gen_id),
            validate=partial(_generator_validate, gen_id),
        ))
