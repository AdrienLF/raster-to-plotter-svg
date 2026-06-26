"""Generator framework — the shared post-processing pipeline.

A faithful port of the generic machinery in revdancatt's page.js that every
sketch runs after building its raw lines: decimate, 3D pre-transforms, Perlin
distortions, 3D rotation + perspective, margin/RoD/CoD cropping and final scale.

Works in the generator's own units (cm), on lines of (x, y, z) points, and is
reused by every generator via FRAMEWORK_PARAMS.
"""

from __future__ import annotations

import math

from .params import Param

Pt = tuple[float, float, float]
Line = list[Pt]


# ── Perlin noise (classic Ken Perlin permutation) ───────────────────────────────

_PERM = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225, 140, 36,
    103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148, 247, 120, 234, 75, 0,
    26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32, 57, 177, 33, 88, 237, 149, 56, 87,
    174, 20, 125, 136, 171, 168, 68, 175, 74, 165, 71, 134, 139, 48, 27, 166, 77, 146,
    158, 231, 83, 111, 229, 122, 60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40,
    244, 102, 143, 54, 65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18,
    169, 200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64, 52,
    217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212, 207, 206, 59,
    227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213, 119, 248, 152, 2, 44, 154,
    163, 70, 221, 153, 101, 155, 167, 43, 172, 9, 129, 22, 39, 253, 19, 98, 108, 110, 79,
    113, 224, 232, 178, 185, 112, 104, 218, 246, 97, 228, 251, 34, 242, 193, 238, 210,
    144, 12, 191, 179, 162, 241, 81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31,
    181, 199, 106, 157, 184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236,
    205, 93, 222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
]
_P = _PERM + _PERM


def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6 - 15) + 10)


def _lerp(a: float, b: float, t: float) -> float:
    return a + t * (b - a)


def _grad(h: int, x: float, y: float, z: float) -> float:
    h &= 15
    u = x if h < 8 else y
    v = y if h < 4 else (x if h in (12, 14) else z)
    return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)


def perlin3(x: float, y: float, z: float) -> float:
    xi = int(math.floor(x)) & 255
    yi = int(math.floor(y)) & 255
    zi = int(math.floor(z)) & 255
    xf, yf, zf = x - math.floor(x), y - math.floor(y), z - math.floor(z)
    u, v, w = _fade(xf), _fade(yf), _fade(zf)
    a = _P[xi] + yi
    aa, ab = _P[a] + zi, _P[a + 1] + zi
    b = _P[xi + 1] + yi
    ba, bb = _P[b] + zi, _P[b + 1] + zi
    return _lerp(
        _lerp(
            _lerp(_grad(_P[aa], xf, yf, zf), _grad(_P[ba], xf - 1, yf, zf), u),
            _lerp(_grad(_P[ab], xf, yf - 1, zf), _grad(_P[bb], xf - 1, yf - 1, zf), u), v),
        _lerp(
            _lerp(_grad(_P[aa + 1], xf, yf, zf - 1), _grad(_P[ba + 1], xf - 1, yf, zf - 1), u),
            _lerp(_grad(_P[ab + 1], xf, yf - 1, zf - 1), _grad(_P[bb + 1], xf - 1, yf - 1, zf - 1), u), v),
        w)


# ── point transforms ────────────────────────────────────────────────────────────

def _translate(lines, dx, dy, dz=0.0):
    return [[(x + dx, y + dy, z + dz) for x, y, z in ln] for ln in lines]


def _scale(lines, sx, sy, sz):
    return [[(x * sx, y * sy, z * sz) for x, y, z in ln] for ln in lines]


def _rotate_point(x, y, z, ax, ay, az):
    rx, ry, rz = math.radians(ax), math.radians(ay), math.radians(az)
    ny = y * math.cos(rx) - z * math.sin(rx)
    nz = y * math.sin(rx) + z * math.cos(rx)
    y, z = ny, nz
    nx = z * math.sin(ry) + x * math.cos(ry)
    nz = z * math.cos(ry) - x * math.sin(ry)
    x, z = nx, nz
    nx = x * math.cos(rz) - y * math.sin(rz)
    ny = x * math.sin(rz) + y * math.cos(rz)
    return nx, ny, z


