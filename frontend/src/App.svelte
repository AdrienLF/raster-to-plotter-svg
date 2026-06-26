<script lang="ts">
  import { onMount } from "svelte";
  import { studio } from "./lib/state.svelte";
  import { api, connectStream } from "./lib/api";
  import { isSvgFile } from "./lib/files";
  import type { AlignMode } from "./lib/placement";
  import MenuBar from "./components/MenuBar.svelte";
  import StepTabs from "./components/StepTabs.svelte";
  import Toolbar from "./components/Toolbar.svelte";
  import ToolRail from "./components/ToolRail.svelte";
  import Viewport from "./components/Viewport.svelte";
  import StatusBar from "./components/StatusBar.svelte";
  import Panel from "./components/Panel.svelte";
  import GeneratePanel from "./components/panels/GeneratePanel.svelte";
  import CompositionPanel from "./components/panels/CompositionPanel.svelte";
  import LayerStylePanel from "./components/panels/LayerStylePanel.svelte";
  import DrawingAreaPanel from "./components/panels/DrawingAreaPanel.svelte";
  import PensPanel from "./components/panels/PensPanel.svelte";
  import PlotterPanel from "./components/panels/PlotterPanel.svelte";
  import VersionsPanel from "./components/panels/VersionsPanel.svelte";

  let viewport = $state<Viewport>();
  let fileInput: HTMLInputElement;

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

  type Step = "pathfinding" | "generate" | "composition" | "plot";
  function selectStep(step: Step) {
    studio.step = step;
    if (step === "plot") {
      studio.plotterTab = "estimate";
      void api.refreshEstimate(true);
    }
  }
  function align(mode: AlignMode) {
    viewport?.align(mode);
  }
</script>

<div class="app-grid">
  <div class="area-menu"><MenuBar onImport={pickImage} onPlot={() => selectStep("plot")} /></div>
  <div class="area-tabs"><StepTabs onSelect={selectStep} /></div>
  <div class="area-toolbar"><Toolbar onAlign={align} onFit={() => viewport?.fit()} /></div>
  <div class="area-rail"><ToolRail onImport={pickImage} onFit={() => viewport?.fit()} onPlot={() => selectStep("plot")} /></div>
  <div class="area-viewport"><Viewport bind:this={viewport} /></div>
  <div class="area-dock dock scroll">
    {#if studio.step !== "plot"}
      <Panel title="Layers"><CompositionPanel /></Panel>
    {/if}
    {#if studio.step === "pathfinding"}
      <Panel title="Drawing Area" open={false}><DrawingAreaPanel /></Panel>
      <Panel title="Pens"><PensPanel /></Panel>
      <Panel title="Versions"><VersionsPanel /></Panel>
    {:else if studio.step === "generate"}
      <Panel title="Generate"><GeneratePanel /></Panel>
      <Panel title="Drawing Area" open={false}><DrawingAreaPanel /></Panel>
      <Panel title="Pens"><PensPanel /></Panel>
      <Panel title="Versions" open={false}><VersionsPanel /></Panel>
    {:else if studio.step === "composition"}
      <Panel title="Drawing Area" open={false}><DrawingAreaPanel /></Panel>
      <Panel title="Pens" open={false}><PensPanel /></Panel>
      <Panel title="Versions" open={false}><VersionsPanel /></Panel>
    {:else}
      <Panel title="Plotter"><PlotterPanel /></Panel>
      <Panel title="Versions" open={false}><VersionsPanel /></Panel>
    {/if}
  </div>
  <div class="area-status"><StatusBar /></div>
</div>

<LayerStylePanel />

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
