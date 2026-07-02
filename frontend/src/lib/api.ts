import { studio, pushLog, reportError } from "./state.svelte";
import { plotPlayback } from "./plotPlayback.svelte";
import type { CompositionLayerT, MaskShape, Param, PathfindingStyleT, PlotPreview, SegmentationPromptT } from "./types";

// Active export request, so the Cancel button can abort it client-side while
// /api/export/cancel stops the server-side compose.
let exportController: AbortController | null = null;

async function jget(url: string) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || r.statusText);
  return r.json();
}
async function jpost(url: string, body?: any, method = "POST") {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || r.statusText);
  return r.json();
}

function paramDefaults(schema: Param[]): Record<string, any> {
  const out: Record<string, any> = {};
  for (const p of schema) out[p.name] = p.default;
  return out;
}

// Svelte's deeply reactive state is a Proxy, which structuredClone rejects.
// Generator settings are JSON data already, so serialize them when crossing
// between API payloads, composition snapshots, and reactive state.
function cloneData<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function layerStyle(layer: CompositionLayerT | null | undefined) {
  const style = (layer?.pathfinding_style ?? {}) as Partial<PathfindingStyleT>;
  return {
    enabled: style.enabled ?? true,
    pfm_id: style.pfm_id ?? studio.pfmId,
    params: { ...(style.params ?? {}) },
    status: style.status ?? "stale",
    error: style.error ?? "",
    cache: { ...(style.cache ?? {}) },
  };
}

function normalizeReordering(value: any) {
  const key = String(value).trim().toLowerCase().replace(/[-\s]/g, "_");
  const aliases: Record<string, string> = {
    "0": "none",
    "false": "none",
    none: "none",
    off: "none",
    "1": "nearest",
    nearest: "nearest",
    nearest_neighbor: "nearest",
    nearest_neighbour: "nearest",
    "2": "nearest_reversible",
    nearest_reverse: "nearest_reversible",
    nearest_reversible: "nearest_reversible",
    reversible: "nearest_reversible",
    "3": "two_opt",
    twoopt: "two_opt",
    "2opt": "two_opt",
    "2_opt": "two_opt",
    two_opt: "two_opt",
  };
  return aliases[key] ?? "nearest";
}

let genPending = false;
let genTimer: ReturnType<typeof setTimeout> | null = null;
let projectGeneration = 0;
let samPollTimer: ReturnType<typeof setTimeout> | null = null;

// Poll SAM setup status every 1.5s until ready/error, so the UI shows live
// install/download progress without blocking any request.
function scheduleSamPoll() {
  if (samPollTimer) return;
  samPollTimer = setTimeout(async () => {
    samPollTimer = null;
    let s: any;
    try {
      s = await jget("/api/segmentation/status");
    } catch {
      return; // give up quietly; re-selecting the model retriggers polling
    }
    studio.segmentationStatus = s;
    if (!s.available && s.setup_state !== "error" && s.auto_setup !== false) {
      scheduleSamPoll();
    } else if (s.available) {
      pushLog("AI segmentation ready");
    }
  }, 1500);
}

function beginProjectGeneration() {
  projectGeneration += 1;
  return projectGeneration;
}

function isCurrentProject(generation: number) {
  return generation === projectGeneration;
}

function reportBootError(error: unknown) {
  studio.processing = false;
  reportError("Boot error", error);
  console.error(error);
}

function flushGenerate() {
  if (genTimer) clearTimeout(genTimer);
  genTimer = setTimeout(() => {
    if (!genPending || studio.processing) return;
    genPending = false;
    void api.generate();
  }, 0);
}