def _rotate(lines, ax, ay, az):
    return [[_rotate_point(x, y, z, ax, ay, az) for x, y, z in ln] for ln in lines]


def _project(lines, perspective):
    pp = perspective * perspective
    out = []
    for ln in lines:
        out.append([(x * (1 + z / pp), y * (1 + z / pp), 0.0) for x, y, z in ln])
    return out


def _centred(lines, pw, ph, fn):
    lines = _translate(lines, -pw / 2, -ph / 2)
    lines = fn(lines)
    return _translate(lines, pw / 2, ph / 2)


# ── decimate (subdivide segments so distortions stay smooth) ─────────────────────

def _decimate(lines, d_distance):
    d = max(0.01, float(d_distance))
    out = []
    for ln in lines:
        if len(ln) < 2:
            out.append(ln)
            continue
        nl = []
        for (x0, y0, z0), (x1, y1, z1) in zip(ln, ln[1:]):
            dist = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)
            times = int(dist / d)
            if times > 0:
                for s in range(times):
                    f = s / times
                    nl.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, z0 + (z1 - z0) * f))
            else:
                nl.append((x0, y0, z0))
        nl.append(ln[-1])
        out.append(nl)
    return out


# ── Perlin displacement ──────────────────────────────────────────────────────────

def _displace(lines, d, pw, ph):
    """lines are already centred on (0,0). d is a dict of the d1/d2 params."""
    amp = float(d["amplitude"])
    if amp <= 0:
        return lines
    res = max(0.01, float(d["resolution"]))
    xs, ys, zs = float(d["x_scale"]), float(d["y_scale"]), float(d["z_scale"])
    xn, yn, zn = float(d["x_nudge"]), float(d["y_nudge"]), float(d["z_nudge"])
    direction = d["direction"]
    invert = bool(d["invert"])
    weighting = float(d["weighting"])
    middle_dist = float(d["middle_dist"])
    mx, my = pw / 2, ph / 2
    corner = mx * mx + my * my
    out = []
    for ln in lines:
        nl = []
        for x, y, z in ln:
            wx, wy = x + mx, y + my
            wmod = 1.0
            if direction == "topDown":
                wmod = 1 - wy / ph
            elif direction == "leftRight":
                wmod = 1 - wx / pw
            elif direction == "middle":
                td = (mx - wx) ** 2 + (my - wy) ** 2
                wmod = 0.71 - (td / corner - middle_dist / 1000)
            elif direction == "noise":
                wmod = (perlin3(wx / 20, wy / 20, 0.0) + 1) / 2
            if weighting != 0:
                wmod *= weighting
            if invert:
                wmod = 1 - wmod
            nx = x + perlin3((x + xn) / res, (y + xn) / res, (z + xn) / res) * xs * amp * wmod
            ny = y + perlin3((x + yn) / res, (y + yn) / res, (z + yn) / res) * ys * amp * wmod
            nz = z + perlin3((x + zn) / res, (y + zn) / res, (z + zn) / res) * zs * amp * wmod
            nl.append((nx, ny, nz))
        out.append(nl)
    return out


def _d_params(v, prefix):
    return {
        "amplitude": v[f"{prefix}_amplitude"], "resolution": v[f"{prefix}_resolution"],
        "x_scale": v[f"{prefix}_x_scale"], "y_scale": v[f"{prefix}_y_scale"], "z_scale": v[f"{prefix}_z_scale"],
        "x_nudge": v[f"{prefix}_x_nudge"], "y_nudge": v[f"{prefix}_y_nudge"], "z_nudge": v[f"{prefix}_z_nudge"],
        "direction": v[f"{prefix}_direction"], "invert": v[f"{prefix}_invert"],
        "weighting": v[f"{prefix}_weighting"], "middle_dist": v[f"{prefix}_middle_dist"],
    }


