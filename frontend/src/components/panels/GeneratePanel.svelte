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
</script>

<div class="col">
  <select class="gen-select" value={studio.generatorId} onchange={onSelect}>
    {#each studio.generators as g (g.id)}
      <option value={g.id}>{g.name}</option>
    {/each}
  </select>

  <button class="primary gen" disabled={studio.processing} onclick={() => api.generate()}>
    {studio.processing ? "Generating…" : "✦ Generate"}
  </button>

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
  .gen {
    width: 100%;
    padding: 6px;
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
