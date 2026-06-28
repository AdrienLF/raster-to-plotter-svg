import { test, expect, freshProject, gotoApp } from "./fixtures";

// A2: switching project via the Project menu updates the title bar immediately.
test("A2: switch project updates title", async ({ page, request, baseURL }) => {
  await request.post(`${baseURL}/api/projects`, { data: { name: "Alpha" } });
  await freshProject(request, baseURL!, "Beta");
  await gotoApp(page);
  await expect(page.locator(".menubar")).toContainText("Beta");

  await page.getByRole("button", { name: "Project" }).click();
  // "Alpha" appears without the "● " prefix (that's reserved for the current project).
  await page.locator(".items button", { hasText: "Alpha" }).click();
  await expect(page.locator(".menubar")).toContainText("Alpha", { timeout: 15_000 });
  await expect(page.locator(".menubar")).not.toContainText("Beta");
});

// A3: renaming persists across a page reload (written to disk).
test("A3: rename project persists across reload", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "Before Rename");
  await gotoApp(page);

  page.on("dialog", (d) => d.accept("After Rename"));
  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Rename current…" }).click();
  await expect(page.locator(".menubar")).toContainText("After Rename");

  await page.reload();
  await expect(page.locator(".badge")).not.toHaveText("… · …", { timeout: 20_000 });
  await expect(page.locator(".menubar")).toContainText("After Rename");
});

// A4: deleting the current project switches to another automatically.
test("A4: delete current project; another becomes current", async ({ page, request, baseURL }) => {
  await request.post(`${baseURL}/api/projects`, { data: { name: "Keep Me" } });
  await freshProject(request, baseURL!, "Delete Me");
  await gotoApp(page);
  await expect(page.locator(".menubar")).toContainText("Delete Me");

  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Project" }).click();
  await page.getByRole("button", { name: "Delete current…" }).click();
  await expect(page.locator(".menubar")).not.toContainText("Delete Me", { timeout: 15_000 });
  await expect(page.locator(".menubar")).toContainText("Keep Me");

  // "Delete Me" is also absent from the project list.
  await page.getByRole("button", { name: "Project" }).click();
  await expect(page.locator(".items")).not.toContainText("Delete Me");
});

// A6: first-run empty state — all primary actions are disabled until an image is loaded.
// UX: the canvas has no visible on-screen guidance for new users (empty state should add a hint).
test("A6: empty state disables Run, Plot, and Export", async ({ page, request, baseURL }) => {
  await freshProject(request, baseURL!, "Empty");
  let failFirstBootFetch = true;
  await page.route("**/api/pfm/list", async (route) => {
    if (failFirstBootFetch && route.request().method() === "GET") {
      failFirstBootFetch = false;
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await gotoApp(page);

  await expect(page.locator('button[title="Run path finding"]')).toBeDisabled();
  await expect(page.locator('button[title="Plot"]')).toBeDisabled();

  await page.getByRole("button", { name: "File" }).click();
  await expect(page.getByRole("button", { name: "Export SVG" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Export layers (zip)" })).toBeDisabled();
});
