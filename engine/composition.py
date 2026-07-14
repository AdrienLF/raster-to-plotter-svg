from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _sax_escape


def _attr(value: object) -> str:
    """Escape a string for safe inclusion in a double-quoted XML attribute."""
    return _sax_escape(str(value), {'"': "&quot;"})

A3_PAGE = {"width": 297.0, "height": 420.0, "units": "mm"}

_SVG_NS = "http://www.w3.org/2000/svg"
_UNIT_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "px": 25.4 / 96.0,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
}


def _fmt(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _parse_length(value: str | None, fallback: float) -> float:
    if not value:
        return fallback
    raw = str(value).strip()
    match = re.match(r"^([-+]?[0-9]*\.?[0-9]+)\s*([a-zA-Z]*)$", raw)
    if not match:
        return fallback
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    return round(number * _UNIT_MM.get(unit, _UNIT_MM["px"]), 4)


def _root(svg: str) -> ET.Element:
    return ET.fromstring(svg.encode("utf-8"))


def _viewbox(svg_root: ET.Element) -> tuple[float, float, float, float] | None:
    value = svg_root.attrib.get("viewBox") or svg_root.attrib.get("viewbox")
    if not value:
        return None
    try:
        parts = [float(p) for p in re.split(r"[\s,]+", value.strip()) if p]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def parse_svg_size_mm(svg: str) -> tuple[float, float]:
    root = _root(svg)
    view_box = _viewbox(root)
    fallback_w = view_box[2] if view_box else A3_PAGE["width"]
    fallback_h = view_box[3] if view_box else A3_PAGE["height"]
    width = _parse_length(root.attrib.get("width"), fallback_w)
    height = _parse_length(root.attrib.get("height"), fallback_h)
    return width, height


def normalize_svg_to_page(svg: str, page: dict) -> str:
    """Fit an arbitrary-unit SVG (e.g. a px-based Cavalry export) onto the mm page.

    Uniform fit (letterbox): scale so the source viewBox fills the page without
    cropping, producing a native mm document like every other layer. Without
    this, compose/plot would read px user units as mm (``_inner_svg`` does no
    unit rescaling) and a 1080 px export would plot 1080 mm wide.
    """
    root = _root(svg)
    view_box = _viewbox(root)
    if view_box:
        vb_w, vb_h = view_box[2], view_box[3]
    else:
        # No viewBox: user units span the numeric width/height attributes.
        vb_w = _user_units(root.attrib.get("width"), page["width"])
        vb_h = _user_units(root.attrib.get("height"), page["height"])
    if vb_w <= 0 or vb_h <= 0:
        return svg
    s = min(page["width"] / vb_w, page["height"] / vb_h)
    body = f'<g transform="scale({_fmt(s)})">{_inner_svg(svg)}</g>'
    return _svg_document(vb_w * s, vb_h * s, body)


def _user_units(value: str | None, fallback: float) -> float:
    match = re.match(r"^([-+]?[0-9]*\.?[0-9]+)", str(value or "").strip())
    return float(match.group(1)) if match else fallback


def _inner_svg(svg: str) -> str:
    root = _root(svg)
    view_box = _viewbox(root)
    body = "".join(ET.tostring(child, encoding="unicode") for child in list(root))
    if not view_box:
        return body
    min_x, min_y, _, _ = view_box
    if not min_x and not min_y:
        return body
    return f'<g transform="translate({_fmt(-min_x)} {_fmt(-min_y)})">{body}</g>'


def _svg_document(width: float, height: float, body: str) -> str:
    return (
        f'<svg xmlns="{_SVG_NS}" width="{_fmt(width)}mm" height="{_fmt(height)}mm" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">\n{body}\n</svg>'
    )


@dataclass
class CompositionLayer:
    id: str
    name: str
    kind: str                     # "svg" | "pathfinding" | "generate" | "raster"
    visible: bool = True
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    svg: str = ""
    svg_path: str = ""
    source: dict = field(default_factory=dict)
    crop: dict | None = None
    mask: dict | None = None
    scale: float = 1.0
    rotation: float = 0.0         # degrees, about the layer content centre
    image_path: str = ""          # raster layers: image file relative to project dir
    region_id: str | None = None
    display_mode: str = "pathfinding"
    occlude_below: bool = False
    occlusion_mode: str = "mask"  # "mask" (outline polygon) | "strokes" (exact HLR)
    pathfinding_style: dict = field(default_factory=dict)
    occlusion_mask: dict | None = None

    def to_dict(self, include_svg: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "visible": self.visible,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "svg_path": self.svg_path,
            "source": self.source,
            "crop": self.crop,
            "mask": self.mask,
            "scale": self.scale,
            "rotation": self.rotation,
            "image_path": self.image_path,
            "region_id": self.region_id,
            "display_mode": self.display_mode,
            "occlude_below": self.occlude_below,
            "occlusion_mode": self.occlusion_mode,
            "pathfinding_style": self.pathfinding_style,
            "occlusion_mask": self.occlusion_mask,
        }
        if include_svg:
            data["svg"] = self.svg
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CompositionLayer":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:10]),
            name=str(data.get("name") or "Layer"),
            kind=str(data.get("kind") or "svg"),
            visible=bool(data.get("visible", True)),
            x=float(data.get("x", 0) or 0),
            y=float(data.get("y", 0) or 0),
            width=float(data.get("width", 0) or 0),
            height=float(data.get("height", 0) or 0),
            svg=str(data.get("svg") or ""),
            svg_path=str(data.get("svg_path") or ""),
            source=dict(data.get("source") or {}),
            crop=data.get("crop") or None,
            mask=data.get("mask") or None,
            scale=float(data.get("scale", 1) or 1),
            rotation=float(data.get("rotation", 0) or 0),
            image_path=str(data.get("image_path") or ""),
            region_id=data.get("region_id") or None,
            display_mode=str(data.get("display_mode") or "pathfinding"),
            occlude_below=bool(data.get("occlude_below", False)),
            occlusion_mode=("strokes" if data.get("occlusion_mode") == "strokes" else "mask"),
            pathfinding_style=dict(data.get("pathfinding_style") or {}),
            occlusion_mask=data.get("occlusion_mask") or None,
        )


