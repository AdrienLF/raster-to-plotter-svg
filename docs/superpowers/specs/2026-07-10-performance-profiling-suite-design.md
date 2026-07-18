# Performance Profiling Suite Design

**Date:** 2026-07-10

**Status:** Approved design, pending implementation plan

## Purpose

PlotterForge has useful performance signals but no unified profiling system. Backend wide events record operation and stage durations, and selected Playwright stories append wall-clock measurements to JSONL. Those measurements are not normalized, cover only a small subset of the application, do not capture CPU or memory profiles, do not compare like-for-like machines, and do not produce a trend report.

This work will add a full local and CI profiling suite and implement one measured optimization in SVG circle parsing. Performance regressions will be reported as warnings, not CI failures. Correctness and profiling-infrastructure failures will continue to fail.

## Evidence and Targeted Optimization

The existing K9 Playwright journey was reproduced with a 7,983-circle drawing. Disabling path ordering did not materially reduce the roughly 5.2-second plot-estimate latency, showing that ordering was not the primary cost. Function-level profiling separated the stages as follows:

- SVG parsing: approximately 4.9 seconds without profiler overhead.
- Nearest-path ordering: approximately 0.63 seconds.
- Estimate calculation: approximately 0.03 seconds.

Under `cProfile`, about 92% of SVG parsing time was attributable to `svgelements` bounding-box calculations triggered by `_circle_meta()` for every circle. A diagnostic direct-center/radius implementation reduced the same parse from approximately 4.9 seconds to 0.91 seconds, a 5.37x speedup. It produced the same path count and geometry with a maximum coordinate difference of approximately `2.84e-14` from floating-point operation order.

The production optimization will use already-resolved circle center and radius values when they describe a valid circle. Ellipses, malformed shapes, or geometry that cannot be proven circular will retain the existing bounding-box/flattening fallback. Fidelity tests will cover native circles, ellipses, transforms, groups, and clipped shapes before the fast path is enabled.

## Goals

1. Provide one command-line profiling interface for local CPU, MPS, CUDA, and browser workloads.
2. Cover engine primitives, every registered PFM and generator, SVG/composition/plot pipelines, server journeys, and representative browser rendering.
3. Record repeated wall time, CPU profile data, Python peak memory, GPU timing and memory where supported, output metrics, and full environment identity.
4. Normalize existing Playwright performance records into the same result model.
5. Produce raw JSON, Markdown summaries, named-baseline comparisons, and diagnostic profile artifacts.
6. Publish a warning-only CI trend report and downloadable artifacts.
7. Make results comparable only within matching workload, fixture, backend, hardware, and software segments.
8. Preserve output fidelity while removing the measured SVG circle parsing bottleneck.

## Non-goals

- Performance regressions will not fail CI.
- CPU, MPS, and CUDA results will not be compared with each other.
- The suite will not install or require native sampling profilers such as py-spy or Scalene.
- The suite will not change PlotterForge's user-facing behavior or UI.
- The suite will not profile physical plotter motion; it profiles preparation and command-generation software only.
- The implementation will not refactor unrelated engine or server code.

## Architecture

The suite will be a first-party Python package with a thin command-line entry point. It will use the standard library for orchestration, statistics, `cProfile`, `pstats`, and `tracemalloc`. Existing project dependencies provide NumPy, SciPy, Pillow, Flask, SVG parsing, and optional PyTorch acceleration.

The package will have focused responsibilities:

- **Model:** versioned result, environment, workload, and baseline records.
- **Environment:** commit, OS, architecture, Python, dependency, backend, and accelerator identity.
- **Workloads:** deterministic fixture setup, one measured callable, output invariants, and workload-specific warning floors.
- **Runner:** subprocess isolation, warmups, repeated sampling, synchronization, CPU profiles, and memory measurements.
- **GPU adapter:** accelerator discovery, synchronization, memory metrics, PyTorch tracing, and fallback detection.
- **Playwright adapter:** conversion of current browser JSONL records into normalized samples.
- **Reporter:** aggregation, segmentation, baseline comparison, Markdown/JSON output, and CI annotations.
- **CLI:** `quick`, `full`, `diagnose`, and explicit baseline-management commands.

