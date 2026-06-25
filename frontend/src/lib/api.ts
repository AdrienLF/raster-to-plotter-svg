import { studio, pushLog } from "./state.svelte";
import type { Param } from "./types";

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

export const api = {
  async boot() {
    const [list, area, pens, settings, plotJob] = await Promise.all([
      jget("/api/pfm/list"),
      jget("/api/area"),
      jget("/api/pens"),
      jget("/api/settings"),
      jget("/api/plot/job"),
    ]);
    studio.pfms = list.pfms;
    studio.backend = list.backend;
    studio.area = area.area;
    studio.presets = area.presets;
    studio.drawingSet = pens.drawing_set;
    studio.libraries = pens.libraries;
    studio.settings = { ...settings, reordering: normalizeReordering(settings.reordering) };
    studio.plotJob = plotJob;
    await this.selectPfm(studio.pfmId);
    await this.refreshVersions();
  },

  async selectPfm(id: string) {
    studio.pfmId = id;
    const sch = await jget(`/api/pfm/${id}/schema`);
    studio.schema = sch.params;
    studio.params = { ...paramDefaults(sch.params), ...studio.params };
    // drop params not in the new schema
    const keep: Record<string, any> = {};
    for (const p of sch.params) keep[p.name] = studio.params[p.name] ?? p.default;
    studio.params = keep;
  },

  async uploadImage(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/image", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "upload failed");
    studio.imageUrl = j.image_url ?? j.data_url;
    studio.imageName = j.name;
    studio.imageW = j.width;
    studio.imageH = j.height;
    pushLog(`Loaded image ${j.name} (${j.width}×${j.height})`);
  },

  async uploadSvg(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "SVG upload failed");
    studio.previewSvg = j.svg;
    studio.imageUrl = null;
    studio.imageName = j.name;
    studio.processing = false;
    studio.progress = 0;
    studio.status = "Ready";
    studio.placement = { x: 0, y: 0 };
    studio.stats = null;
    studio.plotProgress = null;
    pushLog(`Loaded SVG ${j.name}`);
    await this.refreshEstimate(true);
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
    }).catch((e) => {
      studio.processing = false;
      studio.status = "Error";
      pushLog("Process error: " + e.message);
    });
  },

  async refreshVersions() {
    const j = await jget("/api/versions");
    studio.versions = j.versions;
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
    await this.process();
  },

  exportUrl(split = false) {
    return split ? "/api/export?split=1" : "/api/export";
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

  async savePlacement(silent = true) {
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
    else if (m.t === "state") {
      studio.status = cap(m.state);
      studio.plotting = m.state === "plotting" || m.state === "homing" || m.state === "parsing";
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
      pushLog("⚠ " + m.msg);
      studio.status = "Error";
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
    studio.status = "Error";
    pushLog("Process error: " + m.msg);
  }
}

function cap(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
