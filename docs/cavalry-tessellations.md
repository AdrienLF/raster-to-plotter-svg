# Cavalry-authored tessellations

PlotterForge can turn a Cavalry composition into a reusable Path Finding
Module in the **Tessellation** family. Cavalry bakes one repeat unit at 32 tone
states; PlotterForge then repeats those vector states over any source image, choosing
lighter or darker states from the image tone.

This guide is both the artist workflow and the developer contract for the
Cavalry bridge, storage format, HTTP sequence, and validation limits.

## Artist workflow

1. Start PlotterForge with `./start-macos.command` on macOS or
   `start-windows.bat` on Windows. The local server listens on
   `http://localhost:7438`.
2. Install `cavalry/plotter-bridge.js` in Cavalry: open
   **Help > Show Scripts Folder**, copy the file there, then run it from
   **Window > Scripts > plotter-bridge**. The script window is titled
   **Plotter Bridge**.
3. In Cavalry, prepare one repeat unit in the active composition. The artwork
   should describe a single tile, not a whole page. The active composition
   resolution becomes the bake bounds.
4. In the bridge's **Tessellation** section, enter **Name**. Pattern names must
   be 1-80 visible characters.
5. Select exactly one finite numeric Cavalry attribute and click
   **Add selected parameter**. Each binding stores the selected layer and
   attribute, plus **Light** and **Dark** values. Repeat for up to 16 bindings.
6. Set each binding's **Light** value for the lightest source-image tones and
   **Dark** value for the darkest source-image tones. All bindings share one
   32-state tone axis, so every linked Cavalry value is interpolated together.
7. Choose a **Lattice** preset and set **W** and **H**, or choose **Custom** and
   set **Custom A** and **B** vectors.
8. Click **Bake tessellation**. The bridge creates a session, renders and uploads
   32 SVG states, finalizes the package, restores your original Cavalry values,
   and reports **Installed <name>** when PlotterForge accepts it.
9. In PlotterForge, add or edit a path-finding layer, choose a style from the
   **Tessellation** family, then click **Apply / Regenerate**. The installed
   pattern uses the same controls as the built-in tessellations.

PlotterForge controls for every tessellation pattern:

| Control | Effect |
| --- | --- |
| **Columns** | Pattern repeats across the page width. More columns make smaller tiles. |
| **Rotation** | Rotates the whole lattice around the page. |
| **Phase X** | Slides the lattice along its first axis, in tile units. |
| **Phase Y** | Slides the lattice along its second axis, in tile units. |
| **Tone Response** | Gamma applied before choosing a state. Values above 1 favor lighter states. |
| **Invert Tone** | Swaps which states dark and light image tones use. |
| **Remove Duplicate Lines** | Drops shared tile edges and welds the remaining strokes into longer lines. |

## Lattice presets

The bridge sends lattice vectors in Cavalry composition units. PlotterForge normalizes
them by the active composition bounds before storing the package.

| Preset | Vectors sent by the bridge | Use it for |
| --- | --- | --- |
| **Rectangular** | `a = [W, 0]`, `b = [0, H]` | Straight rows and columns. |
| **Brick** | `a = [W, 0]`, `b = [W / 2, H]` | Offset rows, masonry, scales, woven repeats. |
| **Hex/Isometric** | `a = [W, 0]`, `b = [W / 2, H * 0.8660254038]` | Triangular or hexagonal rhythm. |
| **Custom** | `a = [Custom A x, Custom A y]`, `b = [B x, B y]` | Any finite, non-collinear repeat vectors. |

Invalid or collinear vectors are rejected before the bake changes attribute
values.

## Rebaking and recovery

Custom pattern IDs are derived from the visible name. Reusing the same name
replaces the existing package atomically: the new package is staged, validated,
written, and then swapped into
`~/.plotterforge/tessellations/<pattern-id>/`. If the final rename fails, the
previous package is restored.

The Cavalry bridge records the original value of every bound attribute before
baking. It restores those original Cavalry values in a `finally` block after
success or failure, so a failed session should not leave the scene stuck on one
of the 32 sampled states.

Already generated PlotterForge layers keep their cached SVG geometry. If a project is
opened later and the custom tessellation package is missing, the existing cached
SVG survives, but the layer cannot regenerate that style until the package is
installed again.

## Package format

