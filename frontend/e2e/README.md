# E2E tests (Playwright)

Browser e2e tests driving the built Svelte app against a live, **isolated** Flask backend.
See `USER_STORIES.md` for the full story library these tests map to.

## Run

```bash
cd frontend
npm install
npx playwright install chromium   # one-time browser download
npm run e2e                       # or: npm run e2e:ui
```

`global-setup.ts` builds the SPA, then spawns the backend with:

- a **temp HOME** (`USERPROFILE`/`HOME`) so `~/.plotter_studio`, `~/.plotter_settings.json`,
  the resume-job and paths-cache files never touch your real profile;
- `PLOTTER_FAKE_SERIAL=1` — an in-memory Grbl stub so plot/manual flows run with no hardware;
- `SAM2_AUTO_SETUP=0` — never downloads the segmentation model in tests.

The backend listens on port **7440** (override `E2E_PORT`). Set `E2E_SKIP_BUILD=1` to reuse the
existing `web/static/app` build, or `E2E_BACKEND_CMD` to change how the server is launched
(default `uv run --isolated --locked --no-dev python -m web.server`).

The default command runs the backend in an **isolated** uv environment built only from the
locked runtime dependencies. Playwright therefore cannot inherit or mutate the project's
`.venv`, CUDA, MPS, or SAM2 — every run starts from the same deterministic base environment.

## Performance

`perf-pfm.spec.ts` appends `{story, pfm, duration_ms, shapes}` rows to `perf/results.jsonl`.
Budgets live in `perf/budgets.json` — over-budget logs a warning, it never fails the run.

## Layout

The suite currently contains 17 spec files and 85 serial Chromium tests covering 74 of the 87 catalogued story IDs. Specs combine direct API setup with real UI interactions so expensive setup stays fast while user-visible behavior remains end-to-end.

Thirteen story IDs are intentionally deferred: A5, D1-D6, F6, F8-F10, H6, and K10. See `USER_STORIES.md` for their requirements.

- `fixtures.ts` — app helpers (`gotoApp`, `importImage`, `runPathFinding`, `gotoStep`) + the
  `recordPerf` fixture.
- `assets/` — fixture image + svg.
