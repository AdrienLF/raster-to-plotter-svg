"""Reusable parameter groups for samplers and styles."""

from __future__ import annotations

from ..params import Param

SEED = [Param("seed", "int", 0, group="General", help="Random seed for reproducible output")]

VORONOI_SAMPLER = [
    Param("point_density", "int", 500, group="Voronoi Sampling", min=1, max=1200,
          help="Roughly how many points to place, scaled to image size"),
    Param("point_limit", "int", 0, group="Voronoi Sampling", min=0, max=1_000_000,
          help="Hard cap on points (0 = no limit)"),
    Param("luminance_power", "float", 5.0, group="Voronoi Sampling", min=1, max=50,
          help="How strongly the starting points favor dark areas (higher = points start almost only in the darkest spots)"),
    Param("density_power", "float", 5.0, group="Voronoi Sampling", min=1, max=50,
          help="How strongly point spacing favors dark areas once settled (higher = sharper contrast between crowded dark regions and sparse light ones)"),
    Param("voronoi_iterations", "int", 8, group="Voronoi Sampling", min=1, max=100,
          help="Passes that spread points evenly within their region; more = smoother, more regular spacing, fewer = more random, organic placement"),
    Param("voronoi_accuracy", "int", 80, group="Voronoi Sampling", min=1, max=100,
          help="Precision of the spacing calculation; higher is smoother but slower to compute"),
    Param("ignore_white", "bool", True, group="Voronoi Sampling",
          help="Skip placing points on near-white background"),
]

ADAPTIVE_SAMPLER = [
    Param("min_sample_radius", "float", 1.0, group="Adaptive Sampling", min=0.5, max=100,
          help="Closest points can get to each other, used in the darkest areas"),
    Param("max_sample_radius", "float", 6.0, group="Adaptive Sampling", min=0.5, max=100,
          help="Spacing between points in the lightest areas"),
    Param("brightness", "float", 1.0, group="Adaptive Sampling", min=0, max=2,
          help="Brighten or darken the image before sampling (1 = unchanged)"),
    Param("contrast", "float", 1.0, group="Adaptive Sampling", min=0, max=2,
          help="Increase or decrease contrast before sampling (1 = unchanged)"),
    Param("ignore_white", "bool", True, group="Adaptive Sampling",
          help="Skip placing points on near-white background"),
]

LBG_SAMPLER = [
    Param("stipple_radius_min", "float", 1.0, group="LBG Sampling", min=0.5, max=100,
          help="Smallest dot radius, used in the darkest areas"),
    Param("stipple_radius_max", "float", 8.0, group="LBG Sampling", min=0.5, max=100,
          help="Largest dot radius, used in the lightest areas"),
    Param("density", "float", 50.0, group="LBG Sampling", min=0, max=100,
          help="Overall dot count; higher lets dark regions split into more, smaller dots before settling"),
    Param("threshold", "float", 0.0, group="LBG Sampling", min=0, max=100,
          help="Discard dots below this darkness % (0 = keep all)"),
    Param("max_iterations", "int", 20, group="LBG Sampling", min=1, max=100,
          help="Split/merge passes; more lets dot sizes settle more precisely to local tone"),
]

POISSON_SAMPLER = [
    Param("min_radius", "float", 2.0, group="Poisson Sampling", min=0.5, max=100,
          help="Minimum centre-to-centre spacing in the darkest areas"),
    Param("max_radius", "float", 10.0, group="Poisson Sampling", min=0.5, max=150,
          help="Spacing used in the lightest areas"),
    Param("candidates", "int", 30, group="Poisson Sampling", min=4, max=100,
          help="Rejection-sample attempts per active point before giving up"),
    Param("point_limit", "int", 0, group="Poisson Sampling", min=0, max=200_000,
          help="Hard cap on points (0 = no limit)"),
    Param("ignore_white", "bool", True, group="Poisson Sampling",
          help="Skip placing points on near-white background"),
]

SAMPLER_PARAMS = {
    "voronoi": VORONOI_SAMPLER,
    "adaptive": ADAPTIVE_SAMPLER,
    "lbg": LBG_SAMPLER,
    "poisson": POISSON_SAMPLER,
}


def style_params(style: str) -> list[Param]:
    if style == "stippling":
        return [Param("stipple_size", "float", 0.9, group="Stippling", min=0.1, max=10,
                      help="Dot radius in mm at the darkest points (lighter areas shrink down to 30% of this)")]
    if style == "dashes":
        return [
            Param("stipple_size", "float", 0.9, group="Dashes", min=0.1, max=10,
                  help="Half of the dash length in mm at the darkest points (lighter areas shrink down to 30% of this)"),
            Param("distortion", "float", 40.0, group="Dashes", min=0, max=100,
                  help="Random wobble added to each dash's angle (0 = all dashes point the same way)"),
        ]
    if style == "shapes":
        return [
            Param("shape_type", "enum", "circle", group="Shapes",
                  choices=["circle", "square", "star", "triangle", "cross", "lp", "random"],
                  help="Shape stamped at each point (random = a different shape per point)"),
            Param("align_rotation", "bool", False, group="Shapes",
                  help="Keep every shape upright instead of giving it a random rotation"),
            Param("min_rotation", "angle", 0.0, group="Shapes", min=0, max=360,
                  help="Low end of the random rotation range, in degrees (ignored when Align Rotation is on)"),
            Param("max_rotation", "angle", 0.0, group="Shapes", min=0, max=360,
                  help="High end of the random rotation range, in degrees (ignored when Align Rotation is on)"),
            Param("fill_size", "float", 100.0, group="Shapes", min=1, max=400,
                  help="Shape size as a % of the point spacing"),
        ]
    if style == "triangulation":
        return [Param("triangulate_corners", "bool", False, group="Triangulation",
                      help="Add the four page corners as extra points so triangles reach the edges")]
    if style == "tree":
        return [Param("create_curves", "bool", False, group="Tree",
                      help="Smooth tree branches into curves instead of straight segments")]
    if style == "diagram":
        return [Param("voronoi_style", "enum", "classic", group="Diagram",
                      choices=["classic", "smooth"],
                      help="How the cell boundary lines are drawn")]
    if style == "tsp":
        return [Param("merge_tsp_paths", "bool", True, group="TSP",
                      help="Join the whole tour into one continuous path (fewer pen lifts)")]
    return []


STYLE_LABELS = {
    "stippling": "Stippling",
    "dashes": "Dashes",
    "shapes": "Shapes",
    "triangulation": "Triangulation",
    "tree": "Tree",
    "diagram": "Diagram",
    "tsp": "TSP",
}

FAMILY_LABELS = {"voronoi": "Voronoi", "adaptive": "Adaptive", "lbg": "LBG", "poisson": "Poisson"}

STYLE_ORDER = ["stippling", "dashes", "shapes", "triangulation", "tree", "diagram", "tsp"]
