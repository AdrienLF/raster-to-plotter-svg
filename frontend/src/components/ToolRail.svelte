<script lang="ts">
  import { studio } from "../lib/state.svelte";
  import { api } from "../lib/api";

  let {
    onImport,
    onFit,
    onPlot,
  }: {
    onImport: () => void;
    onFit: () => void;
    onPlot: () => void;
  } = $props();
</script>

<div class="rail">
  <button class="icon" title="Import image" onclick={onImport}>🖼</button>
  <button class="icon" title="Fit to view" onclick={onFit}>⤢</button>
  <div class="sep"></div>
  <button
    class="icon go"
    title="Run path finding"
    disabled={studio.processing || !studio.imageUrl}
    onclick={() => api.process()}>▶</button
  >
  <div class="sep"></div>
  <button
    class="icon"
    title="Plot"
    disabled={studio.plotting || !studio.previewSvg}
    onclick={onPlot}>🖊</button
  >
  <button class="icon stop" title="Stop" disabled={!studio.plotting} onclick={() => api.stop()}>■</button>
</div>

<style>
  .rail {
    background: var(--rail);
    border-right: 1px solid var(--line);
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 8px 0;
  }
  .icon {
    width: 34px;
    height: 34px;
    font-size: 15px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .go {
    color: var(--ok);
  }
  .stop {
    color: var(--danger);
  }
  .sep {
    width: 24px;
    height: 1px;
    background: var(--line);
    margin: 2px 0;
  }
</style>
