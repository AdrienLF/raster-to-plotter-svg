# Cavalry Tessellation Documentation Design

## Goal

Document Cavalry-authored tessellations for both artists and developers without
turning the main README or the in-app manual into an implementation dump.

## Audiences

- **Artists using Cavalry and PlotterForge** need a visual-language-first
  explanation of repeat units, light/dark parameter boundaries, lattice presets,
  baking, rebaking, and what happens when something fails.
- **Developers and maintainers** need the package contract, API sequence, limits,
  storage locations, replacement semantics, and verification commands.

## Deliverables

### In-app artist manual

Add `web/static/docs/tessellations.html` in the existing manual style. Link it
from a new card on `web/static/docs/index.html` and from the manual footer.

The chapter will cover:

1. what a raster-driven tessellation is;
2. preparing one repeat unit in an active Cavalry composition;
3. adding one or more selected numeric attributes;
4. setting Light and Dark endpoints;
5. choosing Rectangular, Brick, Hex/Isometric, or Custom vectors;
6. baking 32 states and finding the installed style in PlotterForge;
7. tuning Columns, Rotation, Phase, Tone Response, inversion, and duplicate-line
   cleanup without rebaking;
8. safe rebaking and restoration of original Cavalry values;
9. practical troubleshooting and the five-case smoke checklist.

The manual will avoid protocol details except where they explain artist-visible
behavior. It will use the existing typography, cards, steps, notes, tables, and
footer conventions. If the installed Cavalry app can be staged and captured
cleanly, add real screenshots of the bridge's tessellation authoring controls
and a finished installed pattern. The written workflow must remain complete
without the images so GUI automation or capture permissions cannot block the
documentation.

### Repository guide

Add `docs/cavalry-tessellations.md` as the durable user/developer reference.
It will repeat the concise artist workflow, then add:

- installation of `cavalry/plotter-bridge.js`;
- the 32-state model and shared tone axis;
- manifest and binding fields;
- session creation, indexed SVG upload, finalization, and listing endpoints;
- package validation and size/path/point limits;
- storage under `~/.plotterforge/tessellations/`;
- atomic replacement and startup registration;
- cached-layer behavior when a package is missing;
- focused verification commands and the manual smoke checklist.

### README discovery

Add a short Cavalry tessellation section to `README.md` with links to the
repository guide and the in-app manual URL. Keep the README entry short enough
that it remains orientation rather than a second manual.

## Consistency and validation

- Add a frontend/documentation contract test confirming the manual home page,
  manual chapter, and README links remain present.
- Check all documented field names, endpoint paths, limits, storage paths, and
  UI labels against the implementation.
- Run the focused documentation contract test and `git diff --check`.
- Reload `http://localhost:7438/static/docs/index.html` in the in-app browser,
  open the new chapter, and inspect the rendered desktop layout and navigation.
- When screenshots are captured, verify that they contain no unrelated project
  data and render legibly at the manual's content width.

## Non-goals

- No generated or mock Cavalry screenshots presented as the real application.
- No duplicate copy of the full implementation plan.
- No public plugin SDK or third-party package distribution workflow.
- No behavioral changes to the tessellation engine, API, or Cavalry script.
