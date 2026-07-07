<script lang="ts">
  // Popover editor for one param's spatial-field binding. Edits a local copy
  // and reports every change up via onChange; the parent owns persistence
  // (commit into pathfinding_style.params.field_bindings).
  import { api } from "../lib/api";
  import { studio } from "../lib/state.svelte";
  import type { FieldBinding, FieldLayer, Param } from "../lib/types";
  import NumStep from "./NumStep.svelte";

  let {
    param,
    layerId,
    binding,
    onChange,
    onClose,
    onPaint,
  }: {
    param: Param;
    layerId: string;
    binding: FieldBinding | null;
    onChange: (b: FieldBinding | null) => void;
    onClose: () => void;
    onPaint: () => void;
  } = $props();

  const LAYER_DEFS: { type: FieldLayer["type"]; label: string }[] = [
    { type: "luminance", label: "Image tone" },
    { type: "gradient_mag", label: "Edge strength" },
    { type: "edge_distance", label: "Edge distance" },
    { type: "noise", label: "Noise" },
    { type: "radial", label: "Radial" },
    { type: "linear", label: "Linear" },
    { type: "paint", label: "Painted mask" },
  ];

  function fresh(): FieldBinding {
    return {
      kind: param.type === "angle" ? "orientation" : "scalar",
      out_min: param.min ?? 0,
      out_max: param.max ?? 1,
      invert: false,
      gamma: 1.0,
      layers: LAYER_DEFS.map(({ type }) => ({
        type,
        weight: type === "luminance" ? 1.0 : 0.0,
        ...(type === "noise" ? { scale: 25, octaves: 3, seed: 0 } : {}),
        ...(type === "radial" ? { cx: 50, cy: 50, inner: 0, outer: 100 } : {}),
        ...(type === "linear" ? { angle: 0 } : {}),
        ...(type === "paint" ? { paint_id: "" } : {}),
      })),
    };
  }

  function withAllLayers(b: FieldBinding): FieldBinding {
    // Ensure every canonical layer type has an entry so the UI rows are stable.
    const base = fresh();
    for (const row of base.layers) {
      const existing = b.layers.find((l) => l.type === row.type);
      if (existing) Object.assign(row, existing);
      else row.weight = 0;
    }
    return { ...base, ...b, layers: base.layers };
  }

  let local = $state<FieldBinding>(binding ? withAllLayers(binding) : fresh());
  let previewTick = $state(0);
  let timer: ReturnType<typeof setTimeout> | null = null;

  function commit() {
    onChange($state.snapshot(local) as FieldBinding);
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => (previewTick += 1), 400);
  }

  function unbind() {
    onChange(null);
    onClose();
  }

  function layerRow(type: FieldLayer["type"]): FieldLayer {
    return local.layers.find((l) => l.type === type)!;
  }

  async function renameMask(id: string) {
    const current = studio.fieldMasks.find((m) => m.id === id);
    const name = window.prompt("Rename field mask", current?.name ?? "");
    if (name === null) return;
    await api.renameFieldMask(id, name.trim() || (current?.name ?? "Field mask"));
  }

  async function deleteMask(id: string) {
    const current = studio.fieldMasks.find((m) => m.id === id);
    if (!window.confirm(`Delete field mask “${current?.name ?? id}”? Bindings using it will fall back to neutral gray.`)) return;
    await api.deleteFieldMask(id);
    const row = layerRow("paint");
    if (row.paint_id === id) {
      row.paint_id = "";
      commit();
    }
  }

  const previewUrl = $derived(
    `/api/composition/layers/${layerId}/field-preview?param=${param.name}&v=${previewTick}`,
  );
  const isOrientation = $derived(local.kind === "orientation");
</script>