The data flow is one-way:

`workload registry -> isolated measurements -> normalized samples -> aggregation -> reports and artifacts`

Application projects, settings, caches, and user files will not be profiling storage. Runtime artifacts will live under `artifacts/profiling/<run-id>/` and will be ignored by Git. Only named baselines under `profiling/baselines/` may be committed.

## Result Model

Each run has a stable schema version, run ID, UTC timestamp, command, commit, and environment record. Each sample contains at least:

- workload ID and workload version;
- fixture ID and fixture checksum;
- category and requested/actual backend;
- cold or warm classification and sample index;
- duration in milliseconds;
- Python peak bytes when memory measurement is enabled;
- GPU allocation/reservation metrics when supported;
- output metrics such as shape count, segment count, path count, SVG bytes, or geometry checksum;
- outcome (`success`, `error`, or `skipped`) and a structured reason;
- links to associated CPU/GPU trace artifacts.

Environment segmentation includes:

- OS name and version;
- CPU architecture and processor identity;
- Python implementation and version;
- package and schema versions relevant to the workload;
- actual PlotterForge backend;
- PyTorch version;
- CUDA runtime, device name, and compute capability for CUDA;
- Apple hardware identity and OS version for MPS;
- workload dtype, problem size, and accelerator tile configuration.

A sample requested as GPU is invalid if execution falls back to NumPy. The runner will report that as an infrastructure/correctness error instead of silently classifying the result as GPU.

## Workload Matrix

### Engine primitives

- nearest-site assignment below and above the production GPU crossover;
- weighted centroids;
- greedy nearest-path ordering;
- endpoint chaining;
- rectangle and polygon clipping;
- SVG serialization and path-length estimation.

### Creative engines

- every PFM registered in `engine.pfm.REGISTRY`;
- every generator registered in `engine.generate.GENERATORS`;
- representative explicit sampler/style combinations for stable family-level trends;
- final and draft-quality PFM runs where both paths exist.

All stochastic workloads use fixed seeds. Registry enumeration makes newly added PFMs and generators visible automatically; adding one without a successful full-profile result is reported as a workload failure.

### SVG, composition, and plot pipeline

- dense native-circle SVG parsing, which protects the measured optimization;
- mixed path, curve, ellipse, and transformed SVG parsing;
- clipped and Cavalry-style nested-clip parsing;
- crop, mask, and occlusion composition;
- multi-layer composition and SVG serialization;
- per-pen SVG splitting;
- plot polyline preparation with each ordering mode;
- plot estimate and preview-path preparation;
- cold and warm path-cache behavior.

### Application and browser journeys

The existing performance stories for import, PFM generation, generator execution, version saving, export, plot preparation, and event latency will be ingested rather than duplicated. Browser-specific workloads will add app boot, large-composition loading, and large-SVG viewport rendering.

The `full` command requires its selected categories to be available. Missing Playwright/browser prerequisites are an explicit infrastructure error unless the caller deliberately excludes the browser category. A report may never label a run "full" after an implicit category skip.

## Fixtures and Correctness Invariants

Fixtures will be deterministic and versioned. The suite will reuse the small checked-in image where appropriate and generate synthetic dense SVG and composition fixtures from fixed parameters so large binary fixtures are unnecessary.

Every workload defines at least one invariant that is checked outside the measured region:

- exact shape, path, or segment count;
- geometry checksum after stable coordinate quantization;
- expected page dimensions;
- SVG parseability;
- required backend;
- non-empty output and stable output byte class where exact bytes are inappropriate.

Fixture or invariant changes require a workload-version increment. Results with different workload versions or fixture checksums are incomparable.

## Measurement Profiles

### Quick

- Intended for normal development and pull requests.
- One warmup and three warm samples by default.
- Uses a representative CPU-safe workload subset.
- CI overrides warm samples to five.
- Does not generate heavyweight diagnostic traces unless a workload fails.

