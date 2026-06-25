<script lang="ts">
  import { onMount } from "svelte";
  import { studio } from "./lib/state.svelte";
  import { api, connectStream } from "./lib/api";
  import { isSvgFile } from "./lib/files";
  import MenuBar from "./components/MenuBar.svelte";
  import ToolRail from "./components/ToolRail.svelte";
  import Viewport from "./components/Viewport.svelte";
  import StatusBar from "./components/StatusBar.svelte";
  import Panel from "./components/Panel.svelte";
  import PathFindingPanel from "./components/panels/PathFindingPanel.svelte";
  import DrawingAreaPanel from "./components/panels/DrawingAreaPanel.svelte";
  import PensPanel from "./components/panels/PensPanel.svelte";
  import PlotterPanel from "./components/panels/PlotterPanel.svelte";
  import VersionsPanel from "./components/panels/VersionsPanel.svelte";

  let viewport = $state<Viewport>();
  let fileInput: HTMLInputElement;
  let plotterOpen = $state(true);

  onMount(() => {
    api.boot().catch((e) => console.error(e));
    const es = connectStream();
    return () => es.close();
  });

  function pickImage() {
    fileInput.click();
  }
  async function onFile(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) {
      if (isSvgFile(f)) await api.uploadSvg(f);
      else await api.uploadImage(f);
    }
    (e.target as HTMLInputElement).value = "";
  }
  function openPlotter() {
    studio.plotterTab = "estimate";
    plotterOpen = true;
    void api.refreshEstimate(true);
  }
</script>

<div class="app-grid">
  <div class="area-menu"><MenuBar onImport={pickImage} onPlot={openPlotter} /></div>
  <div class="area-rail"><ToolRail onImport={pickImage} onFit={() => viewport?.fit()} onPlot={openPlotter} /></div>
  <div class="area-viewport"><Viewport bind:this={viewport} /></div>
  <div class="area-dock dock scroll">
    <Panel title="Path Finding"><PathFindingPanel /></Panel>
    <Panel title="Plotter" bind:open={plotterOpen}><PlotterPanel /></Panel>
    <Panel title="Drawing Area" open={false}><DrawingAreaPanel /></Panel>
    <Panel title="Pens"><PensPanel /></Panel>
    <Panel title="Versions"><VersionsPanel /></Panel>
  </div>
  <div class="area-status"><StatusBar /></div>
</div>

<input
  bind:this={fileInput}
  type="file"
  accept="image/*,.svg"
  onchange={onFile}
  style="display:none"
/>

<style>
  .dock {
    background: var(--panel);
    border-left: 1px solid var(--line);
    height: 100%;
  }
</style>
