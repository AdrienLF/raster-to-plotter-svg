<script lang="ts">
  import { studio } from "../lib/state.svelte";
  import type { AlignMode } from "../lib/placement";

  let { onAlign, onFit }: { onAlign: (mode: AlignMode) => void; onFit: () => void } = $props();

  const placed = $derived(!!studio.selectedLayer);
</script>

<div class="toolbar">
  {#if placed}
    <span class="ctx">{studio.step === "plot" ? "Paper Placement" : "Layer Placement"}</span>

    <div class="group" role="group" aria-label="Align horizontally">
      <button title="Align left edges" onclick={() => onAlign("left")} aria-label="Align left edges">
        <svg viewBox="0 0 16 16"><rect class="ref" x="1" y="2" width="1.6" height="12" rx="0.4" /><rect x="3.4" y="3.5" width="9" height="3.2" rx="0.8" /><rect x="3.4" y="9.3" width="6" height="3.2" rx="0.8" /></svg>
      </button>
      <button title="Align horizontal centers" onclick={() => onAlign("center_h")} aria-label="Align horizontal centers">
        <svg viewBox="0 0 16 16"><rect class="ref" x="7.2" y="2" width="1.6" height="12" rx="0.4" /><rect x="3.5" y="3.5" width="9" height="3.2" rx="0.8" /><rect x="5" y="9.3" width="6" height="3.2" rx="0.8" /></svg>
      </button>
      <button title="Align right edges" onclick={() => onAlign("right")} aria-label="Align right edges">
        <svg viewBox="0 0 16 16"><rect class="ref" x="13.4" y="2" width="1.6" height="12" rx="0.4" /><rect x="4" y="3.5" width="9" height="3.2" rx="0.8" /><rect x="7" y="9.3" width="6" height="3.2" rx="0.8" /></svg>
      </button>
    </div>

    <div class="group" role="group" aria-label="Align vertically">
      <button title="Align top edges" onclick={() => onAlign("top")} aria-label="Align top edges">
        <svg viewBox="0 0 16 16"><rect class="ref" x="2" y="1" width="12" height="1.6" rx="0.4" /><rect x="3.5" y="3.4" width="3.2" height="9" rx="0.8" /><rect x="9.3" y="3.4" width="3.2" height="6" rx="0.8" /></svg>
      </button>
      <button title="Align vertical centers" onclick={() => onAlign("center_v")} aria-label="Align vertical centers">
        <svg viewBox="0 0 16 16"><rect class="ref" x="2" y="7.2" width="12" height="1.6" rx="0.4" /><rect x="3.5" y="3.5" width="3.2" height="9" rx="0.8" /><rect x="9.3" y="5" width="3.2" height="6" rx="0.8" /></svg>
      </button>
      <button title="Align bottom edges" onclick={() => onAlign("bottom")} aria-label="Align bottom edges">
        <svg viewBox="0 0 16 16"><rect class="ref" x="2" y="13.4" width="12" height="1.6" rx="0.4" /><rect x="3.5" y="4" width="3.2" height="9" rx="0.8" /><rect x="9.3" y="7" width="3.2" height="6" rx="0.8" /></svg>
      </button>
    </div>

    {#if studio.selectedLayer}
      <span class="readout">X {studio.selectedLayer.x.toFixed(1)} &nbsp; Y {studio.selectedLayer.y.toFixed(1)} <em>mm</em></span>
    {/if}
  {:else}
    <span class="ctx muted">No layer selected — run Path Finding, Generate, or import an SVG.</span>
  {/if}

  <div class="spacer"></div>
  <button class="text" title="Fit to view" onclick={onFit}>Fit</button>
</div>

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 100%;
    padding: 0 10px;
    background: var(--header);
    border-bottom: 1px solid var(--line);
  }
  .ctx {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-dim);
  }
  .group {
    display: flex;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 5px;
    overflow: hidden;
  }
  .group button {
    background: none;
    border: none;
    border-radius: 0;
    padding: 3px 6px;
    height: 26px;
    display: flex;
    align-items: center;
  }
  .group button + button {
    border-left: 1px solid var(--line);
  }
  .group button:hover {
    background: var(--accent);
  }
  svg {
    width: 16px;
    height: 16px;
    fill: var(--text);
  }
  svg .ref {
    fill: var(--accent);
  }
  .group button:hover svg,
  .group button:hover svg .ref {
    fill: #fff;
  }
  .readout {
    font-size: 12px;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .readout em {
    color: var(--text-dim);
    font-style: normal;
  }
  .spacer {
    flex: 1;
  }
  .text {
    padding: 3px 12px;
  }
</style>
