# E2E Branch Stabilization Design

**Date:** 2026-06-27

**Status:** Approved for planning

## Goal

Finish `e2e-playwright-harness` as a trustworthy branch: all 84 current Playwright tests pass, genuine product defects exposed by those tests are fixed, the passing E7 test is committed, and the 13 catalogued but uncovered stories are recorded as future work rather than silently implied to be complete.

## Definition of done

The branch is done when all of the following are true:

- `uv run --with pytest python -m pytest` passes the complete backend suite.
- `npm run check` reports no errors.
- `npm run build` succeeds.
- `npm run e2e` reports 84 passed, 0 failed, 0 flaky, and 0 skipped.
- The working tree contains no accidental build or report changes.
- `frontend/e2e/README.md` and `frontend/e2e/USER_STORIES.md` accurately describe implemented coverage and deferred stories.
- A product/engineering roadmap ranks the best next improvements by user impact, effort, and risk.

The branch will not implement the 13 currently uncovered stories: A5, D1-D6, F6, F8-F10, H6, and K10.

## Evidence and root causes

The first full run produced 63 passes and 19 failures. Investigation found three dominant causes.

1. **Startup is not synchronized.** `gotoApp()` treats `CPU · …` as a loaded backend because it only rejects the exact placeholder `… · …`. Tests can read layer, pen, and project state before `api.boot()` finishes.
2. **Terminal SSE events leak across projects.** The backend caches the latest `proc` and `state` event and replays it to new subscribers. Creating or opening a project does not clear those events, so a new page can receive `Ready`, stale statistics, or a plot state from the previous project.
3. **Several assertions describe an older contract.** Examples include querying buttons by visible text when an `aria-label` defines a different accessible name, reading `total_shapes` from an estimate that exposes `paths`, rejecting namespaced SVG elements such as `<ns0:path>`, and expecting `ready` where layer path-finding status uses `clean`.

Other failures, including crop-to-content and plot completion, remain unclassified until the shared synchronization defects are removed. They will be investigated individually after the harness is deterministic.

## Architecture

### 1. Deterministic application startup

`App.svelte` will complete `api.boot()` before opening the event stream. A failed boot will leave a visible error state and log the error; it will not open a stream against partially initialized state.

Project switching will explicitly reset transient UI state: processing, plotting, progress, statistics, plot progress, and status. Persistent project data will still come from the existing boot endpoints.

The Playwright `gotoApp()` helper will synchronize on the boot sequence's final `/api/versions` response and then require a backend badge with no ellipsis. Tests will not infer readiness from elapsed time.

### 2. Project-bound event state

Project activation endpoints will return HTTP 409 without changing projects while a process or plot worker is active. When the system is idle, activating a different project—create, open, or delete-current fallback—will clear cached process and plot terminal events and drain subscriber queues before the new project's payload becomes active. This keeps the current global-single-project architecture while preventing prior-project state from being replayed or a worker from completing against the wrong project.

This branch will not redesign workers as project-scoped jobs. Switching projects while a worker is actively mutating state is a larger concurrency concern and will be recorded in the roadmap.

### 3. Condition-based E2E helpers

Shared helpers will express the conditions the application actually guarantees:

- application boot completed;
- generation produced a layer with non-empty SVG;
- a requested composition mutation is visible through `/api/composition`;
- a plot estimate exposes a numeric path count;
- a plot job reaches a terminal state.

Fixed sleeps will be removed where a response, DOM state, or polled API value can provide a deterministic boundary. Performance tests may retain elapsed-time measurement, but pass/fail synchronization will not depend on arbitrary delays.

### 4. Contract-aligned assertions

Tests will use the UI's accessible names, including layer-specific action labels such as `Open <layer> path finding` and `Move <layer> down`. Where the user-facing contract is visual text rather than an accessible name, locators will be scoped to the relevant row.

SVG assertions will recognize both plain and namespace-prefixed drawing elements. Plot estimate assertions will use the `paths` field. Path-finding terminal assertions will use the model's actual statuses: `clean` or `error`.

Assertions will not be weakened merely to make a test green. Each correction must match an existing product contract or a documented desired behavior.

## Data flow

Application startup becomes:

1. mount the app;
2. fetch and apply boot data;
3. expose initialized project/backend state;
4. connect the SSE stream;
5. process only events produced after the active project was established.

A project transition becomes:

1. reject the transition with HTTP 409 if a process or plot worker is active;
2. clear cached and queued transient events;
3. activate the selected project;
4. return the project payload;
5. reset and reload transient frontend state.

An E2E action becomes:

1. trigger one user or API action;
2. wait for its observable completion condition;
3. assert the resulting DOM and backend state;
4. leave no active worker or plot job for the next serial test.

## Error handling

- Boot failures set the frontend status to `Error` and append a concise log entry.
- Event-stream disconnects retain native browser reconnection behavior.
- A rejected project transition leaves the current project and transient state unchanged.
- Project transitions must not replay old terminal events after reconnection.
- Test helpers fail with the expected missing condition—boot response, layer geometry, estimate, or terminal job state—rather than timing out on a downstream selector.
- Performance budgets remain informational and do not become hard functional failures.

## Testing strategy

Work proceeds from the shared causes outward.

1. Add backend regression coverage proving that active workers block project transitions and idle project activation clears cached transient events.
2. Add or adjust frontend contract coverage for boot-before-stream ordering and transient-state reset.
3. Run a small E2E slice that previously exposed each shared race: L2 for boot, E3-E5 for stale process events, and F1/F7/H2 for pre-boot collection counts.
4. Correct stale test contracts one behavior at a time and rerun each affected spec.
5. Investigate remaining failures with fresh isolated reproductions. Fix production code only when the test demonstrates a real user-visible defect.
6. Run backend tests, frontend check, frontend build, then the complete serial Playwright suite.
7. Repeat the full Playwright suite once more if the first green run involved timing-sensitive changes; any flaky result blocks completion.

## Documentation and roadmap

`frontend/e2e/README.md` will list the actual suite shape rather than the original three representative specs. `USER_STORIES.md` will distinguish implemented IDs from the deferred backlog.

After verification, a new roadmap document will assess the finished software from four angles:

- core workflow friction and discoverability;
- reliability, recovery, and hardware safety;
- drawing quality and creative control;
- architecture, performance, and maintainability.

Recommendations will be ranked in three horizons: quick wins, medium investments, and ambitious bets. Each item will state the user problem, expected value, rough effort, major dependencies, and why it belongs at that rank.

## Non-goals

- Implementing A5 backend-restart persistence coverage.
- Implementing SAM2 region stories D1-D6.
- Adding mask, alignment, snapping, or UX-benchmark stories F6 and F8-F10.
- Redesigning the visual interface.
- Replacing the global Flask process model with a multi-project job system.
- Turning soft performance budgets into CI gates.
- Pushing the branch or opening a pull request without a separate user request.