export const api = {
  invalidateProjectWork() {
    return beginProjectGeneration();
  },

  async boot(generation = beginProjectGeneration()) {
    try {
      const [list, gens, area, pens, settings, plotJob, composition, projects, regions, segStatus] = await Promise.all([
        jget("/api/pfm/list"),
        jget("/api/generate/list"),
        jget("/api/area"),
        jget("/api/pens"),
        jget("/api/settings"),
        jget("/api/plot/job"),
        jget("/api/composition"),
        jget("/api/projects"),
        jget("/api/regions"),
        jget("/api/segmentation/status"),
      ]);
      if (!isCurrentProject(generation)) return false;
      studio.pfms = list.pfms;
      studio.backend = list.backend;
      studio.generators = gens.generators;
      studio.area = area.area;
      studio.presets = area.presets;
      studio.drawingSet = pens.drawing_set;
      studio.libraries = pens.libraries;
      studio.settings = { ...settings, reordering: normalizeReordering(settings.reordering) };
      studio.plotJob = plotJob;
      this.applyComposition(composition);
      this.applyProject(projects);
      this.applyRegions(regions);
      studio.segmentationStatus = segStatus;
      this.watchSamSetup();
      await this.selectPfm(studio.pfmId, generation);
      if (!isCurrentProject(generation)) return false;
      await this.selectGenerator(studio.generatorId, generation);
      if (!isCurrentProject(generation)) return false;
      await this.restoreGeneratorLayer(studio.selectedLayer);
      if (!isCurrentProject(generation)) return false;
      await this.refreshVersions(generation);
      if (!isCurrentProject(generation)) return false;
      return true;
    } catch (error) {
      if (!isCurrentProject(generation)) return false;
      throw error;
    }
  },

  applyProject(payload: any) {
    if (payload?.projects) studio.projects = payload.projects;
    if (payload?.current) {
      studio.currentProject = { id: payload.current.id, name: payload.current.name };
      studio.imageName = payload.current.image_name || "";
      studio.imageUrl = payload.current.image_url ?? null;
      studio.imageW = payload.current.image_width ?? studio.imageW;
      studio.imageH = payload.current.image_height ?? studio.imageH;
      studio.selectedRegionId = payload.current.selected_region_id ?? studio.selectedRegionId;
    }
  },

  // Reload everything for a freshly created/opened project.
  async switchProject(payload: any, generation = beginProjectGeneration()) {
    if (!isCurrentProject(generation)) return false;
    this.applyProject(payload);
    studio.previewSvg = null;
    studio.stats = null;
    studio.plotProgress = null;
    studio.plotEstimate = null;
    plotPlayback.reset();
    studio.processing = false;
    studio.plotting = false;
    studio.progress = 0;
    studio.status = "Idle";
    studio.regionDraftMask = null;
    studio.regionDraftBbox = null;
    studio.regionPositivePoints = [];
    studio.regionNegativePoints = [];
    studio.regionSelecting = false;
    studio.regionPredicting = false;
    studio.maskMode = null;
    studio.maskEdit = false;
    studio.layerStyleOpen = false;
    studio.cavalryPrompt = null;
    try {
      return await this.boot(generation);
    } catch (error) {
      if (isCurrentProject(generation)) reportBootError(error);
      return false;
    }
  },

  async newProject(name: string) {
    const generation = beginProjectGeneration();
    try {
      const payload = await jpost("/api/projects", { name });
      if (!isCurrentProject(generation)) return;
      await this.switchProject(payload, generation);
    } catch (error) {
      if (isCurrentProject(generation)) reportBootError(error);
    }
  },

  async openProject(id: string) {
    if (id === studio.currentProject?.id) return;
    const generation = beginProjectGeneration();
    try {
      const payload = await jpost(`/api/projects/${id}/open`);
      if (!isCurrentProject(generation)) return;
      await this.switchProject(payload, generation);
    } catch (error) {
      if (isCurrentProject(generation)) reportBootError(error);
    }
  },

  async renameProject(id: string, name: string) {
    this.applyProject(await jpost(`/api/projects/${id}`, { name }, "PATCH"));
  },

  async deleteProject(id: string) {
    const generation = beginProjectGeneration();
    try {
      const payload = await jpost(`/api/projects/${id}`, undefined, "DELETE");
      if (!isCurrentProject(generation)) return;
      await this.switchProject(payload, generation);
    } catch (error) {
      if (isCurrentProject(generation)) reportBootError(error);
    }
  },

  applyComposition(payload: any) {
    if (payload?.composition) studio.composition = payload.composition;
    if (payload && "svg" in payload) studio.previewSvg = payload.svg;
    // A layer change (visibility, geometry, order) invalidates a loaded preview —
    // it must never keep showing a now-hidden/removed layer. Force a reload.
    if (plotPlayback.loaded || plotPlayback.loading) plotPlayback.reset();
  },

  applyRegions(payload: any) {
    if (payload?.regions) studio.regions = payload.regions;
    if (payload && "selected_region_id" in payload) {
      studio.selectedRegionId = payload.selected_region_id ?? null;
    }
  },

  async refreshComposition() {
    const j = await jget("/api/composition");
    this.applyComposition(j);
    return j;
  },

  async patchLayer(id: string, data: Record<string, any>) {
    const j = await jpost(`/api/composition/layers/${id}`, data, "PATCH");
    this.applyComposition(j);
    await this.refreshEstimate(true);
    return j;
  },

  async cropToContent(id: string) {
    const j = await jpost(`/api/composition/layers/${id}/crop-to-content`);
    this.applyComposition(j);
    await this.refreshEstimate(true);
    return j;
  },

  async clearCrop(id: string) {
    return this.patchLayer(id, { crop: null });
  },

  async setMask(id: string, mask: MaskShape) {
    return this.patchLayer(id, { mask });
  },

  async clearMask(id: string) {
    return this.patchLayer(id, { mask: null });
  },

  async selectLayer(id: string) {
    if (!id) return;
    await this.patchLayer(id, { selected: true });
    await this.restoreGeneratorLayer(studio.selectedLayer);
  },

  // Clear the target so the next generate / upload creates a new layer.
  async newLayer() {
    const j = await jpost("/api/composition/new-layer");
    this.applyComposition(j);
    await this.refreshEstimate(true);
    return j;
  },

  // Create a concrete, selectable empty path-finding layer (Photoshop-style
  // "new layer" you then apply an algorithm to via the Path Finding window).
  async addPathfindingLayer(region_id?: string | null) {
    const j = await jpost("/api/composition/add-layer", { region_id: region_id ?? undefined });
    this.applyComposition(j);
    await this.refreshEstimate(true);
    return j;
  },

  // Armed Cavalry capture layer: receives live frames from the Cavalry bridge.
  async addCavalryLayer() {
    const j = await jpost("/api/composition/cavalry-layer");
    this.applyComposition(j);
    return j;
  },

  // Answer the "Cavalry reconnected" prompt.
  async cavalrySession(action: "new" | "continue" | "dismiss") {
    const j = await jpost("/api/cavalry/session", { action });
    studio.cavalryPrompt = null;
    if (j.composition) this.applyComposition(j);
    return j;
  },

  async duplicateLayer(id: string) {
    const j = await jpost(`/api/composition/layers/${id}/duplicate`);
    this.applyComposition(j);
    await this.refreshEstimate(true);
  },

  async deleteLayer(id: string) {
    const j = await jpost(`/api/composition/layers/${id}`, undefined, "DELETE");
    this.applyComposition(j);
    await this.refreshEstimate(true);
  },

  async moveLayer(id: string, direction: number) {
    const j = await jpost(`/api/composition/layers/${id}/move`, { direction });
    this.applyComposition(j);
    await this.refreshEstimate(true);
  },

  async selectGenerator(id: string, generation = projectGeneration) {
    if (!isCurrentProject(generation)) return false;
    studio.generatorId = id;
    const sch = await jget(`/api/generate/${id}/schema`);
    if (!isCurrentProject(generation)) return false;
    studio.genSchema = sch.params;
    studio.generatorEditor = sch.editor ?? null;
    const defaults = cloneData(sch.defaults ?? {});
    studio.generatorDefaults = defaults;
    studio.generatorShapeTypes = sch.shape_types ?? [];
    const keep: Record<string, any> = {};
    for (const p of sch.params) keep[p.name] = studio.genParams[p.name] ?? p.default;
    if (studio.generatorEditor === "shape_field") {
      keep.shape_layers = cloneData(
        Array.isArray(studio.genParams.shape_layers)
          ? studio.genParams.shape_layers
          : defaults.shape_layers ?? [],
      );
    }
    studio.genParams = keep;
    return true;
  },

  async restoreGeneratorLayer(layer: CompositionLayerT | null | undefined) {
    if (layer?.kind !== "generate" || !layer.source?.generator_id) return false;
    const previousAutoRedraw = studio.autoRedraw;
    studio.autoRedraw = false;
    try {
      if (!await this.selectGenerator(layer.source.generator_id)) return false;
      studio.genParams = {
        ...studio.genParams,
        ...cloneData(layer.source.params ?? {}),
      };
      return true;
    } finally {
      studio.autoRedraw = previousAutoRedraw;
    }
  },

  async generate() {
    studio.processing = true;
    studio.status = "Generating";
    studio.progress = 0;
    await jpost("/api/generate", {
      generator_id: studio.generatorId,
      params: studio.genParams,
    }).catch((e) => {
      studio.processing = false;
      reportError("Generate error", e);
      flushGenerate();
    });
  },

  // Coalescing redraw: at most one generate in flight; the latest params are
  // always rendered next. Gives near-real-time feedback while dragging sliders.
  requestGenerate() {
    genPending = true;
    flushGenerate();
  },

  async selectPfm(id: string, generation = projectGeneration) {
    if (!isCurrentProject(generation)) return false;
    studio.pfmId = id;
    const sch = await jget(`/api/pfm/${id}/schema`);
    if (!isCurrentProject(generation)) return false;
    studio.schema = sch.params;
    studio.params = { ...paramDefaults(sch.params), ...studio.params };
    // drop params not in the new schema
    const keep: Record<string, any> = {};
    for (const p of sch.params) keep[p.name] = studio.params[p.name] ?? p.default;
    studio.params = keep;
    return true;
  },

  async loadLayerStyleSchema(pfmId: string) {
    const sch = await jget(`/api/pfm/${pfmId}/schema`);
    studio.layerStyleSchema = sch.params;
    return sch.params as Param[];
  },

  async patchLayerStyle(layerId: string, patch: Record<string, any>) {
    const layer = studio.composition.layers.find((item) => item.id === layerId);
    const next = { ...layerStyle(layer), ...patch };
    return this.patchLayer(layerId, { pathfinding_style: next });
  },

  clearRegionDraft() {
    studio.regionDraftMask = null;
    studio.regionDraftBbox = null;
    studio.regionPositivePoints = [];
    studio.regionNegativePoints = [];
  },

  async selectRegion(id: string) {
    studio.selectedRegionId = id || null;
  },

  async setSamModel(model: string) {
    try {
      studio.segmentationStatus = await jpost("/api/segmentation/model", { model });
      pushLog(`SAM model → ${model.replace("sam2.1_hiera_", "")}`);
      scheduleSamPoll();
    } catch (e) {
      pushLog("SAM model error: " + (e instanceof Error ? e.message : String(e)));
    }
  },

  // Poll segmentation status while the model is still installing/downloading so
  // the UI reflects live setup progress.
  watchSamSetup() {
    const s = studio.segmentationStatus;
    if (s && !s.available && s.setup_state !== "error" && s.auto_setup !== false) {
      scheduleSamPoll();
    }
  },

  async predictRegion(prompt?: SegmentationPromptT) {
    const generation = projectGeneration;
    const body = prompt ?? {
      positive_points: studio.regionPositivePoints,
      negative_points: studio.regionNegativePoints,
    };
    if (!body.positive_points.length) {
      pushLog("Add a positive region click first");
      return null;
    }
    studio.regionPredicting = true;
    try {
      const j = await jpost("/api/segmentation/predict", body);
      if (!isCurrentProject(generation)) return null;
      studio.regionDraftMask = j.mask_png;
      studio.regionDraftBbox = j.bbox_px ?? null;
      studio.regionPositivePoints = j.positive_points ?? body.positive_points;
      studio.regionNegativePoints = j.negative_points ?? body.negative_points;
      return j;
    } catch (e) {
      if (isCurrentProject(generation)) {
        pushLog("Region prediction error: " + (e instanceof Error ? e.message : String(e)));
      }
      return null;
    } finally {
      if (isCurrentProject(generation)) studio.regionPredicting = false;
    }
  },

  async saveRegion(name = "Region", invert = false) {
    if (!studio.regionDraftMask) {
      pushLog("No region mask to save");
      return null;
    }
    const j = await jpost("/api/regions", {
      name,
      mask_png: studio.regionDraftMask,
      bbox_px: studio.regionDraftBbox,
      positive_points: studio.regionPositivePoints,
      negative_points: studio.regionNegativePoints,
      invert,
    });
    this.applyRegions(j);
    this.clearRegionDraft();
    studio.regionSelecting = false;
    pushLog(`Saved region ${j.region?.name ?? name}`);
    return j.region;
  },

  async renameRegion(id: string, name: string) {
    const j = await jpost(`/api/regions/${id}`, { name }, "PATCH");
    this.applyRegions(j);
  },

  async deleteRegion(id: string) {
    const j = await jpost(`/api/regions/${id}`, undefined, "DELETE");
    this.applyRegions(j);
    if (studio.selectedRegionId === id) studio.selectedRegionId = j.selected_region_id ?? null;
  },

  async uploadImage(file: File) {
    studio.status = `Loading ${file.name}…`;
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/image", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "upload failed");
      studio.imageUrl = j.image_url ?? j.data_url;
      studio.imageName = j.name;
      studio.imageW = j.width;
      studio.imageH = j.height;
      studio.regions = [];
      studio.selectedRegionId = null;
      this.clearRegionDraft();
      studio.status = "Ready";
      pushLog(`Loaded image ${j.name} (${j.width}×${j.height})`);
    } catch (e) {
      reportError("Image load error", e);
      throw e;
    }
  },

  async uploadSvg(file: File) {
    studio.status = `Loading ${file.name}…`;
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) {
      reportError("SVG load error", j.error || "SVG upload failed");
      throw new Error(j.error || "SVG upload failed");
    }
    this.applyComposition(j);
    studio.imageUrl = null;
    studio.imageName = j.name;
    studio.processing = false;
    studio.progress = 0;
    studio.status = "Ready";
    studio.placement = { x: 0, y: 0 };
    studio.stats = null;
    studio.plotProgress = null;
    pushLog(`Loaded SVG ${j.name}`);
  },

  async saveArea() {
    if (!studio.area) return;
    await jpost("/api/area", studio.area);
  },

  async savePens() {
    if (!studio.drawingSet) return;
    await jpost("/api/pens", studio.drawingSet);
  },

  async loadLibrary(name: string) {
    const j = await jget(`/api/pens/library/${encodeURIComponent(name)}`);
    if (studio.drawingSet) studio.drawingSet.pens = j.pens;
    await this.savePens();
  },

  async process() {
    if (!studio.imageUrl) {
      pushLog("Load an image first");
      return;
    }
    studio.processing = true;
    studio.status = "Processing";
    studio.progress = 0;
    await this.saveArea();
    await this.savePens();
    await jpost("/api/process", {
      pfm_id: studio.pfmId,
      params: studio.params,
      area: studio.area,
      drawing_set: studio.drawingSet,
      region_id: studio.selectedRegionId || undefined,
    }).catch((e) => {
      studio.processing = false;
      reportError("Process error", e);
    });
  },

  async generateLayerPathfinding(id: string) {
    const layer = studio.composition.layers.find((item) => item.id === id);
    if (!layer) return;
    if (!studio.imageUrl) {
      pushLog("Load an image first");
      return;
    }
    const style = layerStyle(layer);
    studio.processing = true;
    studio.status = "Generating layer";
    studio.progress = 0;
    try {
      await this.saveArea();
      await this.savePens();
      const j = await jpost(`/api/composition/layers/${id}/pathfinding/generate`, {
        pfm_id: style.pfm_id,
        params: style.params,
        region_id: layer.region_id,
        enabled: style.enabled,
        display_mode: layer.display_mode,
        area: studio.area,
        drawing_set: studio.drawingSet,
      });
      this.applyComposition(j);
      studio.status = "Ready";
      studio.progress = 1;
      // Don't block "Ready" on the plot-time estimate — it re-parses the whole
      // drawing and can take a moment on dense stipples. Let it fill in after.
      void this.refreshEstimate(true);
      pushLog(`Generated layer ${layer.name}`);
      return j;
    } catch (e) {
      reportError("Layer pathfinding error", e);
      return null;
    } finally {
      studio.processing = false;
    }
  },

  async refreshVersions(generation = projectGeneration) {
    const j = await jget("/api/versions");
    if (!isCurrentProject(generation)) return false;
    studio.versions = j.versions;
    return true;
  },

  async saveVersion(name: string, notes: string) {
    await jpost("/api/versions", { name, notes });
    await this.refreshVersions();
  },

  async deleteVersion(id: string) {
    await jpost(`/api/versions/${id}`, undefined, "DELETE");
    await this.refreshVersions();
  },

  async rateVersion(id: string, rating: number) {
    await jpost(`/api/versions/${id}`, { rating }, "PATCH");
    await this.refreshVersions();
  },

  async moveVersion(id: string, direction: number) {
    await jpost(`/api/versions/${id}/move`, { direction });
    await this.refreshVersions();
  },

  async clearVersions() {
    await jpost("/api/versions/clear");
    await this.refreshVersions();
  },

  async loadVersion(id: string) {
    const j = await jpost(`/api/versions/${id}/load`);
    studio.pfmId = j.pfm_id;
    studio.schema = j.schema;
    studio.params = j.params;
    studio.area = j.area;
    studio.drawingSet = j.drawing_set;
    pushLog("Loaded version");
    if (j.composition) {
      this.applyComposition(j);
      const restoredLayer = studio.selectedLayer;
      await this.restoreGeneratorLayer(restoredLayer);
      studio.previewSvg = null;
      studio.stats = null;
      studio.plotEstimate = null;
      studio.plotProgress = null;
      studio.processing = false;
      studio.progress = 1;
      studio.status = "Ready";
    } else {
      await this.process();
    }
  },

  exportUrl(split = false) {
    return split ? "/api/export?split=1" : "/api/export";
  },

  // Fetch the export (so we get progress via the event stream + real error
  // handling) and trigger a download from the resulting blob.
  async exportSvg(split = false) {
    if (studio.exporting) return;
    const controller = new AbortController();
    exportController = controller;
    studio.exporting = true;
    studio.processing = true;
    studio.progress = 0;
    studio.status = "Exporting…";
    try {
      const res = await fetch(this.exportUrl(split), { signal: controller.signal });
      if (res.status === 409) {
        studio.status = "Export canceled"; // server stopped mid-compose
        return;
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.error || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = split ? "plot_layers.zip" : "plot.svg";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      studio.status = "Exported";
    } catch (e: any) {
      if (e?.name === "AbortError") studio.status = "Export canceled";
      else reportError("Export failed", e);
    } finally {
      studio.exporting = false;
      studio.processing = false;
      studio.progress = 0;
      exportController = null;
    }
  },

  async cancelExport() {
    exportController?.abort();
    try {
      await fetch("/api/export/cancel", { method: "POST" });
    } catch {
      /* server already finished or unreachable */
    }
  },

  async plot() {
    studio.plotProgress = null;
    const j = await jpost("/api/plot").catch((e) => {
      pushLog("Plot error: " + e.message);
      return null;
    });
    if (j?.job) studio.plotJob = j.job;
  },

  async resumePlot() {
    studio.plotProgress = null;
    const j = await jpost("/api/plot/resume");
    if (j.job) studio.plotJob = j.job;
    pushLog("Resume requested");
  },

  async stop() {
    await jpost("/api/stop").catch(() => {});
    await this.refreshPlotJob();
  },

  async saveSettings() {
    if (!studio.settings) return;
    const j = await jpost("/api/settings", studio.settings);
    studio.settings = { ...j.cfg, reordering: normalizeReordering(j.cfg.reordering) };
    pushLog(`Plotter settings saved · ${j.cfg.port}`);
  },

  async refreshEstimate(silent = false) {
    // The estimate is only shown on the Plot step, but computing it re-parses the
    // whole drawing (tens of thousands of dots) with svgelements — ~30s, minutes
    // with occlusion clipping. Layer mutations call this after every change, so
    // skip it off the Plot step; entering Plot refreshes it. This is what makes
    // show/hide and occlusion toggles feel instant.
    if (studio.step !== "plot") return null;
    const r = await fetch("/api/plot/estimate");
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      studio.plotEstimate = null;
      if (!silent) pushLog("Estimate error: " + (j.error || r.statusText));
      return null;
    }
    studio.plotEstimate = j;
    return j;
  },

  async fetchPlotPreview(): Promise<PlotPreview | null> {
    const r = await fetch("/api/plot/preview-paths");
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      pushLog("Preview error: " + (j.error || r.statusText));
      return null;
    }
    return j as PlotPreview;
  },

  async refreshPlotJob() {
    const j = await jget("/api/plot/job");
    studio.plotJob = j;
    return j;
  },

  async discardPlotJob() {
    await jpost("/api/plot/discard");
    studio.plotJob = { exists: false, resumable: false };
    studio.plotProgress = null;
    pushLog("Saved plot job discarded");
  },

  async plotPens(): Promise<{ multi: boolean; pens: import("./types").PlotPen[] }> {
    const j = await jget("/api/plot/pens").catch(() => ({ multi: false, pens: [] }));
    return { multi: !!j.multi, pens: j.pens ?? [] };
  },

  async confirmPen() {
    studio.penChange = null;
    await jpost("/api/plot/confirm-pen").catch((e) => pushLog("Confirm pen error: " + e.message));
  },

  async savePlacement(silent = true) {
    const layer = studio.selectedLayer;
    if (layer) {
      await this.patchLayer(layer.id, { x: layer.x, y: layer.y });
      if (!silent) {
        pushLog(`Layer saved · x ${layer.x.toFixed(1)} · y ${layer.y.toFixed(1)} mm`);
      }
      return;
    }
    await jpost("/api/placement", studio.placement);
    await this.refreshEstimate(true);
    if (!silent) {
      pushLog(`Placement saved · x ${studio.placement.x.toFixed(1)} · y ${studio.placement.y.toFixed(1)} mm`);
    }
  },

  async manual(cmd: string, data: Record<string, any> = {}) {
    const j = await jpost("/api/manual", { cmd, ...data });
    if (j.status) studio.machineStatus = j.status;
    return j;
  },
};