### Full

- Intended for release checks and deliberate performance work.
- Two warmups and ten warm samples by default.
- Covers every workload in the selected categories.
- Defaults to `all` backends: forced CPU plus every available production accelerator.
- Includes isolated cold-start measurements for backend initialization, PFM setup, SVG parser startup, and browser boot workload groups.

### Diagnose

- Targets one workload ID.
- One warmup and five warm samples by default.
- Adds one separate `cProfile` run and one separate memory run.
- Adds accelerator-specific tracing for a GPU workload.
- Profiling overhead never contributes to ordinary wall-time samples.

The CLI exposes `--backend auto|cpu|gpu|all`, repeat overrides, category inclusion/exclusion, output directory, and named baseline selection. `quick` defaults to `auto`; `full` defaults to `all`; `diagnose` defaults to `auto`.

## CPU and Memory Profiling

Wall time uses `time.perf_counter_ns()`. Python CPU diagnostics use `cProfile` and persist `.prof` files that can be opened with standard `pstats`-compatible tools. The Markdown report includes the top cumulative functions for convenience.

Python peak memory uses `tracemalloc` in a separate run. It is labeled as Python-managed allocation rather than total process resident memory. Workload output is released between measurement phases, and subprocess isolation prevents retained caches from leaking across backend groups.

## GPU Profiling

GPU timing must account for asynchronous execution. The adapter will synchronize the active device immediately before starting and immediately after stopping every timed region. It will separately record fresh-process cold behavior and warmed steady-state samples.

GPU workloads will include accelerator primitives with problem sizes above the application's production crossover and real PFM runs that use those primitives. Reports will state requested and actual backend for every sample.

### CUDA

CUDA diagnostics will use PyTorch CPU/CUDA activities to capture operator and kernel timing, transfers, and a Chrome-trace-compatible artifact. Each memory run resets peak counters and reports maximum allocated and reserved bytes after synchronization.

Comparisons require matching CUDA device model, compute capability, PyTorch version, CUDA runtime, dtype, problem size, and tile configuration.

### MPS

The pinned PyTorch 2.6 profiler exposes no portable MPS `ProfilerActivity`. MPS timing will therefore use explicit synchronization around end-to-end and stage regions. Memory records will include current allocated and driver-allocated bytes at defined synchronized boundaries. Diagnose mode will support PyTorch MPS signposts for inspection in Instruments.

The report will state that MPS signpost traces require Instruments and that synchronized wall/stage time, not CPU dispatch time, is the portable MPS timing source. Comparisons require matching Apple hardware identity, macOS version, PyTorch version, dtype, problem size, and tile configuration.

## Aggregation and Baselines

The reporter calculates sample count, minimum, median, nearest-rank p90, maximum, and peak recorded memory. Cold samples are reported separately from warm samples.

Baseline comparison requires an exact match on workload ID/version, fixture checksum, backend, hardware segment, relevant runtime versions, dtype, problem size, and tile configuration. A mismatch is `incomparable`, never a regression.

The default warning policy is:

1. current warm median is more than 20% slower than baseline warm median;
2. the absolute median increase is at least 25 milliseconds; and
3. at least 75% of current warm samples exceed the baseline median.

Workloads whose expected median is below 25 milliseconds may declare a smaller absolute floor in their registry entry. The ratio and majority conditions remain unchanged. These warnings never change the process exit code.

A named baseline is created or replaced only by an explicit command that points at a completed results file. Baseline updates validate that all included records succeeded and that environment segments are internally consistent. CI never updates a baseline.

## Reports and CI

Each run produces:

- `results.json` with normalized samples and environment metadata;
- `summary.md` with aggregate tables, baseline deltas, and warnings;
- `profiles/*.prof` for requested CPU diagnostics;
- GPU trace/signpost metadata for requested accelerator diagnostics;
- Playwright report and trace artifacts when browser workloads run.

