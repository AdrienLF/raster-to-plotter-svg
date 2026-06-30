<script lang="ts">
  // Number input with slim custom up/down steppers. The native browser spinners
  // are hidden (they're oversized and cover the digits in narrow fields); the
  // ▲/▼ buttons dock at the right edge without overlapping the value.
  //
  // Works both bound (`bind:value`) and controlled (`value={…} onchange={…}`).
  // The `class` prop is applied to the inner <input> so existing selectors and
  // styles (e.g. `.numbox`) keep working; extra attrs (id, title, aria-label,
  // disabled, placeholder) are forwarded to the input too.
  let {
    value = $bindable(),
    min,
    max,
    step = 1,
    title,
    onchange,
    class: inputClass = "",
    ...rest
  }: {
    value?: number;
    min?: number;
    max?: number;
    step?: number;
    title?: string;
    onchange?: (v: number) => void;
    class?: string;
    [key: string]: unknown;
  } = $props();

  const fullValue = $derived(Number.isFinite(value) ? String(value) : "");
  const inputTitle = $derived(title && fullValue ? `${title}: ${fullValue}` : title ?? fullValue);

  function commit(v: number) {
    if (!Number.isFinite(v)) return;
    value = v;
    onchange?.(v);
  }

  function bump(dir: number) {
    const s = step || 1;
    const cur = Number.isFinite(value as number) ? (value as number) : 0;
    let next = cur + dir * s;
    // snap to the step grid so floats stay clean (0.1 + 0.2 → 0.3, not 0.30000004)
    next = Math.round(next / s) * s;
    if (typeof min === "number") next = Math.max(min, next);
    if (typeof max === "number") next = Math.min(max, next);
    commit(Number(next.toFixed(6)));
  }
</script>

<span class="numstep">
  <input
    class={inputClass}
    type="number"
    {min}
    {max}
    {step}
    {value}
    title={inputTitle}
    oninput={(e) => (value = (e.currentTarget as HTMLInputElement).valueAsNumber)}
    onchange={(e) => commit((e.currentTarget as HTMLInputElement).valueAsNumber)}
    {...rest}
  />
  <span class="arrows">
    <button type="button" tabindex="-1" aria-label="Increase" onclick={() => bump(1)}>▲</button>
    <button type="button" tabindex="-1" aria-label="Decrease" onclick={() => bump(-1)}>▼</button>
  </span>
</span>

<style>
  .numstep {
    position: relative;
    display: inline-flex;
    width: 100%;
    min-width: 0;
  }
  .numstep input {
    width: 100%;
    min-width: 0;
    padding-right: 15px; /* room for the steppers */
    -moz-appearance: textfield;
    appearance: textfield;
  }
  .numstep input::-webkit-outer-spin-button,
  .numstep input::-webkit-inner-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  .arrows {
    position: absolute;
    top: 1px;
    bottom: 1px;
    right: 1px;
    display: flex;
    flex-direction: column;
    width: 13px;
    pointer-events: none; /* let the input keep the rest of the row */
  }
  .arrows button {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: none;
    border-radius: 2px;
    background: transparent;
    color: var(--text-dim);
    font-size: 6px;
    line-height: 1;
    cursor: pointer;
    pointer-events: auto;
  }
  .arrows button:hover {
    color: var(--text);
    background: color-mix(in srgb, var(--accent) 25%, transparent);
  }
</style>
