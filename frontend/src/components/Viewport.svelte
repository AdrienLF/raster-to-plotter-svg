<script lang="ts">
  import { api } from "../lib/api";
  import {
    A4_PORTRAIT,
    alignPlacement,
    clampPlacement,
    parseSvgSizeMm,
    snapPlacement,
    type AlignMode,
  } from "../lib/placement";
  import { studio } from "../lib/state.svelte";

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
    if (studio.previewSvg && studio.settings) {
      return {
        w: Number(studio.settings.paper_width) || 297,
        h: Number(studio.settings.paper_height) || 420,
        bg: areaPage.bg,
        canvas: "#fff",
      };
    }
    return areaPage;
  });

  const drawingSize = $derived.by(() => {
    if (!studio.previewSvg) return { w: page.w, h: page.h };
    return parseSvgSizeMm(studio.previewSvg, { w: page.w, h: page.h });
  });

  const a4Guide = $derived.by(() => ({
    w: Math.min(A4_PORTRAIT.w, page.w),
    h: Math.min(A4_PORTRAIT.h, page.h),
  }));

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

  function startPlacement(e: PointerEvent) {
    if (!studio.previewSvg) return;
    e.preventDefault();
    e.stopPropagation();
    placing = true;
    placementPointer = e.currentTarget as HTMLElement;
    placementPointer.setPointerCapture(e.pointerId);
    placementStart = clientToPage(e);
    placementOrigin = { ...studio.placement };
  }

  function movePlacement(e: PointerEvent) {
    const mm = clientToPage(e);
    const raw = {
      x: placementOrigin.x + mm.x - placementStart.x,
      y: placementOrigin.y + mm.y - placementStart.y,
    };
    const snapped = snapPlacement(raw, drawingSize, page, A4_PORTRAIT, 4);
    studio.placement = { x: round1(snapped.x), y: round1(snapped.y) };
    snapGuideX = snapped.guideX;
    snapGuideY = snapped.guideY;
  }

  function finishPlacement(e: PointerEvent) {
    placing = false;
    snapGuideX = null;
    snapGuideY = null;
    placementPointer?.releasePointerCapture?.(e.pointerId);
    placementPointer = null;
    void api.savePlacement(true);
  }

  function align(mode: AlignMode) {
    const aligned = alignPlacement(mode, studio.placement, drawingSize, page);
    studio.placement = { x: round1(aligned.x), y: round1(aligned.y) };
    void api.savePlacement(true);
  }

  $effect(() => {
    if (!studio.previewSvg) return;
    const clamped = clampPlacement(studio.placement, drawingSize, page);
    if (Math.abs(clamped.x - studio.placement.x) > 0.05 || Math.abs(clamped.y - studio.placement.y) > 0.05) {
      studio.placement = { x: round1(clamped.x), y: round1(clamped.y) };
    }
  });

  function round1(value: number) {
    return Math.round(value * 10) / 10;
  }
</script>

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
      {#if studio.previewSvg}
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
        <div
          class="art"
          style:left={`${studio.placement.x * PX_PER_MM}px`}
          style:top={`${studio.placement.y * PX_PER_MM}px`}
          style:width={`${drawingSize.w * PX_PER_MM}px`}
          style:height={`${drawingSize.h * PX_PER_MM}px`}
          onpointerdown={startPlacement}
          role="application"
          aria-label="Drawing placement"
        >
          <div class="svgwrap">{@html studio.previewSvg}</div>
        </div>
      {:else if studio.imageUrl}
        <img class="src" src={studio.imageUrl} alt="source" />
      {:else}
        <div class="placeholder">Import an image to begin</div>
      {/if}
    </div>
  </div>

  {#if studio.processing}
    <div class="busy">Processing… {Math.round(studio.progress * 100)}%</div>
  {/if}
  {#if studio.previewSvg}
    <div class="placement-tools" onpointerdown={(e) => e.stopPropagation()} role="toolbar" tabindex="-1" aria-label="Placement alignment">
      <button title="Align left" onclick={() => align("left")}>⬅</button>
      <button title="Align horizontal center" onclick={() => align("center_h")}>↔</button>
      <button title="Align right" onclick={() => align("right")}>➡</button>
      <button title="Align top" onclick={() => align("top")}>⬆</button>
      <button title="Align vertical center" onclick={() => align("center_v")}>↕</button>
      <button title="Align bottom" onclick={() => align("bottom")}>⬇</button>
      <span>x {studio.placement.x.toFixed(1)} · y {studio.placement.y.toFixed(1)} mm</span>
    </div>
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
    position: absolute;
    touch-action: none;
    z-index: 4;
  }
  .art:active {
    cursor: grabbing;
  }
  .svgwrap {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .svgwrap :global(svg) {
    width: 100%;
    height: 100%;
    display: block;
  }
  .src {
    width: 100%;
    height: 100%;
    object-fit: contain;
    opacity: 0.85;
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
  .placement-tools {
    align-items: center;
    background: rgba(22, 24, 28, 0.88);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 4px;
    display: flex;
    gap: 4px;
    left: 12px;
    padding: 5px;
    position: absolute;
    top: 12px;
    z-index: 10;
  }
  .placement-tools button {
    align-items: center;
    display: flex;
    height: 28px;
    justify-content: center;
    padding: 0;
    width: 28px;
  }
  .placement-tools span {
    color: var(--text-dim);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    margin-left: 5px;
    min-width: 104px;
  }
</style>