// ── Server-Sent Events: live process + plot progress ────────────────────────────
export function connectStream() {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    let m: any;
    try {
      m = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (m.t === "ping") return;
    if (m.t === "proc") handleProc(m);
    else if (m.t === "log") pushLog(m.msg);
    else if (m.t === "cavalry") void api.refreshComposition();
    else if (m.t === "cavalry_session")
      studio.cavalryPrompt = { session: m.session, layer_id: m.layer_id ?? null, layer_name: m.layer_name ?? null };
    else if (m.t === "state") {
      studio.plotting =
        m.state === "plotting" ||
        m.state === "homing" ||
        m.state === "parsing" ||
        m.state === "pen_change";
      if (m.state === "pen_change") {
        studio.status = "Change pen";
        studio.penChange = {
          name: m.name,
          colour: m.colour,
          pen_index: m.pen_index ?? 0,
          pen_total: m.pen_total ?? 0,
          copy_index: m.copy_index ?? 0,
          copies: m.copies ?? 1,
          reason: m.reason ?? "swap",
        };
        return;
      }
      studio.status = cap(m.state);
      studio.penChange = null;
      if (m.state === "plotting") {
        studio.plotProgress = {
          done: m.done ?? 0,
          total: m.total ?? 0,
          segments_remaining: Math.max(0, (m.total ?? 0) - (m.done ?? 0)),
          shapes_done: m.shapes_done ?? 0,
          shapes_total: m.shapes_total ?? 0,
          shapes_remaining: Math.max(0, (m.shapes_total ?? 0) - (m.shapes_done ?? 0)),
          elapsed_seconds: 0,
          remaining_seconds: m.estimated_seconds ?? null,
          progress_fraction: 0,
        };
      } else if (m.state === "done" || m.state === "idle" || m.state === "error") {
        void api.refreshPlotJob();
      }
    } else if (m.t === "progress") {
      if (m.phase === "plotting") {
        studio.plotProgress = {
          done: m.done ?? 0,
          total: m.total ?? 0,
          segments_remaining: m.segments_remaining ?? 0,
          shapes_done: m.shapes_done ?? 0,
          shapes_total: m.shapes_total ?? 0,
          shapes_remaining: m.shapes_remaining ?? 0,
          elapsed_seconds: m.elapsed_seconds ?? 0,
          remaining_seconds: m.remaining_seconds ?? null,
          progress_fraction: m.progress_fraction ?? 0,
        };
        studio.progress = studio.plotProgress.progress_fraction;
      } else if (m.total) {
        studio.progress = m.done / m.total;
      }
    } else if (m.t === "error") {
      reportError("Plotter error", m.msg);
    }
  };
  es.onerror = () => {
    /* browser auto-reconnects */
  };
  return es;
}

function handleProc(m: any) {
  if (m.state === "running") {
    studio.processing = true;
    studio.status = "Processing";
  } else if (m.state === "progress") {
    studio.progress = m.frac ?? 0;
    studio.status = "Processing · " + (m.stage ?? "");
  } else if (m.state === "done") {
    studio.processing = false;
    studio.progress = 1;
    studio.status = "Ready";
    studio.previewSvg = m.svg;
    if (m.composition) {
      studio.composition = m.composition;
    } else {
      void api.refreshComposition();
    }
    studio.stats = {
      total: m.total,
      length_mm: m.length_mm,
      backend: m.backend,
      per_pen: m.per_pen,
    };
    pushLog(`Generated ${m.total} shapes · ${m.length_mm} mm · ${m.backend}`);
    void api.refreshEstimate(true);
  } else if (m.state === "error") {
    studio.processing = false;
    reportError("Process error", m.msg);
  }
}

function cap(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