# ── cropping (2D, after flatten) ─────────────────────────────────────────────────

def _clip_lines(lines, seg_fn):
    """Apply a per-segment clip that returns kept (a,b) pieces; stitch them."""
    out = []
    for ln in lines:
        cur: Line = []
        for p0, p1 in zip(ln, ln[1:]):
            for a, b in seg_fn(p0, p1):
                if cur and cur[-1] == a:
                    cur.append(b)
                else:
                    if len(cur) >= 2:
                        out.append(cur)
                    cur = [a, b]
        if len(cur) >= 2:
            out.append(cur)
    return out


def _liang_barsky(p0, p1, rect):
    x0, y0, _ = p0
    x1, y1, _ = p1
    xmin, ymin, xmax, ymax = rect
    dx, dy = x1 - x0, y1 - y0
    p = [-dx, dx, -dy, dy]
    q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0]
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        else:
            t = qi / pi
            if pi < 0:
                u0 = max(u0, t)
            else:
                u1 = min(u1, t)
    if u0 > u1:
        return None
    return u0, u1


def _seg_rect_inside(p0, p1, rect):
    r = _liang_barsky(p0, p1, rect)
    if r is None:
        return []
    u0, u1 = r
    x0, y0, _ = p0
    dx, dy = p1[0] - x0, p1[1] - y0
    return [((x0 + dx * u0, y0 + dy * u0, 0.0), (x0 + dx * u1, y0 + dy * u1, 0.0))]


def _seg_rect_outside(p0, p1, rect):
    r = _liang_barsky(p0, p1, rect)
    x0, y0, _ = p0
    dx, dy = p1[0] - x0, p1[1] - y0

    def at(t):
        return (x0 + dx * t, y0 + dy * t, 0.0)

    if r is None:
        return [(at(0.0), at(1.0))]
    u0, u1 = r
    out = []
    if u0 > 0:
        out.append((at(0.0), at(u0)))
    if u1 < 1:
        out.append((at(u1), at(1.0)))
    return out


def _circle_roots(p0, p1, cx, cy, r):
    x0, y0, _ = p0
    dx, dy = p1[0] - x0, p1[1] - y0
    fx, fy = x0 - cx, y0 - cy
    a = dx * dx + dy * dy
    if a == 0:
        return None
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c
    if disc <= 0:
        return None
    sd = math.sqrt(disc)
    return (-b - sd) / (2 * a), (-b + sd) / (2 * a)


def _seg_circle_inside(p0, p1, cx, cy, r):
    x0, y0, _ = p0
    dx, dy = p1[0] - x0, p1[1] - y0

    def at(t):
        return (x0 + dx * t, y0 + dy * t, 0.0)

    roots = _circle_roots(p0, p1, cx, cy, r)
    if roots is None:
        mx, my = x0 + dx * 0.5, y0 + dy * 0.5
        return [(at(0.0), at(1.0))] if (mx - cx) ** 2 + (my - cy) ** 2 <= r * r else []
    t0, t1 = max(0.0, roots[0]), min(1.0, roots[1])
    return [(at(t0), at(t1))] if t1 > t0 else []


def _seg_circle_outside(p0, p1, cx, cy, r):
    x0, y0, _ = p0
    dx, dy = p1[0] - x0, p1[1] - y0

    def at(t):
        return (x0 + dx * t, y0 + dy * t, 0.0)

    roots = _circle_roots(p0, p1, cx, cy, r)
    if roots is None:
        mx, my = x0 + dx * 0.5, y0 + dy * 0.5
        return [] if (mx - cx) ** 2 + (my - cy) ** 2 < r * r else [(at(0.0), at(1.0))]
    t0, t1 = roots
    out = []
    if t0 > 0:
        out.append((at(0.0), at(min(t0, 1.0))))
    if t1 < 1:
        out.append((at(max(t1, 0.0)), at(1.0)))
    return out


