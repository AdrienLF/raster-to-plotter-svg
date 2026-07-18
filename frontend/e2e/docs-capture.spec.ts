import { dirname, join } from "path";
import { fileURLToPath } from "url";
import {
  test,
  expect,
  ASSETS,
  freshProject,
  gotoApp,
  gotoStep,
  waitForGeneratedLayer,
  waitForReady,
} from "./fixtures";
import type { Page } from "@playwright/test";

// Regenerates the manual's screenshots (web/static/docs/img/*.png) from the
// live app, so they always show the current UI and branding. Not part of the
// regular e2e suite — run explicitly with:
//
//   DOCS_CAPTURE=1 npx playwright test docs-capture
//
// tutorial-source.png is a data asset (the tutorials' source image), not a
// screenshot; it is never overwritten here.
const IMG = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web", "static", "docs", "img");
const TUTORIAL_SOURCE = join(IMG, "tutorial-source.png");

test.skip(!process.env.DOCS_CAPTURE, "docs screenshot capture is opt-in (DOCS_CAPTURE=1)");

const shot = (name: string) => join(IMG, `${name}.png`);

async function importRaster(page: Page, file: string) {
  await page.locator('input[type="file"]').setInputFiles(file);
  await expect(page.locator(".menubar")).toContainText(/source|sample|tutorial/, { timeout: 15_000 });
}

async function selectLayer(page: Page, name: string) {
  await page.locator(".panel .layer", { hasText: name }).first().locator("button.pick").click();
}

async function clipAnchoredRight(page: Page, anchor: { x: number; y: number; width: number; height: number },
  width: number, height: number) {
  const viewport = page.viewportSize()!;
  const x = Math.max(0, Math.min(anchor.x + anchor.width - width, viewport.width - width));
  const y = Math.max(0, Math.min(anchor.y, viewport.height - height));
  return { x, y, width: Math.min(width, viewport.width - x), height: Math.min(height, viewport.height - y) };
}

