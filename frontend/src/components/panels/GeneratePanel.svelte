<script lang="ts">
  import { studio } from "../../lib/state.svelte";
  import { api } from "../../lib/api";
  import ParamControl from "../ParamControl.svelte";

  // group params by their `group` field, preserving order
  const groups = $derived.by(() => {
    const m = new Map<string, typeof studio.genSchema>();
    for (const p of studio.genSchema) {
      if (!m.has(p.group)) m.set(p.group, []);
      m.get(p.group)!.push(p);
    }
    return [...m.entries()];
  });

  async function onSelect(e: Event) {
    await api.selectGenerator((e.target as HTMLSelectElement).value);
  }

  async function onTarget(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    if (value === "__new__") await api.newLayer();
    else await api.selectLayer(value);
  }

  // Auto-redraw: regenerate (debounced) on entering the step and whenever a
  // parameter changes. The panel only mounts on the Generate step, so the
  // initial run gives an immediate first draw.
  let timer: ReturnType<typeof setTimeout>;
  $effect(() => {
    JSON.stringify(studio.genParams); // track every parameter
    studio.generatorId;
    studio.autoRedraw;
    clearTimeout(timer);
    if (!studio.autoRedraw) return;
    timer = setTimeout(() => {
      if (!studio.processing) void api.generate();
    }, 350);
  });
</script>

<div class="col">
  <label class="target">
    <span>Layer</span>
    <select value={studio.composition.selected_layer_id ?? "__new__"} onchange={onTarget}>
      <option value="__new__">＋ New layer</option>
      {#each studio.composition.layers as layer (layer.id)}
        <option value={layer.id}>{layer.name}</option>
      {/each}
    </select>
  </label>

  <select class="gen-select" value={studio.generatorId} onchange={onSelect}>
    {#each studio.generators as g (g.id)}
      <option value={g.id}>{g.name}</option>
    {/each}
  </select>

  <div class="row">
    <button class="primary gen" disabled={studio.processing} onclick={() => api.generate()}>
      {studio.processing ? "Generating…" : "✦ Generate"}
    </button>
    <label class="auto" title="Redraw automatically when a parameter changes">
      <input type="checkbox" bind:checked={studio.autoRedraw} />
      <span>Auto</span>
    </label>
  </div>

  {#each groups as [group, params] (group)}
    <div class="group">
      <div class="group-title">{group}</div>
      {#each params as p (p.name)}
        <ParamControl param={p} bind:value={studio.genParams[p.name]} />
      {/each}
    </div>
  {/each}
</div>

<style>
  .gen-select {
    width: 100%;
  }
  .target {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 11px;
  }
  .target select {
    width: 100%;
  }
  .gen {
    flex: 1;
    padding: 6px;
  }
  .auto {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--text-dim);
    white-space: nowrap;
  }
  .auto input {
    width: auto;
  }
  .group {
    border-top: 1px solid var(--line);
    padding-top: 8px;
    margin-top: 4px;
  }
  .group-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--accent);
    margin-bottom: 6px;
  }
</style>
