# Spokes & Circles Pen Stagger Design

## Context

The Spokes & Circles generator can assign pens per ring. In that mode, every circle cluster currently uses the same pen for the same ring index, producing aligned color rows. The generator needs an optional progressive offset so adjacent clusters can form diagonal or rotating color patterns without changing the drawing set.

## User-facing behavior

Add an integer **Circle stagger** parameter to the existing **Pens** group:

- parameter name: `pen_circle_stagger`
- default: `0`
- minimum: `0`
- maximum: `32`
- active behavior: only when **Circles** is set to `per_ring`

A value of `0` preserves the current aligned rows. A value of `1` advances each successive cluster by one pen; `2` advances it by two pens, and so on. Pen indices continue to wrap around the enabled drawing-set pens downstream.

The existing **Pen offset** remains the global starting pen. The existing **Order** setting controls the direction of both the ring sequence and the progressive cluster shift.

## Assignment rule

For zero-based cluster index `s`, one-based ring index `c`, and configured stagger `stagger`, the logical cycle position is:

```text
(c - 1) + s * stagger
```

That position is passed through the existing bucket function, which applies `pen_offset` and forward/reverse order. No additional modulo is needed in the generator because the worker already maps buckets to the live enabled pen list.

Example with three pens and stagger `1`:

```text
cluster 0: A B C A ...
cluster 1: B C A B ...
cluster 2: C A B C ...
```

## Compatibility and scope

- Default output is unchanged because `pen_circle_stagger` defaults to `0`.
- `per_cluster` and `off` circle modes are unchanged.
- Spoke, ray, border, crop, and margin pen assignments are unchanged.
- The schema-driven Generate panel will render the new numeric control automatically; no dedicated frontend component is required.
- Saved layers and older project payloads remain compatible because missing parameters receive the schema default.

## Testing

Extend `tests/test_generate_pens.py` with exact bucket-sequence assertions for:

- stagger `0`, preserving aligned per-ring colors;
- stagger `1`, shifting each cluster by one position;
- stagger `2`, shifting each cluster by two positions;
- stagger combined with reverse order and a nonzero pen offset.

Also assert that the generator schema exposes `pen_circle_stagger` with the documented default and bounds. Existing pen-distribution and frontend contract tests remain part of final verification.
