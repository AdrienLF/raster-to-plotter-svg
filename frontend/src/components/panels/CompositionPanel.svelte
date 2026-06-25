<script lang="ts">
  import { api } from "../../lib/api";
  import { anchorOffset, effectiveBounds, studio } from "../../lib/state.svelte";

  const layersTopFirst = $derived([...studio.composition.layers].reverse());
  const selectedBounds = $derived(
    studio.selectedLayer ? effectiveBounds(studio.selectedLayer) : null,
  );
  // Intrinsic visible (cropped, unscaled) content size.
  const contentSize = $derived.by(() => {
    const l = studio.selectedLayer;
    if (!l) return null;
    return { w: l.crop?.width || l.width, h: l.crop?.height || l.height };
  });

  async function setVisible(id: string, visible: boolean) {
    await api.patchLayer(id, { visible });
  }

  async function rename(id: string, name: string) {
    await api.patchLayer(id, { name });
  }

  async function moveSelected(axis: "x" | "y", value: number) {
    const layer = studio.selectedLayer;
    if (!layer || !Number.isFinite(value)) return;
    // Inputs show the visible position; convert back to the stored anchor.
    const off = anchorOffset(layer)[axis];
    layer[axis] = value - off;
    await api.patchLayer(layer.id, { [axis]: layer[axis] });
  }

  // Apply a new uniform scale, keeping the visible top-left corner fixed.
  async function applyScale(newScale: number) {
    const layer = studio.selectedLayer;
    if (!layer || !Number.isFinite(newScale) || newScale <= 0) return;
    const eb = effectiveBounds(layer);
    layer.scale = newScale;
    layer.x = eb.x - newScale * (layer.crop?.x || 0);
    layer.y = eb.y - newScale * (layer.crop?.y || 0);
    await api.patchLayer(layer.id, { scale: layer.scale, x: layer.x, y: layer.y });
  }

  function setWidth(value: number) {
    if (contentSize?.w) applyScale(value / contentSize.w);
  }
  function setHeight(value: number) {
    if (contentSize?.h) applyScale(value / contentSize.h);
  }

  async function remove(id: string) {
    await api.deleteLayer(id);
  }

  // Start a fresh layer: clear the target and jump to Generate to fill it.
  async function addLayer() {
    await api.newLayer();
    studio.step = "generate";
  }

  function setTool(mode: "rect" | "ellipse" | "pen") {
    studio.maskEdit = false;
    studio.maskMode = studio.maskMode === mode ? null : mode;
  }

  function toggleMaskEdit() {
    studio.maskMode = null;
    studio.maskEdit = !studio.maskEdit;
  }

  async function removeMask(id: string) {
    studio.maskMode = null;
    studio.maskEdit = false;
    await api.clearMask(id);
  }
</script>

