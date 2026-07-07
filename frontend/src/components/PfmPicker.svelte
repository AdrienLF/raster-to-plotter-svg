<script lang="ts">
  // Visual PFM chooser: a grid of pre-rendered previews (one per module,
  // /static/pfm-previews/<id>.png — same tonal study image for all, so the
  // algorithms compare honestly). Complements the dropdown, doesn't replace it.
  let {
    current,
    groups,
    onPick,
    onClose,
  }: {
    current: string;
    groups: { label: string; items: { id: string; label: string }[] }[];
    onPick: (id: string) => void;
    onClose: () => void;
  } = $props();

  function pick(id: string) {
    onPick(id);
    onClose();
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onClose()} />

<section class="pfm-picker" role="dialog" aria-label="Choose a path finding module">
  <header>
    <strong>Choose a style</strong>
    <span class="hint">every preview: the same shaded sphere</span>
    <button aria-label="Close" onclick={onClose}>✕</button>
  </header>
  <div class="body">
    {#each groups as group (group.label)}
      <div class="family">
        <div class="family-title">{group.label}</div>
        <div class="grid">
          {#each group.items as item (item.id)}
            <button
              class="cell"
              class:current={item.id === current}
              title={item.label}
              onclick={() => pick(item.id)}
            >
              <img
                src={`/static/pfm-previews/${item.id}.png`}
                alt={item.label}
                loading="lazy"
                onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")}
              />
              <span>{item.label}</span>
            </button>
          {/each}
        </div>
      </div>
    {/each}
  </div>
</section>

<style>
  .pfm-picker {
    position: fixed;
    right: 652px;
    top: 92px;
    z-index: 40;
    width: min(560px, calc(100vw - 360px));
    max-height: calc(100vh - 120px);
    display: flex;
    flex-direction: column;
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.5);
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border-bottom: 1px solid var(--line);
  }
  .hint {
    color: var(--text-dim);
    font-size: 11px;
    flex: 1;
  }
  .body {
    overflow-y: auto;
    padding: 10px;
  }
  .family-title {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-dim);
    margin: 10px 0 6px;
  }
  .family:first-child .family-title {
    margin-top: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 8px;
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 5px;
    background: none;
    border: 1px solid var(--line);
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
  }
  .cell:hover {
    border-color: var(--accent);
  }
  .cell.current {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }
  .cell img {
    width: 100%;
    aspect-ratio: 105 / 148;
    object-fit: cover;
    border-radius: 3px;
    background: white;
  }
  .cell span {
    font-size: 10px;
    line-height: 1.25;
    color: var(--text);
  }
  @media (max-width: 1280px) {
    .pfm-picker {
      right: auto;
      left: 12px;
    }
  }
</style>