def convex_interval(p0, p1, poly):
    """Parametric interval [u0,u1] of segment p0->p1 that lies inside the convex
    polygon `poly` (clip against each edge half-plane). None if no overlap.
    Reads only [0],[1] of each point, so works for 2D or 3D points."""
    n = len(poly)
    cx = sum(pt[0] for pt in poly) / n
    cy = sum(pt[1] for pt in poly) / n
    x0, y0 = p0[0], p0[1]
    dx, dy = p1[0] - x0, p1[1] - y0
    edges = list(zip(poly, poly[1:]))
    if poly[0] != poly[-1]:
        edges.append((poly[-1], poly[0]))
    u0, u1 = 0.0, 1.0
    for a, b in edges:
        ex, ey = b[0] - a[0], b[1] - a[1]
        s = 1.0 if (ex * (cy - a[1]) - ey * (cx - a[0])) >= 0 else -1.0
        c0 = s * (ex * (y0 - a[1]) - ey * (x0 - a[0]))
        c1 = s * (ex * dy - ey * dx)
        if abs(c1) < 1e-12:
            if c0 < 0:
                return None
        else:
            t = -c0 / c1
            if c1 > 0:
                u0 = max(u0, t)
            else:
                u1 = min(u1, t)
    return (u0, u1) if u0 <= u1 else None


def _seg_poly_inside(p0, p1, poly):
    iv = convex_interval(p0, p1, poly)
    if iv is None:
        return []
    x0, y0 = p0[0], p0[1]
    dx, dy = p1[0] - x0, p1[1] - y0
    return [((x0 + dx * iv[0], y0 + dy * iv[0], 0.0), (x0 + dx * iv[1], y0 + dy * iv[1], 0.0))]


def _seg_poly_outside(p0, p1, poly):
    x0, y0 = p0[0], p0[1]
    dx, dy = p1[0] - x0, p1[1] - y0

    def at(t):
        return (x0 + dx * t, y0 + dy * t, 0.0)

    iv = convex_interval(p0, p1, poly)
    if iv is None:
        return [(at(0.0), at(1.0))]
    out = []
    if iv[0] > 0:
        out.append((at(0.0), at(iv[0])))
    if iv[1] < 1:
        out.append((at(iv[1]), at(1.0)))
    return out


def _squarify_offsets(pw, ph, squarify):
    tb = lr = 0.0
    if squarify:
        if ph > pw:
            tb = (ph - pw) / 2
        elif pw > ph:
            lr = (pw - ph) / 2
    return lr, tb


def _circle_outline(cx, cy, size, sides, rotation):
    sides = max(3, int(sides))
    rot = math.radians(rotation - 90)
    pts = []
    for i in range(sides + 1):
        a = 2 * math.pi * i / sides + rot
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a), 0.0))
    return pts


# ── the pipeline ─────────────────────────────────────────────────────────────────

