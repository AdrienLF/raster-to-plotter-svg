import type {
  AreaT,
  CompositionLayerT,
  CompositionT,
  DrawingSetT,
  Param,
  PlacementMm,
  PlotEstimate,
  PlotJob,
  PlotProgress,
  PfmInfo,
  RegionT,
  Stats,
  VersionT,
} from "./types";

// Single runes-based store shared across the app.
class Studio {
  // image
  imageUrl = $state<string | null>(null);
  imageName = $state("");
  imageW = $state(0);
  imageH = $state(0);

  // backend
  backend = $state("…");

  // projects
  projects = $state<{ id: string; name: string }[]>([]);
  currentProject = $state<{ id: string; name: string } | null>(null);

  // path finding
  pfms = $state<PfmInfo[]>([]);
  pfmId = $state("voronoi_stippling");
  schema = $state<Param[]>([]);
  params = $state<Record<string, any>>({});

  // generate step
  generators = $state<{ id: string; name: string }[]>([]);
  generatorId = $state("spokes_and_circles");
  genSchema = $state<Param[]>([]);
  genParams = $state<Record<string, any>>({});
  autoRedraw = $state(true);

  // drawing area
  area = $state<AreaT | null>(null);
  presets = $state<Record<string, [number, number]>>({});

  // composition
  composition = $state<CompositionT>({
    page: { width: 297, height: 420, units: "mm" },
    selected_layer_id: null,
    layers: [],
  });
  showLayerBounds = $state(true);
  layerStyleOpen = $state(false);
  layerStyleSchema = $state<Param[]>([]);
  // Active mask-drawing tool (composition step). null = not drawing.
  maskMode = $state<null | "rect" | "ellipse" | "pen">(null);
  // When true, on-canvas handles edit the selected layer's mask instead of
  // scaling the layer.
  maskEdit = $state(false);

  // source-image AI regions
  regions = $state<RegionT[]>([]);
  selectedRegionId = $state<string | null>(null);
  regionDraftMask = $state<string | null>(null);
  regionDraftBbox = $state<{ x: number; y: number; width: number; height: number } | null>(null);
  regionPositivePoints = $state<{ x: number; y: number }[]>([]);
  regionNegativePoints = $state<{ x: number; y: number }[]>([]);
  regionSelecting = $state(false);
  regionPredicting = $state(false);
  segmentationStatus = $state<Record<string, any> | null>(null);

  // pens
  drawingSet = $state<DrawingSetT | null>(null);
  libraries = $state<string[]>([]);

  // versions
  versions = $state<VersionT[]>([]);

  // active workspace step
  step = $state<"pathfinding" | "generate" | "composition" | "plot">("pathfinding");

  // plotter / machine
  settings = $state<Record<string, any> | null>(null);
  machineStatus = $state("");
  placement = $state<PlacementMm>({ x: 0, y: 0 });
  plotEstimate = $state<PlotEstimate | null>(null);
  plotJob = $state<PlotJob | null>(null);
  plotProgress = $state<PlotProgress | null>(null);
  plotterTab = $state("estimate");

  // preview + status
  previewSvg = $state<string | null>(null);
  stats = $state<Stats | null>(null);
  status = $state("Idle");
  progress = $state(0);
  processing = $state(false);
  plotting = $state(false);
  exporting = $state(false);
  log = $state<string[]>([]);

  pfmName = $derived(
    this.pfms.find((p) => p.id === this.pfmId)?.name ?? this.pfmId,
  );
  selectedLayer = $derived<CompositionLayerT | null>(
    this.composition.layers.find((layer) => layer.id === this.composition.selected_layer_id) ??
      this.composition.layers.at(-1) ??
      null,
  );
  selectedRegion = $derived<RegionT | null>(
    this.regions.find((region) => region.id === this.selectedRegionId) ?? null,
  );
  hasVisibleLayers = $derived(this.composition.layers.some((layer) => layer.visible));
}

export const studio = new Studio();

// Layer bounds on the page, accounting for an active crop and scale. Mirrors
// engine.composition.effective_bounds on the backend.
export function effectiveBounds(layer: CompositionLayerT) {
  const s = layer.scale || 1;
  const c = layer.crop;
  const cx = c?.x || 0;
  const cy = c?.y || 0;
  const cw = c?.width || layer.width;
  const ch = c?.height || layer.height;
  return {
    x: layer.x + s * cx,
    y: layer.y + s * cy,
    width: s * cw,
    height: s * ch,
  };
}

// Offset between a layer's visible top-left and its stored anchor (layer.x/y).
export function anchorOffset(layer: CompositionLayerT) {
  const s = layer.scale || 1;
  return { x: s * (layer.crop?.x || 0), y: s * (layer.crop?.y || 0) };
}

export function pushLog(msg: string) {
  const t = new Date().toLocaleTimeString();
  studio.log = [...studio.log.slice(-200), `${t}  ${msg}`];
}

// Surface a failure with a human/LLM-useful message instead of a bare "Error".
// Sets the status line to "<context>: <detail>" and logs it. `context` should
// describe the action (e.g. "Layer pathfinding error").
export function reportError(context: string, error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  const text = detail && detail !== context ? `${context}: ${detail}` : context || "Error";
  studio.status = text;
  pushLog("⚠ " + text);
  return text;
}
