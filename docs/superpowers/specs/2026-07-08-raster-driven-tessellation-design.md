# Raster-Driven Tessellation

## Goal

Add a plotter-safe tessellation family that repeats vector tiles across a
raster image and changes each tile's geometry continuously according to the
local image tone. Ship several built-in patterns and extend the Cavalry bridge
so artists can bake reusable custom patterns by linking one or more numeric
Cavalry parameters to light and dark boundaries.

## Scope

This feature includes:

- four built-in tessellations: Isometric Y, Hex Aperture, Truchet Weave, and
  Diamond Lattice;
- a reusable vector-state pattern format and renderer;
- a local custom-pattern library discovered by the existing PFM browser;
- a Cavalry bridge workflow for defining a lattice, binding numeric
  parameters, baking 32 vector states, and installing or replacing a pattern;
- common PlotterForge controls for scale, placement, tone response, inversion, and
  duplicate-line removal;
- validation, transactional installation, previews, and automated tests.

The following are deliberately deferred:

- a native PlotterForge pattern editor;
- a separate response curve for each Cavalry binding;
- non-numeric or discrete Cavalry attributes;
- independent raster channels or fields for different bindings;
- evaluating Cavalry once per output tile;
- cloud sharing or a public pattern marketplace.

The data model reserves an optional per-binding curve field so adding separate
curves later does not require a pattern-format migration.

## User Experience

### Built-in patterns

The Path Finding style browser gains a **Tessellation** family containing the
four built-ins. Each entry has a normal preview image and participates in the
existing per-layer Path Finding workflow.

Selecting a tessellation shows these controls:

- **Columns**: number of repeats across the prepared source image. Expressing
  scale as a repeat count, rather than source pixels, keeps draft and final
  generation visually consistent.
- **Rotation**: rotates both lattice vectors and tile artwork around the page
  origin.
- **Phase X** and **Phase Y**: translate the lattice by a fraction of a repeat.
- **Tone response**: a positive gamma applied to normalized image darkness.
- **Invert tone**: swaps light and dark interpretation.
- **Remove duplicate lines**: removes coincident tile-border segments and is
  enabled by default.
- the shared brightness and contrast parameters already appended to every PFM.

Region masks, drawing-area clipping, pen distribution, live draft, composition
placement, preview, versioning, SVG export, and plotting continue through the
existing paths.

### Cavalry authoring

The existing `cavalry/plotter-bridge.js` window keeps its Live capture controls
and adds a **Tessellation Pattern** section with:

- a pattern-name field;
- a lattice preset: Rectangular, Brick, Hex/Isometric, or Custom;
- editable custom vectors `A(dx, dy)` and `B(dx, dy)` when Custom is selected;
- a binding table with Layer, Parameter, Light, Dark, and Remove columns;
- **Add selected parameter** and **Bake to PlotterForge** buttons;
- bake progress from state 1 through state 32 and a concise final status.

The bridge lists script-visible scalar numeric attributes for the selected
layer. Adding an attribute creates a binding row whose light and dark values
are edited directly in the bridge. Multiple bindings share the same normalized
tone value and sweep together; reversing a row's boundaries reverses that
parameter without a separate invert option.

The Cavalry composition contains the artwork for one repeat unit. The selected
lattice preset derives repeat vectors from the composition bounds; Custom uses
the entered vectors. Artwork may extend outside the fundamental cell so
interlocking motifs can cross repeat boundaries.

Pressing Bake performs the following sequence:

1. Validate the name, non-degenerate lattice, and at least one finite numeric
   binding.
2. Save the current value of every bound attribute.
3. For each state index `i` from 0 through 31, calculate `t = i / 31`, set every
   binding to `light + t * (dark - light)`, and render the unit artwork to SVG.
4. Upload the manifest and rendered states into a temporary server-side import
   session.
5. Restore all original attribute values in a guaranteed cleanup path,
   including render, upload, and validation failures.
6. Ask PlotterForge to validate and atomically install the complete package.

