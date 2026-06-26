export interface Param {
  name: string;
  type: "float" | "int" | "bool" | "enum" | "angle";
  default: any;
  label: string;
  group: string;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[] | null;
  help: string;
}

export interface PfmInfo {
  id: string;
  name: string;
  family: string;
  style: string;
}

export interface Pen {
  name: string;
  type: string;
  colour: string;
  weight: number;
  stroke_mm: number;
  enabled: boolean;
}

export interface DrawingSetT {
  pens: Pen[];
  distribution_type: string;
  distribution_order: string;
}

export interface AreaT {
  use_original_sizing: boolean;
  units: string;
  width: number;
  height: number;
  orientation: string;
  pad_left: number;
  pad_right: number;
  pad_top: number;
  pad_bottom: number;
  scaling_mode: string;
  rescale_to_pen_width: boolean;
  rescale_mode: string;
  pen_width_mm: number;
  canvas_colour: string;
  background_colour: string;
  clipping: string;
}

export interface VersionT {
  id: string;
  name: string;
  pfm_id: string;
  rating: number;
  notes: string;
  timestamp: number;
  thumbnail: string;
}

export interface RegionT {
  id: string;
  name: string;
  mask_path: string;
  bbox_px: { x: number; y: number; width: number; height: number } | null;
  positive_points: { x: number; y: number }[];
  negative_points: { x: number; y: number }[];
  created_at: number;
  updated_at: number;
  preview_path?: string;
}

export interface SegmentationPromptT {
  positive_points: { x: number; y: number }[];
  negative_points: { x: number; y: number }[];
}

export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type MaskShape =
  | { type: "rect"; x: number; y: number; width: number; height: number }
  | { type: "ellipse"; cx: number; cy: number; rx: number; ry: number }
  | { type: "path"; d: string };

export type LayerDisplayMode = "raster" | "pathfinding" | "both";

export interface PathfindingStyleT {
  enabled: boolean;
  pfm_id: string;
  params: Record<string, any>;
  status: "clean" | "stale" | "generating" | "error";
  error?: string;
  cache?: Record<string, any>;
}

export interface CompositionLayerT {
  id: string;
  name: string;
  kind: "generate" | "pathfinding" | "svg";
  visible: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  svg: string;
  svg_path?: string;
  source: Record<string, any>;
  crop?: CropRect | null;
  mask?: MaskShape | null;
  scale?: number;
  region_id?: string | null;
  display_mode: LayerDisplayMode;
  occlude_below: boolean;
  pathfinding_style: PathfindingStyleT;
  occlusion_mask?: MaskShape | null;
}

export interface CompositionT {
  page: { width: number; height: number; units: "mm" };
  selected_layer_id: string | null;
  layers: CompositionLayerT[];
}

export interface Stats {
  total: number;
  length_mm: number;
  backend: string;
  per_pen: { name: string; colour: string; count: number }[];
}

export interface PlotEstimate {
  paths: number;
  segments: number;
  copies: number;
  total_segments: number;
  draw_distance_mm: number;
  travel_distance_mm: number;
  total_distance_mm: number;
  pen_cycles: number;
  estimated_seconds: number;
  breakdown: {
    draw_seconds: number;
    travel_seconds: number;
    pen_seconds: number;
    pen_move_seconds: number;
    pen_delay_seconds: number;
    copy_delay_seconds: number;
  };
}

export interface PlacementMm {
  x: number;
  y: number;
}

export interface PlotProgress {
  done: number;
  total: number;
  segments_remaining: number;
  shapes_done: number;
  shapes_total: number;
  shapes_remaining: number;
  elapsed_seconds: number;
  remaining_seconds: number | null;
  progress_fraction: number;
}

export interface PlotJob {
  exists: boolean;
  id?: string;
  created_at?: number;
  updated_at?: number;
  status?: string;
  resumable: boolean;
  copies?: number;
  next_copy?: number;
  next_path?: number;
  total_paths?: number;
  total_shapes?: number;
  total_segments?: number;
  completed_shapes?: number;
  completed_segments?: number;
  shapes_remaining?: number;
  segments_remaining?: number;
  progress_fraction?: number;
}
