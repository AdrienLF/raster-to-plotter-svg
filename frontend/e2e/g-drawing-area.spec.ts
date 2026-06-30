import { test, expect, freshProject, gotoApp, ASSETS } from "./fixtures";
import { readFileSync } from "fs";
import { join } from "path";

// G1: selecting a preset from the Drawing Area panel persists width/height.
test("G1: area preset sets width and height via API", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G1");
  await gotoApp(page);

  // Drawing Area panel is collapsed by default in the pathfinding step.
  await page.getByRole("button", { name: "Drawing Area" }).click();

  // Fetch presets to avoid hard-coding dimensions.
  const { presets } = await (await request.get(`${baseURL}/api/area`)).json();
  const [expectedW, expectedH] = presets["A4"] as [number, number];

  // The preset select is uniquely identified by its A4 option.
  await page.locator('select:has(option[value="A4"])').selectOption("A4");

  await page.waitForTimeout(300);
  const { area } = await (await request.get(`${baseURL}/api/area`)).json();
  expect(area.width).toBeCloseTo(expectedW, 0);
  expect(area.height).toBeCloseTo(expectedH, 0);
});

// G2: padding inputs save to the backend.
test("G2: padding left input saves to area settings", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G2");
  await gotoApp(page);

  await page.getByRole("button", { name: "Drawing Area" }).click();

  // The four padding inputs live inside .grid4 (L/R/T/B order).
  const padInputs = page.locator(".grid4 input");
  await padInputs.first().fill("15");
  await padInputs.first().press("Tab"); // triggers onchange → api.saveArea()

  await page.waitForTimeout(300);
  const { area } = await (await request.get(`${baseURL}/api/area`)).json();
  expect(area.pad_left).toBe(15);
});

// G3: pen width (mm) setting persists to the backend.
test("G3: pen width input saves to area settings", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G3");
  await gotoApp(page);
  await page.getByRole("button", { name: "Drawing Area" }).click();

  // Pen width input is identified by its label text.
  const pwLabel = page.locator('label', { hasText: "Pen width (mm)" });
  // Its sibling input is right after the label inside the same .f container.
  const pwInput = page.locator(".f").filter({ has: pwLabel }).locator("input");
  await pwInput.fill("0.5");
  await pwInput.press("Tab");

  await page.waitForTimeout(300);
  const { area } = await (await request.get(`${baseURL}/api/area`)).json();
  expect(area.pen_width_mm).toBeCloseTo(0.5, 3);
});

// G4: clipping mode select persists to the backend.
test("G4: clipping mode saves to area settings", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G4");
  await gotoApp(page);
  await page.getByRole("button", { name: "Drawing Area" }).click();

  // Clipping select has options drawing/page/none.
  await page.locator('select:has(option[value="page"])').selectOption("page");

  await page.waitForTimeout(300);
  const { area } = await (await request.get(`${baseURL}/api/area`)).json();
  expect(area.clipping).toBe("page");
});

// G5 (UX inventory): changing page preset after layers exist doesn't destroy layers.
test("G5: switching page preset preserves existing layers", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G5");
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const layerId: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${layerId}/pathfinding/generate`, {
    data: { pfm_id: "spiral", params: {} },
  });

  await gotoApp(page);
  await page.getByRole("button", { name: "Drawing Area" }).click();
  await page.locator('select:has(option[value="A4"])').selectOption("A5");
  await page.waitForTimeout(300);

  // Layer count must not change after a preset switch.
  const { composition } = await (await request.get(`${baseURL}/api/composition`)).json();
  expect(composition.layers.length).toBe(1);
  expect(composition.layers[0].id).toBe(layerId);
});

// G6: custom number steppers reserve space for slim controls and expose the
// complete current value through the input title.
test("G6: number fields use readable custom steppers", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "E2E G6");
  await gotoApp(page);
  await page.getByRole("button", { name: "Drawing Area" }).click();

  const paddingSteppers = page.locator(".grid4 .numstep");
  await expect(paddingSteppers).toHaveCount(4);

  const firstStepper = paddingSteppers.first();
  const input = firstStepper.locator("input");
  const increase = firstStepper.getByRole("button", { name: "Increase" });
  await expect(input).toHaveAttribute("title", "0");
  await increase.click();

  await expect(input).toHaveValue("1");
  await expect(input).toHaveAttribute("title", "1");
  const rightPadding = await input.evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).paddingRight),
  );
  expect(rightPadding).toBeGreaterThanOrEqual(15);

  await expect.poll(async () => {
    const { area } = await (await request.get(`${baseURL}/api/area`)).json();
    return area.pad_left;
  }).toBe(1);
});
