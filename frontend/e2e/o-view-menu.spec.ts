import { readFileSync } from "fs";
import { join } from "path";
import { test, expect, ASSETS, freshProject, gotoApp } from "./fixtures";

/** Project with one visible generated layer so guides and artwork both render. */
async function setupOneLayer(request: any, baseURL: string, name: string) {
  await freshProject(request, baseURL, name);
  await request.post(`${baseURL}/api/image`, {
    multipart: {
      file: { name: "sample.png", mimeType: "image/png", buffer: readFileSync(join(ASSETS, "sample.png")) },
    },
  });
  const add = await (await request.post(`${baseURL}/api/composition/add-layer`, { data: {} })).json();
  const id: string = add.composition.layers.at(-1).id;
  await request.post(`${baseURL}/api/composition/layers/${id}/pathfinding/generate`, {
    data: { pfm_id: "spiral", params: {} },
  });
}

test("O1: View menu toggles guides and bounds, and closes on selection", async ({ page, request, baseURL }) => {
  await setupOneLayer(request, baseURL!, "E2E O1");
  await gotoApp(page);

  // Artwork is present and guides render by default.
  await expect(page.locator(".art").first()).toBeVisible();
  await expect(page.locator(".guide.a4")).toBeVisible();
  await expect(page.locator(".sheet-mid-v")).toHaveCount(1);
  await expect(page.locator(".sheet-mid-h")).toHaveCount(1);

  // Open View: both toggles report on.
  await page.getByRole("button", { name: "View" }).click();
  const guidesItem = page.getByRole("button", { name: "Show guides" });
  const boundsItem = page.getByRole("button", { name: "Show bounds" });
  await expect(guidesItem).toHaveAttribute("aria-pressed", "true");
  await expect(boundsItem).toHaveAttribute("aria-pressed", "true");

  // Choosing Show guides disables guides and closes the menu.
  await guidesItem.click();
  await expect(guidesItem).toHaveCount(0);
  await expect(page.locator(".guide.a4")).toHaveCount(0);
  await expect(page.locator(".sheet-mid-v")).toHaveCount(0);
  await expect(page.locator(".sheet-mid-h")).toHaveCount(0);
  // Artwork stays.
  await expect(page.locator(".art").first()).toBeVisible();

  // Reopen View, disable bounds: layer-bound styling is removed.
  await page.getByRole("button", { name: "View" }).click();
  await page.getByRole("button", { name: "Show bounds" }).click();
  await expect(page.locator(".art.show-bounds")).toHaveCount(0);
  await expect(page.locator(".art").first()).toBeVisible();
});
