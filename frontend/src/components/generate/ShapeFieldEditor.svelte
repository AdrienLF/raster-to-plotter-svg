<script lang="ts">
  import { studio } from "../../lib/state.svelte";
  import type { ShapeLayerT } from "../../lib/types";
  import NumStep from "../NumStep.svelte";

  const layers = $derived((studio.genParams.shape_layers ?? []) as ShapeLayerT[]);

  function setLayers(layers: ShapeLayerT[]) {
    studio.genParams = { ...studio.genParams, shape_layers: layers };
  }

  function patchLayer(id: string, patch: Partial<ShapeLayerT>) {
    setLayers(
      layers.map((layer) => (layer.id === id ? { ...layer, ...patch } : layer)),
    );
  }

  function addLayer() {
    const source = studio.generatorDefaults.shape_layers?.[0] ?? layers[0];
    if (!source) return;
    setLayers([...layers, { ...source, id: crypto.randomUUID() }]);
  }

  function duplicateLayer(id: string) {
    const index = layers.findIndex((layer) => layer.id === id);
    if (index < 0) return;
    const copy = {
      ...layers[index],
      id: crypto.randomUUID(),
    };
    setLayers([
      ...layers.slice(0, index + 1),
      copy,
      ...layers.slice(index + 1),
    ]);
  }

  function removeLayer(id: string) {
    setLayers(layers.filter((layer) => layer.id !== id));
  }

  function moveLayer(id: string, direction: number) {
    const index = layers.findIndex((layer) => layer.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= layers.length) return;
    const next = [...layers];
    [next[index], next[target]] = [next[target], next[index]];
    setLayers(next);
  }

</script>

{#snippet numField(
  label: string,
  value: number,
  min: number,
  max: number,
  step: number,
  set: (v: number) => void,
  wide = false,
)}
  <label class="field" class:wide>
    <span>{label}</span>
    <NumStep {min} {max} {step} {value} onchange={set} aria-label={label} />
  </label>
{/snippet}

