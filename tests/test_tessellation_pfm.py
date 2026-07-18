"""Tessellation PFM registration and PlotterForge parameter schema."""

from PIL import Image

from engine.canvas import DrawingArea
from engine.pens import DrawingSet
from engine.pfm import REGISTRY


def test_four_tessellation_pfms_are_registered_with_shared_controls():
    ids = {key for key in REGISTRY if key.startswith("tessellation_")}
    assert ids == {
        "tessellation_isometric_y", "tessellation_hex_aperture",
        "tessellation_truchet_weave", "tessellation_diamond_lattice",
    }
    names = {p.name for p in REGISTRY["tessellation_isometric_y"].params}
    assert {"columns", "rotation", "phase_x", "phase_y", "tone_response",
            "invert_tone", "remove_duplicates"} <= names


def test_tessellation_pfm_produces_paths():
    pfm = REGISTRY["tessellation_isometric_y"]
    drawing = pfm.run(Image.new("RGB", (96, 64), "#666"), DrawingArea(),
                      DrawingSet(), {"columns": 8})
    assert drawing.total() > 0
    assert sum(len(layer.paths) for layer in drawing.layers) > 0


def test_columns_keep_draft_and_full_tile_density_stable():
    pfm = REGISTRY["tessellation_hex_aperture"]
    image = Image.new("RGB", (900, 600), "#777")
    full = pfm.run(image, DrawingArea(), DrawingSet(), {"columns": 12})
    draft = pfm.run(image, DrawingArea(), DrawingSet(), {"columns": 12}, draft=True)
    assert abs(full.total() - draft.total()) <= 4
