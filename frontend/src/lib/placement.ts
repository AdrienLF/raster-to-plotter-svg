export interface SizeMm {
  w: number;
  h: number;
}

export interface PlacementMm {
  x: number;
  y: number;
}

export interface SnapResult extends PlacementMm {
  guideX: number | null;
  guideY: number | null;
}

export type AlignMode = "left" | "center_h" | "right" | "top" | "center_v" | "bottom";

export const A4_PORTRAIT: SizeMm = { w: 210, h: 297 };
export const A3_PORTRAIT: SizeMm = { w: 297, h: 420 };

export const PAPER_PRESETS = [
  { id: "a5", label: "A5", w: 148, h: 210 },
  { id: "a4", label: "A4", w: 210, h: 297 },
  { id: "a3", label: "A3", w: 297, h: 420 },
] as const;

function uniq(values: number[]) {
  return [...new Set(values.map((v) => Number(v.toFixed(3))))];
}

export function snapLines(sheet: SizeMm, guide: SizeMm = A4_PORTRAIT) {
  return {
    x: uniq([0, sheet.w / 2, sheet.w, guide.w / 2, guide.w].filter((v) => v <= sheet.w)),
    y: uniq([0, sheet.h / 2, sheet.h, guide.h / 2, guide.h].filter((v) => v <= sheet.h)),
  };
}

export function clampPlacement(pos: PlacementMm, drawing: SizeMm, sheet: SizeMm): PlacementMm {
  return {
    x: clamp(pos.x, 0, Math.max(0, sheet.w - drawing.w)),
    y: clamp(pos.y, 0, Math.max(0, sheet.h - drawing.h)),
  };
}

export function snapPlacement(
  pos: PlacementMm,
  drawing: SizeMm,
  sheet: SizeMm,
  guide: SizeMm = A4_PORTRAIT,
  threshold = 4,
): SnapResult {
  const lines = snapLines(sheet, guide);
  const sx = snapAxis(pos.x, drawing.w, lines.x, threshold);
  const sy = snapAxis(pos.y, drawing.h, lines.y, threshold);
  const clamped = clampPlacement({ x: sx.value, y: sy.value }, drawing, sheet);
  return {
    x: clamped.x,
    y: clamped.y,
    guideX: sx.line,
    guideY: sy.line,
  };
}

export function alignPlacement(
  mode: AlignMode,
  pos: PlacementMm,
  drawing: SizeMm,
  sheet: SizeMm,
): PlacementMm {
  let { x, y } = pos;
  if (mode === "left") x = 0;
  if (mode === "center_h") x = (sheet.w - drawing.w) / 2;
  if (mode === "right") x = sheet.w - drawing.w;
  if (mode === "top") y = 0;
  if (mode === "center_v") y = (sheet.h - drawing.h) / 2;
  if (mode === "bottom") y = sheet.h - drawing.h;
  return clampPlacement({ x, y }, drawing, sheet);
}

export function parseSvgSizeMm(svgString: string, fallback: SizeMm): SizeMm {
  const tag = svgString.match(/<svg\b[^>]*>/i)?.[0] ?? "";
  const width = attr(tag, "width");
  const height = attr(tag, "height");
  return {
    w: toMm(width, fallback.w),
    h: toMm(height, fallback.h),
  };
}

function snapAxis(pos: number, size: number, lines: number[], threshold: number) {
  const checks = [pos, pos + size / 2, pos + size];
  let bestDistance = threshold;
  let value = pos;
  let line: number | null = null;
  for (const target of lines) {
    for (const check of checks) {
      const distance = Math.abs(check - target);
      if (distance < bestDistance) {
        bestDistance = distance;
        value = pos + target - check;
        line = target;
      }
    }
  }
  return { value, line };
}

function attr(tag: string, name: string) {
  const m = tag.match(new RegExp(`${name}\\s*=\\s*["']([^"']+)["']`, "i"));
  return m?.[1] ?? null;
}

function toMm(value: string | null, fallback: number) {
  if (!value) return fallback;
  const raw = value.trim();
  const numeric = Number.parseFloat(raw);
  if (!Number.isFinite(numeric)) return fallback;
  const unit = raw.match(/[a-z%]+$/i)?.[0]?.toLowerCase() ?? "px";
  const factors: Record<string, number> = {
    mm: 1,
    cm: 10,
    in: 25.4,
    px: 25.4 / 96,
    pt: 25.4 / 72,
    pc: 25.4 / 6,
  };
  return Number((numeric * (factors[unit] ?? factors.px)).toFixed(3));
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
