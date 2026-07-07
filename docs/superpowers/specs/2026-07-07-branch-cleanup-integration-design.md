# Branch Cleanup and Integration Design

## Goal

Finish `feat/param-fields`, preserve the outstanding work on the growth, line-compiler, and plot-preview branches, and leave `main` as the verified integrated branch.

## Integration strategy

Complete the current branch before merging anything into it. Fix the Svelte check regression, finish the user-manual text and screenshots, and commit that coherent state. Then merge `feat/growth`, `feat/line-compiler`, and `origin/plot-preview-emulator` one at a time. Resolve source and test conflicts deliberately; never hand-merge hashed files under `web/static/app/assets`. Rebuild the production frontend after source conflicts are resolved so `web/static/app/index.html` and its asset hashes describe one build.

The order is intentional: growth is a small registry/style addition, line-compiler extends geometry and occlusion behavior, and plot-preview has the broadest UI/server surface. Verification after every merge localizes regressions.

## Documentation

The manual must describe the current three-step Compose / Generate / Plot workflow. Each screenshot must match its caption and page purpose. `overview.png` may show the Compose home screen, while `composition.png` must be a distinct composition-focused frame. `panel-direction.png` must visibly show an Engraving bindable field control.

## Verification

Each integration checkpoint runs the Python suite and Svelte check. The final state additionally runs the production build and complete Playwright suite. Browser inspection covers the manual pages and refreshed images. No stale local or remote-tracking branch is deleted until its tip is proven to be an ancestor of the integrated branch; remote deletion is out of scope unless explicitly requested.

## Git outcome

Merge the verified integration branch into local `main` without rewriting history. Preserve the existing local `main` commit, push nothing without a separate explicit request, and delete only fully merged local feature branches.
