# Plotter Studio Product Roadmap

## Product assessment

Plotter Studio is already a capable single-user artwork workstation, not a prototype algorithm viewer. It combines a broad path-finding engine, from-scratch generation, layer composition, physical page and pen models, immutable versions, SVG export, and direct Grbl plotting. The verified branch has 84 Playwright tests covering 73 of 86 named user stories and 105 backend tests. Its strongest product trait is that creative settings are tied to real output and real hardware rather than isolated demos.

The product is best described as a strong private beta for an experienced plotter user. The core artwork loop is fast: the recorded C12 path-finding flow reaches a result in two interactions and M4 reaches its first export in three counted steps. The remaining gap is not raw feature count; it is confidence at the edges. A new user gets little contextual direction, save state is mostly implicit, several promising editing workflows are not yet regression-covered, and Start can drive a physical machine without a consolidated preflight.

Reliability has improved materially. Project transitions are serialized against active work, plot jobs are checkpointed and resumable, cancelled parsing cannot poison the path cache, version snapshots restore generated compositions, and transient browser boot failures are bounded. However, processing and generation still use process-global daemon threads and state, project switching is blocked rather than jobs being owned by a project, and A5 restart persistence remains deferred. Those constraints are acceptable for one active studio session, but they define the boundary of the current architecture.

SAM2 is part of the intended product, not an optional future embellishment. Region APIs, masks, model status, checkpoint download, and editing UI exist, but D1-D6 are all deferred. The runtime deliberately avoids automatic SAM2 installation because an unconstrained torchvision install can replace a CUDA build of PyTorch with a CPU build. The roadmap therefore treats deterministic SAM2 readiness on the existing uv-only Windows/macOS setup as a prerequisite for completing the region workflow. Reintroducing Conda is not part of the plan.

## What is already strong

- **Workflow and discoverability:** The four-step Path Finding → Generate → Composition → Plot structure is legible, primary actions are consistently disabled when invalid, the viewport has a basic “Import an image to begin” state, and the fast C12/M4 interaction counts show that the core path is not intrinsically cumbersome.
- **Reliability and hardware safety:** The backend blocks project transitions during active processing or plotting, serializes worker starts, persists plot checkpoints, detects crashed jobs, supports Stop/Resume/Discard, preserves cancellation semantics during real plotting, and tests Grbl output against a fake serial device. The UI warns users to keep paper fixed before resuming.
- **Creative power and output quality:** Roughly 23 registered PFMs span Voronoi, LBG, adaptive, stipple, hatch, sketch, spiral, streamline, TSP, composite, and mosaic families. Typed parameter schemas generate consistent controls. GPU acceleration uses CUDA or Metal/MPS with a CPU fallback. Layers support visibility, order, placement, crop, scale, occlusion, pens, and deterministic generators.
- **Project and version persistence:** Projects persist source image metadata, drawing area, pens, composition, regions, layer SVG files, PFM parameters, and versions. Versions include thumbnails, ratings, notes, and immutable composition snapshots for generated work. Corrupt or missing snapshots fail atomically rather than partially mutating the project.
- **Regions and composition foundations:** SAM2 model selection/status, positive and negative points, mask persistence, inversion, layer region assignment, alignment commands, snapping guides, A4 guides, and mask state already exist. This is substantial implementation to finish and verify rather than a greenfield feature.
- **Engineering leverage:** The E2E suite exercises real Flask/Svelte flows and fake hardware; backend tests isolate global state; performance stories record import, PFM, generator, version, export, estimate, and feedback timings. PFM and generator registries plus typed schemas are useful internal extension seams.
- **Cross-platform base:** uv is the Python environment authority, separate Windows and macOS launchers build and start the same application, the GPU extra supports CUDA/MPS with CPU fallback, and the setup no longer depends on Conda.

## Friction and risks observed