<div class="shape-field-editor">
  <section class="group stack">
    <div class="stack-heading">
      <div>
        <div class="group-title">Shape stack</div>
        <div class="hint">
          <span class="stack-count">{layers.length} motifs</span>
          Layers combine inside every field tile.
        </div>
      </div>
      <button class="add-shape" aria-label="Add shape" onclick={addLayer}>＋ Add</button>
    </div>

    {#if layers.length === 0}
      <div class="empty">Add at least one shape to generate a field.</div>
    {/if}

    {#each layers as layer, index (layer.id)}
      <article class="shape-card">
        <div class="card-heading">
          <label class="enabled">
            <input
              type="checkbox"
              checked={layer.enabled}
              aria-label={`Enable shape ${index + 1}`}
              onchange={(event) =>
                patchLayer(layer.id, {
                  enabled: (event.currentTarget as HTMLInputElement).checked,
                })}
            />
            <strong>Shape {index + 1}</strong>
          </label>
          <div class="card-actions">
            <button
              aria-label={`Move shape ${index + 1} up`}
              disabled={index === 0}
              onclick={() => moveLayer(layer.id, -1)}>↑</button
            >
            <button
              aria-label={`Move shape ${index + 1} down`}
              disabled={index === layers.length - 1}
              onclick={() => moveLayer(layer.id, 1)}>↓</button
            >
            <button
              aria-label={`Duplicate shape ${index + 1}`}
              onclick={() => duplicateLayer(layer.id)}>⧉</button
            >
            <button
              class="remove"
              aria-label={`Remove shape ${index + 1}`}
              onclick={() => removeLayer(layer.id)}>×</button
            >
          </div>
        </div>

        <label class="field wide">
          <span>Type</span>
          <select
            value={layer.type}
            aria-label={`Shape ${index + 1} type`}
            onchange={(event) =>
              patchLayer(layer.id, {
                type: (event.currentTarget as HTMLSelectElement)
                  .value as ShapeLayerT["type"],
              })}
          >
            {#each studio.generatorShapeTypes as shapeType}
              <option value={shapeType}>{shapeType}</option>
            {/each}
          </select>
        </label>

        <div class="numeric-grid">
          {@render numField("Scale", layer.scale, 0, 4, 0.01, (v) => patchLayer(layer.id, { scale: v }))}
          {@render numField("Rotation", layer.rotation, -360, 360, 1, (v) => patchLayer(layer.id, { rotation: v }))}
          {@render numField("Offset X", layer.offset_x, -4, 4, 0.01, (v) => patchLayer(layer.id, { offset_x: v }))}
          {@render numField("Offset Y", layer.offset_y, -4, 4, 0.01, (v) => patchLayer(layer.id, { offset_y: v }))}
          {@render numField("Repeats", layer.repeat_count, 1, 24, 1, (v) => patchLayer(layer.id, { repeat_count: v }))}
          {@render numField("Repeat scale", layer.repeat_scale, 0.05, 2, 0.01, (v) => patchLayer(layer.id, { repeat_scale: v }))}
          {@render numField("Repeat rotation", layer.repeat_rotation, -360, 360, 1, (v) => patchLayer(layer.id, { repeat_rotation: v }), true)}

          {#if layer.type === "circle" || layer.type === "spiral" || layer.type === "wave"}
            {@render numField("Segments", layer.segments, 3, 360, 1, (v) => patchLayer(layer.id, { segments: v }))}
          {/if}
          {#if layer.type === "polygon"}
            {@render numField("Sides", layer.sides, 3, 24, 1, (v) => patchLayer(layer.id, { sides: v }))}
          {/if}
          {#if layer.type === "star"}
            {@render numField("Points", layer.points, 3, 24, 1, (v) => patchLayer(layer.id, { points: v }))}
            {@render numField("Inner ratio", layer.inner_ratio, 0.05, 0.95, 0.01, (v) => patchLayer(layer.id, { inner_ratio: v }))}
          {/if}
          {#if layer.type === "diamond"}
            {@render numField("Aspect", layer.aspect, 0.1, 3, 0.01, (v) => patchLayer(layer.id, { aspect: v }))}
          {/if}
          {#if layer.type === "cross"}
            {@render numField("Arm width", layer.arm_width, 0.05, 0.95, 0.01, (v) => patchLayer(layer.id, { arm_width: v }))}
          {/if}
          {#if layer.type === "spiral"}
            {@render numField("Turns", layer.turns, 0.25, 12, 0.05, (v) => patchLayer(layer.id, { turns: v }))}
          {/if}
          {#if layer.type === "wave"}
            {@render numField("Cycles", layer.cycles, 0.25, 12, 0.05, (v) => patchLayer(layer.id, { cycles: v }))}
            {@render numField("Amplitude", layer.amplitude, 0, 1, 0.01, (v) => patchLayer(layer.id, { amplitude: v }))}
          {/if}
        </div>
      </article>
    {/each}
  </section>
</div>

<style>
  .shape-field-editor {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .group {
    border-top: 1px solid var(--line);
    padding-top: 8px;
    margin-top: 4px;
  }
  .group-title {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent);
    margin-bottom: 6px;
  }
  .stack-heading,
  .card-heading,
  .card-actions,
  .enabled {
    display: flex;
    align-items: center;
  }
  .stack-heading,
  .card-heading {
    justify-content: space-between;
    gap: 8px;
  }
  .stack-heading .group-title {
    margin-bottom: 1px;
  }
  .hint,
  .empty {
    color: var(--text-dim);
    font-size: 10px;
  }
  .hint {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .stack-count {
    padding: 1px 5px;
    border: 1px solid color-mix(in srgb, var(--accent) 55%, var(--line));
    border-radius: 999px;
    color: var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .empty {
    padding: 10px;
    border: 1px dashed var(--line);
  }
  .add-shape {
    font-size: 11px;
    padding: 3px 7px;
  }
  .shape-card {
    position: relative;
    overflow: hidden;
    margin-top: 7px;
    padding: 7px;
    border: 1px solid var(--line);
    border-left: 3px solid color-mix(in srgb, var(--accent) 75%, transparent);
    border-radius: 5px;
    background:
      linear-gradient(105deg, color-mix(in srgb, var(--accent) 7%, transparent), transparent 40%),
      var(--panel-2);
    transition: border-color 120ms ease, transform 120ms ease;
  }
  .shape-card:hover {
    border-color: color-mix(in srgb, var(--accent) 55%, var(--line));
    transform: translateX(1px);
  }
  .enabled {
    gap: 6px;
    color: var(--text);
  }
  .enabled input {
    width: auto;
    margin: 0;
  }
  .card-actions {
    gap: 3px;
  }
  .card-actions button {
    min-width: 25px;
    padding: 2px 5px;
  }
  .card-actions .remove {
    color: var(--danger);
  }
  .numeric-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    margin-top: 7px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    font-size: 10px;
    color: var(--text-dim);
  }
  .field.wide {
    grid-column: 1 / -1;
    margin-top: 7px;
  }
  .field select {
    width: 100%;
  }
</style>