<div class="composition col">
  <div class="topbar">
    <button class="add" onclick={addLayer}>＋ Add layer</button>
    <label class="bounds-toggle">
      <input type="checkbox" bind:checked={studio.showLayerBounds} />
      <span>Show bounds</span>
    </label>
  </div>

  {#if studio.composition.layers.length}
    <div class="layers">
      {#each layersTopFirst as layer (layer.id)}
        <div
          class="layer"
          class:active={layer.id === studio.composition.selected_layer_id}
        >
          <input
            aria-label={`Toggle ${layer.name}`}
            type="checkbox"
            checked={layer.visible}
            onchange={(e) => setVisible(layer.id, (e.target as HTMLInputElement).checked)}
          />
          <button class="pick" onclick={() => api.selectLayer(layer.id)}>
            <span>{layer.name}</span>
            <em>{Math.round(effectiveBounds(layer).width)} x {Math.round(effectiveBounds(layer).height)} mm</em>
          </button>
          <input
            class="name"
            value={layer.name}
            aria-label={`Rename ${layer.name}`}
            onchange={(e) => rename(layer.id, (e.target as HTMLInputElement).value)}
          />
          <div class="actions">
            <button title="Move up" aria-label={`Move ${layer.name} up`} onclick={() => api.moveLayer(layer.id, 1)}>↑</button>
            <button title="Move down" aria-label={`Move ${layer.name} down`} onclick={() => api.moveLayer(layer.id, -1)}>↓</button>
            <button title="Duplicate" aria-label={`Duplicate ${layer.name}`} onclick={() => api.duplicateLayer(layer.id)}>⧉</button>
            <button class="danger-text" title="Delete" aria-label={`Delete ${layer.name}`} onclick={() => remove(layer.id)}>×</button>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="empty">No layers</div>
  {/if}

  {#if studio.selectedLayer && selectedBounds}
    <div class="position">
      <div class="f">
        <label for="layer-x">X</label>
        <input
          id="layer-x"
          type="number"
          step="0.1"
          value={Math.round(selectedBounds.x * 10) / 10}
          onchange={(e) => moveSelected("x", Number((e.target as HTMLInputElement).value))}
        />
      </div>
      <div class="f">
        <label for="layer-y">Y</label>
        <input
          id="layer-y"
          type="number"
          step="0.1"
          value={Math.round(selectedBounds.y * 10) / 10}
          onchange={(e) => moveSelected("y", Number((e.target as HTMLInputElement).value))}
        />
      </div>
      <div class="f">
        <label for="layer-w">W (mm)</label>
        <input
          id="layer-w"
          type="number"
          step="0.1"
          value={Math.round(selectedBounds.width * 10) / 10}
          onchange={(e) => setWidth(Number((e.target as HTMLInputElement).value))}
        />
      </div>
      <div class="f">
        <label for="layer-h">H (mm)</label>
        <input
          id="layer-h"
          type="number"
          step="0.1"
          value={Math.round(selectedBounds.height * 10) / 10}
          onchange={(e) => setHeight(Number((e.target as HTMLInputElement).value))}
        />
      </div>
      <div class="f">
        <label for="layer-scale">Scale %</label>
        <input
          id="layer-scale"
          type="number"
          step="1"
          value={Math.round((studio.selectedLayer.scale ?? 1) * 100)}
          onchange={(e) => applyScale(Number((e.target as HTMLInputElement).value) / 100)}
        />
      </div>
    </div>

    <div class="tools">
      <div class="row">
        <span class="lbl">Crop</span>
        <button onclick={() => api.cropToContent(studio.selectedLayer!.id)}>To content</button>
        {#if studio.selectedLayer.crop}
          <button onclick={() => api.clearCrop(studio.selectedLayer!.id)}>Reset</button>
        {/if}
      </div>
      <div class="row">
        <span class="lbl">Mask</span>
        <button class:on={studio.maskMode === "rect"} onclick={() => setTool("rect")}>Rectangle</button>
        <button class:on={studio.maskMode === "ellipse"} onclick={() => setTool("ellipse")}>Oval</button>
        <button class:on={studio.maskMode === "pen"} onclick={() => setTool("pen")}>Pen</button>
        {#if studio.selectedLayer.mask}
          <button class:on={studio.maskEdit} onclick={toggleMaskEdit}>Edit</button>
          <button class="danger-text" onclick={() => removeMask(studio.selectedLayer!.id)}>Remove</button>
        {/if}
      </div>
      {#if studio.maskMode === "rect" || studio.maskMode === "ellipse"}
        <p class="hint">Drag on the canvas to draw the mask.</p>
      {:else if studio.maskMode === "pen"}
        <p class="hint">Click to add corners, click-drag for curves. Double-click or Enter to close, Esc to cancel.</p>
      {:else if studio.maskEdit}
        <p class="hint">Drag the mask box to move it, or its corners to resize.</p>
      {:else}
        <p class="hint">Drag the layer's corner handles to scale; drag the layer to move it.</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .composition {
    gap: 10px;
  }
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .add {
    padding: 4px 8px;
    font-size: 12px;
  }
  .bounds-toggle {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
  }
  .bounds-toggle input {
    width: auto;
  }
  .layers {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .layer {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr);
    gap: 6px;
    align-items: center;
    border: 1px solid var(--line);
    background: var(--panel-2);
    padding: 5px;
  }
  .layer.active {
    border-color: var(--accent);
    background: #263346;
  }
  .pick {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    min-width: 0;
    border: 0;
    background: transparent;
    padding: 0;
  }
  .pick span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pick em {
    color: var(--text-dim);
    font-size: 10px;
    font-style: normal;
  }
  .name {
    grid-column: 2;
    width: 100%;
  }
  .actions {
    grid-column: 2;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
  }
  .actions button {
    min-width: 0;
    padding: 2px 4px;
  }
  .danger-text {
    color: var(--danger);
  }
  .position {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    border-top: 1px solid var(--line);
    padding-top: 8px;
  }
  .f {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .f input {
    width: 100%;
  }
  .empty {
    color: var(--text-dim);
    font-size: 12px;
    padding: 6px 0;
  }
  .tools {
    display: flex;
    flex-direction: column;
    gap: 6px;
    border-top: 1px solid var(--line);
    padding-top: 8px;
  }
  .tools .row {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tools .lbl {
    width: 40px;
    color: var(--text-dim);
    font-size: 11px;
  }
  .tools button {
    flex: 1;
    min-width: 0;
    padding: 3px 4px;
    font-size: 11px;
  }
  .tools button.on {
    border-color: var(--accent);
    background: #263346;
  }
  .hint {
    margin: 0;
    color: var(--text-dim);
    font-size: 10px;
    line-height: 1.4;
  }
</style>
