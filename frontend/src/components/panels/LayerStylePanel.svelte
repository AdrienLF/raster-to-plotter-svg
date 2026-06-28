<script lang="ts">
  import { api } from "../../lib/api";
  import { studio } from "../../lib/state.svelte";
  import type { LayerDisplayMode, Param, PathfindingStyleT } from "../../lib/types";
  import ParamControl from "../ParamControl.svelte";

  let localParams = $state<Record<string, any>>({});
  let loadedPfm = $state("");
  let paramKey = "";
  let regionName = $state("Region");
  let invertRegion = $state(false);

  const layer = $derived(studio.selectedLayer);
  const style = $derived.by(() => {
    const current = (layer?.pathfinding_style ?? {}) as Partial<PathfindingStyleT>;
    return {
      enabled: current.enabled ?? true,
      pfm_id: current.pfm_id ?? studio.pfmId,
      params: { ...(current.params ?? {}) },
      status: current.status ?? "stale",
      error: current.error ?? "",
      cache: { ...(current.cache ?? {}) },
    };
  });
  const selectedRegionId = $derived(layer?.region_id ?? "");
  // Live feedback for SAM model setup (install/download/ready/error).
  const samSetup = $derived.by(() => {
    const s = studio.segmentationStatus;
    if (!s) return null;
    if (s.available) return { kind: "ready" as const, text: "Model ready", pct: 1 };
    if (s.setup_state === "error" || s.error)
      return { kind: "error" as const, text: `AI unavailable: ${s.error ?? "setup failed"}`, pct: 0 };
    if (s.auto_setup === false)
      return { kind: "error" as const, text: "AI selection unavailable", pct: 0 };
    if (s.setup_state === "installing") return { kind: "busy" as const, text: "Installing SAM 2…", pct: 0 };
    if (s.setup_state === "downloading")
      return { kind: "busy" as const, text: `Downloading model… ${Math.round((s.progress ?? 0) * 100)}%`, pct: s.progress ?? 0 };
    return { kind: "busy" as const, text: "Preparing AI model…", pct: 0 };
  });
  const samBusy = $derived(samSetup?.kind === "busy");
  const groups = $derived.by(() => {
    const m = new Map<string, Param[]>();
    for (const p of studio.layerStyleSchema) {
      if (!m.has(p.group)) m.set(p.group, []);
      m.get(p.group)!.push(p);
    }
    return [...m.entries()];
  });

  $effect(() => {
    if (!studio.layerStyleOpen || !layer) return;
    const pfm = style.pfm_id || studio.pfmId;
    if (pfm && pfm !== loadedPfm) {
      loadedPfm = pfm;
      void loadSchema(pfm);
    }
  });

  $effect(() => {
    const key = `${layer?.id ?? ""}:${style.pfm_id}:${JSON.stringify(style.params ?? {})}:${studio.layerStyleSchema.map((p) => p.name).join(",")}`;
    if (key === paramKey) return;
    paramKey = key;
    localParams = { ...defaults(studio.layerStyleSchema), ...(style.params ?? {}) };
  });

  function defaults(schema: Param[]) {
    const out: Record<string, any> = {};
    for (const p of schema) out[p.name] = p.default;
    return out;
  }

  async function loadSchema(pfmId: string) {
    const schema = await api.loadLayerStyleSchema(pfmId);
    localParams = { ...defaults(schema), ...(style.params ?? {}) };
  }

  async function setRegion(region_id: string) {
    if (!layer) return;
    await api.patchLayer(layer.id, { region_id: region_id || null });
  }

  function startRegion() {
    studio.regionSelecting = true;
    api.clearRegionDraft();
  }

  async function saveRegion() {
    if (!layer) return;
    const name = regionName.trim() || "Region";
    const region = await api.saveRegion(name, invertRegion);
    if (region) {
      regionName = "Region";
      invertRegion = false;
      await api.patchLayer(layer.id, { region_id: region.id });
    }
  }

  function cancelRegion() {
    studio.regionSelecting = false;
    api.clearRegionDraft();
  }

  async function deleteRegion() {
    if (!layer?.region_id) return;
    await api.deleteRegion(layer.region_id);
    await api.patchLayer(layer.id, { region_id: null });
  }

  async function setDisplay(display_mode: LayerDisplayMode) {
    if (!layer) return;
    layer.display_mode = display_mode;
    await api.patchLayer(layer.id, { display_mode });
  }

  async function setOcclusion(occlude_below: boolean) {
    if (!layer) return;
    layer.occlude_below = occlude_below;
    await api.patchLayer(layer.id, { occlude_below });
  }

  async function patchStyle(patch: Record<string, any>) {
    if (!layer) return;
    await api.patchLayerStyle(layer.id, { ...patch, status: "stale" });
  }

  async function setPfm(pfm_id: string) {
    const schema = await api.loadLayerStyleSchema(pfm_id);
    loadedPfm = pfm_id;
    localParams = defaults(schema);
    await patchStyle({ pfm_id, params: localParams });
  }

  async function setEnabled(enabled: boolean) {
    if (!layer) return;
    if (!enabled && layer.display_mode === "pathfinding") {
      layer.display_mode = "raster";
      await api.patchLayer(layer.id, { display_mode: "raster" });
    }
    await patchStyle({ enabled });
  }

  async function commitParams() {
    await patchStyle({ params: localParams });
  }

  async function generate() {
    if (!layer) return;
    await commitParams();
    await api.generateLayerPathfinding(layer.id);
  }
