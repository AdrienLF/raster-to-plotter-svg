<script lang="ts">
  import type { FieldBinding, Param } from "../lib/types";
  import NumStep from "./NumStep.svelte";

  let {
    param,
    value = $bindable(),
    binding = null,
    onEditBinding = null,
  }: {
    param: Param;
    value: any;
    binding?: FieldBinding | null;
    onEditBinding?: (() => void) | null;
  } = $props();

  const isNumeric = $derived(
    param.type === "float" || param.type === "int" || param.type === "angle",
  );
  const canBindField = $derived(Boolean(param.bindable && onEditBinding));
  const bound = $derived(Boolean(binding));
</script>

<div class="ctrl" data-param={param.name}>
  {#if param.type === "bool"}
    <label class="bool" title={param.help}>
      <input type="checkbox" bind:checked={value} />
      <span>{param.label}</span>
    </label>
  {:else}
    <div class="label-row">
      <label for={param.name} title={param.help}>{param.label}</label>
      {#if canBindField}
        <button
          type="button"
          class="bind"
          class:bound
          title={bound
            ? "This value is driven by a spatial field — click to edit the field"
            : "Drive this value with a spatial field (image tone, noise, gradients, painted mask)"}
          onclick={() => onEditBinding?.()}
        >◉ {bound ? "field ✓" : "field"}</button>
      {/if}
    </div>
    {#if param.type === "enum"}
      <select id={param.name} bind:value>
        {#each param.choices ?? [] as opt}
          <option value={opt}>{opt}</option>
        {/each}
      </select>
    {:else if isNumeric}
      <div class="num">
        {#if param.min !== null && param.max !== null}
          <input
            type="range"
            min={param.min}
            max={param.max}
            step={param.step ?? (param.type === "int" ? 1 : 0.01)}
            bind:value
            disabled={bound}
          />
        {/if}
        <NumStep
          class="numbox"
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          step={param.step ?? (param.type === "int" ? 1 : 0.01)}
          bind:value
          disabled={bound}
        />
      </div>
    {/if}
  {/if}
</div>

<style>
  .ctrl {
    display: grid;
    grid-template-columns: 1fr;
    gap: 3px;
    margin-bottom: 8px;
  }
  label {
    font-size: 11px;
  }
  .label-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }
  .bind {
    border: 1px solid var(--line);
    border-radius: 9px;
    background: transparent;
    color: var(--text-dim, #888);
    font-size: 10px;
    line-height: 1;
    padding: 3px 8px;
    cursor: pointer;
    white-space: nowrap;
  }
  .bind:hover {
    border-color: var(--accent, #6cf);
    color: var(--text);
  }
  .bind.bound {
    color: white;
    background: var(--accent, #2e8bff);
    border-color: var(--accent, #2e8bff);
  }
  .bool {
    display: flex;
    align-items: center;
    gap: 7px;
    cursor: pointer;
  }
  .bool input {
    width: auto;
    margin: 0;
    flex: none;
  }
  .bool span {
    color: var(--text);
  }
  .num {
    display: grid;
    grid-template-columns: 1fr 56px;
    gap: 6px;
    align-items: center;
  }
  .num input[disabled] {
    opacity: 0.4;
  }
  select {
    width: 100%;
  }
</style>
