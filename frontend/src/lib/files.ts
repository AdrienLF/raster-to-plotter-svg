export interface FileLike {
  name: string;
  type?: string;
}

export function isSvgFile(file: FileLike) {
  const type = (file.type ?? "").toLowerCase();
  return type === "image/svg+xml" || file.name.toLowerCase().endsWith(".svg");
}
