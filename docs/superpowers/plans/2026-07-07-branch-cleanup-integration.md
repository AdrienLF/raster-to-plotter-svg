# Branch Cleanup and Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a verified `main` containing the completed param-fields documentation plus growth, line-compiler, and plot-preview work.

**Architecture:** Stabilize the current branch, then merge feature lines sequentially. Resolve authored source first and regenerate compiled frontend assets from that source.

**Tech Stack:** Python 3.13, pytest, Svelte 5, TypeScript, Vite, Playwright, Git.

## Global Constraints

- Preserve all existing user documentation edits.
- Do not rewrite history or force-push.
- Do not hand-edit hashed production bundles.
- Verify after every merge and before every commit.

---

### Task 1: Stabilize `feat/param-fields`

**Files:**
- Modify: `frontend/src/components/ParamControl.svelte`
- Test: `frontend` Svelte diagnostics

- [ ] Reproduce `npm run check` and confirm the `$bindable` rune is shadowed by the later local `bindable` derived value.
- [ ] Add a focused frontend contract that prevents reusing Svelte rune names for local state and run it to observe failure.
- [ ] Rename the local derived flag to `canBindField` and update its template use.
- [ ] Run the focused contract and `npm run check`; expect zero errors.

### Task 2: Finish and verify the manual

**Files:**
- Modify: `web/static/docs/*.html`
- Modify: `web/static/docs/img/*.png`

- [ ] Validate all local manual links and image references.
- [ ] Capture a distinct composition frame and an Engraving field-control frame from the running app.
- [ ] Inspect every changed screenshot against its caption in the browser.
- [ ] Run `git diff --check` and commit the stabilized current branch.

### Task 3: Integrate growth

**Files:**
- Merge: `feat/growth`
- Resolve: registry, PFM smoke cases, performance budgets, style grouping, generated app output.

- [ ] Merge without committing and resolve authored-file conflicts by retaining both Engraving and Growth entries.
- [ ] Rebuild production frontend assets.
- [ ] Run `uv run --with pytest python -m pytest -q` and `npm run check`.
- [ ] Commit the merge.

### Task 4: Integrate line compiler

**Files:**
- Merge: `feat/line-compiler`
- Resolve: parameter declarations, layer style UI, shared types, server settings, generated app output.

- [ ] Merge without committing and preserve both field-binding UI and stroke-level occlusion controls.
- [ ] Rebuild production frontend assets.
- [ ] Run backend tests and `npm run check`.
- [ ] Commit the merge.

### Task 5: Integrate plot preview

**Files:**
- Merge: `origin/plot-preview-emulator`
- Resolve: app shell, viewport, layer panel, API/state/types, server, generated app output.

- [ ] Merge without committing and preserve both current Compose workflow and plot playback behavior.
- [ ] Rebuild production frontend assets.
- [ ] Run backend tests and `npm run check`.
- [ ] Commit the merge.

### Task 6: Final verification and cleanup

- [ ] Run the full Python suite, Svelte check, production build, and complete Playwright suite.
- [ ] Merge the verified feature branch into local `main`.
- [ ] Re-run the full verification on `main`.
- [ ] Delete only local branches whose tips are ancestors of `main`; report remote branches separately.