- **First-use context is thin.** The empty canvas names the first action but does not explain the four-stage mental model, the difference between Path Finding and Generate, why Plot/Export are disabled, or the shortest path to a first physical result. A modal wizard would be excessive given the already-low click counts; contextual guidance is the better fit.
- **Save behavior is invisible.** Many controls persist immediately on `change`, layer mutations call APIs directly, and failures appear in a compact status/log area. There is no consistent Saving/Saved/Unsaved/Retry state, no project dirty model, and A5 does not yet prove image, composition, pens, regions, and versions survive a backend restart together.
- **Accessibility debt is small but concrete.** `svelte-check` reports 14 form-label warnings: 12 in DrawingAreaPanel and two in PensPanel. Dynamic parameter controls and most newer plotter controls already show the correct association pattern.
- **Plotting lacks a safety gate.** Estimate exposes paths, segments, pen cycles, draw distance, travel distance, and time, while Setup exposes paper and machine parameters. Start does not consolidate page-bound violations, selected paper, pen order, connection/status, homing, pen readiness, or a travel preview into an explicit go/no-go decision.
- **Cancellation is uneven.** Plotting is checkpointed and resumable, but PFM/generator workers are global daemon threads with no equivalent durable job identity or project ownership. The global stop/event model and “block switching while work is active” policy prevent corruption but do not support clean cancellation, recovery, or multiple queued projects.
- **Promising creative workflows are not yet product-complete.** D1-D6, F6, F8, F9, F10, H6, and K10 remain deferred. Region, mask, alignment, and snapping code exists, but without full-journey coverage it is risky to present these as dependable editing tools. SAM2 availability also depends on a compatible torch/torchvision/SAM2 installation and checkpoint.
- **Versions support recall, not comparison.** Thumbnails, rating, order, load, and delete are present, but users cannot compare a saved version against the current artwork, inspect changed parameters, or restore selectively.
- **Performance data is recorded but not interpreted.** Results are append-only JSONL and budgets only warn. The samples show useful signals—K9 path reordering ranged from about 9.3 to 19.7 seconds, while repeated C9 PFM timings also vary substantially—but there is no baseline, hardware label, percentile, regression trend, or owner-facing summary.
- **Persistence claims outrun coverage.** The on-disk project model is comprehensive, but deferred story A5 means restart recovery is not yet verified as a flagship contract. Plot jobs are durable, while PFM/generator work is not.
- **Architecture concentrates risk.** `web/server.py` owns API routing, global project state, SAM2 setup, event streaming, worker lifecycle, SVG parsing, cache behavior, serial I/O, and plot execution in one module of more than 2,600 lines. This is workable today but makes durable multi-project jobs and a public plugin boundary expensive.

## Prioritization method

Each candidate is scored from 1 (low) to 5 (high) for **impact**, **confidence**, and **effort**. The raw priority is `(impact × confidence) / effort`; higher is better. Impact reflects user and hardware outcomes, confidence reflects the strength of repository/test evidence, and effort includes implementation, migration, documentation, and regression coverage. The roadmap follows the raw order except where hardware safety must move earlier or one item is a prerequisite for another.

| Raw rank | Candidate | Impact | Confidence | Effort | Score | Decision |
|---:|---|---:|---:|---:|---:|---|
| 1 | Remove the 14 current form-label warnings | 3 | 5 | 1 | 15.0 | Quick win |
| 2 | Guided first-artwork flow and contextual empty states | 5 | 5 | 2 | 12.5 | Quick win |
| 3 | Autosave/dirty/error/recovery indicators plus A5 restart contract | 5 | 5 | 2 | 12.5 | Quick win and reliability gate |
| 4 | Plot preflight: bounds, pen order, travel, and hardware checklist | 5 | 5 | 3 | 8.3 | Medium; safety-adjusted ahead of creative expansion |
| 5 | Performance budgets surfaced as trends | 3 | 5 | 2 | 7.5 | Quick win |
| 6 | Reusable generator/PFM/pen recipes | 4 | 4 | 3 | 5.3 | Medium investment |
| 7 | Operation cancellation and project-safe background jobs | 5 | 4 | 4 | 5.0 | Medium; precedes durable workers |
| 8 | Complete regions, masks, alignment, and snapping | 5 | 4 | 4 | 5.0 | Medium; SAM2 readiness is a prerequisite |
| 9 | Visual before/after and version comparison | 3 | 4 | 3 | 4.0 | Medium investment |
| 10 | Project-scoped durable worker architecture | 4 | 3 | 5 | 2.4 | Conditional ambitious bet |
| 11 | Camera-assisted paper alignment and calibration | 4 | 2 | 5 | 1.6 | Evaluate after preflight/manual calibration |
| 12 | PFM/generator plugin SDK | 3 | 2 | 5 | 1.2 | Explicitly not now |

The scores are comparative, not promises. An effort score of 5 means “architectural program with migration risk,” not merely a long implementation. Plot preflight is scheduled before performance trends and creative expansion despite its lower raw rank because a software defect there can damage artwork, hardware, or both.

