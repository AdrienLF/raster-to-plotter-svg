<script lang="ts">
  import { onMount } from "svelte";
  import { studio, pushLog } from "./lib/state.svelte";
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
    let es: EventSource | null = null;
    let disposed = false;
    void api.boot()
      .then((ready) => {
        if (disposed || !ready) return;
        es = connectStream();
      })
      .catch((e) => {
        if (disposed) return;
        studio.processing = false;
        studio.status = "Error";
        pushLog("Boot error: " + (e instanceof Error ? e.message : String(e)));
        console.error(e);
      });
    return () => {
      disposed = true;
      api.invalidateProjectWork();
      es?.close();
    };
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

{#if studio.penChange}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Change pen">
      <h3>
        <span class="swatch" style:background={studio.penChange.colour}></span>
        Load pen: {studio.penChange.name}
      </h3>
      <p>
        Pen {studio.penChange.pen_index + 1} of {studio.penChange.pen_total}{#if studio.penChange.copies > 1}
          · copy {studio.penChange.copy_index + 1} of {studio.penChange.copies}{/if}.
        {#if studio.penChange.reason === "new_sheet"}
          Place a fresh sheet, then load this pen.
        {:else}
          Swap in this pen, then confirm. The plotter re-homes before continuing.
        {/if}
      </p>
      <div class="modal-actions">
        <button class="primary" onclick={() => api.confirmPen()}>Pen loaded — continue</button>
        <button class="danger" onclick={() => api.stop()}>Stop</button>
      </div>
    </div>
  </div>
{/if}

{#if studio.cavalryPrompt}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Cavalry reconnected">
      <h3>Cavalry reconnected</h3>
      <p>
        {#if studio.cavalryPrompt.layer_name}
          Keep capturing into “{studio.cavalryPrompt.layer_name}” (its content will be
          overwritten), or start a new layer?
        {:else}
          Cavalry is sending frames but no capture layer exists. Start a new layer?
        {/if}
      </p>
      <div class="modal-actions">
        {#if studio.cavalryPrompt.layer_name}
          <button class="primary" onclick={() => api.cavalrySession("continue")}>
            Continue on “{studio.cavalryPrompt.layer_name}”
          </button>
          <button onclick={() => api.cavalrySession("new")}>New layer</button>
        {:else}
          <button class="primary" onclick={() => api.cavalrySession("new")}>New layer</button>
        {/if}
        <button onclick={() => api.cavalrySession("dismiss")}>Ignore this session</button>
      </div>
    </div>
  </div>
{/if}

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
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.55);
  }
  .modal {
    max-width: 340px;
    padding: 18px;
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  }
  .modal h3 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 10px;
    font-size: 15px;
  }
  .modal p {
    margin: 0 0 14px;
    font-size: 13px;
    line-height: 1.45;
  }
  .swatch {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid var(--line);
    flex: none;
  }
  .modal-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .modal-actions button {
    padding: 7px;
  }
</style>