The bridge bakes linearly. Tone response remains a PlotterForge rendering control,
so the artist can tune the source-image mapping without rebaking Cavalry.

Rebaking the same normalized pattern name replaces that library entry
atomically. Existing generated layer SVGs do not change automatically; the new
pattern is used the next time the artist explicitly regenerates such a layer.

## Pattern Model

A pattern package has format version 1 and contains:

- stable identifier derived from the normalized name;
- display name and source (`builtin` or `cavalry`);
- two finite, non-collinear normalized lattice vectors;
- unit-artwork bounds;
- exactly 32 ordered states;
- zero or more Cavalry binding records containing layer identity, attribute
  identity, light value, dark value, and nullable future curve metadata;
- a generated preview image;
- creation and update timestamps for custom patterns.

Each state contains normalized plotter polylines. A polyline records its point
list and whether it is closed. Cavalry SVG is parsed and flattened during
installation; generation never reparses SVG. Curves are flattened with the
same fidelity conventions used by existing Cavalry/imported SVG plotting.

Built-ins are constructed through the same pattern-model interface. Their 32
states are generated deterministically from compact procedural definitions,
then consumed by the same placement, tone selection, interpolation, and
deduplication code as custom packages.

Custom patterns live under the PlotterForge workspace in a dedicated pattern
library and are loaded into the PFM registry at server startup. A successful
installation also registers or replaces the PFM immediately, so restarting the
app is unnecessary. Custom PFMs use stable IDs beneath a reserved
`tessellation_custom_` prefix and appear in the existing style list and schema
endpoints.

Generated composition layers remain self-contained SVG layers. If a custom
pattern later goes missing, saved projects still display, export, and plot the
last generated SVG; only a regeneration attempt reports the missing pattern.

## Rendering Algorithm

The renderer receives a prepared image, validated common parameters, and one
pattern definition.

1. Convert the image to luminance and alpha using the existing image helpers.
2. Scale the lattice so vector A produces the requested number of Columns
   across the prepared image, then apply rotation and phase to both lattice and
   artwork.
3. Enumerate enough integer lattice coordinates to cover the image plus one
   repeat of overscan on every side.
4. For each tile, average luminance and alpha over its fundamental-cell
   footprint. Skip cells whose mean alpha coverage is below 0.05.
5. Convert mean luminance to darkness `d` in `[0, 1]`, optionally invert it,
   then calculate `u = d ** tone_response`.
6. Map `u` to the 32-state interval. Let `lo` and `hi` be adjacent state indices
   and retain the fractional remainder `f`.
7. If the adjacent states have equal path counts and matching closed flags and
   point counts for every corresponding path, linearly interpolate every point
   by `f`. Otherwise select the nearer complete state.
8. Transform the chosen/interpolated unit geometry to the tile position and
   append plotter `Geometry` items using the tile darkness as `Item.lum`.
9. When duplicate removal is enabled, split paths into segments, remove exact
   coincident segments after tolerance-aware endpoint normalization, and chain
   the surviving segments back into efficient paths.
10. Return normal PFM items. Existing pen distribution and drawing-area
    clipping finish the drawing.

Tone averaging uses the actual parallelogram footprint rather than only the
center pixel. This makes parameter changes stable at useful tile sizes and
keeps oblique lattices aligned with what they sample.

## Built-in Pattern Behaviour

All four built-ins morph geometry rather than merely changing stroke opacity:

- **Isometric Y** reproduces the reference's interlocking three-arm relief.
  Darkness opens the central void and retracts the three arms while preserving
  the isometric repeat.
- **Hex Aperture** opens and closes a six-sided aperture inside a honeycomb
  lattice.
- **Truchet Weave** changes paired ribbon curvature and crossing separation
  inside a square repeat while preserving edge connections.
- **Diamond Lattice** changes inset depth and diagonal spread within an oblique
  diamond repeat.

The light and dark endpoints remain plotter-readable and periodic. Intermediate
states do not introduce fills; the visual weight comes from line geometry and
negative space.

