// Plot preview / emulator playback engine.
//
// All animation state lives here (Svelte 5 runes) so the app state stays untouched.
// Geometry + timeline are stored as parallel typed arrays — compact for the
// tens of thousands of vertices a dot drawing produces, and a binary search on
// t1 maps a playback time to a segment in O(log n).
//
// Timing is a port of the server's _estimate_polylines (web/server.py) with one
// deliberate difference: position re-homes to (0,0) at each pen start, matching
// the multi-pen worker. The client retimes locally so changing speed settings
// doesn't need a round trip.

import type { PlotPreview } from "./types";

// kind: 0 = pause (pen up/down, draws nothing), 1 = travel, 2 = draw
type Kind = 0 | 1 | 2;

export interface Seg {
  x0: number; y0: number; x1: number; y1: number;
  t0: number; t1: number;
  kind: Kind;
  colour: string;
}

function secondsForDistance(distMm: number, speedMmMin: number): number {
  const s = Number(speedMmMin) || 0;
  return s <= 0 ? 0 : (Number(distMm) / s) * 60;
}

class PlotPlayback {
  // ── public reactive state ───────────────────────────────────────────────
  loading = $state(false);
  loaded = $state(false);
  error = $state<string | null>(null);
  playing = $state(false);
  speed = $state<1 | 5 | 20 | 100>(5);
  currentTime = $state(0);
  totalTime = $state(0);
  copies = $state(1);
  markers = $state<{ t: number; name: string; colour: string }[]>([]);
  loadGeneration = $state(0);

  // ── geometry / timeline (parallel typed arrays) ─────────────────────────
  private x0 = new Float64Array(0);
  private y0 = new Float64Array(0);
  private x1 = new Float64Array(0);
  private y1 = new Float64Array(0);
  private t0 = new Float64Array(0);
  private t1 = new Float64Array(0);
  private kind = new Uint8Array(0);   // 0 pause / 1 travel / 2 draw
  private pen = new Uint16Array(0);   // pen index
  private ptype = new Uint8Array(0);  // for pauses: 0 = lower, 1 = raise
  private dist = new Float64Array(0); // travel/draw distance (mm)
  private colours: string[] = [];
  private penStart: number[] = [];    // segment index each pen starts at
  private penNames: string[] = [];

  private raf = 0;
  private lastTs = 0;

  reset() {
    this.stopRaf();
    this.loading = false;
    this.loaded = false;
    this.error = null;
    this.playing = false;
    this.currentTime = 0;
    this.totalTime = 0;
    this.copies = 1;
    this.markers = [];
    this.x0 = this.x1 = this.y0 = this.y1 = this.t0 = this.t1 = this.dist = new Float64Array(0);
    this.kind = this.ptype = new Uint8Array(0);
    this.pen = new Uint16Array(0);
    this.colours = [];
    this.penStart = [];
    this.penNames = [];
    this.loadGeneration++;
  }

  // Build geometry from the preview payload, then compute timing from settings.
  load(payload: PlotPreview, settings: Record<string, any>) {
    // Count segments: per path → 1 travel + 1 lower-pause + (n-1) draw +
    // 1 raise-pause; plus one final travel home after the last pen.
    const pens = payload.pens || [];
    let count = 0;
    let hasAny = false;
    for (const p of pens) {
      for (const path of p.paths) {
        const n = path.length / 2;
        if (n < 2) continue;
        count += n + 2; // travel + lower + (n-1) draw + raise
        hasAny = true;
      }
    }
    if (hasAny) count += 1; // final travel home

    this.x0 = new Float64Array(count);
    this.y0 = new Float64Array(count);
    this.x1 = new Float64Array(count);
    this.y1 = new Float64Array(count);
    this.t0 = new Float64Array(count);
    this.t1 = new Float64Array(count);
    this.kind = new Uint8Array(count);
    this.pen = new Uint16Array(count);
    this.ptype = new Uint8Array(count);
    this.dist = new Float64Array(count);
    this.colours = pens.map((p) => p.colour || "#000000");
    this.penNames = pens.map((p) => p.name || "Pen");
    this.penStart = [];

    let i = 0;
    let px = 0, py = 0; // pen position
    const push = (
      ax: number, ay: number, bx: number, by: number, k: Kind, penIdx: number, pt = 0,
    ) => {
      this.x0[i] = ax; this.y0[i] = ay; this.x1[i] = bx; this.y1[i] = by;
      this.kind[i] = k; this.pen[i] = penIdx; this.ptype[i] = pt;
      this.dist[i] = Math.hypot(bx - ax, by - ay);
      i++;
    };

    for (let pi = 0; pi < pens.length; pi++) {
      const drawablePaths = pens[pi].paths.filter((p) => p.length >= 4);
      if (drawablePaths.length === 0) continue;
      this.penStart.push(i);
      px = 0; py = 0; // re-home at each pen start (matches multi-pen worker)
      for (const path of drawablePaths) {
        const sx = path[0], sy = path[1];
        push(px, py, sx, sy, 1, pi);            // travel to path start
        push(sx, sy, sx, sy, 0, pi, 0);         // pen-lower pause
        let lx = sx, ly = sy;
        for (let v = 2; v < path.length; v += 2) {
          const nx = path[v], ny = path[v + 1];
          push(lx, ly, nx, ny, 2, pi);          // draw segment
          lx = nx; ly = ny;
        }
        push(lx, ly, lx, ly, 0, pi, 1);         // pen-raise pause
        px = lx; py = ly;
      }
    }
    if (hasAny) push(px, py, 0, 0, 1, Math.max(0, pens.length - 1)); // travel home

    this.copies = Math.max(1, Number(settings?.copies ?? 1) || 1);
    this.retime(settings);
    this.currentTime = 0;
    this.playing = false;
    this.error = null;
    this.loaded = true;
    this.loadGeneration++;
  }