@dataclass
class Composition:
    page: dict = field(default_factory=lambda: dict(A3_PAGE))
    selected_layer_id: str | None = None
    layers: list[CompositionLayer] = field(default_factory=list)

    def selected_layer(self) -> CompositionLayer | None:
        return next((layer for layer in self.layers if layer.id == self.selected_layer_id), None)

    def add_layer(self, svg: str, name: str, kind: str, source: dict) -> CompositionLayer:
        width, height = parse_svg_size_mm(svg)
        layer = CompositionLayer(
            id=uuid.uuid4().hex[:10],
            name=name,
            kind=kind,
            width=width,
            height=height,
            svg=svg,
            source=dict(source or {}),
        )
        self.layers.append(layer)
        self.selected_layer_id = layer.id
        return layer

    def add_raster_layer(self, name: str, width_mm: float, height_mm: float,
                         source: dict) -> CompositionLayer:
        """An imported image as a freely transformable layer. The raster bytes
        live on disk (``image_path``, set by the caller once the id exists);
        ``svg`` stays empty until pathfinding generates strokes for it."""
        layer = CompositionLayer(
            id=uuid.uuid4().hex[:10],
            name=name,
            kind="raster",
            width=float(width_mm),
            height=float(height_mm),
            source=dict(source or {}),
            display_mode="raster",
        )
        self.layers.append(layer)
        self.selected_layer_id = layer.id
        return layer

    def delete_layer(self, layer_id: str) -> bool:
        before = len(self.layers)
        self.layers = [layer for layer in self.layers if layer.id != layer_id]
        if len(self.layers) == before:
            return False
        if self.selected_layer_id == layer_id:
            self.selected_layer_id = self.layers[-1].id if self.layers else None
        return True

    def duplicate_layer(self, layer_id: str) -> CompositionLayer | None:
        layer = next((item for item in self.layers if item.id == layer_id), None)
        if layer is None:
            return None
        copy = CompositionLayer.from_dict(
            {
                **layer.to_dict(include_svg=True),
                "id": uuid.uuid4().hex[:10],
                "name": f"{layer.name} copy",
                "svg_path": "",
            }
        )
        index = self.layers.index(layer) + 1
        self.layers.insert(index, copy)
        self.selected_layer_id = copy.id
        return copy

    def move_layer(self, layer_id: str, direction: int) -> bool:
        ids = [layer.id for layer in self.layers]
        if layer_id not in ids:
            return False
        index = ids.index(layer_id)
        target = index + direction
        if target < 0 or target >= len(self.layers):
            return False
        self.layers[index], self.layers[target] = self.layers[target], self.layers[index]
        return True

    def to_dict(self, include_svg: bool = False) -> dict:
        return {
            "page": self.page,
            "selected_layer_id": self.selected_layer_id,
            "layers": [layer.to_dict(include_svg=include_svg) for layer in self.layers],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Composition":
        data = data or {}
        comp = cls(
            page=dict(data.get("page") or A3_PAGE),
            selected_layer_id=data.get("selected_layer_id"),
            layers=[CompositionLayer.from_dict(item) for item in data.get("layers", [])],
        )
        if comp.layers and not comp.selected_layer():
            comp.selected_layer_id = comp.layers[-1].id
        return comp


def replace_selected_layer(
    comp: Composition,
    svg: str,
    name: str,
    kind: str,
    source: dict,
) -> CompositionLayer:
    layer = comp.selected_layer()
    width, height = parse_svg_size_mm(svg)
    if layer is None:
        return comp.add_layer(svg, name=name, kind=kind, source=source)
    layer.name = name
    layer.kind = kind
    layer.width = width
    layer.height = height
    layer.svg = svg
    layer.source = dict(source or {})
    # Crop/mask/scale are keyed to the previous geometry; reset them on replace.
    layer.crop = None
    layer.mask = None
    layer.scale = 1.0
    return layer


def effective_bounds(layer: CompositionLayer) -> dict:
    """Layer bounds on the page, accounting for an active crop and scale."""
    s = float(layer.scale or 1)
    crop = layer.crop
    crop_x = float(crop.get("x", 0) or 0) if crop else 0.0
    crop_y = float(crop.get("y", 0) or 0) if crop else 0.0
    crop_w = float(crop.get("width", layer.width) or layer.width) if crop else layer.width
    crop_h = float(crop.get("height", layer.height) or layer.height) if crop else layer.height
    return {
        "x": layer.x + s * crop_x,
        "y": layer.y + s * crop_y,
        "width": s * crop_w,
        "height": s * crop_h,
    }


def _layer_body(layer: CompositionLayer, exclude_masks: list[dict] | None = None) -> str:
    """Inner SVG for a layer: raw when unclipped, baked when crop/mask present."""
    if not layer.svg.strip():
        return ""  # raster layers before any pathfinding generation
    if layer.crop or layer.mask or exclude_masks:
        from . import layer_clip

        return layer_clip.clipped_layer_body(layer.svg, layer.crop, layer.mask, exclude_masks)
    return _inner_svg(layer.svg)


def _layer_transform(layer: CompositionLayer) -> str:
    tf = f"translate({_fmt(layer.x)} {_fmt(layer.y)})"
    s = float(layer.scale or 1)
    if s != 1:
        tf += f" scale({_fmt(s)})"
    r = float(layer.rotation or 0)
    if r:
        # About the content centre, in layer-local units (after the scale).
        tf += f" rotate({_fmt(r)} {_fmt(layer.width / 2)} {_fmt(layer.height / 2)})"
    return tf


def rotated_page_bounds(layer: CompositionLayer) -> dict:
    """Axis-aligned page-mm bbox of the layer's (possibly rotated) bounds."""
    b = effective_bounds(layer)
    r = float(layer.rotation or 0)
    if not r:
        return b
    import math

    s = float(layer.scale or 1)
    cx = layer.x + s * layer.width / 2
    cy = layer.y + s * layer.height / 2
    cos_r, sin_r = math.cos(math.radians(r)), math.sin(math.radians(r))
    xs, ys = [], []
    for px, py in ((b["x"], b["y"]), (b["x"] + b["width"], b["y"]),
                   (b["x"], b["y"] + b["height"]),
                   (b["x"] + b["width"], b["y"] + b["height"])):
        dx, dy = px - cx, py - cy
        xs.append(cx + dx * cos_r - dy * sin_r)
        ys.append(cy + dx * sin_r + dy * cos_r)
    return {"x": min(xs), "y": min(ys),
            "width": max(xs) - min(xs), "height": max(ys) - min(ys)}


def _rect_to_page(layer: CompositionLayer, rect: dict) -> dict:
    s = float(layer.scale or 1)
    return {
        "type": "rect",
        "x": layer.x + s * float(rect.get("x", 0) or 0),
        "y": layer.y + s * float(rect.get("y", 0) or 0),
        "width": s * float(rect.get("width", 0) or 0),
        "height": s * float(rect.get("height", 0) or 0),
    }


def _rect_to_layer(layer: CompositionLayer, rect: dict) -> dict:
    s = float(layer.scale or 1)
    return {
        "type": "rect",
        "x": (float(rect.get("x", 0) or 0) - layer.x) / s,
        "y": (float(rect.get("y", 0) or 0) - layer.y) / s,
        "width": float(rect.get("width", 0) or 0) / s,
        "height": float(rect.get("height", 0) or 0) / s,
    }


def _mask_to_layer(layer: CompositionLayer, upper: CompositionLayer, mask: dict) -> dict | None:
    """Express ``upper``'s occlusion mask in ``layer``'s local mm coordinates."""
    kind = mask.get("type")
    if kind == "rect":
        return _rect_to_layer(layer, _rect_to_page(upper, mask))
    if kind == "path":
        su = float(upper.scale or 1)
        sl = float(layer.scale or 1)
        i = 0

        def remap(m: "re.Match") -> str:
            nonlocal i
            v = float(m.group())
            page = (upper.x + su * v) if i % 2 == 0 else (upper.y + su * v)
            origin = layer.x if i % 2 == 0 else layer.y
            i += 1
            return _fmt((page - origin) / sl)

        return {"type": "path", "d": re.sub(r"-?\d*\.?\d+(?:e[-+]?\d+)?", remap, str(mask.get("d", "")))}
    return None


def _upper_occlusion_masks(
    visible: list[CompositionLayer], index: int, skip_strokes: bool = False
) -> list[dict]:
    masks: list[dict] = []
    layer = visible[index]
    for upper in visible[index + 1:]:
        if not upper.occlude_below or not upper.occlusion_mask:
            continue
        if skip_strokes and upper.occlusion_mode == "strokes":
            continue  # handled by the stroke-level HLR pre-pass
        mapped = _mask_to_layer(layer, upper, upper.occlusion_mask)
        if mapped:
            masks.append(mapped)
    return masks


# Stroke-level HLR is heavy (shapely buffers/unions over every stroke), and
# compose runs on every layer tweak — cache baked bodies by the stack state.
_HLR_CACHE: dict[str, dict[str, str]] = {}
_HLR_CACHE_MAX = 4


def _hlr_stack_key(visible: list[CompositionLayer]) -> str:
    import hashlib

    h = hashlib.sha256()
    for layer in visible:
        state = {
            "id": layer.id,
            "x": layer.x,
            "y": layer.y,
            "scale": layer.scale,
            "crop": layer.crop,
            "mask": layer.mask,
            "occlude": layer.occlude_below,
            "mode": layer.occlusion_mode,
            "svg": hashlib.sha256(layer.svg.encode("utf-8")).hexdigest(),
        }
        h.update(json.dumps(state, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _strokes_occlusion_bodies(visible: list[CompositionLayer]) -> dict[str, str]:
    """Run stroke-level HLR when any visible layer occludes in "strokes" mode.

    Returns ``{layer_id: baked_svg_body}`` for every layer whose geometry was
    clipped by a nearer strokes-mode occluder. Empty dict when the pass does
    not apply (no strokes occluder, or shapely unavailable — callers then fall
    back to the outline-mask occlusion path).
    """
    from . import hlr

    occluders = [
        layer for layer in visible
        if layer.occlude_below and layer.occlusion_mode == "strokes"
    ]
    if not occluders or not hlr.available():
        return {}
    key = _hlr_stack_key(visible)
    cached = _HLR_CACHE.get(key)
    if cached is not None:
        return cached

    from . import layer_clip

    ordered = list(reversed(visible))            # near (top of stack) first
    first = min(ordered.index(layer) for layer in occluders)
    participating = ordered[first:]

    entries = []        # hlr.occlude_stack input, parallel to `participating`
    attrs_per_layer = []
    for layer in participating:
        s = float(layer.scale or 1)
        flat = layer_clip.flattened_clipped_polylines(layer.svg, layer.crop, layer.mask)
        # Outline-mask occluders above this layer still apply (mixed stacks).
        index = visible.index(layer)
        exclude_polys = [
            layer_clip.mask_polygon(m)
            for m in _upper_occlusion_masks(visible, index, skip_strokes=True)
        ]
        pieces: list[tuple[list, str, float]] = []
        for pts, attrs, width_mm in flat:
            subs = [pts]
            for poly in exclude_polys:
                if not poly:
                    continue
                subs = [
                    out_pl
                    for pl in subs
                    for out_pl in layer_clip._clip_polyline_outside_polygon(pl, poly)
                ]
            for pl in subs:
                if len(pl) >= 2:
                    pieces.append((pl, attrs, width_mm))
        entries.append({
            "polylines": [
                [(layer.x + s * px, layer.y + s * py) for px, py in pl]
                for pl, _attrs, _w in pieces
            ],
            # The layer transform scales rendered stroke widths too.
            "widths": [w * s for _pl, _attrs, w in pieces],
            "occludes": layer in occluders,
        })
        attrs_per_layer.append([attrs for _pl, attrs, _w in pieces])

    clipped = hlr.occlude_stack(entries)

    baked: dict[str, str] = {}
    for layer, layer_pieces, attrs_list in zip(participating[1:], clipped[1:],
                                               attrs_per_layer[1:]):
        # participating[0] is the nearest occluder: nothing above clips it, so
        # it keeps its normal (unbaked) emission path.
        s = float(layer.scale or 1)
        out = []
        for pts, src_index in layer_pieces:
            local = [((x - layer.x) / s, (y - layer.y) / s) for x, y in pts]
            out.append(layer_clip.polyline_path_el(local, attrs_list[src_index]))
        baked[layer.id] = "\n".join(out)

    if len(_HLR_CACHE) >= _HLR_CACHE_MAX:
        _HLR_CACHE.pop(next(iter(_HLR_CACHE)))
    _HLR_CACHE[key] = baked
    return baked


def compose_visible_svg(comp: Composition, on_progress=None) -> str:
    """Compose all visible layers into one page SVG.

    ``on_progress(done, total)`` is called before each layer (``done`` = layers
    finished so far) and once at completion. Raising from it aborts the compose,
    which the server uses for cancellation.
    """
    body = []
    visible = [layer for layer in comp.layers if layer.visible]
    total = len(visible)
    baked = _strokes_occlusion_bodies(visible)
    page_w, page_h = comp.page["width"], comp.page["height"]
    needs_page_clip = False
    for index, layer in enumerate(visible):
        if on_progress:
            on_progress(index, total)
        if layer.id in baked:
            layer_body = baked[layer.id]
        else:
            exclude_masks = _upper_occlusion_masks(visible, index,
                                                   skip_strokes=bool(baked))
            layer_body = _layer_body(layer, exclude_masks)
        # A layer dragged (partly) off the page keeps overflowing freely in the
        # preview, but its plotted/exported geometry must stay on the page.
        rb = rotated_page_bounds(layer)
        clipped = bool(layer_body.strip()
                       and (rb["x"] < -1e-6 or rb["y"] < -1e-6
                            or rb["x"] + rb["width"] > page_w + 1e-6
                            or rb["y"] + rb["height"] > page_h + 1e-6))
        needs_page_clip = needs_page_clip or clipped
        group = (
            f'<g data-layer-id="{_attr(layer.id)}" data-layer-name="{_attr(layer.name)}" '
            f'transform="{_layer_transform(layer)}">'
            f"{layer_body}</g>"
        )
        if clipped:
            # An outer group so the clip resolves in page mm, untouched by the
            # layer transform (clip-path on the transformed group would rotate
            # and scale the page rect along with the content).
            group = f'<g clip-path="url(#page-clip)">{group}</g>'
        body.append(group)
    if needs_page_clip:
        body.insert(0, (f'<defs><clipPath id="page-clip" clipPathUnits="userSpaceOnUse">'
                        f'<rect x="0" y="0" width="{_fmt(page_w)}" '
                        f'height="{_fmt(page_h)}"/></clipPath></defs>'))
    if on_progress:
        on_progress(total, total)
    return _svg_document(comp.page["width"], comp.page["height"], "\n".join(body))


def layer_bound_svg(layer: CompositionLayer) -> str:
    bounds = effective_bounds(layer)
    body = _layer_body(layer)
    s = float(layer.scale or 1)
    crop = layer.crop
    ox = float(crop.get("x", 0) or 0) if crop else 0.0
    oy = float(crop.get("y", 0) or 0) if crop else 0.0
    # Map content coords -> the (scaled, cropped) document: scale then shift the
    # crop origin to (0,0). transform list applies right-to-left.
    parts = []
    if ox or oy:
        parts.append(f"translate({_fmt(-s * ox)} {_fmt(-s * oy)})")
    if s != 1:
        parts.append(f"scale({_fmt(s)})")
    if parts:
        body = f'<g transform="{" ".join(parts)}">{body}</g>'
    return _svg_document(bounds["width"], bounds["height"], body)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned or "Layer"


def layer_svg_zip(comp: Composition, on_progress=None) -> bytes:
    """Zip one SVG per visible layer plus a manifest.

    ``on_progress(done, total)`` follows the same contract as
    ``compose_visible_svg``; raising from it aborts the export.
    """
    manifest = {"page": comp.page, "layers": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        visible = [layer for layer in comp.layers if layer.visible]
        total = len(visible)
        for index, layer in enumerate(visible):
            if on_progress:
                on_progress(index, total)
            filename = f"{index:02d}_{safe_name(layer.name)}.svg"
            zf.writestr(filename, layer_bound_svg(layer))
            manifest["layers"].append(
                {**layer.to_dict(include_svg=False), "filename": filename, "order": index}
            )
        if on_progress:
            on_progress(total, total)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()
