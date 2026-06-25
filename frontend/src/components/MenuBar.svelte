<script lang="ts">
  import { studio } from "../lib/state.svelte";
  import { api } from "../lib/api";

  let { onImport, onPlot }: { onImport: () => void; onPlot: () => void } = $props();

  function exportSvg(split: boolean) {
    window.location.href = api.exportUrl(split);
  }
</script>

<div class="menubar">
  <span class="brand">✦ Plotter Studio</span>

  <details class="menu">
    <summary>File</summary>
    <div class="items">
      <button onclick={onImport}>Import image…</button>
      <button disabled={!studio.stats} onclick={() => exportSvg(false)}>Export SVG</button>
      <button disabled={!studio.stats} onclick={() => exportSvg(true)}>Export layers (zip)</button>
    </div>
  </details>

  <details class="menu">
    <summary>Drawing</summary>
    <div class="items">
      <button disabled={!studio.imageUrl} onclick={() => api.process()}>Run path finding</button>
      <button disabled={!studio.previewSvg} onclick={onPlot}>Plot…</button>
    </div>
  </details>

  <div class="spacer"></div>
  <span class="doc muted">{studio.imageName || "no image"}</span>
</div>

<style>
  .menubar {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--header);
    border-bottom: 1px solid var(--line);
    height: 100%;
    padding: 0 8px;
  }
  .brand {
    font-weight: 700;
    color: var(--accent);
    margin-right: 12px;
  }
  .menu {
    position: relative;
  }
  .menu summary {
    list-style: none;
    cursor: pointer;
    padding: 3px 9px;
    border-radius: 4px;
  }
  .menu summary::-webkit-details-marker {
    display: none;
  }
  .menu[open] summary {
    background: var(--accent);
    color: white;
  }
  .items {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: 30;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 5px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    min-width: 170px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  }
  .items button {
    background: none;
    border: none;
    text-align: left;
    padding: 6px 8px;
    border-radius: 4px;
  }
  .items button:hover:not(:disabled) {
    background: var(--accent);
    color: white;
  }
  .doc {
    font-size: 12px;
  }
</style>
