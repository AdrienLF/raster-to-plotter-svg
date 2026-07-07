<script lang="ts">
  // Guided tutorial: anchored coach-mark tooltips that walk through painting
  // a direction field for the Engraving PFM. Steps target live DOM elements
  // via [data-tour]/[data-param] anchors and auto-advance when their `done`
  // predicate turns true (polled — elements come and go with panels).
  import { studio } from "../lib/state.svelte";

  type Step = {
    target: string | null;          // CSS selector; null = centered card
    title: string;
    body: string;
    done?: () => boolean;           // auto-advance when true
    doneLabel?: string;             // what we're waiting for, shown dimmed
  };

  const STEPS: Step[] = [
    {
      target: null,
      title: "Steer lines by hand",
      body: "This tour walks you through the field system: you'll paint a grayscale mask and use it to steer the direction of Engraving lines — like combing the strokes across your image. Takes about two minutes.",
    },
    {
      target: '[data-tour="import"]',
      title: "Import an image",
      body: "Fields are sampled over your source image, so start with one. Any photo works — portraits and clouds are great.",
      done: () => !!studio.imageUrl,
      doneLabel: "waiting for an image…",
    },
    {
      target: '[data-tour="add-pf"]',
      title: "Add a path-finding layer",
      body: "Click “＋ Path finding”. This creates a layer that converts your image into pen strokes and opens its settings.",
      done: () => studio.layerStyleOpen,
      doneLabel: "waiting for the panel…",
    },
    {
      target: '[data-tour="pfm-select"]',
      title: "Choose Engraving",
      body: "In the Style dropdown pick “Engraving” (under Streamline) — or click ▦ Browse styles for previews. It shades your image with flowing lines — density follows tone, direction follows a field.",
      done: () => studio.selectedLayer?.pathfinding_style?.pfm_id === "engraving",
      doneLabel: "waiting for Engraving…",
    },
    {
      target: '[data-param="direction"] .bind',
      title: "Bind Direction to a field",
      body: "Every parameter with a ◉ button can be driven by a spatial field instead of a single number. Click the ◉ next to Direction.",
      done: () => !!document.querySelector(".binding-editor"),
      doneLabel: "waiting for the editor…",
    },
    {
      target: ".binding-editor",
      title: "Mix your field",
      body: "A field blends weighted source layers. For pure hand-steering: drag “Image tone” down to 0 and raise “Painted mask” to 1. (Tip: leave some “Edge strength” in to blend your strokes with the image's natural flow.)",
    },
    {
      target: '[data-tour="paint-btn"]',
      title: "Paint it",
      body: "Click “Paint…” — the canvas switches to a brush over your image.",
      done: () => !!studio.fieldPaint,
      doneLabel: "waiting for paint mode…",
    },
    {
      target: ".field-paint-bar",
      title: "Brightness is angle",
      body: "Paint where you want to steer: BLACK strokes make horizontal lines (0°), MID-GRAY vertical (90°), WHITE wraps back to horizontal (180°). The canvas starts neutral mid-gray. Sweep the value slider, brush a few gestures, then name the mask and hit Save.",
      done: () => !studio.fieldPaint && studio.fieldMasks.length > 0,
      doneLabel: "waiting for a saved mask…",
    },
    {
      target: '[data-tour="paint-select"]',
      title: "Pick your mask",
      body: "Back in the field editor, choose the mask you just painted in the “Painted mask” dropdown. The preview below shows the resolved angles (dark = 0°, light = 180°).",
    },
    {
      target: '[data-tour="generate"]',
      title: "Regenerate",
      body: "Apply it — the engraving lines now follow your painted angles while the image's tone still controls their density. Try Bands = 2 for crosshatched shadows.",
      done: () => studio.processing,
      doneLabel: "waiting for generate…",
    },
    {
      target: null,
      title: "That's the field system ✦",
      body: "Everything with a ◉ works this way — stipple size, dash angle, streamline density… mix image tone, noise, gradients and painted masks per parameter. The Fields guide (Help menu) has recipes and pictures.",
    },
  ];

  let rect = $state<{ x: number; y: number; w: number; h: number } | null>(null);

  const step = $derived(
    studio.tourStep !== null ? STEPS[studio.tourStep] ?? null : null,
  );
  const last = $derived(studio.tourStep === STEPS.length - 1);

  // Poll: re-anchor the tooltip (panels open/move) and check auto-advance.
  $effect(() => {
    if (!step) {
      rect = null;
      return;
    }
    const id = setInterval(() => {
      const el = step.target ? document.querySelector(step.target) : null;
      if (el) {
        const r = el.getBoundingClientRect();
        rect = r.width || r.height ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
      } else {
        rect = null;
      }
      if (step.done?.()) next();
    }, 300);
    return () => clearInterval(id);
  });

  function next() {
    if (studio.tourStep === null) return;
    if (studio.tourStep >= STEPS.length - 1) studio.tourStep = null;
    else studio.tourStep += 1;
  }
  function back() {
    if (studio.tourStep !== null && studio.tourStep > 0) studio.tourStep -= 1;
  }
  function skip() {
    studio.tourStep = null;
  }

  // Tooltip placement: below the target when there's room, else above; keep
  // inside the viewport horizontally. Centered card when no target found.
  const tipStyle = $derived.by(() => {
    if (!rect) return "left:50%;top:38%;transform:translate(-50%,-50%);";
    const W = 300;
    const margin = 10;
    const below = rect.y + rect.h + margin;
    const fitsBelow = below + 180 < window.innerHeight;
    const top = fitsBelow ? below : Math.max(margin, rect.y - margin - 180);
    let left = rect.x + rect.w / 2 - W / 2;
    left = Math.min(Math.max(margin, left), window.innerWidth - W - margin);
    return `left:${left}px;top:${top}px;`;
  });
