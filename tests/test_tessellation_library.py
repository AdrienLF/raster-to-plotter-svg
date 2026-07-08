"""Custom tessellation package validation and library persistence."""

import pytest

from engine.tessellation_library import (
    PatternValidationError,
    parse_state_svg,
    slugify_pattern_name,
    validate_package,
)

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0 L100 100" fill="none" stroke="black"/></svg>'


def manifest(name="My Pattern"):
    return {
        "format_version": 1, "name": name,
        "lattice": {"a": [100, 0], "b": [0, 100]},
        "bounds": [0, 0, 100, 100],
        "bindings": [{"layer_id": "basicShape#1", "attribute_id": "rotation",
                      "light": 0, "dark": 90, "curve": None}],
    }


def test_slug_is_stable_and_prefixed():
    assert slugify_pattern_name("  Möbius Grid! ") == "tessellation_custom_mobius_grid"


def test_svg_is_flattened_and_normalized_to_bounds():
    state = parse_state_svg(SVG, (0, 0, 100, 100))
    assert state.paths[0].points[0] == pytest.approx((0, 0))
    assert state.paths[0].points[-1] == pytest.approx((1, 1))


def test_validate_requires_32_states_and_valid_lattice():
    with pytest.raises(PatternValidationError, match="32 states"):
        validate_package(manifest(), [SVG])
    bad = manifest()
    bad["lattice"]["b"] = [200, 0]
    with pytest.raises(PatternValidationError, match="non-collinear"):
        validate_package(bad, [SVG] * 32)


def test_validate_rejects_active_and_external_svg():
    for body in ("<svg><script>alert(1)</script></svg>",
                 '<svg><image href="https://example.com/x.png"/></svg>'):
        with pytest.raises(PatternValidationError):
            validate_package(manifest(), [body] * 32)
