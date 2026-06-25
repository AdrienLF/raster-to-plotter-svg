import type {
  AreaT,
  DrawingSetT,
  Param,
  PlacementMm,
  PlotEstimate,
  PlotJob,
  PlotProgress,
  PfmInfo,
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

  // path finding
  pfms = $state<PfmInfo[]>([]);
  pfmId = $state("voronoi_stippling");
  schema = $state<Param[]>([]);
  params = $state<Record<string, any>>({});

  // drawing area
  area = $state<AreaT | null>(null);
  presets = $state<Record<string, [number, number]>>({});

  // pens
  drawingSet = $state<DrawingSetT | null>(null);
  libraries = $state<string[]>([]);

  // versions
  versions = $state<VersionT[]>([]);

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
  log = $state<string[]>([]);

  pfmName = $derived(
    this.pfms.find((p) => p.id === this.pfmId)?.name ?? this.pfmId,
  );
}

export const studio = new Studio();

export function pushLog(msg: string) {
  const t = new Date().toLocaleTimeString();
  studio.log = [...studio.log.slice(-200), `${t}  ${msg}`];
}