<section class="binding-editor" aria-label={`Field binding for ${param.label}`}>
  <header>
    <strong>{param.label} field</strong>
    <div class="actions">
      <button type="button" onclick={unbind}>Unbind</button>
      <button type="button" onclick={onClose}>✕</button>
    </div>
  </header>

  <div class="body" onchange={commit}>
    {#each LAYER_DEFS as def (def.type)}
      {@const row = layerRow(def.type)}
      <div class="layer" class:active={row.weight > 0}>
        <div class="layer-head">
          <span>{def.label}</span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.05"
            bind:value={row.weight}
            title={`${def.label} weight: ${row.weight}`}
          />
        </div>
        {#if row.weight > 0}
          {#if def.type === "noise"}
            <div class="opts">
              <label>scale <NumStep min={2} max={100} step={1} bind:value={row.scale} /></label>
              <label>octaves <NumStep min={1} max={6} step={1} bind:value={row.octaves} /></label>
              <label>seed <NumStep step={1} bind:value={row.seed} /></label>
            </div>
          {:else if def.type === "radial"}
            <div class="opts">
              <label>cx% <NumStep min={0} max={100} step={1} bind:value={row.cx} /></label>
              <label>cy% <NumStep min={0} max={100} step={1} bind:value={row.cy} /></label>
              <label>inner <NumStep min={0} max={100} step={1} bind:value={row.inner} /></label>
              <label>outer <NumStep min={0} max={200} step={1} bind:value={row.outer} /></label>
            </div>
          {:else if def.type === "linear"}
            <div class="opts">
              <label>angle° <NumStep min={0} max={360} step={1} bind:value={row.angle} /></label>
            </div>
          {:else if def.type === "paint"}
            <div class="opts paint">
              <select data-tour="paint-select" bind:value={row.paint_id}>
                <option value="">— pick a mask —</option>
                {#each studio.fieldMasks as m (m.id)}
                  <option value={m.id}>{m.name}</option>
                {/each}
              </select>
              <button type="button" data-tour="paint-btn" onclick={onPaint}>Paint…</button>
              {#if row.paint_id}
                <div class="mask-manage">
                  <button type="button" title="Rename this mask" onclick={() => void renameMask(row.paint_id!)}>Rename</button>
                  <button type="button" class="danger" title="Delete this mask from the project" onclick={() => void deleteMask(row.paint_id!)}>Delete</button>
                </div>
              {/if}
            </div>
          {/if}
        {/if}
      </div>
    {/each}

    <div class="shaping">
      {#if !isOrientation}
        <label class="check">
          <input type="checkbox" bind:checked={local.invert} />
          <span>Invert</span>
        </label>
        <label>gamma
          <input type="range" min="0.2" max="4" step="0.05" bind:value={local.gamma} />
        </label>
        <div class="range">
          <label>min <NumStep step={param.step ?? 0.1} bind:value={local.out_min} /></label>
          <label>max <NumStep step={param.step ?? 0.1} bind:value={local.out_max} /></label>
        </div>
      {/if}
    </div>

    <div class="preview">
      <img src={previewUrl} alt="Resolved field preview" />
      <span class="hint">dark = {isOrientation ? "0°" : "low"} · light = {isOrientation ? "180°" : "high"}</span>
    </div>
  </div>
</section>

<style>
  .binding-editor {
    position: fixed;
    right: 652px;
    top: 120px;
    z-index: 40;
    width: min(280px, calc(100vw - 24px));
    max-height: calc(100vh - 150px);
    overflow-y: auto;
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.42);
    font-size: 11px;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--line);
  }
  .actions {
    display: flex;
    gap: 6px;
  }
  .body {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .layer {
    opacity: 0.65;
  }
  .layer.active {
    opacity: 1;
  }
  .layer-head {
    display: grid;
    grid-template-columns: 92px 1fr;
    gap: 6px;
    align-items: center;
  }
  .opts {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 4px 0 2px 6px;
  }
  .opts label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .opts :global(.numstep) {
    width: 56px;
  }
  .opts.paint {
    display: grid;
    grid-template-columns: 1fr auto;
  }
  .mask-manage {
    grid-column: 1 / -1;
    display: flex;
    gap: 6px;
  }
  .mask-manage button {
    font-size: 10px;
    padding: 2px 8px;
  }
  .mask-manage .danger {
    color: var(--danger, #e05555);
  }
  .shaping {
    border-top: 1px solid var(--line);
    padding-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .shaping .check {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .shaping .check input {
    width: auto;
  }
  .range {
    display: flex;
    gap: 8px;
  }
  .range :global(.numstep) {
    width: 68px;
  }
  .preview {
    border-top: 1px solid var(--line);
    padding-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .preview img {
    width: 100%;
    image-rendering: pixelated;
    border: 1px solid var(--line);
    background: #333;
    min-height: 60px;
  }
  .hint {
    color: var(--text-dim, #888);
    font-size: 10px;
  }
  @media (max-width: 1280px) {
    .pfm-picker {
      right: auto;
      left: 12px;
    }
  }
</style>
