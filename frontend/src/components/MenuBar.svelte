<script lang="ts">
  import { studio } from "../lib/state.svelte";
  import { api } from "../lib/api";

  let { onImport, onPlot }: { onImport: () => void; onPlot: () => void } = $props();

  // Controlled menus: only one open at a time; clicking an item or anywhere
  // outside closes them, and Escape closes too.
  let open = $state<string | null>(null);

  function toggle(id: string) {
    open = open === id ? null : id;
  }
  function close() {
    open = null;
  }
  // Run a menu action and close the menu.
  function run(fn: () => void) {
    close();
    fn();
  }

  function exportSvg(split: boolean) {
    void api.exportSvg(split);
  }

  async function newProject() {
    const name = window.prompt("New project name", "Untitled");
    if (name === null) return;
    await api.newProject(name.trim() || "Untitled");
  }
  async function renameCurrent() {
    const cur = studio.currentProject;
    if (!cur) return;
    const name = window.prompt("Rename project", cur.name);
    if (name === null) return;
    await api.renameProject(cur.id, name.trim() || cur.name);
  }
  async function deleteCurrent() {
    const cur = studio.currentProject;
    if (!cur) return;
    if (!window.confirm(`Delete project “${cur.name}”? This cannot be undone.`)) return;
    await api.deleteProject(cur.id);
  }
</script>

<svelte:window onclick={close} onkeydown={(e) => e.key === "Escape" && close()} />

<div class="menubar">
  <span class="brand">✦ PlotterForge</span>

  <div class="menu" class:open={open === "file"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("file");
      }}
      onmouseenter={() => open && (open = "file")}
    >
      File
    </button>
    {#if open === "file"}
      <div class="items">
        <button onclick={() => run(onImport)}>Import image…</button>
        <button disabled={!studio.hasVisibleLayers} onclick={() => run(() => exportSvg(false))}>Export SVG</button>
        <button disabled={!studio.hasVisibleLayers} onclick={() => run(() => exportSvg(true))}>Export layers (zip)</button>
      </div>
    {/if}
  </div>

  <div class="menu" class:open={open === "edit"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("edit");
      }}
      onmouseenter={() => open && (open = "edit")}
    >
      Edit
    </button>
    {#if open === "edit"}
      <div class="items">
        <button onclick={() => run(() => void api.undoComposition())}>Undo layer change <span class="shortcut">⌘Z</span></button>
      </div>
    {/if}
  </div>

  <div class="menu" class:open={open === "project"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("project");
      }}
      onmouseenter={() => open && (open = "project")}
    >
      Project
    </button>
    {#if open === "project"}
      <div class="items">
        <button onclick={() => run(() => void newProject())}>New project…</button>
        <button onclick={() => run(() => void renameCurrent())} disabled={!studio.currentProject}>Rename current…</button>
        <button class="danger-text" onclick={() => run(() => void deleteCurrent())} disabled={!studio.currentProject}>Delete current…</button>
        {#if studio.projects.length}
          <div class="sep"></div>
          <div class="label">Open</div>
          <div class="list">
            {#each studio.projects as p (p.id)}
              <button
                class:current={p.id === studio.currentProject?.id}
                onclick={() => run(() => void api.openProject(p.id))}
              >
                {p.id === studio.currentProject?.id ? "● " : ""}{p.name}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <div class="menu" class:open={open === "drawing"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("drawing");
      }}
      onmouseenter={() => open && (open = "drawing")}
    >
      Drawing
    </button>
    {#if open === "drawing"}
      <div class="items">
        <button disabled={!studio.selectedLayer || studio.processing} onclick={() => run(() => void api.generateLayerPathfinding(studio.selectedLayer!.id))}>Regenerate selected layer</button>
        <button disabled={!studio.hasVisibleLayers} onclick={() => run(onPlot)}>Plot…</button>
      </div>
    {/if}
  </div>

  <div class="menu" class:open={open === "view"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("view");
      }}
      onmouseenter={() => open && (open = "view")}
    >
      View
    </button>
    {#if open === "view"}
      <div class="items">
        <button
          aria-pressed={studio.showGuides}
          onclick={() => run(() => (studio.showGuides = !studio.showGuides))}
        >
          <span class="check">{studio.showGuides ? "✓" : ""}</span>Show guides
        </button>
        <button
          aria-pressed={studio.showLayerBounds}
          onclick={() => run(() => (studio.showLayerBounds = !studio.showLayerBounds))}
        >
          <span class="check">{studio.showLayerBounds ? "✓" : ""}</span>Show bounds
        </button>
        <button
          aria-pressed={studio.showPenPreview}
          onclick={() => run(() => (studio.showPenPreview = !studio.showPenPreview))}
          title="Off: draw every stroke as a uniform thin line, ignoring pen width and nib"
        >
          <span class="check">{studio.showPenPreview ? "✓" : ""}</span>Pen width &amp; nib
        </button>
      </div>
    {/if}
  </div>

  <div class="menu" class:open={open === "help"}>
    <button
      class="summary"
      onclick={(e) => {
        e.stopPropagation();
        toggle("help");
      }}
      onmouseenter={() => open && (open = "help")}
    >
      Help
    </button>
    {#if open === "help"}
      <div class="items">
        <button onclick={() => run(() => window.open("/static/docs/index.html", "_blank"))}>User manual</button>
        <button onclick={() => run(() => (studio.tourStep = 0))}>✦ Tutorial: paint a direction field</button>
        <button onclick={() => run(() => window.open("/static/docs/fields.html", "_blank"))}>Fields guide (docs)</button>
      </div>
    {/if}
  </div>

  <div class="spacer"></div>
  <span class="doc muted">{studio.currentProject?.name ?? "—"}</span>
  <span class="doc muted dim">· {studio.imageName || "no image"}</span>
</div>

<style>
  .menubar {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--header);
    border-bottom: 1px solid var(--line);
    height: 100%;
    padding: 0 8px;
  }
  .brand {
    font-weight: 700;
    color: var(--accent);
    margin-right: 12px;
  }
  .menu {
    position: relative;
  }
  .summary {
    list-style: none;
    cursor: pointer;
    padding: 3px 9px;
    border-radius: 4px;
    background: none;
    border: none;
    color: inherit;
    font: inherit;
  }
  .menu.open .summary {
    background: var(--accent);
    color: white;
  }
  .items {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: 30;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 5px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    min-width: 180px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  }
  .items button {
    background: none;
    border: none;
    text-align: left;
    padding: 6px 8px;
    border-radius: 4px;
  }
  .items button:hover:not(:disabled) {
    background: var(--accent);
    color: white;
  }
  .items .danger-text {
    color: var(--danger);
  }
  .check {
    display: inline-block;
    width: 14px;
  }
  .shortcut {
    float: right;
    color: var(--text-dim);
    margin-left: 14px;
  }
  .sep {
    height: 1px;
    background: var(--line);
    margin: 4px 0;
  }
  .label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-dim);
    padding: 2px 8px;
  }
  .list {
    display: flex;
    flex-direction: column;
    max-height: 240px;
    overflow-y: auto;
  }
  .list .current {
    color: var(--accent);
  }
  .doc {
    font-size: 12px;
  }
  .doc.dim {
    color: var(--text-dim);
  }
</style>