test("capture manual screenshots", async ({ page, request, baseURL }) => {
  test.setTimeout(900_000);

  // ── Project 1: compose / generate / plot / shape dither ────────────────────
  await freshProject(request, baseURL!, "Manual");
  await page.setViewportSize({ width: 1280, height: 720 });
  await gotoApp(page);
  await importRaster(page, join(ASSETS, "sample.png"));

  // The imported raster as a freely transformable layer.
  const composition = await (await request.get(`${baseURL}/api/composition`)).json();
  const rasterId: string = composition.composition.layers.at(-1).id;
  await request.patch(`${baseURL}/api/composition/layers/${rasterId}`, {
    data: { x: 28, y: 78, scale: 0.82, rotation: 12, selected: true },
  });
  await gotoApp(page);
  await selectLayer(page, "sample");
  await expect(page.locator("#layer-rotation")).toHaveValue("12", { timeout: 10_000 });
  await page.screenshot({ path: shot("raster-layer") });

  // Spokes & Circles generator layer above it.
  await page.getByRole("button", { name: "＋ Generator" }).click();
  await expect(page.locator(".gen-select")).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "✦ Generate", exact: true }).click();
  await waitForGeneratedLayer(request, baseURL!);
  await waitForReady(page);

  // Compose view with the generator poster selected above the source layer.
  await gotoStep(page, "Compose");
  await selectLayer(page, "Spokes & Circles");
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot("composition") });

  // Generate step: parameters dock + procedural drawing.
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoStep(page, "Generate");
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot("generate-step") });

  // Plot step: Plotter panel with Estimate/Setup/… tabs.
  await gotoStep(page, "Plot");
  await page.waitForTimeout(600);
  await page.screenshot({ path: shot("plot") });

  // Shape Dither showcase in a fresh project: the "Manual" project's generator
  // history re-materialises its layer on reload (Auto generate), so the
  // overview state is built where no generator ever existed.
  await freshProject(request, baseURL!, "Manual v2");
  await page.setViewportSize({ width: 1280, height: 720 });
  await gotoApp(page);
  await importRaster(page, join(ASSETS, "sample.png"));
  const comp2 = await (await request.get(`${baseURL}/api/composition`)).json();
  const ditherId: string = comp2.composition.layers.at(-1).id;
  await request.patch(`${baseURL}/api/composition/layers/${ditherId}`, {
    data: { x: 28, y: 78, scale: 0.82, rotation: 12, display_mode: "pathfinding" },
  });
  const dither = await request.post(`${baseURL}/api/composition/layers/${ditherId}/pathfinding/generate`, {
    data: {
      pfm_id: "shape_dither",
      params: {
        columns: 28, levels: 5, dither_error: true, tone_response: 1,
        min_scale: 0.08, max_scale: 0.95, rotate_with_image: true,
        shape_type: "star", shape_color: "#4468f0",
      },
    },
  });
  expect(dither.ok(), "shape dither generate").toBeTruthy();
  const added = await request.post(`${baseURL}/api/composition/add-layer`, { data: {} });
  expect(added.ok(), "add empty layer").toBeTruthy();
  // A fresh path-finding layer shows the project source raster full-page,
  // which would cover the dither result — keep it in the stack but unchecked.
  const addedId: string = (await added.json()).composition.layers.at(-1).id;
  await request.patch(`${baseURL}/api/composition/layers/${addedId}`, { data: { visible: false } });
  await request.patch(`${baseURL}/api/composition/layers/${ditherId}`, { data: { selected: true } });

  // Overview: rotated blue Shape Dither result above a second layer.
  await gotoApp(page);
  await page.waitForTimeout(800);
  await expect(page.locator(".panel .layer")).toHaveCount(2);
  await page.screenshot({ path: shot("overview") });

  // Shape Dither panel crop: Tone / Shape / Colour controls beside the result.
  await page.getByRole("button", { name: "Path finding settings for sample" }).click();
  const stylePanel = page.locator('[aria-label="Layer style"]');
  await expect(stylePanel).toBeVisible();
  await stylePanel.locator('[data-param="levels"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  const levelsBox = (await stylePanel.locator('[data-param="levels"]').boundingBox())!;
  const panelBox = (await stylePanel.boundingBox())!;
  await page.screenshot({
    path: shot("shape-dither"),
    clip: await clipAnchoredRight(page, { ...panelBox, y: levelsBox.y - 60 }, 660, 605),
  });

  // Style browser dialog (taller viewport so more families are visible).
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator('[data-tour="pfm-browse"]').click();
  const picker = page.locator(".pfm-picker");
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(800); // let preview thumbnails load
  await picker.screenshot({ path: shot("pfm-picker") });
  await page.keyboard.press("Escape");

  // Drawing Area + Pens panel crops.
  const areaPanel = page.locator(".panel", { hasText: "Drawing Area" }).first();
  await areaPanel.locator("button.title").click();
  await page.waitForTimeout(200);
  await areaPanel.screenshot({ path: shot("panel-area") });
  await areaPanel.locator("button.title").click();
  const pensPanel = page.locator(".panel", { hasText: "Pens" }).first();
  await pensPanel.screenshot({ path: shot("panel-pens") });

  // ── Project 2: Voronoi stippling tutorial result ───────────────────────────
  await freshProject(request, baseURL!, "Tutorial · Stipple");
  await page.setViewportSize({ width: 960, height: 720 });
  await gotoApp(page);
  await importRaster(page, TUTORIAL_SOURCE);
  const stippleComp = await (await request.get(`${baseURL}/api/composition`)).json();
  const stippleId: string = stippleComp.composition.layers.at(-1).id;
  await request.patch(`${baseURL}/api/composition/layers/${stippleId}`, {
    data: { x: 28, y: 78, scale: 0.82, rotation: 12, display_mode: "pathfinding", selected: true },
  });
  const stipple = await request.post(`${baseURL}/api/composition/layers/${stippleId}/pathfinding/generate`, {
    data: { pfm_id: "voronoi_stippling", params: { seed: 0, point_density: 500 } },
  });
  expect(stipple.ok()).toBeTruthy();
  await gotoApp(page);
  await page.waitForTimeout(800);
  await page.screenshot({ path: shot("voronoi-tutorial") });

  // ── Project 3: Engraving + direction fields ────────────────────────────────
  await freshProject(request, baseURL!, "Manual · Fields");
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoApp(page);
  await importRaster(page, join(ASSETS, "sample.png"));
  await page.locator('button[data-tour="add-pf"]').click();
  await expect(page.locator('[aria-label="Layer style"]')).toBeVisible();
  await page.locator('select[data-tour="pfm-select"]').selectOption("engraving");
  await page.waitForTimeout(400);

  // Guided tour tip (crop centred on the dialog).
  await page.locator(".menubar .menu .summary", { hasText: "Help" }).click();
  await page.getByRole("button", { name: "✦ Tutorial: paint a direction field" }).click();
  const tip = page.locator(".tour-tip");
  await expect(tip).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(300);
  const tipBox = (await tip.boundingBox())!;
  const tipCx = tipBox.x + tipBox.width / 2;
  const tipCy = tipBox.y + tipBox.height / 2;
  await page.screenshot({
    path: shot("tour"),
    clip: {
      x: Math.max(0, Math.min(tipCx - 340, 1440 - 680)),
      y: Math.max(0, Math.min(tipCy - 210, 900 - 420)),
      width: 680,
      height: 420,
    },
  });
  await page.getByRole("button", { name: "Skip tour" }).click();

  // Engraving parameter panel from the top (Style select → Direction group).
  const engPanel = page.locator('[aria-label="Layer style"]');
  await engPanel.evaluate((el) => (el.scrollTop = 0));
  await page.waitForTimeout(200);
  const engBox = (await engPanel.boundingBox())!;
  await page.screenshot({
    path: shot("panel-direction"),
    clip: { x: engBox.x, y: engBox.y, width: Math.min(320, engBox.width), height: 780 },
  });

  // Open the Spacing Scale field binding editor.
  await engPanel.locator('[data-param="spacing_scale"]').scrollIntoViewIfNeeded();
  await engPanel.locator('[data-param="spacing_scale"] button', { hasText: "field" }).click();
  const editor = page.locator("section.binding-editor");
  await expect(editor).toBeVisible({ timeout: 5_000 });

  // The Painted mask row's controls (incl. Paint…) render only at weight > 0.
  const paintedWeight = editor.locator('input[title*="Painted mask weight"]');
  await paintedWeight.evaluate((el: HTMLInputElement) => {
    el.value = "1.4";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // Paint mode: brush toolbar + canvas over the source image.
  await page.locator('[data-tour="paint-btn"]').click();
  await expect(page.locator(".field-paint-bar")).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot("paint-mode") });

  // Paint a few strokes: two dark sweeps, then a light chevron.
  const canvasBox = (await page.locator(".field-paint-canvas").boundingBox())!;
  const at = (fx: number, fy: number): [number, number] => [
    canvasBox.x + canvasBox.width * fx,
    canvasBox.y + canvasBox.height * fy,
  ];
  const paint = async (points: [number, number][]) => {
    await page.mouse.move(points[0][0], points[0][1]);
    await page.mouse.down();
    for (const [x, y] of points.slice(1)) await page.mouse.move(x, y, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(150);
  };
  const bars = page.locator('.field-paint-bar input[type="range"]');
  const setRange = (el: HTMLInputElement, value: string) => {
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };
  await bars.first().evaluate(setRange, "12"); // brush size (canvas is only 96px wide)
  await bars.last().evaluate(setRange, "0"); // black strokes first
  await paint([at(0.1, 0.25), at(0.28, 0.33), at(0.45, 0.26)]);
  await paint([at(0.08, 0.52), at(0.45, 0.48)]);
  await bars.last().evaluate(setRange, "1"); // white chevron
  await paint([at(0.1, 0.78), at(0.28, 0.68), at(0.45, 0.78)]);
  const maskName = page.locator('.field-paint-bar input.name');
  await maskName.fill("Sweep");
  await page.locator(".field-paint-bar button.primary").click();
  await page.waitForTimeout(600);

  // Bind the painted mask and give it weight.
  const paintSelect = page.locator('[data-tour="paint-select"]');
  const maskValue = await paintSelect
    .locator("option", { hasText: "Sweep" })
    .first()
    .getAttribute("value");
  if (maskValue) await paintSelect.selectOption(maskValue);
  // Let the painted strokes dominate the resolved field so the preview and
  // the regenerated lines visibly follow them.
  await editor.locator('input[title*="Image tone weight"]').evaluate((el: HTMLInputElement) => {
    el.value = "0.5";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.waitForTimeout(800); // field preview refresh

  // Field binding editor with the painted mask preview.
  await editor.screenshot({ path: shot("binding-editor") });

  // Regenerate and capture the bent engraving lines beside the editors.
  await page.locator('[data-tour="generate"]').click();
  await waitForReady(page);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: shot("result"),
    clip: { x: 1440 - 1072, y: 60, width: 1072, height: 774 },
  });
});