## Quick wins (days)

### Q1. Remove the current form-label warnings — score 15.0

- **User problem:** Keyboard and assistive-technology users cannot reliably identify or activate every Drawing Area and Pens control.
- **Outcome:** Associate all 14 labels with stable control IDs or wrap their controls correctly; keep `svelte-check` at zero accessibility warnings for newly touched panels.
- **Evidence:** The current check reports 12 warnings in DrawingAreaPanel and two in PensPanel, while ParamControl and PlotterPanel demonstrate working label patterns.
- **Dependencies:** None beyond a focused keyboard pass and the existing Svelte check.
- **Principal risk:** Mechanical ID changes can create duplicates when panels render more than once; use component-local, stable IDs.

### Q2. Add contextual first-artwork guidance — score 12.5

- **User problem:** A blank canvas says to import an image but does not explain Path Finding versus Generate, the disabled actions, or the route to export/plot.
- **Outcome:** Add contextual empty-state cards and inline next-action prompts for blank project, image-without-layer, generated artwork, and plot-not-ready states. Include “Import photo,” “Create from scratch,” and “Open sample” paths; avoid a blocking wizard.
- **Evidence:** A6 explicitly identifies discoverability as unfinished, while C12 and M4 show the happy path is already only two interactions/three counted steps once the user knows what to do.
- **Dependencies:** Final terminology for Path Finding/PFM and a small bundled sample that is clearly non-user data.
- **Principal risk:** Persistent coaching can become clutter for expert users; prompts must disappear when their condition is satisfied and remain dismissible.

### Q3. Make persistence and recovery visible, then close A5 — score 12.5

- **User problem:** Immediate saves happen silently, so users cannot tell whether a change is saved, in flight, failed, or recoverable after restart.
- **Outcome:** Introduce one project-level save state (`Saving`, `Saved`, `Unsaved`, `Save failed—Retry`) with timestamps, actionable errors, and a deterministic A5 restart test covering source, composition/layer files, pens, regions, and versions.
- **Evidence:** Area, pens, settings, layers, regions, and versions persist through different endpoints; project JSON is comprehensive, but no unified dirty state exists and A5 is the only deferred core project-persistence story.
- **Dependencies:** Inventory every mutating endpoint, define which edits are optimistic, and specify atomic write/backup behavior for project JSON and layer files.
- **Principal risk:** A misleading “Saved” badge is worse than none; the state must acknowledge backend completion, not only local input changes.

### Q4. Turn performance logs into a trend report — score 7.5

- **User problem:** Maintainers collect useful timings but cannot see whether a change is a real regression or normal device/GPU variance.
- **Outcome:** Aggregate JSONL by story, PFM, backend, OS, and fixture; show median/p90 and change from a named baseline; publish one CI artifact and warn on sustained regression rather than a single run.
- **Evidence:** Soft budgets already exist, but they never fail and are much broader than observed timings. K9 varies from roughly 9.3–19.7 seconds and repeated C9 runs vary by several multiples, demonstrating the need for trends and hardware labels.
- **Dependencies:** Stable fixture/version metadata, backend identity, minimum sample counts, and retention rules.
- **Principal risk:** Heterogeneous CUDA, MPS, and CPU machines can produce false alarms; do not create hard cross-device gates until baselines are segmented.

## Medium investments (weeks)

### M1. Add a plot preflight and explicit arm step — score 8.3, safety-adjusted first

- **User problem:** Start can command real hardware without one place confirming that artwork fits the paper, the machine is reachable/homed, pens are ready and ordered, and travel is acceptable.
- **Outcome:** Present a preflight summary with page-bound violations, clipping decision, pen sequence and changes, draw/travel preview, estimated time, paper and orientation, connection/status, homing state, pen-up/down check, and a final “Arm and start” confirmation. Hard-block unsafe bounds or unavailable hardware; allow documented overrides for warnings.
- **Evidence:** Estimate and setup data already expose most metrics, fake-serial tests cover commands, and resume state is durable. What is missing is a consolidated decision gate and spatial travel preview.
- **Dependencies:** Reliable effective bounds for all masks/crops, pen-split order, a non-moving machine status probe, and clear warning/error policy.
- **Principal risk:** A preflight that claims safety from stale machine state creates false confidence; timestamp checks and revalidate immediately before Start.

### M2. Unify cancellation and project-safe job ownership — score 5.0