def apply_framework(lines, pw: float, ph: float, v: dict, seed: int = 0):
    """Run the full framework pipeline. Returns (lines, extra_outline_lines)."""
    lines = [[(float(x), float(y), 0.0) for x, y in ln] for ln in lines]

    if v["decimate"]:
        lines = _decimate(lines, v["d_distance"])

    # pre-transforms (around page centre)
    if v["pre_x"] != 1 or v["pre_y"] != 1 or v["pre_z"] != 1:
        lines = _centred(lines, pw, ph, lambda L: _scale(L, v["pre_x"], v["pre_y"], v["pre_z"]))
    if v["pre_rot_x"] or v["pre_rot_y"] or v["pre_rot_z"]:
        lines = _centred(lines, pw, ph, lambda L: _rotate(L, v["pre_rot_x"], v["pre_rot_y"], v["pre_rot_z"]))
    if v["pre_tran_x"] or v["pre_tran_y"] or v["pre_tran_z"]:
        lines = _translate(lines, v["pre_tran_x"], v["pre_tran_y"], v["pre_tran_z"])

    # Perlin distortions (centred)
    if v["d1_amplitude"] > 0 or v["d2_amplitude"] > 0:
        lines = _translate(lines, -pw / 2, -ph / 2)
        if v["d1_amplitude"] > 0:
            lines = _displace(lines, _d_params(v, "d1"), pw, ph)
        if v["d2_amplitude"] > 0:
            lines = _displace(lines, _d_params(v, "d2"), pw, ph)
        lines = _translate(lines, pw / 2, ph / 2)

    # 3D rotation + perspective
    if any(v[k] for k in ("rot1_x", "rot1_y", "rot1_z", "rot2_x", "rot2_y", "rot2_z")):
        def rot(L):
            L = _rotate(L, v["rot1_x"], v["rot1_y"], v["rot1_z"])
            L = _rotate(L, v["rot2_x"], v["rot2_y"], v["rot2_z"])
            return _project(L, max(0.1, v["perspective"]))
        lines = _centred(lines, pw, ph, rot)

    # croppers
    lr, tb = _squarify_offsets(pw, ph, v["squarify"])
    margin = (v["side_margin"] + lr, v["top_bottom_margin"] + tb,
              pw - (v["side_margin"] + lr), ph - (v["top_bottom_margin"] + tb))
    lines = _clip_lines(lines, lambda a, b: _seg_rect_inside(a, b, margin))

    extras = []
    if v["use_rod"]:
        rod = (v["rod_left"] + lr, v["rod_top"] + tb,
               pw - (v["rod_right"] + lr), ph - (v["rod_bottom"] + tb))
        keep_in = bool(v["rod_crop_outside"])
        lines = _clip_lines(lines, lambda a, b: (_seg_rect_inside if keep_in else _seg_rect_outside)(a, b, rod))
        if v["draw_rod"]:
            x0, y0, x1, y1 = rod
            extras.append([(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0), (x0, y0, 0.0)])

    for pre in ("cod", "cod2"):
        if not v[f"use_{pre}"]:
            continue
        poly = _circle_outline(v[f"{pre}_x"], v[f"{pre}_y"], v[f"{pre}_size"],
                               v[f"{pre}_sides"], v[f"{pre}_rotation"])
        keep_in = bool(v[f"{pre}_crop_outside"])
        seg = (lambda a, b, poly=poly: _seg_poly_inside(a, b, poly)) if keep_in \
            else (lambda a, b, poly=poly: _seg_poly_outside(a, b, poly))
        lines = _clip_lines(lines, seg)
        if v[f"draw_{pre}"]:
            extras.append(poly)

    if v["draw_margin"]:
        x0, y0, x1, y1 = margin
        extras.append([(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0), (x0, y0, 0.0)])

    # final scale (around centre)
    if v["final_scale"] != 1:
        s = v["final_scale"]
        lines = _centred(lines, pw, ph, lambda L: _scale(L, s, s, s))
        extras = _centred(extras, pw, ph, lambda L: _scale(L, s, s, s))

    to_xy = lambda L: [[(x, y) for x, y, z in ln] for ln in L]
    return to_xy(lines), to_xy(extras)


# ── framework parameter schema (appended to every generator) ────────────────────

def _angle(name, group, default=0.0):
    return Param(name, "angle", default, group=group, min=-360, max=360)


FRAMEWORK_PARAMS = [
    Param("decimate", "bool", False, group="Decimate"),
    Param("d_distance", "float", 0.2, group="Decimate", min=0.05, max=42,
          help="Re-sample spacing (cm); smaller = smoother distortion"),

    Param("pre_x", "float", 1.0, group="Transform", min=0, max=4),
    Param("pre_y", "float", 1.0, group="Transform", min=0, max=4),
    Param("pre_z", "float", 1.0, group="Transform", min=0, max=4),
    Param("pre_tran_x", "float", 0.0, group="Transform", min=-50, max=50),
    Param("pre_tran_y", "float", 0.0, group="Transform", min=-50, max=50),
    Param("pre_tran_z", "float", 0.0, group="Transform", min=-50, max=50),
    _angle("pre_rot_x", "Transform"),
    _angle("pre_rot_y", "Transform"),
    _angle("pre_rot_z", "Transform"),

    _angle("rot1_x", "3D Rotation"),
    _angle("rot1_y", "3D Rotation"),
    _angle("rot1_z", "3D Rotation"),
    _angle("rot2_x", "3D Rotation"),
    _angle("rot2_y", "3D Rotation"),
    _angle("rot2_z", "3D Rotation"),
    Param("perspective", "float", 5.0, group="3D Rotation", min=0.5, max=40),
]

