# Composition Layers Design

Date: 2026-06-25

## Goal

Make PlotterForge layer-based. Path Finding, Generate, SVG import, export, and plotting should all work through one shared composition document. The physical plotting page is always A3 portrait, while each layer keeps its own artwork bounds and can be moved freely on that A3 page.

## Current Context

The app currently has workflow steps for Path Finding, Generate, and Plot. The viewport previews a single `previewSvg`, and plotting applies a single `{x, y}` placement offset to that SVG. Drawing Area presets change the generated SVG page size, but there is no persistent composition document or layer list. Export also has two separate code paths: `_drawing` exports use engine drawings, while generator/upload exports return `_current_svg` directly.

This creates an unclear model: an A4 drawing area can exist, but it is not clearly an A4 layer placed on an A3 plot page.

## Chosen Approach

Add a real composition document as the source of truth.

The workflow becomes:

```text
Path Finding -> Generate -> Composition -> Plot
```

The composition page is fixed at A3 portrait:

```json
{ "width": 297, "height": 420, "units": "mm" }
```

Every generated, pathfinding, or imported SVG output becomes a layer in that composition. The selected layer is the target for Generate and Path Finding. Rerunning a generator or pathfinding module replaces the selected layer in place. Versions remain manual snapshots and are not created automatically.

## Data Model

Persist composition state in the existing project workspace. Store large SVG layer artwork as files under the project directory instead of embedding all SVG text directly into `project.json`.

Composition fields:

- `page`: fixed A3 page metadata.
- `selected_layer_id`: the active layer for Generate, Path Finding, and Composition editing.
- `layers`: ordered bottom-to-top list.

Layer fields:

- `id`: stable unique id.
- `name`: editable display name.
- `kind`: `generate`, `pathfinding`, or `svg`.
- `visible`: whether the layer participates in preview, export, estimate, and plot.
- `x`, `y`: layer position in millimetres from the A3 page top-left.
- `width`, `height`: artwork bounds in millimetres, parsed from the layer SVG.
- `svg_path`: file path relative to the project directory.
- `source`: regeneration metadata, including generator/PFM id, params, drawing area, and drawing set where relevant.

Layer bounds are the size of their content. A layer generated from an A4 drawing area is approximately 210 x 297 mm. It defaults to `x = 0`, `y = 0` on the fixed A3 page, so A4 presets align to the top-left of the A3 plot area by default.

## UI Design

The viewport always displays the fixed A3 page whenever artwork exists. Visible layers render in stack order at their `x/y` positions. In the Composition step, the selected layer can be dragged freely. Alignment controls apply to the selected layer against the A3 page.

Path Finding panel:

- Add a layer selector at the top.
- If no layer exists, processing creates the first layer.
- If a layer is selected, processing replaces only that layer's artwork and source metadata.

Generate panel:

- Add the same layer selector at the top.
- The generator controls apply only to the selected layer.
- Running Generate replaces only that layer's artwork and source metadata.

Composition panel:

- Show a Photoshop-like layer list.
- Support selecting layers.
- Support visibility toggles.
- Support renaming.
- Support duplicate, delete, move up, and move down.
- Show numeric `x` and `y` fields in millimetres for the selected layer.

Plot panel:

- Plot and estimate use the composed visible-layer SVG on the fixed A3 page.
- Plotter paper settings should no longer redefine the composition page size. The plot page is A3.

## SVG Composition

Introduce backend helpers to parse SVG dimensions and compose layers.

Composed SVG:

- `width="297mm"` and `height="420mm"`.
- `viewBox="0 0 297 420"`.
- Includes visible layers only.
- Wraps each layer's inner SVG content in a translated group:

```xml
<g data-layer-id="..." transform="translate(x y)">...</g>
```

Layer SVG normalization should preserve the artwork relative to the layer's own top-left bounds. If a source SVG has a non-zero viewBox origin, composition should account for that so the layer still behaves as content with top-left at `(0, 0)` inside its own bounds.

## Export

Export must be rebuilt around composition.

`/api/export` returns one composed A3 SVG containing all visible layers at their current A3 positions.

`/api/export?split=1` returns a zip with one SVG per visible layer. Each layer SVG uses that layer's own current bounds, not the A3 page. For example:

- An A4 layer exports as a 210 x 297 mm SVG.
- A 120 x 80 mm generated layer exports as a 120 x 80 mm SVG.

Split layer exports should bake the layer artwork relative to its own top-left bounds, so opening the file alone shows only that layer content without A3 whitespace. Include a manifest in the zip with each layer's composition `x/y`, order, visibility, id, and name so placement can be reconstructed later if needed.

## Plotting

Plot estimate, plot job creation, resume, and export should all read from the same composed visible-layer SVG. This removes the old split between `_drawing`, `_current_svg`, and placement-only plotting.

The plotter should interpret the SVG as an A3 document. Hidden layers must not contribute paths, estimates, or plot jobs.

## Versioning

Manual saved Versions remain explicit snapshots. The first implementation can keep versioning for engine `Drawing` results as-is, but the target model is for a saved version to snapshot the composition state and layer artwork references. Running Generate or Path Finding must not create a version automatically.

## Testing

Add focused tests for:

- A4 drawing-area preset produces an A4-sized layer that defaults to `x = 0`, `y = 0` on A3.
- Composed export has A3 dimensions and translates visible layers correctly.
- Hidden layers are excluded from composed export and plot estimates.
- Split export emits per-layer SVGs at layer bounds, not A3 bounds.
- Split export includes a manifest with layer placement metadata.
- Replacing the selected layer updates only that layer.
- Existing placement helper tests continue covering align, snap, and clamp behavior.

## Migration

On boot, if a legacy `_current_svg` or uploaded/generated SVG exists but no composition layer exists, create a single visible layer from it at `x = 0`, `y = 0`. Existing projects without composition data should open with an empty A3 composition and keep their saved drawing area, pens, pathfinding settings, and versions.

## Non-Goals

- Automatic version creation.
- Layer blending modes or opacity.
- Multi-select transforms.
- Rotation and scale handles.
- Nested groups or masks.
