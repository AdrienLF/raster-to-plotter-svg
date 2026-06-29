# Spokes & Circles Crop Clipping Design

## Problem

The Spokes & Circles generator can leave background rays inside circle-cluster crops. Its structural spokes are also currently exempt from those crops, although the intended behavior is for every straight line to disappear inside each cluster.

The ray leak comes from `convex_interval` treating an almost-closed polygon ring as open. Circle builders calculate their last vertex independently, so floating-point rounding makes it microscopically different from the first vertex. The clipper then adds a near-zero closing edge, which can incorrectly reject a real segment/polygon intersection. With overlapping cluster crops, later clipping exposes the missed portions seen in the preview and exported geometry.

## Required Behavior

- Every background ray and structural spoke is clipped outside every circle-cluster crop.
- Circle outlines remain unchanged and visible.
- The crop polygon continues to use `circle_segments` and `circle_rotation`, including deliberately low-sided polygonal circles.
- `draw_crop_radius` continues to control only whether the crop outline itself is drawn.
- The fix applies to generated SVG geometry, so preview, export, and plotting agree.
- Existing composition-layer crop and mask behavior is out of scope.

## Design

### Robust convex rings

Harden `engine.genframe.convex_interval` at the shared geometry boundary. Before computing the polygon centroid and edges, normalize a terminal vertex that is within a small absolute tolerance of the first vertex. Build one closing edge from the resulting unique vertices and ignore degenerate polygons with fewer than three vertices.

This fixes the source of the floating-point failure for both Spokes & Circles and the framework's polygonal Circle Crop controls. It is preferable to changing individual circle builders because any caller can supply an approximately closed ring.

### Crop all straight lines

In `engine.generate.spokes_and_circles`, keep circle outlines separate from the generator's straight lines. Put both background rays and structural spokes through the same sequence of cluster crop polygons before assembling the final output. A spoke therefore stops at the first crop boundary it reaches and never continues to the cluster center.

No SVG `clipPath` will be introduced; clipping remains baked into polylines so downstream plotting code sees the same geometry as the browser.

## Error Handling and Compatibility

`convex_interval` will return no intersection for polygons with fewer than three usable vertices instead of attempting invalid centroid or edge calculations. Boundary-touching segments remain valid: only a positive-length interval inside a crop is removed.

No API, saved-project schema, parameter name, or frontend control changes are required.

## Tests

Add focused regression coverage for:

1. An approximately closed convex ring produces the same segment interval as an exactly closed ring.
2. Spokes & Circles emits no positive-length background-ray segment inside any cluster crop, including overlapping default crops that reproduced the leak.
3. With rays disabled, a structural spoke is cut at the crop boundary and has no positive-length segment inside its cluster.

Run the focused generator tests first, then the complete Python test suite. The implementation follows red-green-refactor: each regression test must fail for the diagnosed behavior before production code changes are made.
