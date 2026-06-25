import { isSvgFile } from "./files.js";

function assertEqual(actual: unknown, expected: unknown, label: string) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

assertEqual(isSvgFile({ name: "drawing.svg", type: "" }), true, "svg extension");
assertEqual(isSvgFile({ name: "drawing.SVG", type: "" }), true, "uppercase svg extension");
assertEqual(isSvgFile({ name: "export", type: "image/svg+xml" }), true, "svg mime");
assertEqual(isSvgFile({ name: "photo.png", type: "image/png" }), false, "png image");

console.log("file helpers ok");