</script>

{#if studio.layerStyleOpen}
  <section class="layer-style" aria-label="Layer style">
    <header>
      <div>
        <strong>Path Finding</strong>
        {#if layer}
          <span>{layer.name}</span>
        {/if}
      </div>
      <button aria-label="Close path finding" onclick={() => (studio.layerStyleOpen = false)}>×</button>
    </header>

    {#if layer}
      <div class="body">
        <div class="regions">
          <label>
            <span>Region</span>
            <select value={selectedRegionId} onchange={(e) => setRegion((e.target as HTMLSelectElement).value)}>
              <option value="">Whole image</option>
              {#each studio.regions as region (region.id)}
                <option value={region.id}>{region.name}</option>
              {/each}
            </select>
          </label>
          <div class="region-actions">
            <button
              disabled={!studio.imageUrl || studio.regionPredicting || studio.segmentationStatus?.available === false}
              onclick={startRegion}
            >
              Create AI region
            </button>
            {#if selectedRegionId}
              <button class="danger-text" onclick={deleteRegion}>Delete</button>
            {/if}
          </div>
          {#if studio.segmentationStatus?.models?.length}
            <label class="sam-model">
              <span>SAM model {#if samSetup?.kind === "ready"}<span class="ok-dot" title="Model ready">●</span>{/if}</span>
              <select
                value={studio.segmentationStatus.model}
                disabled={samBusy}
                onchange={(e) => api.setSamModel((e.target as HTMLSelectElement).value)}
              >
                {#each studio.segmentationStatus.models as m (m)}
                  <option value={m}>{m.replace("sam2.1_hiera_", "")}</option>
                {/each}
              </select>
            </label>
            {#if samSetup && samSetup.kind !== "ready"}
              <div class="sam-status" class:error={samSetup.kind === "error"}>
                {#if samSetup.kind === "busy"}<span class="spinner"></span>{/if}
                <span>{samSetup.text}</span>
                {#if samSetup.kind === "busy" && samSetup.pct > 0}
                  <div class="mini-bar"><div class="mini-fill" style:width={`${samSetup.pct * 100}%`}></div></div>
                {/if}
              </div>
            {/if}
          {/if}
          {#if studio.regionSelecting}
            <div class="region-save">
              <input aria-label="Region name" bind:value={regionName} placeholder="Region name" />
              <label class="check">
                <input type="checkbox" bind:checked={invertRegion} />
                <span>Invert for background</span>
              </label>
              <div class="region-actions">
                <button class="primary" disabled={!studio.regionDraftMask || studio.regionPredicting} onclick={saveRegion}>
                  Save region
                </button>
                <button onclick={cancelRegion}>Cancel</button>
              </div>
            </div>
          {/if}
          {#if studio.regionPredicting}
            <p class="hint"><span class="spinner"></span> Selecting region…</p>
          {:else if studio.regionSelecting}
            <p class="hint">Click the image to include a part; Alt-click or right-click to exclude.</p>
          {/if}
        </div>

        <div class="row display">
          <span>Display</span>
          <button class:on={(layer.display_mode ?? "pathfinding") === "raster"} onclick={() => setDisplay("raster")}>Raster</button>
          <button class:on={(layer.display_mode ?? "pathfinding") === "pathfinding"} onclick={() => setDisplay("pathfinding")}>Paths</button>
          <button class:on={(layer.display_mode ?? "pathfinding") === "both"} onclick={() => setDisplay("both")}>Both</button>
        </div>

        <label class="check">
          <input
            type="checkbox"
            checked={style.enabled}
            onchange={(e) => setEnabled((e.target as HTMLInputElement).checked)}
          />
          <span>Path finding</span>
          <em class:dirty={style.status === "stale"}>{style.status}</em>
        </label>

        <label class="check">
          <input
            type="checkbox"
            checked={layer.occlude_below}
            onchange={(e) => setOcclusion((e.target as HTMLInputElement).checked)}
          />
          <span>Occlude below</span>
        </label>

        <label>
          <span>PFM</span>
          <select value={style.pfm_id || studio.pfmId} onchange={(e) => setPfm((e.target as HTMLSelectElement).value)}>
            {#each studio.pfms as pfm (pfm.id)}
              <option value={pfm.id}>{pfm.name}</option>
            {/each}
          </select>
        </label>

        <div class="params" onchange={commitParams}>
          {#each groups as [group, params]}
            <div class="group">
              <div class="group-title">{group}</div>
              {#each params as p (p.name)}
                <ParamControl param={p} bind:value={localParams[p.name]} />
              {/each}
            </div>
          {/each}
        </div>

        {#if style.error}
          <p class="error">{style.error}</p>
        {/if}

        <button
          class="primary"
          disabled={studio.processing || !style.enabled}
          onclick={generate}
        >
          {studio.processing ? "Generating..." : "Apply / Regenerate"}
        </button>
      </div>
    {:else}
      <p class="empty">Select a layer</p>
    {/if}
  </section>
{/if}

<style>
  .layer-style {
    position: fixed;
    right: 324px;
    top: 92px;
    z-index: 30;
    width: min(320px, calc(100vw - 24px));
    max-height: calc(100vh - 120px);
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.42);
    display: flex;
    flex-direction: column;
  }
  header {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: center;
    border-bottom: 1px solid var(--line);
    padding: 9px 10px;
  }
  header div {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
  }
  header strong {
    font-size: 13px;
  }
  header span {
    color: var(--text-dim);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  header button {
    width: 26px;
    height: 26px;
    padding: 0;
  }
  .body {
    overflow: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 11px;
  }
  select {
    width: 100%;
  }
  .row {
    display: grid;
    align-items: center;
    gap: 6px;
  }
  .display {
    grid-template-columns: 52px repeat(3, 1fr);
  }
  .display span {
    color: var(--text-dim);
    font-size: 11px;
  }
  .display button {
    padding: 4px 6px;
  }
  .display button.on {
    border-color: var(--accent);
    background: #263346;
  }
  .check {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 7px;
  }
  .check input {
    width: auto;
    margin: 0;
  }
  .check em {
    color: var(--text-dim);
    font-size: 10px;
    font-style: normal;
  }
  .check em.dirty {
    color: var(--accent);
  }
  .group {
    border-top: 1px solid var(--line);
    padding-top: 8px;
  }
  .group:first-child {
    border-top: 0;
  }
  .group-title {
    color: var(--accent);
    font-size: 10px;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
    text-transform: uppercase;
  }
  .primary {
    width: 100%;
    padding: 6px;
  }
  .regions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .region-actions {
    display: flex;
    gap: 6px;
  }
  .region-actions button {
    flex: 1;
    min-width: 0;
    padding: 4px 6px;
    font-size: 11px;
  }
  .region-save {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .region-save .check {
    grid-template-columns: auto 1fr;
  }
  .danger-text {
    color: var(--danger);
  }
  .hint {
    margin: 0;
    color: var(--text-dim);
    font-size: 10px;
    line-height: 1.35;
  }
  .sam-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--text-dim);
  }
  .sam-status.error {
    color: var(--danger);
  }
  .sam-status .mini-bar {
    flex: 1;
    height: 4px;
    background: var(--panel-2);
    border-radius: 2px;
    overflow: hidden;
  }
  .sam-status .mini-fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.2s;
  }
  .ok-dot {
    color: var(--ok);
    font-size: 9px;
  }
  .spinner {
    width: 10px;
    height: 10px;
    border: 1.5px solid var(--line);
    border-top-color: var(--accent);
    border-radius: 50%;
    display: inline-block;
    flex: none;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .error,
  .empty {
    color: var(--danger);
    font-size: 11px;
    margin: 0;
  }
  .empty {
    color: var(--text-dim);
    padding: 10px;
  }
  @media (max-width: 900px) {
    .layer-style {
      left: 12px;
      right: 12px;
      top: 76px;
      width: auto;
    }
  }
</style>
