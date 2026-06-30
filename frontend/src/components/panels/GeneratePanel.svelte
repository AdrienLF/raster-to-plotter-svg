<script lang="ts">
  import { untrack } from "svelte";
  import { studio } from "../../lib/state.svelte";
  import { api } from "../../lib/api";
  import ParamControl from "../ParamControl.svelte";
  import ShapeFieldEditor from "../generate/ShapeFieldEditor.svelte";

  // group params by their `group` field, preserving order
  const groups = $derived.by(() => {
    const m = new Map<string, typeof studio.genSchema>();
    for (const p of studio.genSchema) {
      if (!m.has(p.group)) m.set(p.group, []);
      m.get(p.group)!.push(p);
    }
    return [...m.entries()];
  });

  // Show one param group at a time via a tab strip. Derive the active group so it
  // stays valid when the generator (and thus the group list) changes.
  // Generators with a custom editor (e.g. shape_field) contribute an extra tab
  // rendered by their dedicated component instead of plain ParamControls.
  const SHAPES_TAB = "Shapes";
  let activeGroup = $state<string | null>(null);
  const groupNames = $derived.by(() => {
    const names = groups.map(([g]) => g);
    if (studio.generatorEditor === "shape_field") names.unshift(SHAPES_TAB);
    return names;
  });
  const current = $derived(
    activeGroup && groupNames.includes(activeGroup) ? activeGroup : groupNames[0],
  );
  const activeParams = $derived(groups.find(([g]) => g === current)?.[1] ?? []);

  async function onSelect(e: Event) {
    await api.selectGenerator((e.target as HTMLSelectElement).value);
  }

  async function onTarget(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    if (value === "__new__") await api.newLayer();
    else await api.selectLayer(value);
  }

  function paramsKey(params: Record<string, any>) {
    return JSON.stringify(
      Object.entries(params).sort(([left], [right]) => left.localeCompare(right)),
    );
  }

  // Auto-redraw: live-redraw (debounced) when a parameter changes — but only for
  // a layer that's already a generate layer running the *same* generator.
  // Switching generators never auto-redraws; applying a new generator (or first
  // generating a layer) requires the explicit ✦ Generate button.
  let timer: ReturnType<typeof setTimeout>;
  let mounted = false;
  $effect(() => {
    const paramsJson = paramsKey(studio.genParams); // track every parameter
    const generatorId = studio.generatorId;
    studio.autoRedraw;
    clearTimeout(timer);
    if (!mounted) { mounted = true; return; } // don't fire just from opening the step
    if (!studio.autoRedraw) return;
    // Never spawn a generate layer implicitly — only redraw an existing one.
    const selectedLayer = untrack(() => studio.selectedLayer);
    if (selectedLayer?.kind !== "generate") return;
    const selectedSource = selectedLayer.source ?? {};
    // A different generator is a deliberate change — wait for ✦ Generate.
    if (selectedSource.generator_id !== generatorId) return;
    if (paramsKey(selectedSource.params ?? {}) === paramsJson) return;
    timer = setTimeout(() => {
      if (!studio.processing) void api.generate();
    }, 350);
  });

  // ✦ Generate: warn before overwriting a layer that already holds a generation,
  // offering to spawn a fresh layer instead. The explicit target is
  // selected_layer_id (null = "＋ New layer", which never overwrites) — not the
  // selectedLayer fallback, which points at the top layer when nothing is chosen.
  const genTarget = $derived(
    studio.composition.selected_layer_id
      ? studio.composition.layers.find((l) => l.id === studio.composition.selected_layer_id) ?? null
      : null,
  );
  let confirmOverwrite = $state(false);
  function onGenerate() {
    if (genTarget?.kind === "generate") confirmOverwrite = true;
    else void api.generate();
  }
  async function generateNewLayer() {
    confirmOverwrite = false;
    await api.newLayer();
    await api.generate();
  }
  function overwriteLayer() {
    confirmOverwrite = false;
    void api.generate();
  }
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
    <button class="primary gen" disabled={studio.processing} onclick={onGenerate}>
      {studio.processing ? "Generating…" : "✦ Generate"}
    </button>
    <label class="auto" title="Redraw automatically when a parameter changes">
      <input type="checkbox" bind:checked={studio.autoRedraw} />
      <span>Auto</span>
    </label>
  </div>

  <div class="tabs">
    {#each groupNames as group (group)}
      <button class:active={group === current} onclick={() => (activeGroup = group)}>{group}</button>
    {/each}
  </div>
  {#if current === SHAPES_TAB}
    <ShapeFieldEditor />
  {:else}
    <div class="group">
      {#each activeParams as p (p.name)}
        <ParamControl param={p} bind:value={studio.genParams[p.name]} />
      {/each}
    </div>
  {/if}
</div>

{#if confirmOverwrite}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Layer already generated">
      <p>
        “{genTarget?.name}” already has a generation. Generating will
        overwrite it.
      </p>
      <div class="modal-actions">
        <button class="primary" onclick={generateNewLayer}>Create new layer</button>
        <button onclick={overwriteLayer}>Overwrite this layer</button>
        <button onclick={() => (confirmOverwrite = false)}>Cancel</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .gen-select {
    width: 100%;
  }
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
  .modal-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .modal-actions button {
    padding: 6px;
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
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    border-top: 1px solid var(--line);
    padding-top: 8px;
    margin-top: 4px;
  }
  .tabs button {
    padding: 3px 6px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .tabs button.active {
    border-color: var(--accent);
    background: #263346;
    color: var(--accent);
  }
  .group {
    padding-top: 4px;
  }
</style>
