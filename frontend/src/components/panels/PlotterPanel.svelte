<script lang="ts">
  import { api } from "../../lib/api";
  import { PAPER_PRESETS } from "../../lib/placement";
  import { pushLog, studio } from "../../lib/state.svelte";
  import NumStep from "../NumStep.svelte";

  const piBridge = "socket://100.92.241.24:4000";
  const macPty = "/Users/adrien/.idraw-tty";
  const tabs = [
    ["estimate", "Estimate"],
    ["setup", "Setup"],
    ["speed", "Speed"],
    ["timing", "Pen Timing"],
    ["manual", "Manual"],
    ["advanced", "Advanced"],
  ];

  let busy = $state("");
  let jogStep = $state(10);
  let penReview = $state<import("../../lib/types").PlotPen[] | null>(null);

  const paperPresetId = $derived.by(() => {
    if (!studio.settings) return "";
    const w = Number(studio.settings.paper_width);
    const h = Number(studio.settings.paper_height);
    return PAPER_PRESETS.find((p) => Math.abs(p.w - w) < 0.5 && Math.abs(p.h - h) < 0.5)?.id ?? "";
  });

  async function run(label: string, fn: () => Promise<void>) {
    busy = label;
    try {
      await fn();
    } catch (e) {
      pushLog(`Plotter ${label} error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      busy = "";
    }
  }

  async function save(refresh = true) {
    await run("save", async () => {
      await api.saveSettings();
      if (refresh) await api.refreshEstimate(true);
    });
  }

  async function usePort(port: string) {
    if (!studio.settings) return;
    studio.settings.port = port;
    await save(false);
  }

  async function usePaperPreset(id: string) {
    const preset = PAPER_PRESETS.find((p) => p.id === id);
    if (!preset || !studio.settings) return;
    studio.settings.paper_width = preset.w;
    studio.settings.paper_height = preset.h;
    await save();
  }

  async function swapPaper() {
    if (!studio.settings) return;
    const w = studio.settings.paper_width;
    studio.settings.paper_width = studio.settings.paper_height;
    studio.settings.paper_height = w;
    await save();
  }

  async function refreshEstimate() {
    await run("estimate", async () => {
      await api.refreshEstimate();
    });
  }

  async function startPlot() {
    // Multi-pen drawings get a review window first; single-pen plots straight away.
    const { multi, pens } = await api.plotPens();
    if (multi) {
      penReview = pens;
      return;
    }
    await run("plot", async () => {
      await api.saveSettings();
      await api.plot();
    });
  }

  async function confirmStartPlot() {
    penReview = null;
    await run("plot", async () => {
      await api.saveSettings();
      await api.plot();
    });
  }

  async function resumePlot() {
    await run("resume", async () => {
      await api.resumePlot();
    });
  }

  async function stopPlot() {
    await run("stop", async () => {
      await api.stop();
      pushLog("Plotter stop requested");
    });
  }

  async function discardJob() {
    await run("discard", async () => {
      await api.discardPlotJob();
    });
  }

  async function manual(cmd: string, data: Record<string, any> = {}) {
    await run(cmd, async () => {
      const result = await api.manual(cmd, data);
      if (cmd !== "status") pushLog(`Plotter command sent · ${cmd}`);
      if (cmd === "status" && !result.status) studio.machineStatus = "No status reply";
    });
  }

  function jog(dx: number, dy: number) {
    return manual("walk", { dx: dx * jogStep, dy: dy * jogStep });
  }

  function fmtSeconds(value: number | null | undefined) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    const total = Math.max(0, Math.round(value));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h) return `${h}h ${m}m ${s}s`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function fmtMm(value: number | undefined) {
    if (value === undefined || !Number.isFinite(value)) return "—";
    return `${Math.round(value).toLocaleString()} mm`;
  }
</script>

{#if studio.settings}
  <div class="plotter col">
    <div class="tabs">
      {#each tabs as tab}
        <button
          class:active={studio.plotterTab === tab[0]}
          onclick={() => (studio.plotterTab = tab[0])}
        >{tab[1]}</button>
      {/each}
    </div>

    <div class="actions">
      <button class="primary" onclick={startPlot} disabled={busy !== "" || !studio.hasVisibleLayers}>
        Start
      </button>
      <button onclick={resumePlot} disabled={busy !== "" || studio.plotting || !studio.plotJob?.resumable}>
        Resume
      </button>
      <button class="danger" onclick={stopPlot} disabled={busy !== "" || !studio.plotting}>
        Stop
      </button>
      <button onclick={refreshEstimate} disabled={busy !== "" || !studio.hasVisibleLayers}>Refresh</button>
    </div>

    {#if studio.plotterTab === "estimate"}
      <div class="estimate">
        <div class="hero">
          <div class="label">Estimated time</div>
          <div class="time">{fmtSeconds(studio.plotEstimate?.estimated_seconds)}</div>
        </div>
        {#if studio.plotJob?.exists}
          <div class="job">
            <div><span>Saved job</span><strong>{studio.plotJob.status ?? "unknown"}</strong></div>
            <div><span>Done</span><strong>{(studio.plotJob.completed_shapes ?? 0).toLocaleString()} / {(studio.plotJob.total_shapes ?? 0).toLocaleString()}</strong></div>
            <div><span>Remaining</span><strong>{(studio.plotJob.shapes_remaining ?? 0).toLocaleString()} shapes</strong></div>
            <button onclick={discardJob} disabled={busy !== "" || studio.plotting}>Discard</button>
            {#if studio.plotJob.resumable}
              <p>Keep the paper fixed before resuming. The current unfinished path may be redrawn.</p>
            {/if}
          </div>
        {/if}
        {#if studio.plotProgress}
          <div class="live">
            <div><span>Elapsed</span><strong>{fmtSeconds(studio.plotProgress.elapsed_seconds)}</strong></div>
            <div><span>Remaining</span><strong>{fmtSeconds(studio.plotProgress.remaining_seconds)}</strong></div>
            <div><span>Drawn</span><strong>{studio.plotProgress.shapes_done.toLocaleString()} / {studio.plotProgress.shapes_total.toLocaleString()}</strong></div>
            <div><span>Segments left</span><strong>{studio.plotProgress.segments_remaining.toLocaleString()}</strong></div>
          </div>
        {/if}
        <div class="metrics">
          <div><span>Paths</span><strong>{studio.plotEstimate?.paths ?? "—"}</strong></div>
          <div><span>Segments</span><strong>{studio.plotEstimate?.total_segments ?? "—"}</strong></div>
          <div><span>Copies</span><strong>{studio.plotEstimate?.copies ?? studio.settings.copies}</strong></div>
          <div><span>Pen cycles</span><strong>{studio.plotEstimate?.pen_cycles ?? "—"}</strong></div>
          <div><span>Draw</span><strong>{fmtMm(studio.plotEstimate?.draw_distance_mm)}</strong></div>
          <div><span>Travel</span><strong>{fmtMm(studio.plotEstimate?.travel_distance_mm)}</strong></div>
        </div>
        <div class="breakdown">
          <div><span>Drawing</span><strong>{fmtSeconds(studio.plotEstimate?.breakdown.draw_seconds)}</strong></div>
          <div><span>Travel</span><strong>{fmtSeconds(studio.plotEstimate?.breakdown.travel_seconds)}</strong></div>
          <div><span>Pen motion</span><strong>{fmtSeconds(studio.plotEstimate?.breakdown.pen_seconds)}</strong></div>
          <div><span>Copy delays</span><strong>{fmtSeconds(studio.plotEstimate?.breakdown.copy_delay_seconds)}</strong></div>
        </div>
      </div>
    {:else if studio.plotterTab === "setup"}
      <div class="col">
        <div class="f">
          <label for="plotter-port">Port</label>
          <input id="plotter-port" bind:value={studio.settings.port} onchange={() => save(false)} />
        </div>
        <div class="quick">
          <button onclick={() => usePort(macPty)} disabled={busy !== ""}>Mac PTY</button>
          <button onclick={() => usePort(piBridge)} disabled={busy !== ""}>Pi bridge</button>
          <button class="primary" onclick={() => save(false)} disabled={busy !== ""}>Save</button>
        </div>
        <div class="grid2">
          <div class="f wide">
            <label for="plotter-paper-preset">Paper preset</label>
            <div class="paper-row">
              <select id="plotter-paper-preset" value={paperPresetId} onchange={(e) => usePaperPreset((e.target as HTMLSelectElement).value)}>
                <option value="">Custom</option>
                {#each PAPER_PRESETS as preset}
                  <option value={preset.id}>{preset.label}</option>
                {/each}
              </select>
              <button onclick={swapPaper} disabled={busy !== ""}>Swap</button>
            </div>
          </div>
          <div class="f">
            <label for="plotter-pen-up">Pen up</label>
            <NumStep id="plotter-pen-up" min={0} step={0.1} bind:value={studio.settings.pen_pos_up} onchange={() => save()} />
          </div>
          <div class="f">
            <label for="plotter-pen-down">Pen down</label>
            <NumStep id="plotter-pen-down" min={0} step={0.1} bind:value={studio.settings.pen_pos_down} onchange={() => save()} />
          </div>
          <div class="f">
            <label for="plotter-paper-width">Paper width</label>
            <NumStep id="plotter-paper-width" min={50} step={1} bind:value={studio.settings.paper_width} onchange={() => save()} />
          </div>
          <div class="f">
            <label for="plotter-paper-height">Paper height</label>
            <NumStep id="plotter-paper-height" min={50} step={1} bind:value={studio.settings.paper_height} onchange={() => save()} />
          </div>
        </div>
      </div>
    {:else if studio.plotterTab === "speed"}
      <div class="grid2">
        <div class="f wide">
          <label for="plotter-speed-down">Drawing speed</label>
          <NumStep id="plotter-speed-down" min={50} step={50} bind:value={studio.settings.speed_pendown} onchange={() => save()} />
        </div>
        <div class="f wide">
          <label for="plotter-speed-up">Travel speed</label>
          <NumStep id="plotter-speed-up" min={50} step={50} bind:value={studio.settings.speed_penup} onchange={() => save()} />
        </div>
        <div class="f">
          <label for="plotter-copies">Copies</label>
          <NumStep id="plotter-copies" min={1} step={1} bind:value={studio.settings.copies} onchange={() => save()} />
        </div>
        <div class="f">
          <label for="plotter-page-delay">Copy delay</label>
          <NumStep id="plotter-page-delay" min={0} step={1} bind:value={studio.settings.page_delay} onchange={() => save()} />
        </div>
      </div>
    {:else if studio.plotterTab === "timing"}
      <div class="grid2">
        <div class="f wide">
          <label for="plotter-raise-rate">Raise speed</label>
          <NumStep id="plotter-raise-rate" min={100} step={100} bind:value={studio.settings.pen_rate_raise} onchange={() => save()} />
        </div>
        <div class="f wide">
          <label for="plotter-lower-rate">Lower speed</label>
          <NumStep id="plotter-lower-rate" min={100} step={100} bind:value={studio.settings.pen_rate_lower} onchange={() => save()} />
        </div>
        <div class="f">
          <label for="plotter-delay-up">Delay after up</label>
          <NumStep id="plotter-delay-up" min={0} step={10} bind:value={studio.settings.pen_delay_up} onchange={() => save()} />
        </div>
        <div class="f">
          <label for="plotter-delay-down">Delay after down</label>
          <NumStep id="plotter-delay-down" min={0} step={10} bind:value={studio.settings.pen_delay_down} onchange={() => save()} />
        </div>
      </div>
    {:else if studio.plotterTab === "manual"}
      <div class="manual-layout">
        <div class="dpad">
          <div></div>
          <button onclick={() => jog(0, -1)} disabled={busy !== ""}>↑</button>
          <div></div>
          <button onclick={() => jog(-1, 0)} disabled={busy !== ""}>←</button>
          <button onclick={() => manual("status")} disabled={busy !== ""}>?</button>
          <button onclick={() => jog(1, 0)} disabled={busy !== ""}>→</button>
          <div></div>
          <button onclick={() => jog(0, 1)} disabled={busy !== ""}>↓</button>
          <div></div>
        </div>
        <div class="f step">
          <label for="plotter-jog-step">Step</label>
          <NumStep id="plotter-jog-step" min={0.1} step={1} bind:value={jogStep} />
        </div>
      </div>
      <div class="manual">
        <button onclick={() => manual("home")} disabled={busy !== ""}>Home</button>
        <button onclick={() => manual("pen_up")} disabled={busy !== ""}>Pen up</button>
        <button onclick={() => manual("pen_down")} disabled={busy !== ""}>Pen down</button>
        <button onclick={() => manual("cycle_pen")} disabled={busy !== ""}>Cycle</button>
        <button onclick={() => manual("motors_off")} disabled={busy !== ""}>Motors off</button>
        <button onclick={() => manual("status")} disabled={busy !== ""}>Status</button>
      </div>
      {#if studio.machineStatus}
        <div class="status">{studio.machineStatus}</div>
      {/if}
    {:else if studio.plotterTab === "advanced"}
      <div class="col">
        <div class="f">
          <label for="plotter-reordering">Reordering</label>
          <select id="plotter-reordering" bind:value={studio.settings.reordering} onchange={() => save()}>
            <option value="none">None</option>
            <option value="nearest">Nearest neighbour</option>
            <option value="nearest_reversible">Nearest + reverse paths</option>
            <option value="two_opt">2-opt optimizer</option>
          </select>
        </div>
        <div class="f">
          <label for="plotter-curve-step">Curve step</label>
          <NumStep id="plotter-curve-step" min={0.05} step={0.05} bind:value={studio.settings.curve_step_mm} onchange={() => save()} />
        </div>
        <div class="f">
          <label for="plotter-merge-tolerance">Merge tolerance (mm)</label>
          <NumStep
            id="plotter-merge-tolerance"
            min={0}
            max={1}
            step={0.01}
            bind:value={studio.settings.merge_tolerance_mm}
            onchange={() => save()}
            title="Weld near-touching path ends into continuous strokes before reordering. 0 = off. Try 0.05–0.15."
          />
        </div>
        <label class="check" for="plotter-auto-rotate">
          <input id="plotter-auto-rotate" type="checkbox" bind:checked={studio.settings.auto_rotate} onchange={() => save()} />
          <span>Auto-rotate SVG</span>
        </label>
      </div>
    {/if}
  </div>
{/if}

{#if penReview}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Confirm pens">
      <p>
        This drawing uses {penReview.length} pens. They'll be plotted one at a time —
        you'll be prompted to swap pens (and re-home) between each.
      </p>
      <ul class="pen-list">
        {#each penReview as pen, i}
          <li>
            <span class="swatch" style:background={pen.colour}></span>
            <span class="pen-name">{i + 1}. {pen.name}</span>
            <span class="pen-count">{pen.shapes.toLocaleString()} shapes</span>
          </li>
        {/each}
      </ul>
      <div class="modal-actions">
        <button class="primary" onclick={confirmStartPlot}>
          Start with {penReview[0]?.name}
        </button>
        <button onclick={() => (penReview = null)}>Cancel</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.5);
  }
  .modal {
    max-width: 320px;
    padding: 16px;
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  }
  .modal p {
    margin: 0 0 14px;
    font-size: 13px;
    line-height: 1.4;
  }
  .pen-list {
    list-style: none;
    margin: 0 0 14px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .pen-list li {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }
  .swatch {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid var(--line);
    flex: none;
  }
  .pen-name {
    flex: 1;
  }
  .pen-count {
    opacity: 0.7;
  }
  .modal-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .modal-actions button {
    padding: 6px;
  }
  .plotter {
    gap: 8px;
  }
  .tabs {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
  }
  .tabs button {
    min-width: 0;
    padding: 4px 3px;
    font-size: 11px;
  }
  .tabs button.active {
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }
  .actions {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 5px;
  }
  .quick,
  .manual {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 5px;
  }
  .actions button,
  .quick button,
  .manual button {
    min-width: 0;
    padding-left: 4px;
    padding-right: 4px;
  }
  .grid2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .f {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .f label,
  .label {
    color: var(--text-dim);
    font-size: 11px;
  }
  input,
  select {
    width: 100%;
  }
  .hero {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 8px;
  }
  .time {
    color: var(--text);
    font-size: 26px;
    font-weight: 700;
    line-height: 1.1;
  }
  .metrics,
  .breakdown,
  .live,
  .job {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 5px;
    margin-top: 6px;
  }
  .metrics div,
  .breakdown div,
  .live div,
  .job div,
  .status {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 5px 6px;
  }
  .metrics span,
  .breakdown span,
  .live span,
  .job span {
    color: var(--text-dim);
    display: block;
    font-size: 10px;
    text-transform: uppercase;
  }
  .metrics strong,
  .breakdown strong,
  .live strong,
  .job strong {
    font-size: 12px;
    font-weight: 600;
  }
  .job button {
    min-width: 0;
  }
  .job p {
    color: var(--text-dim);
    font-size: 11px;
    grid-column: 1 / -1;
    line-height: 1.3;
    margin: 0;
  }
  .paper-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 54px;
    gap: 5px;
  }
  .manual-layout {
    align-items: end;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 10px;
  }
  .dpad {
    display: grid;
    grid-template-columns: repeat(3, 34px);
    grid-template-rows: repeat(3, 30px);
    gap: 4px;
  }
  .dpad button {
    padding: 0;
  }
  .step {
    max-width: 90px;
  }
  .status {
    color: var(--text-dim);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    overflow-wrap: anywhere;
  }
  .check {
    align-items: center;
    display: flex;
    gap: 7px;
  }
  .check input {
    width: auto;
  }
</style>