A new GitHub Actions workflow will install locked CPU dependencies, run the quick CPU profile with five warm samples, run the selected browser performance journeys, compare against the named CPU-CI baseline, write warnings to the job summary, and upload the profiling directory with finite retention.

The universal CI lane is CPU-only. The workflow design permits an additional explicitly labeled GPU runner, but the initial implementation will not pretend that a hosted CPU runner measures MPS or CUDA. Local `full` runs automatically include available MPS/CUDA hardware.

## Error and Exit Policy

Independent workloads continue after an error so the final report retains useful coverage. At completion:

- performance warnings exit successfully;
- incomparable results exit successfully and are clearly labeled;
- unavailable optional backends are skipped only when they were not explicitly requested;
- missing required categories, invalid result records, changed invariants, requested-GPU fallback, profiler crashes, and broken application journeys exit unsuccessfully.

Errors include workload ID, phase, requested/actual backend, exception type, and message. Tracebacks remain in raw artifacts; the Markdown summary stays concise.

## SVG Circle Optimization

The optimization changes only native-circle recognition in the plot SVG parser:

1. Confirm that the parsed element is a circle/ellipse shape with finite resolved center and radii.
2. Use resolved center and equal radii directly for the native-arc fast path.
3. Fall back to the existing bounding-box and flattening behavior when the shape is non-circular, malformed, clipped, or cannot be proven safe.
4. Preserve current coordinate conversion, Y inversion, arc point sampling, and `ArcPath` metadata.

Tests will compare the optimized and fallback representations within a strict numeric tolerance, including transformed and grouped inputs. A structural regression test will ensure that ordinary dense native circles do not invoke the expensive bounding-box path. The profiling workload records the improvement, but no unit test contains a machine-specific timing threshold.

## Testing Strategy

The implementation will be test-driven. Automated coverage will include:

- schema serialization, validation, and version rejection;
- environment and backend segmentation;
- deterministic percentile aggregation;
- default and workload-specific warning thresholds;
- incomparable baseline cases;
- workload error isolation and final exit behavior;
- output invariant and geometry-checksum failures;
- CPU profile and Python-memory artifact creation;
- Playwright JSONL normalization;
- CLI profile and baseline-update flows;
- mocked GPU synchronization, memory collection, and fallback detection;
- conditional real MPS/CUDA smoke tests when hardware is available;
- circle/ellipse/transform/group/clip parsing fidelity;
- dense-circle fast-path structure and end-to-end plot estimate fidelity.

The final verification run will include the complete Python test suite, frontend checks/tests, a quick profiling run, the dense-circle diagnose workload, and a real local MPS profile when the accelerator is available. Browser tests will use the repository's isolated temporary-home and fake-serial setup.

## Documentation

Developer documentation will cover:

- quick, full, and diagnose commands;
- CPU, MPS, CUDA, and browser prerequisites;
- how to read Markdown, `.prof`, CUDA trace, and MPS signpost artifacts;
- baseline creation and intentional update workflow;
- environment segmentation and incomparable results;
- warning-only CI behavior;
- the difference between Python memory, CUDA peak memory, and MPS boundary memory.

The product feature list will mention the profiling/trend capability only if that file's established commit convention requires it; no artist-facing manual changes are needed.

## Acceptance Criteria

1. One documented CLI runs quick, full, and single-workload diagnostic profiles.
2. Full mode discovers every PFM and generator and refuses to claim full coverage after an implicit category skip.
3. CPU results include repeated timing, CPU profile, and Python peak-memory support.
4. Available MPS/CUDA hardware is profiled by default in full mode with synchronized timing and backend-specific diagnostics.
5. A requested GPU workload fails visibly on NumPy fallback.
6. Existing Playwright performance records normalize into the common schema.
7. JSON and Markdown reports include environment segmentation, median/p90, memory, output metrics, and baseline deltas.
8. CI publishes warning-only trend summaries and downloadable artifacts.
9. Correctness or profiler-infrastructure failures return a failure exit code.
10. The dense-circle SVG workload retains geometry fidelity and demonstrates the measured parser improvement without a machine-specific test threshold.
