/**
 * C7 / C8 — PFM smoke matrix.
 *
 * Each test verifies one representative Path Finding Module produces non-empty
 * SVG geometry. Tests are API-level (no browser) for speed and isolation.
 *
 * C7: sampler-family × style matrix (voronoi, lbg, adaptive × stippling, shapes, tsp…)
 * C8: custom PFMs (spiral, hatch, sketch_lines, grid_halftone, streamlines_flow_field)
 */
import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject } from "./fixtures";

const SHAPE_RE = /<(path|line|polyline|circle|rect|ellipse)\b/;

/** Upload an image and add one PF layer for `pfmId`; returns { layerId }. */
async function setupPfmLayer(request: any, baseURL: string, pfmId: string, params: Record<string, unknown> = {}) {
  await freshProject(request, baseURL, `E2E smoke ${pfmId}`);
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  return { layerId };
}

/** Generate with `pfmId` and assert the layer SVG has visible geometry. */
async function assertGeometry(request: any, baseURL: string, layerId: string, pfmId: string, params: Record<string, unknown> = {}) {
  const r = await request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
    data: { pfm_id: pfmId, params },
  });
  expect(r.ok(), `${pfmId}: generate should return 2xx`).toBeTruthy();
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  const layer = composition.layers.find((l: { id: string }) => l.id === layerId);
  expect(SHAPE_RE.test(layer?.svg ?? ""), `${pfmId}: SVG should contain at least one shape element`).toBeTruthy();
}

// ── C7: Sampler-family × style representative subset ────────────────────────
// Light params (small point_density) so the matrix runs quickly.
const FAMILY_CASES: [string, Record<string, unknown>][] = [
  ["voronoi_stippling",     { point_density: 80 }],
  ["voronoi_shapes",        { point_density: 80 }],
  ["voronoi_tsp",           { point_density: 80 }],
  ["lbg_stippling",         {}],
  ["lbg_shapes",            {}],
  ["adaptive_stippling",    {}],
  ["adaptive_triangulation",{}],
];

for (const [pfmId, params] of FAMILY_CASES) {
  test(`C7: ${pfmId} produces non-empty geometry`, async ({ request, baseURL }) => {
    const { layerId } = await setupPfmLayer(request, baseURL!, pfmId, params);
    await assertGeometry(request, baseURL!, layerId, pfmId, params);
  });
}

// ── C8: Custom / standalone PFMs ─────────────────────────────────────────────
const CUSTOM_CASES: [string, Record<string, unknown>][] = [
  ["spiral",                   {}],
  ["hatch",                    {}],
  ["sketch_lines",             {}],
  ["sketch_curves",            {}],
  ["grid_halftone",            {}],
  ["random_stipple",           {}],
  ["streamlines_flow_field",   {}],
  ["differential_growth",      { iterations: 80, seed_count: 6 }],
  ["quadtree_mosaic",          {}],
];

for (const [pfmId, params] of CUSTOM_CASES) {
  test(`C8: ${pfmId} produces non-empty geometry`, async ({ request, baseURL }) => {
    const { layerId } = await setupPfmLayer(request, baseURL!, pfmId, params);
    await assertGeometry(request, baseURL!, layerId, pfmId, params);
  });
}
