<script lang="ts">
  import { studio } from "../../lib/state.svelte";
  import type { ShapeLayerT } from "../../lib/types";

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

  function numeric(event: Event) {
    return Number((event.currentTarget as HTMLInputElement).value);
  }
</script>

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
          <label class="field">
            <span>Scale</span>
            <input
              type="number"
              min="0"
              max="4"
              step="0.01"
              value={layer.scale}
              aria-label={`Shape ${index + 1} scale`}
              onchange={(event) => patchLayer(layer.id, { scale: numeric(event) })}
            />
          </label>
          <label class="field">
            <span>Rotation</span>
            <input
              type="number"
              min="-360"
              max="360"
              step="1"
              value={layer.rotation}
              aria-label={`Shape ${index + 1} rotation`}
              onchange={(event) => patchLayer(layer.id, { rotation: numeric(event) })}
            />
          </label>
          <label class="field">
            <span>Offset X</span>
            <input
              type="number"
              min="-4"
              max="4"
              step="0.01"
              value={layer.offset_x}
              aria-label={`Shape ${index + 1} offset X`}
              onchange={(event) => patchLayer(layer.id, { offset_x: numeric(event) })}
            />
          </label>
          <label class="field">
            <span>Offset Y</span>
            <input
              type="number"
              min="-4"
              max="4"
              step="0.01"
              value={layer.offset_y}
              aria-label={`Shape ${index + 1} offset Y`}
              onchange={(event) => patchLayer(layer.id, { offset_y: numeric(event) })}
            />
          </label>
          <label class="field">
            <span>Repeats</span>
            <input
              type="number"
              min="1"
              max="24"
              step="1"
              value={layer.repeat_count}
              aria-label={`Shape ${index + 1} repeats`}
              onchange={(event) =>
                patchLayer(layer.id, { repeat_count: numeric(event) })}
            />
          </label>
          <label class="field">
            <span>Repeat scale</span>
            <input
              type="number"
              min="0.05"
              max="2"
              step="0.01"
              value={layer.repeat_scale}
              aria-label={`Shape ${index + 1} repeat scale`}
              onchange={(event) =>
                patchLayer(layer.id, { repeat_scale: numeric(event) })}
            />
          </label>
          <label class="field wide">
            <span>Repeat rotation</span>
            <input
              type="number"
              min="-360"
              max="360"
              step="1"
              value={layer.repeat_rotation}
              aria-label={`Shape ${index + 1} repeat rotation`}
              onchange={(event) =>
                patchLayer(layer.id, { repeat_rotation: numeric(event) })}
            />
          </label>

          {#if layer.type === "circle" || layer.type === "spiral" || layer.type === "wave"}
            <label class="field">
              <span>Segments</span>
              <input
                type="number"
                min="3"
                max="360"
                step="1"
                value={layer.segments}
                aria-label={`Shape ${index + 1} segments`}
                onchange={(event) => patchLayer(layer.id, { segments: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "polygon"}
            <label class="field">
              <span>Sides</span>
              <input
                type="number"
                min="3"
                max="24"
                step="1"
                value={layer.sides}
                aria-label={`Shape ${index + 1} sides`}
                onchange={(event) => patchLayer(layer.id, { sides: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "star"}
            <label class="field">
              <span>Points</span>
              <input
                type="number"
                min="3"
                max="24"
                step="1"
                value={layer.points}
                aria-label={`Shape ${index + 1} points`}
                onchange={(event) => patchLayer(layer.id, { points: numeric(event) })}
              />
            </label>
            <label class="field">
              <span>Inner ratio</span>
              <input
                type="number"
                min="0.05"
                max="0.95"
                step="0.01"
                value={layer.inner_ratio}
                aria-label={`Shape ${index + 1} inner ratio`}
                onchange={(event) =>
                  patchLayer(layer.id, { inner_ratio: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "diamond"}
            <label class="field">
              <span>Aspect</span>
              <input
                type="number"
                min="0.1"
                max="3"
                step="0.01"
                value={layer.aspect}
                aria-label={`Shape ${index + 1} aspect`}
                onchange={(event) => patchLayer(layer.id, { aspect: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "cross"}
            <label class="field">
              <span>Arm width</span>
              <input
                type="number"
                min="0.05"
                max="0.95"
                step="0.01"
                value={layer.arm_width}
                aria-label={`Shape ${index + 1} arm width`}
                onchange={(event) =>
                  patchLayer(layer.id, { arm_width: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "spiral"}
            <label class="field">
              <span>Turns</span>
              <input
                type="number"
                min="0.25"
                max="12"
                step="0.05"
                value={layer.turns}
                aria-label={`Shape ${index + 1} turns`}
                onchange={(event) => patchLayer(layer.id, { turns: numeric(event) })}
              />
            </label>
          {/if}
          {#if layer.type === "wave"}
            <label class="field">
              <span>Cycles</span>
              <input
                type="number"
                min="0.25"
                max="12"
                step="0.05"
                value={layer.cycles}
                aria-label={`Shape ${index + 1} cycles`}
                onchange={(event) => patchLayer(layer.id, { cycles: numeric(event) })}
              />
            </label>
            <label class="field">
              <span>Amplitude</span>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={layer.amplitude}
                aria-label={`Shape ${index + 1} amplitude`}
                onchange={(event) => patchLayer(layer.id, { amplitude: numeric(event) })}
              />
            </label>
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
  .field input,
  .field select {
    width: 100%;
  }
</style>