  // Recompute t0/t1 from settings without rebuilding geometry.
  retime(settings: Record<string, any>) {
    const speedUp = Number(settings?.speed_penup ?? 0) || 0;
    const speedDown = Number(settings?.speed_pendown ?? 0) || 0;
    const zDelta = Math.abs(
      (Number(settings?.pen_pos_down ?? 0) || 0) - (Number(settings?.pen_pos_up ?? 0) || 0),
    );
    const lowerSec =
      secondsForDistance(zDelta, settings?.pen_rate_lower) +
      (Number(settings?.pen_delay_down ?? 0) || 0) / 1000;
    const raiseSec =
      secondsForDistance(zDelta, settings?.pen_rate_raise) +
      (Number(settings?.pen_delay_up ?? 0) || 0) / 1000;

    let t = 0;
    const n = this.kind.length;
    for (let i = 0; i < n; i++) {
      let dur = 0;
      const k = this.kind[i];
      if (k === 1) dur = secondsForDistance(this.dist[i], speedUp);
      else if (k === 2) dur = secondsForDistance(this.dist[i], speedDown);
      else dur = this.ptype[i] === 0 ? lowerSec : raiseSec;
      this.t0[i] = t;
      t += dur;
      this.t1[i] = t;
    }
    this.totalTime = t;
    if (this.currentTime > t) this.currentTime = t;

    this.markers = this.penStart.map((segIdx) => ({
      t: this.t0[segIdx],
      name: this.penNames[this.pen[segIdx]] ?? "Pen",
      colour: this.colours[this.pen[segIdx]] ?? "#000000",
    }));
  }

  // ── playback controls ───────────────────────────────────────────────────
  play() {
    if (!this.loaded || this.playing) return;
    if (this.currentTime >= this.totalTime) this.currentTime = 0;
    this.playing = true;
    this.lastTs = 0;
    this.raf = requestAnimationFrame(this.tick);
  }

  pause() {
    this.playing = false;
    this.stopRaf();
  }

  seek(t: number) {
    this.currentTime = Math.min(this.totalTime, Math.max(0, Number(t) || 0));
  }

  setSpeed(s: number) {
    const allowed = [1, 5, 20, 100];
    this.speed = (allowed.includes(s) ? s : 5) as 1 | 5 | 20 | 100;
  }

  private tick = (ts: number) => {
    if (!this.playing) return;
    if (this.lastTs === 0) this.lastTs = ts;
    const dt = (ts - this.lastTs) / 1000;
    this.lastTs = ts;
    this.currentTime += dt * this.speed;
    if (this.currentTime >= this.totalTime) {
      this.currentTime = this.totalTime;
      this.pause();
      return;
    }
    this.raf = requestAnimationFrame(this.tick);
  };

  private stopRaf() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  // ── read accessors for the Viewport ─────────────────────────────────────
  get segCount() {
    return this.kind.length;
  }

  // Largest segment index whose t1 <= t (last fully-completed segment), or -1.
  segIndexAtOrBefore(t: number): number {
    let lo = 0, hi = this.t1.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.t1[mid] <= t) { ans = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    return ans;
  }

  segAt(i: number): Seg {
    return {
      x0: this.x0[i], y0: this.y0[i], x1: this.x1[i], y1: this.y1[i],
      t0: this.t0[i], t1: this.t1[i],
      kind: this.kind[i] as Kind,
      colour: this.colours[this.pen[i]] ?? "#000000",
    };
  }
}

export const plotPlayback = new PlotPlayback();