for _pfx, _g in (("d1", "Distort 1"), ("d2", "Distort 2")):
    FRAMEWORK_PARAMS += [
        Param(f"{_pfx}_amplitude", "float", 0.0, group=_g, min=0, max=20),
        Param(f"{_pfx}_resolution", "float", 10.0, group=_g, min=0.1, max=80),
        Param(f"{_pfx}_x_scale", "float", 1.0, group=_g, min=0, max=8),
        Param(f"{_pfx}_y_scale", "float", 1.0, group=_g, min=0, max=8),
        Param(f"{_pfx}_z_scale", "float", 1.0, group=_g, min=0, max=8),
        Param(f"{_pfx}_x_nudge", "float", 50.0, group=_g, min=-200, max=200),
        Param(f"{_pfx}_y_nudge", "float", -30.0, group=_g, min=-200, max=200),
        Param(f"{_pfx}_z_nudge", "float", 23.0, group=_g, min=-200, max=200),
        Param(f"{_pfx}_direction", "enum", "normal", group=_g,
              choices=["normal", "topDown", "leftRight", "middle", "noise"]),
        Param(f"{_pfx}_invert", "bool", False, group=_g),
        Param(f"{_pfx}_weighting", "float", 1.0, group=_g, min=-2, max=2),
        Param(f"{_pfx}_middle_dist", "float", 100.0, group=_g, min=0, max=1000),
    ]

FRAMEWORK_PARAMS += [
    Param("use_rod", "bool", False, group="Rectangle Crop"),
    Param("rod_left", "float", 3.8, group="Rectangle Crop", min=0, max=60),
    Param("rod_top", "float", 6.0, group="Rectangle Crop", min=0, max=60),
    Param("rod_right", "float", 3.8, group="Rectangle Crop", min=0, max=60),
    Param("rod_bottom", "float", 6.0, group="Rectangle Crop", min=0, max=60),
    Param("rod_crop_outside", "bool", True, group="Rectangle Crop", help="Keep inside the rectangle"),
    Param("draw_rod", "bool", False, group="Rectangle Crop"),

    Param("use_cod", "bool", False, group="Circle Crop"),
    Param("cod_x", "float", 14.85, group="Circle Crop", min=0, max=120),
    Param("cod_y", "float", 21.0, group="Circle Crop", min=0, max=120),
    Param("cod_size", "float", 7.42, group="Circle Crop", min=0.1, max=60),
    Param("cod_sides", "int", 90, group="Circle Crop", min=3, max=360),
    _angle("cod_rotation", "Circle Crop"),
    Param("cod_crop_outside", "bool", True, group="Circle Crop", help="Keep inside the circle"),
    Param("draw_cod", "bool", False, group="Circle Crop"),

    Param("use_cod2", "bool", False, group="Circle Crop 2"),
    Param("cod2_x", "float", 14.85, group="Circle Crop 2", min=0, max=120),
    Param("cod2_y", "float", 21.0, group="Circle Crop 2", min=0, max=120),
    Param("cod2_size", "float", 7.42, group="Circle Crop 2", min=0.1, max=60),
    Param("cod2_sides", "int", 90, group="Circle Crop 2", min=3, max=360),
    _angle("cod2_rotation", "Circle Crop 2"),
    Param("cod2_crop_outside", "bool", True, group="Circle Crop 2", help="Keep inside the circle"),
    Param("draw_cod2", "bool", False, group="Circle Crop 2"),

    Param("final_scale", "float", 1.0, group="Output", min=0.1, max=4),
    Param("squarify", "bool", False, group="Output"),
]
