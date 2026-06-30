<script lang="ts">
  import { studio } from "../../lib/state.svelte";
  import { api } from "../../lib/api";
  import type { Pen } from "../../lib/types";

  async function save() {
    await api.savePens();
    recalcGenerator();
  }

  // Editing the pens re-maps the generator's pen cycle: recompute the selected
  // generate layer in place (like auto-redraw). Skipped mid generator-switch so an
  // unapplied generator change is never applied, and while a job is in flight.
  function recalcGenerator() {
    const sel = studio.selectedLayer;
    if (
      sel?.kind === "generate" &&
      sel.source?.generator_id === studio.generatorId &&
      !studio.processing
    ) {
      void api.generate();
    }
  }

  function addPen() {
    studio.drawingSet?.pens.push({
      name: "Pen " + ((studio.drawingSet?.pens.length ?? 0) + 1),
      type: "Custom",
      colour: "#888888",
      weight: 1,
      stroke_mm: 0.5,
      enabled: true,
    });
    save();
  }
  function removePen(i: number) {
    studio.drawingSet?.pens.splice(i, 1);
    save();
  }
  function pct(p: Pen): number {
    const layer = studio.stats?.per_pen.find((x) => x.name === p.name);
    const total = studio.stats?.total || 0;
    return layer && total ? Math.round((layer.count / total) * 100) : 0;
  }
  async function loadLib(e: Event) {
    const select = e.target as HTMLSelectElement;
    const name = select.value;
    select.value = "";
    if (name) {
      await api.loadLibrary(name);
      recalcGenerator();
    }
  }
</script>

{#if studio.drawingSet}
  <div class="col">
    <div class="row">
      <select onchange={loadLib} title="Load a pen library">
        <option value="">Library…</option>
        {#each studio.libraries as lib}<option value={lib}>{lib}</option>{/each}
      </select>
      <button class="icon" title="Add pen" onclick={addPen}>＋</button>
    </div>

    <div class="pens">
      {#each studio.drawingSet.pens as pen, i (i)}
        <div class="pen" class:off={!pen.enabled}>
          <input
            type="checkbox"
            bind:checked={pen.enabled}
            onchange={save}
            title="Enabled"
          />
          <input type="color" bind:value={pen.colour} onchange={save} />
          <input class="name" bind:value={pen.name} onchange={save} />
          <input
            class="w"
            type="number"
            min="0"
            step="0.5"
            bind:value={pen.weight}
            onchange={save}
            title="Weight"
          />
          <span class="pct">{pct(pen)}%</span>
          <button class="icon del" title="Remove" onclick={() => removePen(i)}>✕</button>
        </div>
      {/each}
    </div>

    <div class="grid2">
      <div class="f">
        <label>Distribution</label>
        <select bind:value={studio.drawingSet.distribution_type} onchange={save}>
          <option value="luminance">Luminance</option>
          <option value="even">Even weighted</option>
          <option value="random">Random weighted</option>
          <option value="single">Single pen</option>
        </select>
      </div>
      <div class="f">
        <label>Order</label>
        <select bind:value={studio.drawingSet.distribution_order} onchange={save}>
          <option value="darkest">Darkest first</option>
          <option value="lightest">Lightest first</option>
          <option value="displayed">Displayed</option>
          <option value="reversed">Reversed</option>
        </select>
      </div>
    </div>
  </div>
{/if}

<style>
  .pens {
    display: flex;
    flex-direction: column;
    gap: 3px;
    margin: 6px 0;
  }
  .pen {
    display: grid;
    grid-template-columns: auto 30px 1fr 46px 34px auto;
    gap: 5px;
    align-items: center;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 3px 5px;
  }
  .pen.off {
    opacity: 0.45;
  }
  .name {
    width: 100%;
  }
  .pct {
    font-size: 11px;
    color: var(--text-dim);
    text-align: right;
  }
  .del {
    color: var(--text-dim);
    padding: 2px 5px;
  }
  .grid2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .f {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .f label {
    font-size: 11px;
  }
  select {
    width: 100%;
  }
</style>