- **User problem:** Plotting can stop/resume, but long PFM, generator, and SAM2 operations cannot be managed with the same clarity, and project switching is blocked by process-global work.
- **Outcome:** Define a common job record with ID, project ID, type, state, progress, cancel request, terminal error, and result commit. Add Cancel for cancellable processing/generation/segmentation, guarantee that late results cannot mutate another project, and distinguish cancelled from failed.
- **Evidence:** The operation lock and generation guards prevent known races; plot checkpointing proves a durable state model; current `_process_thread`, `_plot_thread`, and stop event remain global.
- **Dependencies:** Q3 save/recovery semantics, cancellation points inside PFMs/SAM2, atomic result publication, and policies for non-interruptible GPU kernels.
- **Principal risk:** Unsafe interruption can leave GPU memory, temporary files, serial state, or partial project data behind; cancellation must be cooperative and transactional.

### M3. Finish the region, mask, alignment, and snapping editing loop — score 5.0

- **User problem:** High-value editing tools exist in pieces but all six SAM2 region stories plus mask/alignment/snapping stories remain deferred, so users cannot trust them as one repeatable workflow.
- **Outcome:** Deliver and test create/edit/invert/delete regions, region-scoped PFMs, composition masks, alignment, visible snapping feedback, undoable removal, and clear include/exclude affordances. Make SAM2 readiness a first-class setup check on Windows CUDA and macOS MPS using uv and platform launchers, with no Conda path.
- **Evidence:** Region APIs, mask files, model status/progress, positive/negative points, layer assignment, mask state, alignment functions, and snap guides are implemented. D1-D6 and F6/F8/F9/F10 remain explicitly deferred. SAM2 installation is deliberately opt-in to avoid replacing GPU PyTorch.
- **Dependencies:** A pinned compatible torch/torchvision/SAM2 matrix, checkpoint verification and disk-space feedback, M2 cancellation/project ownership, and full-journey fixtures that can run with and without the model.
- **Principal risk:** GPU dependency drift can make an essential workflow appear intermittently unavailable; setup diagnostics and a tested CPU fallback must be explicit without silently downgrading performance.

### M4. Add reusable generator, PFM, and pen recipes — score 5.3

- **User problem:** Users repeatedly reconstruct successful parameter, page, and pen combinations and cannot intentionally share a look between projects.
- **Outcome:** Save named, portable recipes with type (PFM/generator/pen set/full style), schema version, preview, compatible algorithm ID, and explicit apply scope. Ship a small curated starter library and support import/export as readable JSON.
- **Evidence:** Typed schemas, deterministic seeds, drawing sets, and version metadata already capture most ingredients; current presets cover page size but not creative treatments.
- **Dependencies:** Stable parameter serialization, migration/default rules, Q3 save feedback, and SAM2/region references represented by portable names rather than project-local IDs.
- **Principal risk:** Recipes can rot as schemas evolve; reject incompatible recipes clearly and provide migrations rather than silently dropping fields.

### M5. Add visual version comparison — score 4.0

- **User problem:** A thumbnail list helps recall, but choosing between iterations requires loading them one at a time and losing the current visual context.
- **Outcome:** Compare current versus saved or saved versus saved using side-by-side and opacity/scrub modes, show changed algorithm/parameter/page/pen fields, and restore the chosen snapshot only after confirmation.
- **Evidence:** Versions already have thumbnails, timestamps, ratings, metadata, and immutable composition snapshots; the UI currently offers only Load, order, rating, and delete.
- **Dependencies:** A non-mutating snapshot render endpoint or client composition renderer, Q3 dirty-state protection, and defined behavior for legacy versions without composition snapshots.
- **Principal risk:** Normalized thumbnails can imply geometric equality when page scale or crop differs; comparisons must show dimensions and use a common coordinate frame.

## Ambitious bets (months)

These are evaluated options, not commitments. They should enter delivery only after the named gates are met.

### A1. Move to project-scoped durable workers — score 2.4

- **User problem:** Global in-process threads limit recovery, observability, and safe work across projects; a backend restart loses PFM/generator progress even though plot jobs survive.
- **Outcome:** Persist project-owned job state and inputs, execute through a worker boundary, replay progress after reconnect, recover or explicitly fail interrupted work, and allow safe project switching while jobs run.
- **Evidence:** The current single-active-project architecture requires transition locks and generation guards; plot job checkpoints demonstrate value; `web/server.py` mixes worker, persistence, API, and hardware responsibilities.
- **Dependencies:** M2’s common job contract, idempotent project mutations, atomic artifacts, A5 recovery coverage, and an explicit single-machine resource scheduler for GPU and plotter ownership.
- **Principal risk:** A queue can add operational complexity without user value if only one project is active; prove demand and keep serial/GPU exclusivity simple.

