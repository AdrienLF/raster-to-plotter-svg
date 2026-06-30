<script lang="ts">
  import { studio } from "../../lib/state.svelte";
  import { api } from "../../lib/api";
  import NumStep from "../NumStep.svelte";

  function applyPreset(e: Event) {
    const name = (e.target as HTMLSelectElement).value;
    const p = studio.presets[name];
    if (p && studio.area) {
      const [w, h] = p;
      studio.area.units = "mm";
      if (studio.area.orientation === "landscape") {
        studio.area.width = h;
        studio.area.height = w;
      } else {
        studio.area.width = w;
        studio.area.height = h;
      }
      api.saveArea();
    }
  }
  const save = () => api.saveArea();
</script>

{#if studio.area}
  <div class="col">
    <label>Preset</label>
    <select onchange={applyPreset}>
      <option value="">— choose —</option>
      {#each Object.keys(studio.presets) as name}
        <option value={name}>{name}</option>
      {/each}
    </select>

    <div class="grid2">
      <div class="f">
        <label>Units</label>
        <select bind:value={studio.area.units} onchange={save}>
          {#each ["mm", "cm", "in", "px"] as u}<option>{u}</option>{/each}
        </select>
      </div>
      <div class="f">
        <label>Orientation</label>
        <select bind:value={studio.area.orientation} onchange={save}>
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>
      </div>
      <div class="f">
        <label>Width</label>
        <NumStep bind:value={studio.area.width} onchange={save} />
      </div>
      <div class="f">
        <label>Height</label>
        <NumStep bind:value={studio.area.height} onchange={save} />
      </div>
    </div>

    <label>Padding (L / R / T / B)</label>
    <div class="grid4">
      <NumStep bind:value={studio.area.pad_left} onchange={save} />
      <NumStep bind:value={studio.area.pad_right} onchange={save} />
      <NumStep bind:value={studio.area.pad_top} onchange={save} />
      <NumStep bind:value={studio.area.pad_bottom} onchange={save} />
    </div>

    <div class="grid2">
      <div class="f">
        <label>Scaling</label>
        <select bind:value={studio.area.scaling_mode} onchange={save}>
          <option value="crop">Crop to fit</option>
          <option value="scale">Scale to fit</option>
          <option value="stretch">Stretch</option>
        </select>
      </div>
      <div class="f">
        <label>Clipping</label>
        <select bind:value={studio.area.clipping} onchange={save}>
          <option value="drawing">Drawing</option>
          <option value="page">Page</option>
          <option value="none">None</option>
        </select>
      </div>
      <div class="f">
        <label>Pen width (mm)</label>
        <NumStep
          step={0.05}
          bind:value={studio.area.pen_width_mm}
          onchange={save}
        />
      </div>
      <div class="f">
        <label>Rescale</label>
        <select bind:value={studio.area.rescale_mode} onchange={save}>
          <option value="high">High</option>
          <option value="low">Low</option>
          <option value="off">Off</option>
        </select>
      </div>
    </div>

    <div class="grid2">
      <div class="f">
        <label>Canvas</label>
        <input type="color" bind:value={studio.area.canvas_colour} onchange={save} />
      </div>
      <div class="f">
        <label>Background</label>
        <input
          type="color"
          bind:value={studio.area.background_colour}
          onchange={save}
        />
      </div>
    </div>
  </div>
{/if}

<style>
  .grid2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .grid4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 5px;
  }
  .f {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .f label {
    font-size: 11px;
  }
  input,
  select {
    width: 100%;
  }
</style>
