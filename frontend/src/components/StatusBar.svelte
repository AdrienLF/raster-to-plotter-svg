<script lang="ts">
  import { studio } from "../lib/state.svelte";

  const gpu = $derived(studio.backend.startsWith("torch"));
  const lastLog = $derived(studio.log[studio.log.length - 1] ?? "");
  const isError = $derived(/error|failed|unavailable/i.test(studio.status));

  function fmtSeconds(value: number | null | undefined) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    const total = Math.max(0, Math.round(value));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }
</script>

<div class="status">
  <span class="badge" class:gpu>{gpu ? "GPU" : "CPU"} · {studio.backend}</span>
  <span class="state" class:err={isError} title={studio.status}>{studio.status}</span>
  {#if studio.processing || studio.plotting}
    <div class="bar"><div class="fill" style:width={`${studio.progress * 100}%`}></div></div>
  {/if}
  <div class="spacer"></div>
  {#if studio.plotting && studio.plotProgress}
    <span class="muted">elapsed {fmtSeconds(studio.plotProgress.elapsed_seconds)}</span>
    <span class="muted">left {fmtSeconds(studio.plotProgress.remaining_seconds)}</span>
    <span class="muted">{studio.plotProgress.shapes_done.toLocaleString()} / {studio.plotProgress.shapes_total.toLocaleString()} shapes</span>
  {:else if studio.stats}
    <span class="muted">{studio.stats.total.toLocaleString()} shapes</span>
    <span class="muted">· {studio.stats.length_mm.toLocaleString()} mm</span>
  {/if}
  <span class="log muted">{lastLog}</span>
</div>

<style>
  .status {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--header);
    border-top: 1px solid var(--line);
    height: 100%;
    padding: 0 10px;
    font-size: 11px;
  }
  .badge {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 1px 6px;
  }
  .badge.gpu {
    border-color: var(--ok);
    color: var(--ok);
  }
  .state {
    color: var(--text);
    max-width: 420px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .state.err {
    color: var(--danger, #ff6b6b);
    font-weight: 600;
  }
  .bar {
    width: 140px;
    height: 6px;
    background: var(--panel-2);
    border-radius: 3px;
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.15s;
  }
  .log {
    max-width: 360px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