## Backend Interfaces and Storage

The server adds pattern-library endpoints for:

- listing installed custom patterns and their metadata;
- creating a temporary Cavalry bake session;
- uploading its manifest and indexed SVG states;
- finalizing, validating, previewing, and atomically installing the session.

Session identifiers are random and scoped to temporary storage. Finalization
requires one manifest and all 32 unique state indices. State uploads may arrive
only once per index. Temporary sessions are removed after success, explicit
failure, or expiry.

The format and endpoints enforce these version-1 limits:

- exactly 32 states;
- at most 8 MiB per SVG state and 128 MiB for the complete uncompressed bake;
- at most 2,000 paths and 200,000 flattened points per state;
- at most 16 linked parameters;
- finite coordinates with an absolute magnitude no greater than 1,000,000;
- non-zero, non-collinear lattice vectors;
- pattern names from 1 through 80 visible characters.

The server rejects malformed XML, active content, external references,
unsupported SVG constructs that cannot become plot paths, non-finite numeric
values, mismatched metadata, missing states, and limit violations. It stages a
validated package and preview beside the library, then uses an atomic rename to
replace the active entry. The old entry survives any failure before that
rename.

## Error Handling

- Cavalry-side validation failures are shown before attribute values change.
- The bridge restores all bound attributes after every bake attempt.
- A state render or upload failure stops the bake and identifies the failing
  state without installing partial content.
- PlotterForge import failures return a concise user-facing error while retaining
  diagnostic detail in the existing server log.
- Custom-pattern load failures are isolated: one corrupt package does not stop
  built-ins or other custom patterns from registering.
- Regenerating a layer whose pattern is unavailable sets the existing layer
  Path Finding error state and preserves its cached SVG.
- Rendering enforces the existing cancellation and progress conventions and
  caps tile enumeration to prevent accidental runaway output.

## Testing and Verification

Engine tests cover:

- luminance-to-state mapping, inversion, and gamma response;
- raster averaging over rectangular and oblique footprints;
- lattice scale, rotation, phase, overscan, and page coverage;
- exact interpolation for compatible states;
- nearest-state fallback for path-count, closure, and point-count changes;
- transparent-cell skipping;
- tolerance-aware duplicate segment removal and path rechaining;
- deterministic, non-empty, periodic output for all four built-ins;
- stable density between draft and full-size generation.

Pattern-library and API tests cover:

- manifest and state validation;
- every size, count, numeric, lattice, and naming limit;
- rejection of malformed or active SVG content;
- missing, duplicate, and out-of-range state indices;
- complete installation, immediate PFM discovery, and preview creation;
- atomic replacement and preservation of the old package after failure;
- cleanup of failed and expired temporary sessions;
- isolation of a corrupt library entry at startup;
- preservation of cached layer SVG when a custom pattern is missing.

Cavalry bridge contract tests cover the new controls, binding interpolation,
32-state loop, original-value restoration, state upload ordering, finalization,
and error statuses. The script receives JavaScript syntax validation. A real
Cavalry smoke test verifies numeric-attribute discovery, a two-parameter bake,
Rectangular and Custom lattices, restoration after success, and restoration
after a forced server error when Cavalry is available in the test environment.

Frontend and end-to-end tests verify the Tessellation family label, built-in
previews, custom-pattern discovery after installation, parameter controls,
draft regeneration, full regeneration, and a saved layer's continued display
when its custom package is unavailable. The complete Python and frontend suites
must remain green.

## Delivery Sequence

Implementation is one vertical feature delivered in four testable increments:

1. Pattern model, tone/lattice renderer, interpolation, and duplicate removal.
2. Four built-in pattern definitions, PFM registration, controls, and previews.
3. Persistent custom-pattern library and transactional import endpoints.
4. Cavalry binding UI, state baking, upload/finalization, and end-to-end
   discovery.

The native in-app editor can later produce the same version-1 package format;
it does not require a second renderer or a migration of existing patterns.