A package is a JSON manifest plus exactly 32 raw SVG state uploads. The server
normalizes that input into a stored `pattern.json` and `preview.png`.

Manifest fields:

| Field | Required value |
| --- | --- |
| `format_version` | Manifest version `1`. |
| `name` | Pattern name, trimmed to 1-80 visible characters. |
| `lattice.a` | Two finite numbers for the first repeat vector. |
| `lattice.b` | Two finite numbers for the second repeat vector. |
| `bounds` | `[minx, miny, maxx, maxy]` from the active Cavalry composition resolution. |
| `bindings` | Zero or more binding records. The bridge requires at least one before baking. |

Binding fields:

| Field | Meaning |
| --- | --- |
| `layer_id` | Cavalry layer ID captured from the selected numeric attribute. |
| `attribute_id` | Cavalry attribute ID captured from the selected numeric attribute. |
| `light` | Attribute value for the lightest state. |
| `dark` | Attribute value for the darkest state. |
| `curve` | Shared PlotterForge tone-response curve data. The current bridge sends `null`. |

Stored packages contain normalized unit-square tile paths, the normalized
lattice vectors, the original binding metadata, and an update timestamp. SVG
curves are flattened during validation, active or external SVG content is
rejected, and only drawable path-like shapes are kept.

## HTTP API

The Cavalry bridge uses these local endpoints on `http://localhost:7438`.

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /api/tessellations/sessions` | JSON manifest. | `{ "session_id": "<32 hex chars>" }`. |
| `POST /api/tessellations/sessions/<session_id>/states/<index>` | Raw SVG for `index` 0-31. | `{ "ok": true, "index": <index> }`. |
| `POST /api/tessellations/sessions/<session_id>/finalize` | Empty body. | Installed pattern metadata and refreshed PFM list. |
| `GET /api/tessellations` | No body. | Installed custom package records. |

Session directories live under `~/.plotterforge/tessellation-imports/` while
the bake is in progress. A session expires after one hour. Unknown, malformed,
or expired session IDs return 404. Uploading the same state index twice returns
409. Missing states at finalize time delete the session and return 400.

Custom preview images are served from
`/static/pfm-previews/<pattern-id>.png` for custom IDs matching
`tessellation_custom_[a-z0-9_]+`.

## Limits

Validation is intentionally strict because the bridge sends untrusted SVG:

| Limit | Value |
| --- | --- |
| States per package | Exactly 32. |
| SVG state size | 8 MiB per SVG. |
| Package upload size | 128 MiB total. |
| Bindings | 16 bindings maximum. |
| Paths per state | 2,000 paths. |
| Flattened points per state | 200,000 points. |
| Coordinate magnitude | 1,000,000 absolute value maximum. |
| Pattern name | 1-80 visible characters after trimming. |
| Format version | `1` only. |

SVG validation rejects malformed XML, `<script>`, `<image>`,
`<foreignObject>`, `<use>`, `href`, `xlink:href`, `onload`, and `onclick`.
Bounds must have positive width and height, and lattice vectors must be finite
and non-collinear.

## Storage and startup

Installed packages are stored at
`~/.plotterforge/tessellations/<pattern-id>/` with:

- `pattern.json` - normalized paths, lattice, bindings, source, and timestamp.
- `preview.png` - a 105 x 148 preview rendered over a light-to-dark gradient.

At server startup, `web/server.py` loads every valid package from
`~/.plotterforge/tessellations/` and registers it with
`replace_tessellation_pattern`. Invalid package directories are skipped and
logged; other valid packages still load.

## Verification checklist

- Run the frontend documentation contract:
  `.venv/bin/python -m pytest tests/test_frontend_contracts.py::FrontendContractsTest::test_cavalry_tessellation_guides_are_linked_and_complete -q`
- Run the full frontend contracts:
  `.venv/bin/python -m pytest tests/test_frontend_contracts.py -q`
- Check whitespace:
  `git diff --check`
- Manual smoke test with real Cavalry when available:
  1. install and open `cavalry/plotter-bridge.js`;
  2. create or open a disposable repeat-unit composition;
  3. bind one numeric attribute with distinct **Light** and **Dark** values;
  4. bake and confirm the style appears in PlotterForge's **Tessellation** family;
  5. force a failed bake and confirm original Cavalry values are restored.