</script>

{#if step}
  {#if rect}
    <div
      class="tour-ring"
      style:left={`${rect.x - 5}px`}
      style:top={`${rect.y - 5}px`}
      style:width={`${rect.w + 10}px`}
      style:height={`${rect.h + 10}px`}
    ></div>
  {/if}
  <div class="tour-tip" style={tipStyle} role="dialog" aria-label="Tutorial step">
    <div class="head">
      <strong>{step.title}</strong>
      <span class="count">{(studio.tourStep ?? 0) + 1}/{STEPS.length}</span>
    </div>
    <p>{step.body}</p>
    {#if step.done && !step.done()}
      <p class="waiting">{step.doneLabel ?? "waiting…"}</p>
    {/if}
    <div class="row">
      <button class="quiet" onclick={skip}>Skip tour</button>
      <div class="nav">
        {#if (studio.tourStep ?? 0) > 0}
          <button onclick={back}>Back</button>
        {/if}
        <button class="primary" onclick={next}>{last ? "Finish" : "Next"}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .tour-ring {
    position: fixed;
    z-index: 60;
    border: 2px solid var(--accent, #2e8bff);
    border-radius: 6px;
    pointer-events: none;
    box-shadow:
      0 0 0 4px color-mix(in srgb, var(--accent, #2e8bff) 25%, transparent),
      0 0 22px color-mix(in srgb, var(--accent, #2e8bff) 45%, transparent);
    animation: tour-pulse 1.6s ease-in-out infinite;
  }
  @keyframes tour-pulse {
    0%, 100% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent, #2e8bff) 25%, transparent); }
    50% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent, #2e8bff) 10%, transparent); }
  }
  .tour-tip {
    position: fixed;
    z-index: 61;
    width: 300px;
    background: var(--panel);
    border: 1px solid var(--accent, #2e8bff);
    border-radius: 8px;
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.55);
    padding: 12px 14px;
    font-size: 12px;
    line-height: 1.45;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 4px;
  }
  .count {
    color: var(--text-dim);
    font-size: 10px;
  }
  p {
    margin: 4px 0 8px;
  }
  .waiting {
    color: var(--accent, #2e8bff);
    font-size: 11px;
    font-style: italic;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .nav {
    display: flex;
    gap: 6px;
  }
  .quiet {
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px 0;
  }
  .quiet:hover {
    color: var(--text);
  }
</style>
