# Flat-Nib Pen Preview Design

## Context

Every `Pen` (`engine/pens.py`) currently has a single `stroke_mm`, rendered everywhere as a plain, direction-independent SVG stroke (`engine/svg_io.py` `_render_layer` / `_lines_group` / `lines_to_svg`): `stroke-width="{stroke_mm}"`, round cap/join. That's an accurate model for round-tip pens (fineliners, brush pens), but not for a **flat/chisel-nib pen** (e.g. the Pilot Parallel Pen, nib widths 1.5–6mm): the mark's visible width depends on the angle between the stroke direction and the fixed angle the nib is held at. The Pens panel currently has no way to express this, and the preview always shows a uniform round stroke regardless.

The same composed SVG (`layer.svg`) that drives the on-screen preview is also what the plot pipeline parses into centerline motion (`svg_to_polylines`, `split_svg_by_pen`). The physical flat nib produces its own width mechanically — the plotter only needs the centerline. So the plotted/exported SVG must stay exactly as it is today; only the **on-screen preview** needs to change to approximate what a flat nib will actually lay down.

## Pen model

`engine/pens.py` `Pen` gains two fields, both defaulting to today's behavior:

- `nib_shape: str = "round"` (`"round" | "flat"`)
- `start_angle_deg: float = 0.0` — the fixed angle (degrees, page frame, 0–179) the flat nib is held at for the whole drawing.

Added to `to_dict`; `from_dict` already generically picks up known dataclass fields, so no other backend change is required for persistence. `frontend/src/lib/types.ts` `Pen` interface gets the matching fields.

## Pens panel

`frontend/src/components/panels/PensPanel.svelte`: each pen row gets a "flat nib" toggle. When on:

- the existing size field's label/title changes to "Nib width (mm)" (hinting the 1.5–6mm Pilot Parallel range, not enforced as a hard bound — same free-form `NumStep` as today);
- a start-angle `NumStep` (0–179°, clamped not wrapped — `NumStep` has no wrap behavior today and adding one is out of scope) appears next to it.

When off, the row is unchanged from today. `addPen()` defaults new pens to `nib_shape: "round"`.

## Preview rendering (client-side only)

`frontend/src/components/Viewport.svelte` `layerPathsUrl()` currently does `data:image/svg+xml;...${encodeURIComponent(layer.svg)}` directly. It changes to first run `layer.svg` through a new pure function, `renderFlatNibPreview(svg, pens)`, only when at least one active pen has `nib_shape === "flat"`:

1. Parse `layer.svg` with `DOMParser` (native browser API, no new dependency).
2. For each pen-stroke `<g>` (identified by `inkscape:label` matching a pen name, falling back to matching `stroke` colour only when exactly one active pen has that colour — pen colours aren't guaranteed unique, so an ambiguous colour match is treated as no-match), look up that group's pen. If it's round, or no pen matches (including arbitrary uploaded/imported `kind: 'svg'` layers with no label/colour correspondence), leave the group untouched.
3. For a flat pen's group: switch the group's paint from `fill="none" stroke="{colour}" stroke-width="…"` to `fill="{colour}" stroke="none"`, and rewrite each child `<path>`'s `d` (currently a plain `M x,y L x,y …` centerline — the only format our own generators emit) into a closed filled outline polygon:
   - for each vertex, take the local segment direction `dir` (endpoints use their one adjacent segment's direction; interior vertices average the incoming/outgoing segment directions as unit vectors — `atan2(sin1+sin2, cos1+cos2)` — never a naive scalar mean of angles, which breaks across the 0°/360° wraparound);
   - `half_width = max(0.05, (nib_width_mm / 2) * abs(sin(dir − start_angle_rad)))` (the standard calligraphy-nib projection; the `0.05` floor matches the existing minimum stroke width used elsewhere in `svg_io.py` so a nib held parallel to travel still leaves a visible hairline instead of vanishing);
   - offset each vertex ± the local normal by `half_width` to build two rails; the outline is rail A forward + rail B reversed, closed with `Z`.
4. Serialize back to a string with `XMLSerializer` and base64/URI-encode as today.

Closed paths (loops) are treated as open polylines for this approximation — the seam may show a small mismatch, which is acceptable for a preview. Dots (`<circle>`) are not affected — they carry their own `fill`/`stroke`, not inherited from the group, so the group-level paint swap in step 3 leaves them alone.

**This function must never write back to `layer.svg` or any server-persisted state** — it only produces the string passed to the `<img>` `src`. `layer.svg` itself, the composition model, `_composition_payload`, and everything in `engine/svg_io.py` used for export/plotting stay untouched — zero risk to physical plot output. (Confirmed: `layer.svg` is the same string that flows through `compose_visible_svg` into `_current_svg` → `svg_to_polylines`/`split_svg_by_pen`, and `frontend/src/lib/api.ts`'s `updateLayer` never sends SVG content back to the server — only metadata.)

## Out of scope

- No change to the exported/plotted SVG.
- No per-stroke or path-following angle (the nib angle is one fixed value for the whole drawing, matching how the pen is actually held).
- No flat-nib rendering for dots/circles.
- No enforcement of the 1.5–6mm range beyond a UI hint.

## Testing

- Frontend unit test for the outline math: a straight horizontal segment at `start_angle_deg = 90` produces full nib width; at `start_angle_deg = 0` (parallel) collapses to the `0.05` floor.
- Frontend unit test that a `nib_shape: "round"` pen's group is passed through `renderFlatNibPreview` unchanged.
- Manual check in the running app: toggle a pen to flat, set width 4mm and a couple of angles, confirm the preview strokes visibly thicken/thin with direction and the exported/plotted SVG (`/api/export` or plot) is unaffected.
