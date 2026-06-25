import {
  A4_PORTRAIT,
  alignPlacement,
  parseSvgSizeMm,
  snapPlacement,
} from "./placement.js";

function assertEqual(actual: unknown, expected: unknown, label: string) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assertClose(actual: number | null, expected: number, label: string) {
  if (actual === null || Math.abs(actual - expected) > 0.001) {
    throw new Error(`${label}: expected ${expected}, got ${String(actual)}`);
  }
}

const sheet = { w: 297, h: 420 };
const drawing = { w: 80, h: 60 };

const snapped = snapPlacement(
  { x: 107, y: 147 },
  drawing,
  sheet,
  A4_PORTRAIT,
  4,
);
assertClose(snapped.x, 108.5, "snap drawing center to A4 center x");
assertClose(snapped.y, 148.5, "snap drawing top to A4 middle y");
assertClose(snapped.guideX, 148.5, "snap guide x");
assertClose(snapped.guideY, 148.5, "snap guide y");

const centered = alignPlacement("center_h", { x: 0, y: 0 }, drawing, sheet);
assertClose(centered.x, 108.5, "center align x");
assertClose(centered.y, 0, "center align preserves y");

const bottom = alignPlacement("bottom", { x: 12, y: 0 }, drawing, sheet);
assertClose(bottom.x, 12, "bottom align preserves x");
assertClose(bottom.y, 360, "bottom align y");

const parsed = parseSvgSizeMm(
  '<svg xmlns="http://www.w3.org/2000/svg" width="21cm" height="297mm" viewBox="0 0 210 297"></svg>',
  { w: 297, h: 420 },
);
assertEqual(parsed.w, 210, "cm width parses to mm");
assertEqual(parsed.h, 297, "mm height parses");

console.log("placement helpers ok");