### A2. Add camera-assisted paper alignment and calibration — score 1.6

- **User problem:** Registering artwork to pre-cut, pre-printed, or partially plotted paper is manual and error-prone.
- **Outcome:** Calibrate camera-to-machine coordinates, detect fiducials or paper corners, preview the transform, and require user confirmation before applying alignment to a plot job.
- **Evidence:** Page coordinates, placement, snapping, manual jog, and alignment already provide mathematical foundations, but there is no camera pipeline or calibration persistence.
- **Dependencies:** M1 preflight, reliable manual calibration, project-scoped calibration profiles, camera/device support research on Windows and macOS, and repeatability measurements on the actual plotter.
- **Principal risk:** Calibration drift or false detection can ruin physical work; the system must fail closed and always show the proposed transform.

### A3. Publish a PFM/generator plugin SDK — score 1.2

- **User problem:** New algorithms currently require editing the repository and understanding internal engine/server conventions.
- **Outcome:** Define a versioned manifest, parameter schema, execution contract, capability declaration, packaging model, sandbox/trust policy, compatibility tests, and documentation for third-party PFMs and generators.
- **Evidence:** Internal `register()` functions and typed `Param` schemas are promising seams, but imports, state, drawing types, progress, errors, and security are not a stable public boundary.
- **Dependencies:** Modularize worker/API responsibilities, stabilize recipes/schema migration, define resource/cancellation contracts, and decide whether plugins are trusted local Python or isolated processes.
- **Principal risk:** Executing third-party Python inside a hardware-controlling application creates compatibility and security obligations far larger than the current internal registry.

## Recommended sequence

1. **Baseline quality in parallel:** remove the 14 label warnings and add performance trend aggregation. These are low-risk changes that improve every later release.
2. **Make work trustworthy:** ship visible save/error/retry state and pass A5 across a real backend restart before expanding persistence-dependent features.
3. **Clarify the first session:** add contextual first-artwork states using the now-stable save and error language; preserve the current low interaction count.
4. **Protect physical output:** deliver plot preflight and arm/start before camera work, advanced automation, or broader hardware support.
5. **Create one job model:** extend project ownership and cooperative cancellation across processing, generation, segmentation, and plotting.
6. **Complete the essential creative loop:** stabilize uv-based SAM2 readiness, then move D1-D6 and F6/F8/F9 out of the deferred list with full journeys.
7. **Capture and compare successful work:** add recipes first, then visual version comparison once schema migration and dirty-state protection exist.
8. **Reassess scale:** pursue durable workers only if restart recovery, background work, or multi-project demand justifies the architecture. Evaluate camera calibration after preflight proves the coordinate/safety model. Revisit an SDK last.

The first releasable milestone is steps 1–4: accessible controls, trustworthy persistence, contextual onboarding, and safe plotting. The next creative milestone is steps 5–7. Ambitious bets do not outrank these prerequisites.

## Explicit non-priorities

- **No plugin SDK in the next release.** Internal registries are sufficient until worker, schema, trust, and migration boundaries stabilize.
- **No camera-controlled transform before preflight and calibration evidence.** Manual alignment and snapping should become dependable first.
- **No concurrent multi-project execution as a goal by itself.** Project-scoped jobs and restart recovery matter; parallelism is useful only if measured demand exceeds the complexity of GPU/plotter scheduling.
- **No framework rewrite.** Svelte, Flask, the engine registries, and the on-disk project model already support the highest-value roadmap work. Extract boundaries incrementally around jobs and plotting.
- **No hard cross-machine performance gate yet.** Establish segmented trends and baselines before failing CI on CUDA/MPS/CPU timing differences.
- **No return to Conda.** Keep uv as the environment authority and retain separate Windows/macOS launchers where platform GPU setup differs.
- **No silent SAM2 downgrade or removal.** SAM2 is essential to the region workflow. The product should diagnose and repair compatible setup, not hide the feature or allow an automatic install to replace a working CUDA/MPS stack.
- **No new algorithm-count target before editing reliability.** The existing PFM/generator breadth is already a strength; finishing regions, masks, safety, recipes, and comparison creates more user value than adding another family immediately.
