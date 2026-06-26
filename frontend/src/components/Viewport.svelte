<script lang="ts">
  import { api } from "../lib/api";
  import {
    A4_PORTRAIT,
    alignPlacement,
    snapPlacement,
    type AlignMode,
  } from "../lib/placement";
  import { anchorOffset, effectiveBounds, studio } from "../lib/state.svelte";
  import type { CompositionLayerT, MaskShape } from "../lib/types";

  const PX_PER_MM = 2.4;

  let zoom = $state(1);
  let tx = $state(0);
  let ty = $state(0);
  let vw = $state(0);
  let vh = $state(0);
  let dragging = false;
  let placing = $state(false);
  let lastX = 0;
  let lastY = 0;
  let pageEl: HTMLDivElement;
  let placementPointer: HTMLElement | null = null;
  let placementLayerId: string | null = null;
  let placementStart = { x: 0, y: 0 };
  let placementOrigin = { x: 0, y: 0 };
  let snapGuideX = $state<number | null>(null);
  let snapGuideY = $state<number | null>(null);
  let fitted = false;

  const areaPage = $derived.by(() => {
    const a = studio.area;
    if (!a) return { w: 297, h: 420, bg: "#202020", canvas: "#fff" };
    const f = a.units === "cm" ? 10 : a.units === "in" ? 25.4 : a.units === "px" ? 25.4 / 96 : 1;
    let w = a.width * f, h = a.height * f;
    if (a.orientation === "landscape" && h > w) [w, h] = [h, w];
    if (a.orientation === "portrait" && w > h) [w, h] = [h, w];
    return { w, h, bg: a.background_colour, canvas: a.canvas_colour };
  });

  const page = $derived.by(() => {
    const compPage = studio.composition.page;
    return {
      w: Number(compPage.width) || 297,
      h: Number(compPage.height) || 420,
      bg: areaPage.bg,
      canvas: "#fff",
    };
  });

  const selectedLayer = $derived(studio.selectedLayer);

  const drawingSize = $derived.by(() => {
    if (!selectedLayer) return { w: page.w, h: page.h };
    const eb = effectiveBounds(selectedLayer);
    return { w: eb.width, h: eb.height };
  });

  const a4Guide = $derived.by(() => ({
    w: Math.min(A4_PORTRAIT.w, page.w),
    h: Math.min(A4_PORTRAIT.h, page.h),
  }));

  const sourceMode = $derived(!!studio.imageUrl && (studio.regionSelecting || !studio.composition.layers.length));
  const sourceRect = $derived.by(() => {
    const iw = studio.imageW || page.w;
    const ih = studio.imageH || page.h;
    const scale = Math.min(page.w / iw, page.h / ih);
    const w = iw * scale;
    const h = ih * scale;
    return { x: (page.w - w) / 2, y: (page.h - h) / 2, w, h, scale };
  });

  export function fit() {
    if (!vw || !vh) return;
    const s = Math.min(vw / (page.w * PX_PER_MM), vh / (page.h * PX_PER_MM)) * 0.9;
    zoom = s || 1;
    tx = (vw - page.w * PX_PER_MM * zoom) / 2;
    ty = (vh - page.h * PX_PER_MM * zoom) / 2;
  }

  // One-shot auto-fit once the viewport first has a measured size. After that
  // the user controls zoom/pan (and the Fit button re-runs fit() on demand).
  $effect(() => {
    if (!fitted && vw && vh) {
      fitted = true;
      fit();
    }
  });

  function onWheel(e: WheelEvent) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const nz = Math.min(40, Math.max(0.05, zoom * factor));
    // zoom toward cursor
    const rx = e.offsetX, ry = e.offsetY;
    tx = rx - (rx - tx) * (nz / zoom);
    ty = ry - (ry - ty) * (nz / zoom);
    zoom = nz;
  }
  function onDown(e: PointerEvent) {
    if (placing) return;
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onMove(e: PointerEvent) {
    if (placing) {
      movePlacement(e);
      return;
    }
    if (!dragging) return;
    tx += e.clientX - lastX;
    ty += e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
  }
  function onUp(e: PointerEvent) {
    if (placing) {
      finishPlacement(e);
      return;
    }
    dragging = false;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }

  function clientToPage(e: PointerEvent) {
    const rect = pageEl.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (page.w / rect.width),
      y: (e.clientY - rect.top) * (page.h / rect.height),
    };
  }

  function clientToSource(e: PointerEvent) {
    const p = clientToPage(e);
    const r = sourceRect;
    if (p.x < r.x || p.y < r.y || p.x > r.x + r.w || p.y > r.y + r.h) return null;
    return {
      x: Math.round((p.x - r.x) / r.scale),
      y: Math.round((p.y - r.y) / r.scale),
    };
  }

  function regionDown(e: PointerEvent) {
    if (!studio.regionSelecting) return;
    e.preventDefault();
    e.stopPropagation();
    const p = clientToSource(e);
    if (!p) return;
    if (e.button === 2 || e.altKey) {
      studio.regionNegativePoints = [...studio.regionNegativePoints, p];
    } else {
      studio.regionPositivePoints = [...studio.regionPositivePoints, p];
    }
    void api.predictRegion();
  }

  function startPlacement(e: PointerEvent, layerId: string) {
    const layer = studio.composition.layers.find((item) => item.id === layerId);
    if (!layer) return;
    e.preventDefault();
    e.stopPropagation();
    if (studio.composition.selected_layer_id !== layerId) {
      studio.composition.selected_layer_id = layerId;
      void api.selectLayer(layerId);
    }
    // Layers are selectable/movable in every editing step now, except while
    // picking an image region (the source overlay owns the pointer there).
    if (studio.step === "plot" || studio.regionSelecting) return;
    placing = true;
    placementLayerId = layerId;
    placementPointer = e.currentTarget as HTMLElement;
    placementPointer.setPointerCapture(e.pointerId);
    placementStart = clientToPage(e);
    // Work in effective (visible/cropped/scaled) space so snapping aligns what's drawn.
    const off = anchorOffset(layer);
    placementOrigin = { x: layer.x + off.x, y: layer.y + off.y };
  }

  function movePlacement(e: PointerEvent) {
    if (!placementLayerId) return;
    const layer = studio.composition.layers.find((item) => item.id === placementLayerId);
    if (!layer) return;
    const mm = clientToPage(e);
    const off = anchorOffset(layer);
    const raw = {
      x: placementOrigin.x + mm.x - placementStart.x,
      y: placementOrigin.y + mm.y - placementStart.y,
    };
    const snapped = snapPlacement(raw, drawingSize, page, A4_PORTRAIT, 4, false);
    layer.x = round1(snapped.x - off.x);
    layer.y = round1(snapped.y - off.y);
    snapGuideX = snapped.guideX;
    snapGuideY = snapped.guideY;
  }

  function finishPlacement(e: PointerEvent) {
    const layer = placementLayerId
      ? studio.composition.layers.find((item) => item.id === placementLayerId)
      : null;
    placing = false;
    placementLayerId = null;
    snapGuideX = null;
    snapGuideY = null;
    placementPointer?.releasePointerCapture?.(e.pointerId);
    placementPointer = null;
    if (layer) void api.patchLayer(layer.id, { x: layer.x, y: layer.y });
  }

  export function align(mode: AlignMode) {
    const layer = selectedLayer;
    if (!layer) return;
    const off = anchorOffset(layer);
    const aligned = alignPlacement(
      mode,
      { x: layer.x + off.x, y: layer.y + off.y },
      drawingSize,
      page,
      false,
    );
    layer.x = round1(aligned.x - off.x);
    layer.y = round1(aligned.y - off.y);
    void api.patchLayer(layer.id, { x: layer.x, y: layer.y });
  }

  function round1(value: number) {
    return Math.round(value * 10) / 10;
  }

  function displayMode(layer: CompositionLayerT) {
    return layer.display_mode ?? "pathfinding";
  }

  function layerShowsRaster(layer: CompositionLayerT) {
    return !!layer.region_id && (!layer.pathfinding_style?.enabled || displayMode(layer) === "raster" || displayMode(layer) === "both");
  }

  function layerShowsPaths(layer: CompositionLayerT) {
    return (layer.pathfinding_style?.enabled ?? true) && displayMode(layer) !== "raster";
  }

  function layerRasterUrl(layer: CompositionLayerT) {
    const stamp = layer.pathfinding_style?.cache?.generated_at ?? layer.region_id ?? layer.id;
    return `/api/composition/layers/${layer.id}/raster?v=${encodeURIComponent(String(stamp))}`;
  }

  // ── Mask drawing ──────────────────────────────────────────────────────────
  type Pt = { x: number; y: number };
  type Anchor = { x: number; y: number; hx: number; hy: number };

  let draftStart = $state<Pt | null>(null);
  let draftEnd = $state<Pt | null>(null);
  let drawingMask = false;
  let penAnchors = $state<Anchor[]>([]);
  let penHover = $state<Pt | null>(null);
  let penDragging = false;

  const f3 = (n: number) => Math.round(n * 1000) / 1000;
  const inHandle = (a: Anchor) => ({ x: 2 * a.x - a.hx, y: 2 * a.y - a.hy });

  function maskDown(e: PointerEvent) {
    if (!selectedLayer) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const p = clientToPage(e);
    if (studio.maskMode === "pen") {
      penDragging = true;
      penAnchors = [...penAnchors, { x: p.x, y: p.y, hx: p.x, hy: p.y }];
    } else {
      drawingMask = true;
      draftStart = p;
      draftEnd = p;
    }
  }

  function maskMove(e: PointerEvent) {
    if (!studio.maskMode) return;
    const p = clientToPage(e);
    if (studio.maskMode === "pen") {
      penHover = p;
      if (penDragging && penAnchors.length) {
        const a = penAnchors[penAnchors.length - 1];
        a.hx = p.x;
        a.hy = p.y;
      }
      return;
    }
    if (!drawingMask) return;
    if (e.shiftKey && draftStart) {
      // Constrain to a square (rect) / circle (oval).
      const dx = p.x - draftStart.x;
      const dy = p.y - draftStart.y;
      const m = Math.max(Math.abs(dx), Math.abs(dy));
      draftEnd = {
        x: draftStart.x + (dx < 0 ? -m : m),
        y: draftStart.y + (dy < 0 ? -m : m),
      };
    } else {
      draftEnd = p;
    }
  }

  function maskUp(e: PointerEvent) {
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    if (studio.maskMode === "pen") {
      penDragging = false;
      return;
    }
    if (!drawingMask) return;
    drawingMask = false;
    commitDragShape();
  }

  function commitDragShape() {
    const layer = selectedLayer;
    if (!layer || !draftStart || !draftEnd) {
      draftStart = draftEnd = null;
      return;
    }
    const s = layer.scale || 1;
    const x0 = (Math.min(draftStart.x, draftEnd.x) - layer.x) / s;
    const y0 = (Math.min(draftStart.y, draftEnd.y) - layer.y) / s;
    const w = Math.abs(draftEnd.x - draftStart.x) / s;
    const h = Math.abs(draftEnd.y - draftStart.y) / s;
    draftStart = draftEnd = null;
    if (w < 0.5 || h < 0.5) {
      studio.maskMode = null;
      return;
    }
    const mask: MaskShape =
      studio.maskMode === "ellipse"
        ? { type: "ellipse", cx: x0 + w / 2, cy: y0 + h / 2, rx: w / 2, ry: h / 2 }
        : { type: "rect", x: x0, y: y0, width: w, height: h };
    studio.maskMode = null;
    void api.setMask(layer.id, mask);
  }

  function penFinish() {
    const layer = selectedLayer;
    if (!layer || penAnchors.length < 2) {
      resetPen();
      return;
    }
    const d = buildPenPath(penAnchors, layer);
    resetPen();
    studio.maskMode = null;
    void api.setMask(layer.id, { type: "path", d });
  }

  function resetPen() {
    penAnchors = [];
    penHover = null;
    penDragging = false;
  }

  function buildPenPath(anchors: Anchor[], layer: CompositionLayerT) {
    const s = layer.scale || 1;
    const P = anchors.map((a) => ({
      x: (a.x - layer.x) / s,
      y: (a.y - layer.y) / s,
      hx: (a.hx - layer.x) / s,
      hy: (a.hy - layer.y) / s,
    }));
    let d = `M ${f3(P[0].x)} ${f3(P[0].y)}`;
    const seg = (a: typeof P[0], b: typeof P[0]) => {
      const bi = inHandle(b as unknown as Anchor);
      return ` C ${f3(a.hx)} ${f3(a.hy)} ${f3(bi.x)} ${f3(bi.y)} ${f3(b.x)} ${f3(b.y)}`;
    };
    for (let i = 1; i < P.length; i++) d += seg(P[i - 1], P[i]);
    d += seg(P[P.length - 1], P[0]) + " Z";
    return d;
  }

  function penPreviewD(): string {
    if (!penAnchors.length) return "";
    const pts = penHover
      ? [...penAnchors, { x: penHover.x, y: penHover.y, hx: penHover.x, hy: penHover.y }]
      : penAnchors;
    let d = `M ${pts[0].x} ${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1];
      const b = pts[i];
      const bi = inHandle(b);
      d += ` C ${a.hx} ${a.hy} ${bi.x} ${bi.y} ${b.x} ${b.y}`;
    }
    return d;
  }

  function onKey(e: KeyboardEvent) {
    if (!studio.maskMode) return;
    if (e.key === "Escape") {
      studio.maskMode = null;
      resetPen();
      draftStart = draftEnd = null;
      drawingMask = false;
    } else if (e.key === "Enter" && studio.maskMode === "pen") {
      penFinish();
    }
  }

  // ── Editing an existing mask (move / resize via bounding box) ──────────────
  type Box = { x: number; y: number; w: number; h: number };
  let editKind = $state<null | "move" | "nw" | "ne" | "se" | "sw">(null);
  let editStart = { x: 0, y: 0 };
  let editBox0: Box = { x: 0, y: 0, w: 0, h: 0 };

  const handleMm = $derived(7 / (PX_PER_MM * zoom));

  function maskBBox(m: MaskShape): Box {
    if (m.type === "rect") return { x: m.x, y: m.y, w: m.width, h: m.height };
    if (m.type === "ellipse")
      return { x: m.cx - m.rx, y: m.cy - m.ry, w: 2 * m.rx, h: 2 * m.ry };
    const nums = (m.d.match(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi) ?? []).map(Number);
    const xs: number[] = [];
    const ys: number[] = [];
    for (let i = 0; i + 1 < nums.length; i += 2) {
      xs.push(nums[i]);
      ys.push(nums[i + 1]);
    }
    if (!xs.length) return { x: 0, y: 0, w: 0, h: 0 };
    const minX = Math.min(...xs),
      minY = Math.min(...ys);
    return { x: minX, y: minY, w: Math.max(...xs) - minX, h: Math.max(...ys) - minY };
  }

  function maskFromBox(m: MaskShape, ob: Box, nb: Box): MaskShape {
    if (m.type === "rect") return { type: "rect", x: nb.x, y: nb.y, width: nb.w, height: nb.h };
    if (m.type === "ellipse")
      return { type: "ellipse", cx: nb.x + nb.w / 2, cy: nb.y + nb.h / 2, rx: nb.w / 2, ry: nb.h / 2 };
    const sx = ob.w ? nb.w / ob.w : 1;
    const sy = ob.h ? nb.h / ob.h : 1;
    let i = 0;
    const d = m.d.replace(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi, (n) => {
      const v = +n;
      const out = i % 2 === 0 ? nb.x + (v - ob.x) * sx : nb.y + (v - ob.y) * sy;
      i++;
      return String(f3(out));
    });
    return { type: "path", d };
  }

  function editDown(e: PointerEvent, kind: NonNullable<typeof editKind>) {
    const m = selectedLayer?.mask;
    if (!m) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    editKind = kind;
    editStart = clientToPage(e);
    editBox0 = maskBBox(m);
  }

  function editMove(e: PointerEvent) {
    const layer = selectedLayer;
    if (!editKind || !layer?.mask) return;
    const p = clientToPage(e);
    // Mask coords are layer-local content mm; page deltas scale by the layer scale.
    const s = layer.scale || 1;
    const dx = (p.x - editStart.x) / s;
    const dy = (p.y - editStart.y) / s;
    const ob = editBox0;
    let nb: Box;
    if (editKind === "move") {
      nb = { x: ob.x + dx, y: ob.y + dy, w: ob.w, h: ob.h };
    } else {
      let left = ob.x,
        top = ob.y,
        right = ob.x + ob.w,
        bottom = ob.y + ob.h;
      if (editKind.includes("w")) left = ob.x + dx;
      if (editKind.includes("e")) right = ob.x + ob.w + dx;
      if (editKind.includes("n")) top = ob.y + dy;
      if (editKind.includes("s")) bottom = ob.y + ob.h + dy;
      if (e.shiftKey && ob.w && ob.h) {
        // Keep aspect ratio.
        const s = Math.max(Math.abs(right - left) / ob.w, Math.abs(bottom - top) / ob.h);
        if (editKind.includes("w")) left = right - (right > left ? 1 : -1) * ob.w * s;
        else right = left + ob.w * s;
        if (editKind.includes("n")) top = bottom - (bottom > top ? 1 : -1) * ob.h * s;
        else bottom = top + ob.h * s;
      }
      nb = {
        x: Math.min(left, right),
        y: Math.min(top, bottom),
        w: Math.abs(right - left),
        h: Math.abs(bottom - top),
      };
    }
    layer.mask = maskFromBox(layer.mask, ob, nb);
  }

  function editUp(e: PointerEvent) {
    if (!editKind) return;
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    editKind = null;
    const layer = selectedLayer;
    if (layer?.mask) void api.setMask(layer.id, layer.mask);
  }

  // ── Scaling the layer (uniform; opposite corner stays fixed) ────────────────
  let scaleKind = $state<null | "nw" | "ne" | "se" | "sw">(null);
  let scaleStart = { x: 0, y: 0 };
  let scaleBox0: Box = { x: 0, y: 0, w: 0, h: 0 };
  let scale0 = 1;

  function scaleDown(e: PointerEvent, kind: NonNullable<typeof scaleKind>) {
    const layer = selectedLayer;
    if (!layer) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    scaleKind = kind;
    scaleStart = clientToPage(e);
    const eb = effectiveBounds(layer);
    scaleBox0 = { x: eb.x, y: eb.y, w: eb.width, h: eb.height };
    scale0 = layer.scale || 1;
  }

  function scaleMove(e: PointerEvent) {
    const layer = selectedLayer;
    if (!scaleKind || !layer) return;
    const p = clientToPage(e);
    const ob = scaleBox0;
    let left = ob.x,
      top = ob.y,
      right = ob.x + ob.w,
      bottom = ob.y + ob.h;
    if (scaleKind.includes("w")) left = p.x;
    if (scaleKind.includes("e")) right = p.x;
    if (scaleKind.includes("n")) top = p.y;
    if (scaleKind.includes("s")) bottom = p.y;
    const r = Math.max(Math.abs(right - left) / ob.w, Math.abs(bottom - top) / ob.h);
    if (!Number.isFinite(r) || r <= 0.001) return;
    const newScale = scale0 * r;
    const newW = ob.w * r;
    const newH = ob.h * r;
    // Opposite corner of the dragged handle stays fixed in page space.
    const anchorX = scaleKind.includes("w") ? ob.x + ob.w : ob.x;
    const anchorY = scaleKind.includes("n") ? ob.y + ob.h : ob.y;
    const nx = scaleKind.includes("w") ? anchorX - newW : anchorX;
    const ny = scaleKind.includes("n") ? anchorY - newH : anchorY;
    const cropX = layer.crop?.x ?? 0;
    const cropY = layer.crop?.y ?? 0;
    layer.scale = newScale;
    layer.x = round1(nx - newScale * cropX);
    layer.y = round1(ny - newScale * cropY);
  }

  function scaleUp(e: PointerEvent) {
    if (!scaleKind) return;
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    scaleKind = null;
    const layer = selectedLayer;
    if (layer) void api.patchLayer(layer.id, { scale: layer.scale, x: layer.x, y: layer.y });
  }

  // CSS clip-path (in svgwrap px space; svgwrap is sized to the scaled content).
  function maskClip(layer: CompositionLayerT): string {
    const m = layer.mask;
    if (!m) return "none";
    const s = (layer.scale || 1) * PX_PER_MM;
    if (m.type === "rect") {
      const x1 = (m.x + m.width) * s,
        y1 = (m.y + m.height) * s,
        x0 = m.x * s,
        y0 = m.y * s;
      return `polygon(${x0}px ${y0}px, ${x1}px ${y0}px, ${x1}px ${y1}px, ${x0}px ${y1}px)`;
    }
    if (m.type === "ellipse")
      return `ellipse(${m.rx * s}px ${m.ry * s}px at ${m.cx * s}px ${m.cy * s}px)`;
    return `path("${m.d.replace(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi, (n) => String(+n * s))}")`;
  }

  // ── Occlusion preview ─────────────────────────────────────────────────────
  // Mirrors engine.composition._rect_to_page / _rect_to_layer / _upper_occlusion_masks
  // so the live canvas matches the exported (occluded) SVG.
  type Rect = { x: number; y: number; width: number; height: number };

  function rectToPage(layer: CompositionLayerT, r: Rect): Rect {
    const s = layer.scale || 1;
    return { x: layer.x + s * r.x, y: layer.y + s * r.y, width: s * r.width, height: s * r.height };
  }
  function rectToLayer(layer: CompositionLayerT, r: Rect): Rect {
    const s = layer.scale || 1;
    return { x: (r.x - layer.x) / s, y: (r.y - layer.y) / s, width: r.width / s, height: r.height / s };
  }

  // Occluder rects (in `layer`'s local mm) from visible layers stacked above it.
  function occludersForLayer(layer: CompositionLayerT): Rect[] {
    const visible = studio.composition.layers.filter((l) => l.visible);
    const index = visible.indexOf(layer);
    if (index < 0) return [];
    const out: Rect[] = [];
    for (const upper of visible.slice(index + 1)) {
      const m = upper.occlusion_mask;
      if (!upper.occlude_below || !m || m.type !== "rect") continue;
      out.push(rectToLayer(layer, rectToPage(upper, m)));
    }
    return out;
  }

  // Map a layer-local path `d` into page-mm coordinates for overlay outlines.
  function pathToPage(d: string, layer: CompositionLayerT): string {
    const s = layer.scale || 1;
    let i = 0;
    return d.replace(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi, (n) => {
      const v = +n;
      const out = i % 2 === 0 ? layer.x + s * v : layer.y + s * v;
      i++;
      return String(f3(out));
    });
  }
</script>

<svelte:window onkeydown={onKey} />

<div
  class="viewport"
  style:background={page.bg}
  bind:clientWidth={vw}
  bind:clientHeight={vh}
  onwheel={onWheel}
  onpointerdown={onDown}
  onpointermove={onMove}
  onpointerup={onUp}
  role="presentation"
>
  <div class="stage" style:transform={`translate(${tx}px, ${ty}px) scale(${zoom})`}>
    <div
      bind:this={pageEl}
      class="page"
      class:placing
      style:width={`${page.w * PX_PER_MM}px`}
      style:height={`${page.h * PX_PER_MM}px`}
      style:background={page.canvas}
    >
      {#if sourceMode}
        <div
          class="source-frame"
          style:left={`${sourceRect.x * PX_PER_MM}px`}
          style:top={`${sourceRect.y * PX_PER_MM}px`}
          style:width={`${sourceRect.w * PX_PER_MM}px`}
          style:height={`${sourceRect.h * PX_PER_MM}px`}
        >
          <img class="src" src={studio.imageUrl!} alt="source" />
          {#if studio.regionDraftMask}
            <img class="region-mask-preview" src={studio.regionDraftMask} alt="" />
          {/if}
          {#each studio.regionPositivePoints as point}
            <span
              class="region-point positive"
              style:left={`${point.x * sourceRect.scale * PX_PER_MM}px`}
              style:top={`${point.y * sourceRect.scale * PX_PER_MM}px`}
            ></span>
          {/each}
          {#each studio.regionNegativePoints as point}
            <span
              class="region-point negative"
              style:left={`${point.x * sourceRect.scale * PX_PER_MM}px`}
              style:top={`${point.y * sourceRect.scale * PX_PER_MM}px`}
            ></span>
          {/each}
        </div>
        {#if studio.regionSelecting}
          <div
            class="region-select-overlay"
            onpointerdown={regionDown}
            oncontextmenu={(e) => e.preventDefault()}
            role="presentation"
          ></div>
        {/if}
      {:else if studio.composition.layers.length}
        <div
          class="guide a4"
          style:width={`${a4Guide.w * PX_PER_MM}px`}
          style:height={`${a4Guide.h * PX_PER_MM}px`}
        >
          <div class="mid-v"></div>
          <div class="mid-h"></div>
        </div>
        <div class="sheet-mid-v"></div>
        <div class="sheet-mid-h"></div>
        {#if snapGuideX !== null}
          <div class="snap-v" style:left={`${snapGuideX * PX_PER_MM}px`}></div>
        {/if}
        {#if snapGuideY !== null}
          <div class="snap-h" style:top={`${snapGuideY * PX_PER_MM}px`}></div>
        {/if}
        {#each studio.composition.layers.filter((layer) => layer.visible) as layer (layer.id)}
          {@const eb = effectiveBounds(layer)}
          {@const cropX = layer.crop?.x ?? 0}
          {@const cropY = layer.crop?.y ?? 0}
          <div
            class="art"
            class:selected={layer.id === studio.composition.selected_layer_id}
            class:show-bounds={studio.step === "composition" || studio.showLayerBounds}
            style:left={`${eb.x * PX_PER_MM}px`}
            style:top={`${eb.y * PX_PER_MM}px`}
            style:width={`${eb.width * PX_PER_MM}px`}
            style:height={`${eb.height * PX_PER_MM}px`}
            onpointerdown={(e) => startPlacement(e, layer.id)}
            role="application"
            aria-label={`Layer ${layer.name}`}
          >
            <div
              class="svgwrap"
              style:left={`${-cropX * (layer.scale || 1) * PX_PER_MM}px`}
              style:top={`${-cropY * (layer.scale || 1) * PX_PER_MM}px`}
              style:width={`${layer.width * (layer.scale || 1) * PX_PER_MM}px`}
              style:height={`${layer.height * (layer.scale || 1) * PX_PER_MM}px`}
              style:clip-path={maskClip(layer)}
            >
              {#if layerShowsRaster(layer)}
                <img class="layer-raster" src={layerRasterUrl(layer)} alt="" />
              {/if}
              {#if layerShowsPaths(layer)}
                {@html layer.svg}
              {/if}
              {#each occludersForLayer(layer) as r, i (i)}
                <div
                  class="knockout"
                  style:left={`${r.x * (layer.scale || 1) * PX_PER_MM}px`}
                  style:top={`${r.y * (layer.scale || 1) * PX_PER_MM}px`}
                  style:width={`${r.width * (layer.scale || 1) * PX_PER_MM}px`}
                  style:height={`${r.height * (layer.scale || 1) * PX_PER_MM}px`}
                  style:background={page.canvas}
                ></div>
              {/each}
            </div>
          </div>
        {/each}

        {#if studio.step === "composition" && selectedLayer?.crop}
          {@const ceb = effectiveBounds(selectedLayer)}
          <svg
            class="overlay"
            viewBox={`0 0 ${page.w} ${page.h}`}
            style:width={`${page.w * PX_PER_MM}px`}
            style:height={`${page.h * PX_PER_MM}px`}
          >
            <rect class="ol-crop" x={ceb.x} y={ceb.y} width={ceb.width} height={ceb.height} vector-effect="non-scaling-stroke" />
          </svg>
        {/if}

        {#if studio.step === "composition" && selectedLayer && !studio.maskMode && !studio.maskEdit}
          {@const seb = effectiveBounds(selectedLayer)}
          {@const hs = handleMm}
          <svg
            class="overlay edit"
            viewBox={`0 0 ${page.w} ${page.h}`}
            style:width={`${page.w * PX_PER_MM}px`}
            style:height={`${page.h * PX_PER_MM}px`}
            onpointermove={scaleMove}
            onpointerup={scaleUp}
            role="presentation"
          >
            <rect class="ebox" x={seb.x} y={seb.y} width={seb.width} height={seb.height} vector-effect="non-scaling-stroke" />
            {#each [["nw", seb.x, seb.y], ["ne", seb.x + seb.width, seb.y], ["se", seb.x + seb.width, seb.y + seb.height], ["sw", seb.x, seb.y + seb.height]] as [k, hx, hy] (k)}
              <rect
                class="ehandle"
                x={(hx as number) - hs / 2}
                y={(hy as number) - hs / 2}
                width={hs}
                height={hs}
                vector-effect="non-scaling-stroke"
                onpointerdown={(e) => scaleDown(e, k as NonNullable<typeof scaleKind>)}
                role="presentation"
              />
            {/each}
          </svg>
        {/if}

        {#if studio.step === "composition" && selectedLayer?.mask && studio.maskEdit && !studio.maskMode}
          {@const layer = selectedLayer}
          {@const m = layer.mask!}
          {@const s = layer.scale || 1}
          {@const bb = maskBBox(m)}
          {@const bx = layer.x + s * bb.x}
          {@const by = layer.y + s * bb.y}
          {@const bw = s * bb.w}
          {@const bh = s * bb.h}
          {@const hs = handleMm}
          <svg
            class="overlay edit"
            viewBox={`0 0 ${page.w} ${page.h}`}
            style:width={`${page.w * PX_PER_MM}px`}
            style:height={`${page.h * PX_PER_MM}px`}
            onpointermove={editMove}
            onpointerup={editUp}
            role="presentation"
          >
            {#if m.type === "rect"}
              <rect class="ol-mask" x={layer.x + s * m.x} y={layer.y + s * m.y} width={s * m.width} height={s * m.height} vector-effect="non-scaling-stroke" />
            {:else if m.type === "ellipse"}
              <ellipse class="ol-mask" cx={layer.x + s * m.cx} cy={layer.y + s * m.cy} rx={s * m.rx} ry={s * m.ry} vector-effect="non-scaling-stroke" />
            {:else if m.type === "path"}
              <path class="ol-mask" d={pathToPage(m.d, layer)} vector-effect="non-scaling-stroke" />
            {/if}
            <rect class="ebox" x={bx} y={by} width={bw} height={bh} vector-effect="non-scaling-stroke" />
            <rect
              class="emove"
              x={bx}
              y={by}
              width={bw}
              height={bh}
              style:stroke-width={`${hs}px`}
              onpointerdown={(e) => editDown(e, "move")}
              role="presentation"
            />
            {#each [["nw", bx, by], ["ne", bx + bw, by], ["se", bx + bw, by + bh], ["sw", bx, by + bh]] as [k, hx, hy] (k)}
              <rect
                class="ehandle"
                x={(hx as number) - hs / 2}
                y={(hy as number) - hs / 2}
                width={hs}
                height={hs}
                vector-effect="non-scaling-stroke"
                onpointerdown={(e) => editDown(e, k as NonNullable<typeof editKind>)}
                role="presentation"
              />
            {/each}
          </svg>
        {/if}

        {#if studio.step === "composition" && studio.maskMode && selectedLayer}
          <svg
            class="overlay draw"
            viewBox={`0 0 ${page.w} ${page.h}`}
            style:width={`${page.w * PX_PER_MM}px`}
            style:height={`${page.h * PX_PER_MM}px`}
            onpointerdown={maskDown}
            onpointermove={maskMove}
            onpointerup={maskUp}
            ondblclick={penFinish}
            role="presentation"
          >
            {#if draftStart && draftEnd}
              {@const dx = Math.min(draftStart.x, draftEnd.x)}
              {@const dy = Math.min(draftStart.y, draftEnd.y)}
              {@const dw = Math.abs(draftEnd.x - draftStart.x)}
              {@const dh = Math.abs(draftEnd.y - draftStart.y)}
              {#if studio.maskMode === "ellipse"}
                <ellipse
                  class="draft"
                  cx={dx + dw / 2}
                  cy={dy + dh / 2}
                  rx={dw / 2}
                  ry={dh / 2}
                  vector-effect="non-scaling-stroke"
                />
              {:else}
                <rect class="draft" x={dx} y={dy} width={dw} height={dh} vector-effect="non-scaling-stroke" />
              {/if}
            {/if}
            {#if studio.maskMode === "pen" && penAnchors.length}
              <path class="draft" d={penPreviewD()} vector-effect="non-scaling-stroke" />
              {#each penAnchors as a}
                <circle class="anchor" cx={a.x} cy={a.y} r="1.4" vector-effect="non-scaling-stroke" />
              {/each}
            {/if}
          </svg>
        {/if}
      {:else}
        <div class="placeholder">Import an image to begin</div>
      {/if}
    </div>
  </div>

  {#if studio.processing}
    <div class="busy">Processing… {Math.round(studio.progress * 100)}%</div>
  {/if}
</div>

<style>
  .viewport {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    cursor: grab;
  }
  .viewport:active {
    cursor: grabbing;
  }
  .stage {
    position: absolute;
    top: 0;
    left: 0;
    transform-origin: 0 0;
  }
  .page {
    position: relative;
    overflow: hidden;
    box-shadow: 0 0 0 1px #000, 0 8px 40px rgba(0, 0, 0, 0.5);
  }
  .page.placing {
    cursor: grabbing;
  }
  .guide,
  .sheet-mid-v,
  .sheet-mid-h,
  .snap-v,
  .snap-h {
    pointer-events: none;
    position: absolute;
  }
  .guide.a4 {
    border: 1px dashed rgba(46, 133, 255, 0.75);
    box-sizing: border-box;
    left: 0;
    top: 0;
  }
  .mid-v,
  .mid-h {
    position: absolute;
    background: rgba(46, 133, 255, 0.45);
  }
  .mid-v {
    bottom: 0;
    left: 50%;
    top: 0;
    width: 1px;
  }
  .mid-h {
    height: 1px;
    left: 0;
    right: 0;
    top: 50%;
  }
  .sheet-mid-v {
    background: rgba(0, 0, 0, 0.18);
    bottom: 0;
    left: 50%;
    top: 0;
    width: 1px;
  }
  .sheet-mid-h {
    background: rgba(0, 0, 0, 0.18);
    height: 1px;
    left: 0;
    right: 0;
    top: 50%;
  }
  .snap-v {
    background: var(--accent);
    bottom: 0;
    top: 0;
    width: 1px;
    z-index: 5;
  }
  .snap-h {
    background: var(--accent);
    height: 1px;
    left: 0;
    right: 0;
    z-index: 5;
  }
  .art {
    cursor: grab;
    outline: 1px solid rgba(17, 17, 17, 0.3);
    overflow: hidden;
    position: absolute;
    touch-action: none;
    z-index: 4;
  }
  .art.selected {
    outline: 1px solid var(--accent);
    outline-offset: 2px;
  }
  .art.show-bounds {
    box-shadow: inset 0 0 0 1px rgba(46, 139, 255, 0.55);
  }
  .art.show-bounds:not(.selected) {
    outline: 1px dashed rgba(46, 139, 255, 0.55);
    outline-offset: 1px;
  }
  .art:active {
    cursor: grabbing;
  }
  .svgwrap {
    position: absolute;
    pointer-events: none;
  }
  .knockout {
    position: absolute;
    pointer-events: none;
  }
  .layer-raster {
    display: block;
    height: 100%;
    left: 0;
    object-fit: fill;
    pointer-events: none;
    position: absolute;
    top: 0;
    width: 100%;
  }
  .overlay {
    position: absolute;
    left: 0;
    top: 0;
    z-index: 5;
    pointer-events: none;
    overflow: visible;
  }
  .overlay.draw {
    z-index: 6;
    pointer-events: auto;
    cursor: crosshair;
    touch-action: none;
  }
  .overlay.edit {
    z-index: 6;
  }
  .ebox {
    fill: none;
    stroke: rgba(46, 133, 255, 0.8);
    stroke-width: 1;
    stroke-dasharray: 3 2;
  }
  .emove {
    fill: none;
    stroke: transparent;
    pointer-events: stroke;
    cursor: move;
    touch-action: none;
  }
  .ehandle {
    fill: #fff;
    stroke: var(--accent);
    stroke-width: 1;
    pointer-events: all;
    cursor: nwse-resize;
    touch-action: none;
  }
  .ol-crop {
    fill: none;
    stroke: rgba(255, 196, 0, 0.9);
    stroke-width: 1;
    stroke-dasharray: 4 3;
  }
  .ol-mask {
    fill: none;
    stroke: rgba(255, 64, 160, 0.95);
    stroke-width: 1;
    stroke-dasharray: 4 3;
  }
  .draft {
    fill: rgba(255, 64, 160, 0.12);
    stroke: rgba(255, 64, 160, 0.95);
    stroke-width: 1.5;
  }
  .anchor {
    fill: #fff;
    stroke: rgba(255, 64, 160, 0.95);
    stroke-width: 1.5;
  }
  .svgwrap :global(svg) {
    width: 100%;
    height: 100%;
    display: block;
  }
  .source-frame {
    position: absolute;
    overflow: hidden;
    background: #fff;
  }
  .src {
    width: 100%;
    height: 100%;
    object-fit: fill;
    opacity: 0.85;
    display: block;
    pointer-events: none;
  }
  .region-mask-preview {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: fill;
    opacity: 0.38;
    mix-blend-mode: multiply;
    filter: sepia(1) saturate(6) hue-rotate(145deg);
    pointer-events: none;
  }
  .region-select-overlay {
    position: absolute;
    inset: 0;
    z-index: 7;
    cursor: crosshair;
    touch-action: none;
  }
  .region-point {
    position: absolute;
    width: 10px;
    height: 10px;
    margin: -5px 0 0 -5px;
    border: 2px solid #fff;
    border-radius: 50%;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.75);
    pointer-events: none;
  }
  .region-point.positive {
    background: #21c46b;
  }
  .region-point.negative {
    background: #f04c5e;
  }
  .placeholder {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
  }
  .busy {
    position: absolute;
    bottom: 12px;
    left: 12px;
    background: rgba(0, 0, 0, 0.6);
    padding: 5px 10px;
    border-radius: 4px;
    font-size: 12px;
  }
</style>
