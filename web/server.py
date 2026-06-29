import os, json, threading, queue, time, tempfile, re, io, zipfile, math, base64, uuid, pickle, hashlib, logging
from pathlib import Path
from xml.etree import ElementTree as ET

import serial
from flask import (
    Flask, render_template, request, jsonify, Response, stream_with_context,
    send_file, send_from_directory, g,
)

from web import obslog
from web.obslog import WideEvent

from engine import accel, svg_io
from engine.canvas import DrawingArea, AREA_PRESETS
from engine.pens import DrawingSet, PEN_LIBRARIES, library_pens
from engine.params import schema_json, validate
from engine.pfm import REGISTRY, get as get_pfm, list_pfms
from engine.generate import GENERATORS, get_generator, list_generators
from engine.genframe import apply_framework
from engine.composition import compose_visible_svg, layer_svg_zip, parse_svg_size_mm, replace_selected_layer
from engine.regions import mask_bbox
from engine import project as project_mod
from engine.project import Project, VersionSnapshotError, get_or_create
from engine.versioning import render_polyline_thumbnail

app = Flask(__name__)

# ── Wide-event request logging ──────────────────────────────────────────────────
# One `http.request` line per request, correlated to worker runs by request_id.
# High-frequency polling routes are suppressed to keep the log signal:noise high.
LOG = obslog.configure()
_LOG_SUPPRESS_PATHS = {
    '/api/stream', '/api/plot/estimate', '/api/plot/job', '/favicon.ico',
}


@app.before_request
def _wide_event_start():
    g.request_id = request.headers.get('X-Request-Id') or obslog.new_request_id()
    g.wide = WideEvent('http.request', g.request_id)
    g.wide_suppress = request.path in _LOG_SUPPRESS_PATHS


@app.after_request
def _wide_event_finish(resp):
    wide = getattr(g, 'wide', None)
    if wide is not None:
        resp.headers['X-Request-Id'] = g.request_id
        if not getattr(g, 'wide_suppress', False):
            wide.set(method=request.method, path=request.path,
                     status=resp.status_code, len=resp.calculate_content_length())
            wide.emit('success' if resp.status_code < 500 else 'error')
    return resp


@app.teardown_request
def _wide_event_teardown(exc):
    # Catch unhandled 500s where after_request never ran.
    wide = getattr(g, 'wide', None)
    if exc is not None and wide is not None and not wide._emitted:
        wide.set(method=request.method, path=request.path, status=500)
        wide.emit('error', level=logging.ERROR, error=str(exc))


def _params_summary(params, limit=120):
    """Compact `k=v,k=v` of scalar params — enough to reproduce a run, not the world."""
    if not isinstance(params, dict):
        return '-'
    parts = [f'{k}={v}' for k, v in sorted(params.items())
             if isinstance(v, (int, float, str, bool))]
    s = ','.join(parts)
    return s[:limit] if s else '-'


# ── Settings ──────────────────────────────────────────────────────────────────

SETTINGS_PATH = Path.home() / '.plotter_settings.json'
PLOT_JOB_PATH = Path.home() / '.plotter_resume_job.json'
PLOT_PATHS_CACHE = Path.home() / '.plotter_paths_cache.pkl'
PI_BRIDGE_PORT = 'socket://100.92.241.24:4000'
LEGACY_USB_PORT = '/dev/ttyACM0'

DEFAULTS = {
    # Reach the Pi-connected plotter over Tailscale via its socat bridge.
    # Use '/dev/ttyACM0' instead when the server runs on the Pi itself.
    'port':            PI_BRIDGE_PORT,
    'paper_width':     297.0,
    'paper_height':    420.0,
    'pen_pos_up':      0.5,
    'pen_pos_down':    2.0,
    'speed_pendown':   2000,
    'speed_penup':     8000,
    'pen_rate_raise':  5000,
    'pen_rate_lower':  5000,
    'pen_delay_up':    0,
    'pen_delay_down':  0,
    'auto_rotate':     True,
    'reordering':      'nearest',
    'copies':          1,
    'page_delay':      15,
    'curve_step_mm':   0.5,
    'sam_model':       'sam2.1_hiera_tiny',
}

def load_cfg():
    s = DEFAULTS.copy()
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text()))
        except Exception:
            pass
    if s.get('port') == LEGACY_USB_PORT and DEFAULTS['port'] == PI_BRIDGE_PORT:
        s['port'] = PI_BRIDGE_PORT
    return s

def save_cfg(s):
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))

cfg = load_cfg()

# ── Global state ──────────────────────────────────────────────────────────────

_plot_thread = None
_stop_event  = threading.Event()
_subscribers = set()
_subscribers_lock = threading.Lock()
_last_events = {}
_current_svg = None   # bytes (the composed SVG; may be stale — see _composition_dirty)
_composition_dirty = True  # recompose _current_svg lazily, on demand
_placement   = {'x': 0.0, 'y': 0.0}  # mm offset from page top-left

# ── Studio state (image → PFM → drawing) ───────────────────────────────────────
_project        = get_or_create('default')
_drawing        = None    # last engine.Drawing produced
_process_thread = None
# Serializes worker validation/start with project transition check/mutation.
_operation_lock = threading.Lock()
_segmentation_adapter = None

def _project_public(p):
    has_image = bool(p.image_path and p.image_path.exists())
    image_w = image_h = 0
    if has_image:
        try:
            from PIL import Image

            with Image.open(p.image_path) as image:
                image_w, image_h = image.size
        except Exception:
            image_w = image_h = 0
    return {
        'id': p.id,
        'name': p.name,
        'image_name': p.image_name,
        'image_url': f'/api/source-image?v={int(time.time() * 1000)}' if has_image else None,
        'image_width': image_w,
        'image_height': image_h,
        'selected_region_id': getattr(p, 'selected_region_id', None),
    }

def _switch_project(pid):
    global _project, _drawing, _current_svg, _placement
    _reset_events('proc', 'state')
    _project = get_or_create(pid)
    _drawing = None
    _current_svg = None
    _placement = {'x': 0.0, 'y': 0.0}
    _sync_current_svg_from_composition()
    return _project

def _project_transition_blocked():
    if ((_process_thread and _process_thread.is_alive())
            or (_plot_thread and _plot_thread.is_alive())):
        return jsonify(error='Project transition blocked while work is active'), 409
    return None

def _composition():
    return _project.composition

def _composition_has_visible_layers():
    return any(layer.visible for layer in _composition().layers)

def _composed_svg_bytes():
    if not _composition_has_visible_layers():
        return None
    return compose_visible_svg(_composition()).encode()

def _recompose_current_svg():
    global _current_svg, _placement, _composition_dirty
    composed = _composed_svg_bytes()
    if composed is not None:
        _current_svg = composed
        _placement = {'x': 0.0, 'y': 0.0}
    _composition_dirty = False
    return composed

def _ensure_current_svg():
    """Recompose only if a mutation has marked the composition dirty."""
    if _composition_dirty:
        _recompose_current_svg()
    return _current_svg

def _sync_current_svg_from_composition():
    # ponytail: just flag dirty (O(1)). The heavy recompose — parse + serialize
    # every path, plus occlusion line-clipping — is deferred to whoever actually
    # needs the composed SVG (plot / estimate / export) instead of running on
    # every layer toggle, show/hide, or nudge.
    global _composition_dirty
    _composition_dirty = True
    return None

def _replace_selected_composition_layer(svg, name, kind, source):
    layer = replace_selected_layer(
        _composition(),
        svg,
        name=name,
        kind=kind,
        source=source,
    )
    _project.save_composition_layers()
    _recompose_current_svg()  # workers read _current_svg right after — recompose now
    return layer

def _set_workflow_layer(svg, name, kind, source):
    """Generate and path finding are separate workflows: never overwrite one with
    the other.

    Reuse the selected layer only when it is on the same side of that divide —
    both generator layers, or both non-generator (image / raster / svg /
    path-finding). Otherwise add a new layer. This keeps the in-place tuning loop
    (re-generate / auto-redraw updates the active layer) while guaranteeing a
    generator never clobbers path-finding/image work, and vice versa.
    """
    comp = _composition()
    selected = comp.selected_layer()
    same_side = selected is not None and (selected.kind == 'generate') == (kind == 'generate')
    if same_side:
        layer = replace_selected_layer(comp, svg, name=name, kind=kind, source=source)
    else:
        layer = comp.add_layer(svg, name=name, kind=kind, source=source)
    _project.save_composition_layers()
    _recompose_current_svg()  # workers read _current_svg right after — recompose now
    return layer

def _composition_payload():
    return _composition().to_dict(include_svg=True)

def _layer_by_id(layer_id):
    return next((l for l in _composition().layers if l.id == layer_id), None)

def _normalize_display_mode(value):
    mode = str(value or 'pathfinding')
    if mode not in {'raster', 'pathfinding', 'both'}:
        raise ValueError(f'Unknown display mode: {mode!r}')
    return mode

def _normalize_pathfinding_style(value=None):
    data = dict(value or {})
    status = data.get('status') or 'stale'
    if status not in {'clean', 'stale', 'generating', 'error'}:
        status = 'stale'
    return {
        'enabled': bool(data.get('enabled', True)),
        'pfm_id': str(data.get('pfm_id') or _project.pfm_id),
        'params': dict(data.get('params') or {}),
        'status': status,
        'error': str(data.get('error') or ''),
        'cache': dict(data.get('cache') or {}),
    }

def _mark_layer_style_stale(layer):
    style = _normalize_pathfinding_style(layer.pathfinding_style)
    if style.get('status') == 'clean':
        style['status'] = 'stale'
    layer.pathfinding_style = style

def _mask_outline_path(mask, layer_w, layer_h):
    """Largest contour of a region mask as a `path` mask in layer-local mm, so
    occlusion follows the region's real outline instead of its bounding box."""
    import cv2
    import numpy as np

    arr = np.asarray(mask)
    mh, mw = arr.shape[:2]
    if not mw or not mh:
        return None
    contours, _ = cv2.findContours((arr > 127).astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 0.0015 * cv2.arcLength(c, True), True)
    if len(c) < 3:
        return None
    sx, sy = layer_w / mw, layer_h / mh
    pts = [(round(float(p[0][0]) * sx, 3), round(float(p[0][1]) * sy, 3)) for p in c]
    d = 'M' + ' L'.join(f'{x},{y}' for x, y in pts) + ' Z'
    return {'type': 'path', 'd': d}


def _region_occlusion_mask(region, layer):
    image = _project.open_image()
    if image is None:
        return None
    image_w, image_h = image.size
    if not image_w or not image_h or not layer.width or not layer.height:
        return None
    mask = _project.open_region_mask(region.id)
    if mask is not None:
        outline = _mask_outline_path(mask, layer.width, layer.height)
        if outline:
            return outline
    bbox = dict(getattr(region, 'bbox_px', None) or {})
    if not bbox and mask is not None:
        bbox = mask_bbox(mask) or {}
    if not bbox:
        return None
    return {
        'type': 'rect',
        'x': round(float(bbox.get('x', 0) or 0) / image_w * layer.width, 4),
        'y': round(float(bbox.get('y', 0) or 0) / image_h * layer.height, 4),
        'width': round(float(bbox.get('width', 0) or 0) / image_w * layer.width, 4),
        'height': round(float(bbox.get('height', 0) or 0) / image_h * layer.height, 4),
    }

def _regions_payload():
    return {
        'regions': [r.to_dict() for r in getattr(_project, 'regions', [])],
        'selected_region_id': getattr(_project, 'selected_region_id', None),
    }

class LocalSam2Adapter:
    """Lazy local SAM 2 image predictor adapter.

    The app can boot without SAM installed. Status and predict surface a clean
    unavailable state instead of importing heavyweight dependencies at module
    import time.
    """

    CHECKPOINT_BASE_URL = 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/'
    # model id -> SAM 2 hydra config. Checkpoint file is f'{model}.pt'.
    MODELS = {
        'sam2.1_hiera_tiny':      'configs/sam2.1/sam2.1_hiera_t.yaml',
        'sam2.1_hiera_small':     'configs/sam2.1/sam2.1_hiera_s.yaml',
        'sam2.1_hiera_base_plus': 'configs/sam2.1/sam2.1_hiera_b+.yaml',
        'sam2.1_hiera_large':     'configs/sam2.1/sam2.1_hiera_l.yaml',
    }

    def __init__(self, checkpoint=None, config=None, model=None):
        self._predictor = None
        self._error = None
        self.setup_state = 'idle'
        self.setup_progress = 0.0
        self._setup_lock = threading.Lock()
        self._setup_thread = None
        model = model or cfg.get('sam_model') or os.environ.get('SAM2_MODEL') or 'sam2.1_hiera_tiny'
        # Explicit checkpoint/config (constructor or env) pin paths and skip the
        # registry — power-user escape hatch kept from the original adapter.
        self._pin_checkpoint = checkpoint or os.environ.get('SAM2_CHECKPOINT')
        self._pin_config = config or os.environ.get('SAM2_CONFIG')
        # SAM2_AUTO_SETUP gates only checkpoint download (a plain file). Packages
        # are never installed at runtime — the setup scripts own that. Disable it
        # in tests/power-user setups to require an explicit checkpoint.
        self.auto_setup = os.environ.get('SAM2_AUTO_SETUP', '1') not in ('0', 'false', 'False')
        self._apply_model(model if model in self.MODELS else 'sam2.1_hiera_tiny')

    def _apply_model(self, model):
        self.model = model
        self.config = self._pin_config or self.MODELS[model]
        self.checkpoint = self._pin_checkpoint or str(
            project_mod.WORKSPACE / 'models' / f'{model}.pt')
        self.checkpoint_url = os.environ.get(
            'SAM2_CHECKPOINT_URL', self.CHECKPOINT_BASE_URL + f'{model}.pt')

    def set_model(self, model):
        if model not in self.MODELS:
            raise ValueError(f'Unknown SAM model {model!r}')
        if model == self.model:
            return
        # An explicit UI choice overrides any env/constructor pin.
        self._pin_checkpoint = None
        self._pin_config = None
        self._predictor = None
        self._error = None
        self.setup_state = 'idle'
        self.setup_progress = 0.0
        self._apply_model(model)
        # Start fetching the newly chosen model so the UI can show progress.
        self.prepare_async()

    def _has_module(self, name):
        import importlib.util

        return importlib.util.find_spec(name) is not None

    def _missing(self):
        missing = [
            name for name in ('sam2', 'torch', 'torchvision')
            if not self._has_module(name)
        ]
        if not Path(self.checkpoint).exists():
            missing.append('checkpoint')
        return missing

    @staticmethod
    def _setup_incomplete_error(missing):
        return (
            'Plotter Studio setup is incomplete: missing '
            + ', '.join(missing)
            + '. Run setup-windows.bat on Windows or ./setup-macos.command on macOS.'
        )

    def _download_checkpoint(self):
        import urllib.request

        self.setup_state = 'downloading'
        self.setup_progress = 0.0
        target = Path(self.checkpoint)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + '.part')

        def hook(blocks, block_size, total):
            if total and total > 0:
                self.setup_progress = min(1.0, blocks * block_size / total)

        urllib.request.urlretrieve(self.checkpoint_url, part, reporthook=hook)
        part.replace(target)
        self.setup_progress = 1.0

    def _ensure_setup(self):
        # Never install packages at runtime — that is the setup scripts' job.
        # Missing modules are a hard, actionable error.
        missing_modules = [
            name for name in ('sam2', 'torch', 'torchvision')
            if not self._has_module(name)
        ]
        if missing_modules:
            raise RuntimeError(self._setup_incomplete_error(missing_modules))
        # Checkpoint is a plain file: download it on demand when auto-setup is on.
        if not Path(self.checkpoint).exists():
            if self.auto_setup:
                self._download_checkpoint()
            else:
                raise RuntimeError(self._setup_incomplete_error(['checkpoint']))
        self.setup_state = 'ready'

    def prepare_async(self):
        """Run install/download in the background so status() can report progress
        without blocking the request. No-op if already ready or in flight."""
        if not self.auto_setup or self._predictor is not None:
            return
        with self._setup_lock:
            if self._setup_thread and self._setup_thread.is_alive():
                return
            if self.setup_state == 'ready' and Path(self.checkpoint).exists():
                return

            def run():
                try:
                    self._ensure_setup()
                except Exception as exc:  # surfaced via status()/setup_state
                    self._error = str(exc)
                    self.setup_state = 'error'

            self._error = None
            self._setup_thread = threading.Thread(target=run, daemon=True)
            self._setup_thread.start()

    @staticmethod
    def _device_for(torch):
        if torch.cuda.is_available():
            return 'cuda'
        mps = getattr(getattr(torch, 'backends', None), 'mps', None)
        if mps is not None and mps.is_available():
            return 'mps'
        return 'cpu'

    def _load(self):
        if self._predictor is not None:
            return self._predictor
        if self._error:
            raise RuntimeError(self._error)
        try:
            self._ensure_setup()
            import numpy as np
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor

            if not Path(self.checkpoint).exists():
                raise RuntimeError(
                    f'SAM 2 checkpoint not found at {self.checkpoint}. '
                    'Set SAM2_CHECKPOINT or download sam2.1_hiera_tiny.pt.'
                )
            model = build_sam2(self.config, self.checkpoint, device=self._device_for(torch))
            self._predictor = SAM2ImagePredictor(model)
            self._np = np
            self._torch = torch
            return self._predictor
        except Exception as exc:
            self._error = str(exc)
            raise RuntimeError(self._error) from exc

    def status(self):
        # Purely observational: never install, download, or start background
        # setup. Report the current state; missing pieces are a setup-incomplete
        # error pointing at the platform setup scripts.
        if self._predictor is not None:
            return {'available': True, 'backend': 'sam2', 'model': self.model,
                    'models': list(self.MODELS), 'setup_state': 'ready', 'progress': 1.0}
        missing = self._missing()
        available = not missing and self._error is None
        payload = {
            'available': available,
            'backend': 'sam2',
            'model': self.model,
            'models': list(self.MODELS),
            'checkpoint': self.checkpoint,
            'setup_state': 'ready' if available else self.setup_state,
            'progress': round(self.setup_progress, 3),
            'auto_setup': self.auto_setup,
        }
        if self._error:
            payload['setup_state'] = 'error'
            payload['error'] = self._error
        elif missing:
            payload['setup_state'] = 'error'
            payload['error'] = self._setup_incomplete_error(missing)
        return payload

    def predict(self, image, positive_points, negative_points):
        predictor = self._load()
        np = self._np
        torch = self._torch
        labels = [1] * len(positive_points) + [0] * len(negative_points)
        points = positive_points + negative_points
        if not points:
            raise ValueError('At least one positive point is required')
        point_coords = np.array([[p['x'], p['y']] for p in points], dtype=np.float32)
        point_labels = np.array(labels, dtype=np.int32)
        with torch.inference_mode():
            predictor.set_image(np.array(image.convert('RGB')))
            masks, scores, _ = predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                multimask_output=True,
            )
        index = int(np.argmax(scores)) if len(scores) else 0
        mask = (masks[index].astype(np.uint8) * 255)
        from PIL import Image

        return Image.fromarray(mask, 'L')

def _get_segmentation_adapter():
    global _segmentation_adapter
    if _segmentation_adapter is None:
        _segmentation_adapter = LocalSam2Adapter()
    return _segmentation_adapter

def _clean_points(value):
    points = []
    for item in value or []:
        try:
            x = float(item['x'])
            y = float(item['y'])
        except (KeyError, TypeError, ValueError):
            continue
        points.append({'x': x, 'y': y})
    return points

def _png_data_url(image):
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')

def _image_from_data_url(value):
    if not isinstance(value, str):
        raise ValueError('mask_png is required')
    raw = value.split(',', 1)[1] if ',' in value else value
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(raw))).convert('L')

def emit(t, **kw):
    evt = {'t': t, **kw}
    try:
        with _subscribers_lock:
            if t in ('proc', 'state'):
                _last_events[t] = evt
            for q in _subscribers:
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    pass
    except Exception:
        pass

def _subscribe_events():
    q = queue.Queue(maxsize=300)
    with _subscribers_lock:
        for key in ('proc', 'state'):
            evt = _last_events.get(key)
            if evt:
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    pass
        _subscribers.add(q)
    return q

def _unsubscribe_events(q):
    with _subscribers_lock:
        _subscribers.discard(q)

def _clear_events_locked():
    for q in _subscribers:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

def _clear_events():
    with _subscribers_lock:
        _clear_events_locked()

def _reset_events(*cached_event_types):
    with _subscribers_lock:
        _clear_events_locked()
        for key in cached_event_types:
            _last_events.pop(key, None)

def _clear_last_plot_events():
    with _subscribers_lock:
        _last_events.pop('state', None)

def _clear_last_proc_events():
    with _subscribers_lock:
        _last_events.pop('proc', None)

# ── SVG → polylines ───────────────────────────────────────────────────────────

def _parse_length(val, default_mm):
    """Parse SVG length string → mm."""
    FACTORS = {'mm': 1, 'cm': 10, 'in': 25.4, 'px': 25.4 / 96,
                'pt': 25.4 / 72, 'pc': 25.4 / 6}
    s = str(val).strip()
    for unit, f in FACTORS.items():
        if s.endswith(unit):
            try:
                return float(s[:-len(unit)]) * f
            except ValueError:
                pass
    try:
        return float(s) * (25.4 / 96)   # assume px
    except ValueError:
        return default_mm

class ArcPath(list):
    """A polyline that may carry circular-arc metadata.

    It behaves exactly like a ``list`` of (x, y) points everywhere (reordering,
    estimation, resume accounting), but when ``arc`` is set the plot worker can
    emit a single native Grbl ``G2`` instead of dozens of ``G1`` segments. If the
    tag is ever lost the polygon points still draw the circle correctly.
    """
    arc = None  # {'cx', 'cy', 'r'} in machine mm, or None

    def __reduce__(self):  # preserve `arc` across the pickle paths cache
        return (_rebuild_path, (list(self), self.arc))


def _rebuild_path(items, arc):
    p = ArcPath(items)
    p.arc = arc
    return p


def _clone(poly):
    arc = getattr(poly, 'arc', None)
    if arc is None:
        return list(poly)
    p = ArcPath(poly)
    p.arc = arc
    return p


def _rev(poly):
    arc = getattr(poly, 'arc', None)
    if arc is not None:
        p = ArcPath(poly)        # a circle reversed is the same circle
        p.arc = arc
        return p
    return list(reversed(poly))


def _circle_meta(element, se, px_to_mm):
    """Return (cx, cy, r) in machine mm for a circular Circle/Ellipse, else None."""
    if not isinstance(element, (se.Circle, se.Ellipse)):
        return None
    try:
        bb = element.bbox()
    except Exception:
        return None
    if not bb:
        return None
    x0, y0, x1, y1 = bb
    w_, h_ = x1 - x0, y1 - y0
    if w_ <= 0 or h_ <= 0 or abs(w_ - h_) > 0.02 * max(w_, h_):
        return None  # degenerate or non-circular (ellipse) -> let it flatten
    cx = (x0 + x1) / 2 * px_to_mm
    cy = -((y0 + y1) / 2) * px_to_mm
    r = (w_ / 2) * px_to_mm
    return cx, cy, r


def svg_to_polylines(svg_bytes, settings, on_progress=None, respect_stop=True):
    """
    Parse SVG → polylines in machine mm coords (X right, Y negative = down).
    svgelements handles all transforms; coordinates come out as 96 dpi px.
    Curves are sampled with direct float math (avoids seg.point() overhead).
    on_progress(done, total) is called after each element.
    """
    try:
        import svgelements as se
    except ImportError:
        raise RuntimeError('svgelements not installed. Run: uv add svgelements')

    PX_TO_MM = 25.4 / 96
    step_px  = float(settings.get('curve_step_mm', 0.5)) / PX_TO_MM

    with tempfile.NamedTemporaryFile(suffix='.svg', delete=False) as f:
        f.write(svg_bytes)
        tmp = f.name
    try:
        svg_doc = se.SVG.parse(tmp)
    finally:
        os.unlink(tmp)

    drawable = [el for el in svg_doc.elements()
                if not isinstance(el, (se.Group, se.SVG))]
    total_el = len(drawable)

    polylines = []

    for idx, element in enumerate(drawable):
        if on_progress:
            on_progress(idx, total_el)
        if respect_stop and _stop_event.is_set():
            raise RuntimeError('__stopped__')

        # True circles become a single native G2 arc at plot time. Keep a polygon
        # of points for travel ordering / estimation / resume accounting, and tag
        # it with the arc so the draw loop can replace the segments with one G2.
        circ = _circle_meta(element, se, PX_TO_MM)
        if circ is not None:
            cx, cy, r = circ
            m = min(48, max(12, int(2 * math.pi * r / max(1e-6, step_px * PX_TO_MM))))
            pts = [(cx + r * math.cos(2 * math.pi * i / m),
                    cy + r * math.sin(2 * math.pi * i / m)) for i in range(m + 1)]
            ring = ArcPath(pts)
            ring.arc = {'cx': cx, 'cy': cy, 'r': r}
            polylines.append(ring)
            continue

        try:
            segs = list(element.segments())
        except Exception:
            continue

        current = []
        for seg in segs:
            name = type(seg).__name__

            if name == 'Move':
                if len(current) >= 2:
                    polylines.append(current)
                p = seg.end
                current = [(p.x * PX_TO_MM, -(p.y * PX_TO_MM))]

            elif name == 'Close':
                if current:
                    current.append(current[0])
                if len(current) >= 2:
                    polylines.append(current)
                current = []

            elif name == 'Line':
                # Straight line — plotter draws these natively, no sampling needed
                p = seg.end
                current.append((p.x * PX_TO_MM, -(p.y * PX_TO_MM)))

            elif name == 'CubicBezier':
                # Direct de Casteljau — avoids seg.point() overhead on slow ARM
                x0, y0 = seg.start.x,    seg.start.y
                x1, y1 = seg.control1.x, seg.control1.y
                x2, y2 = seg.control2.x, seg.control2.y
                x3, y3 = seg.end.x,      seg.end.y
                chord = ((x3-x0)**2 + (y3-y0)**2) ** 0.5
                n = max(1, int(chord * 1.5 / step_px))
                for i in range(1, n + 1):
                    t = i / n; mt = 1.0 - t
                    b0 = mt*mt*mt; b1 = 3*mt*mt*t; b2 = 3*mt*t*t; b3 = t*t*t
                    current.append((
                        (b0*x0 + b1*x1 + b2*x2 + b3*x3) * PX_TO_MM,
                        -(b0*y0 + b1*y1 + b2*y2 + b3*y3) * PX_TO_MM,
                    ))

            elif name == 'QuadraticBezier':
                x0, y0 = seg.start.x,   seg.start.y
                x1, y1 = seg.control.x, seg.control.y
                x2, y2 = seg.end.x,     seg.end.y
                chord = ((x2-x0)**2 + (y2-y0)**2) ** 0.5
                n = max(1, int(chord * 1.5 / step_px))
                for i in range(1, n + 1):
                    t = i / n; mt = 1.0 - t
                    b0 = mt*mt; b1 = 2*mt*t; b2 = t*t
                    current.append((
                        (b0*x0 + b1*x1 + b2*x2) * PX_TO_MM,
                        -(b0*y0 + b1*y1 + b2*y2) * PX_TO_MM,
                    ))

            else:
                # Arc or unknown — fall back to svgelements
                try:
                    seg_len = seg.length()
                except Exception:
                    seg_len = step_px
                n = max(1, int(seg_len / step_px))
                for i in range(1, n + 1):
                    p = seg.point(i / n)
                    current.append((p.x * PX_TO_MM, -(p.y * PX_TO_MM)))

        if len(current) >= 2:
            polylines.append(current)

    if on_progress:
        on_progress(total_el, total_el)

    reordering = _reordering_mode(settings)
    if reordering != 'none':
        polylines = _reorder(polylines, reordering)

    return polylines

def _reordering_mode(settings):
    """Normalize legacy numeric and current named reordering settings."""
    raw = (settings or {}).get('reordering', DEFAULTS['reordering'])
    if isinstance(raw, bool):
        return 'nearest' if raw else 'none'
    if isinstance(raw, (int, float)):
        return {0: 'none', 1: 'nearest', 2: 'nearest_reversible', 3: 'two_opt'}.get(int(raw), 'nearest')
    key = str(raw).strip().lower().replace('-', '_').replace(' ', '_')
    aliases = {
        '0': 'none',
        'off': 'none',
        'false': 'none',
        'preserve': 'none',
        '1': 'nearest',
        'nearest_neighbor': 'nearest',
        'nearest_neighbour': 'nearest',
        'nearest': 'nearest',
        '2': 'nearest_reversible',
        'nearest_reverse': 'nearest_reversible',
        'nearest_reversible': 'nearest_reversible',
        'reversible': 'nearest_reversible',
        '3': 'two_opt',
        '2opt': 'two_opt',
        '2_opt': 'two_opt',
        'twoopt': 'two_opt',
        'two_opt': 'two_opt',
    }
    return aliases.get(key, 'nearest')

def _reorder(polylines, mode='nearest'):
    """Reorder paths to reduce pen-up travel."""
    if not polylines:
        return polylines
    mode = _reordering_mode({'reordering': mode})
    if mode == 'none':
        return [_clone(poly) for poly in polylines]
    if mode == 'nearest_reversible':
        return _reorder_nearest_reversible(polylines)
    if mode == 'two_opt':
        return _reorder_two_opt(polylines)
    return _reorder_nearest(polylines)

def _reorder_nearest(polylines):
    # Vectorised greedy nearest-neighbour (GPU for very dense drawings). Identical
    # tour to the old O(n^2) python loop; ~7x faster at a few thousand dots.
    if len(polylines) < 2:
        return list(polylines)
    order = accel.greedy_nearest_order([p[0] for p in polylines],
                                       [p[-1] for p in polylines])
    return [polylines[i] for i in order]

def _reorder_nearest_reversible(polylines):
    remaining = [_clone(poly) for poly in polylines]
    ordered = []
    pos = (0.0, 0.0)
    while remaining:
        best = None
        for i, poly in enumerate(remaining):
            start_d = _dist2(pos, poly[0])
            end_d = _dist2(pos, poly[-1])
            candidate = (min(start_d, end_d), i, end_d < start_d)
            if best is None or candidate < best:
                best = candidate
        _, idx, reverse = best
        poly = remaining.pop(idx)
        if reverse:
            poly = _rev(poly)
        ordered.append(poly)
        pos = poly[-1]
    return ordered

def _reorder_two_opt(polylines):
    ordered = _reorder_nearest_reversible(polylines)
    n = len(ordered)
    if n < 3:
        return ordered

    # A 2-opt pass over open paths. Reversing a route slice also reverses each
    # path so the pen-down drawing direction remains continuous through the slice.
    max_passes = 2
    window = n if n <= 400 else 250
    origin = (0.0, 0.0)
    for _ in range(max_passes):
        improved = False
        for i in range(n - 1):
            before = origin if i == 0 else ordered[i - 1][-1]
            start_i = ordered[i][0]
            limit = min(n, i + window + 1)
            for k in range(i + 1, limit):
                after = origin if k == n - 1 else ordered[k + 1][0]
                old = _dist2(before, start_i) + _dist2(ordered[k][-1], after)
                new = _dist2(before, ordered[k][-1]) + _dist2(start_i, after)
                if new + 1e-9 < old:
                    ordered[i:k + 1] = [_rev(poly) for poly in reversed(ordered[i:k + 1])]
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return ordered

def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

def _dist(a, b):
    return math.sqrt(_dist2(a, b))

def _placed_polylines(svg_bytes, settings, on_progress=None, placement=None,
                      respect_stop=True):
    polylines = svg_to_polylines(
        svg_bytes, settings, on_progress=on_progress, respect_stop=respect_stop
    )
    place = _placement if placement is None else placement
    ox, oy = place.get('x', 0.0), place.get('y', 0.0)
    if ox or oy:
        polylines = [_shift_poly(poly, ox, oy) for poly in polylines]
    return polylines

def _shift_poly(poly, ox, oy):
    pts = [(x + ox, y - oy) for x, y in poly]
    arc = getattr(poly, 'arc', None)
    if arc is None:
        return pts
    shifted = ArcPath(pts)
    shifted.arc = {'cx': arc['cx'] + ox, 'cy': arc['cy'] - oy, 'r': arc['r']}
    return shifted

# ── Parsed-paths cache ───────────────────────────────────────────────────────
# svg_to_polylines (curve flattening) + reordering (nearest / two-opt) is the
# slow part of a plot. Cache the final placed polylines keyed by everything that
# affects them, so resuming or re-plotting the same drawing skips re-parsing.

def _paths_signature(svg_bytes, settings, placement):
    meta = {
        'curve_step_mm': float((settings or {}).get('curve_step_mm', 0.5) or 0.5),
        'reordering': _reordering_mode(settings),
        'px': round(float((placement or {}).get('x', 0.0)), 4),
        'py': round(float((placement or {}).get('y', 0.0)), 4),
    }
    h = hashlib.sha256()
    h.update(svg_bytes)
    h.update(json.dumps(meta, sort_keys=True).encode())
    return h.hexdigest()

def _load_cached_polylines(sig):
    try:
        with open(PLOT_PATHS_CACHE, 'rb') as f:
            data = pickle.load(f)
        if data.get('sig') == sig:
            return data.get('polylines')
    except Exception:
        return None
    return None

def _save_cached_polylines(sig, polylines):
    try:
        tmp = PLOT_PATHS_CACHE.with_suffix('.tmp')
        with open(tmp, 'wb') as f:
            pickle.dump({'sig': sig, 'polylines': polylines}, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(PLOT_PATHS_CACHE)
    except Exception:
        pass

def _resolve_polylines(svg_bytes, settings, placement, on_progress=None):
    """Parse the SVG to placed polylines, or reuse the cache when the drawing,
    curve resolution, reordering and placement are unchanged."""
    sig = _paths_signature(svg_bytes, settings, placement)
    cached = _load_cached_polylines(sig)
    if cached is not None:
        emit('log', msg=f'Reusing cached paths ({len(cached)}) — skipped re-parsing.')
        if on_progress:
            on_progress(1, 1)
        return cached
    polylines = _placed_polylines(svg_bytes, settings, on_progress=on_progress,
                                  placement=placement)
    _save_cached_polylines(sig, polylines)
    return polylines

def _polyline_distance(poly):
    return sum(_dist(poly[i - 1], poly[i]) for i in range(1, len(poly)))

def _seconds_for_distance(distance_mm, speed_mm_min):
    speed = float(speed_mm_min or 0)
    if speed <= 0:
        return 0.0
    return float(distance_mm) / speed * 60.0

def _estimate_polylines(polylines, settings):
    copies = max(1, int(settings.get('copies', 1) or 1))
    page_delay = max(0.0, float(settings.get('page_delay', 0) or 0))
    path_count = len(polylines)
    segments = sum(max(0, len(poly) - 1) for poly in polylines)

    draw_distance = 0.0
    travel_distance = 0.0
    pos = (0.0, 0.0)
    for _copy_i in range(copies):
        for poly in polylines:
            if len(poly) < 2:
                continue
            travel_distance += _dist(pos, poly[0])
            draw_distance += _polyline_distance(poly)
            pos = poly[-1]
    if path_count:
        travel_distance += _dist(pos, (0.0, 0.0))

    pen_cycles = path_count * copies
    z_delta = abs(float(settings.get('pen_pos_down', 0)) -
                  float(settings.get('pen_pos_up', 0)))
    pen_move_seconds = pen_cycles * (
        _seconds_for_distance(z_delta, settings.get('pen_rate_lower', 0)) +
        _seconds_for_distance(z_delta, settings.get('pen_rate_raise', 0))
    )
    pen_delay_seconds = pen_cycles * (
        float(settings.get('pen_delay_down', 0) or 0) +
        float(settings.get('pen_delay_up', 0) or 0)
    ) / 1000.0
    pen_seconds = pen_move_seconds + pen_delay_seconds
    draw_seconds = _seconds_for_distance(draw_distance, settings.get('speed_pendown', 0))
    travel_seconds = _seconds_for_distance(travel_distance, settings.get('speed_penup', 0))
    copy_delay_seconds = max(0, copies - 1) * page_delay
    estimated_seconds = draw_seconds + travel_seconds + pen_seconds + copy_delay_seconds

    return {
        'paths': path_count,
        'segments': segments,
        'copies': copies,
        'total_segments': segments * copies,
        'draw_distance_mm': round(draw_distance, 3),
        'travel_distance_mm': round(travel_distance, 3),
        'total_distance_mm': round(draw_distance + travel_distance, 3),
        'pen_cycles': pen_cycles,
        'estimated_seconds': round(estimated_seconds, 3),
        'breakdown': {
            'draw_seconds': round(draw_seconds, 3),
            'travel_seconds': round(travel_seconds, 3),
            'pen_seconds': round(pen_seconds, 3),
            'pen_move_seconds': round(pen_move_seconds, 3),
            'pen_delay_seconds': round(pen_delay_seconds, 3),
            'copy_delay_seconds': round(copy_delay_seconds, 3),
        },
    }

def _plot_progress_payload(done_segments, total_segments, done_shapes, total_shapes,
                           started_at, now=None, estimated_seconds=None):
    now = time.time() if now is None else now
    elapsed = max(0.0, float(now) - float(started_at))
    total_segments = max(0, int(total_segments or 0))
    done_segments = min(total_segments, max(0, int(done_segments or 0)))
    total_shapes = max(0, int(total_shapes or 0))
    done_shapes = min(total_shapes, max(0, int(done_shapes or 0)))
    fraction = (done_segments / total_segments) if total_segments else 0.0

    remaining = None
    if total_segments:
        if done_segments > 0:
            remaining = elapsed * (total_segments - done_segments) / done_segments
        elif estimated_seconds is not None:
            remaining = max(0.0, float(estimated_seconds) - elapsed)

    return {
        'done': done_segments,
        'total': total_segments,
        'segments_remaining': total_segments - done_segments,
        'shapes_done': done_shapes,
        'shapes_total': total_shapes,
        'shapes_remaining': total_shapes - done_shapes,
        'elapsed_seconds': round(elapsed, 3),
        'remaining_seconds': round(remaining, 3) if remaining is not None else None,
        'progress_fraction': round(fraction, 4),
    }

# ── Persistent plot jobs / resume checkpoints ────────────────────────────────

def _now_ms():
    return int(time.time() * 1000)

def _plot_job_svg_bytes(job):
    return base64.b64decode(job.get('svg_b64', '').encode('ascii'))

def _save_plot_job(job):
    job['updated_at'] = _now_ms()
    tmp = PLOT_JOB_PATH.with_suffix(PLOT_JOB_PATH.suffix + '.tmp')
    tmp.write_text(json.dumps(job, indent=2))
    # ponytail: Windows raises PermissionError (WinError 5) on rapid renames when
    # an AV/indexer or concurrent reader briefly holds the target; retry ~200ms so
    # a single transient lock can't abort a plot mid-job.
    for attempt in range(10):
        try:
            tmp.replace(PLOT_JOB_PATH)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02)
    return job

def _load_plot_job():
    if not PLOT_JOB_PATH.exists():
        return None
    try:
        return json.loads(PLOT_JOB_PATH.read_text())
    except Exception:
        return None

def _delete_plot_job():
    try:
        PLOT_JOB_PATH.unlink()
    except FileNotFoundError:
        pass

def _create_plot_job(svg_bytes, settings, placement):
    now = _now_ms()
    copies = max(1, int((settings or {}).get('copies', 1) or 1))
    job = {
        'id': uuid.uuid4().hex,
        'created_at': now,
        'updated_at': now,
        'status': 'queued',
        'svg_b64': base64.b64encode(svg_bytes).decode('ascii'),
        'settings': dict(settings or {}),
        'placement': {
            'x': float((placement or {}).get('x', 0)),
            'y': float((placement or {}).get('y', 0)),
        },
        'copies': copies,
        'total_paths': 0,
        'total_shapes': 0,
        'total_segments': 0,
        'next_copy': 0,
        'next_path': 0,
        'completed_shapes': 0,
        'completed_segments': 0,
    }
    return _save_plot_job(job)

def _checkpoint_plot_job(job, **updates):
    job.update(updates)
    return _save_plot_job(job)

def _plot_thread_alive():
    return bool(_plot_thread and _plot_thread.is_alive())

def _normalised_plot_job(job):
    if not job:
        return None
    if job.get('status') == 'running' and not _plot_thread_alive():
        job['status'] = 'crashed'
        _save_plot_job(job)
    return job

def _plot_job_public(job):
    job = _normalised_plot_job(job)
    if not job:
        return {'exists': False, 'resumable': False}

    total_shapes = max(0, int(job.get('total_shapes', 0) or 0))
    total_segments = max(0, int(job.get('total_segments', 0) or 0))
    completed_shapes = min(total_shapes, max(0, int(job.get('completed_shapes', 0) or 0)))
    completed_segments = min(total_segments, max(0, int(job.get('completed_segments', 0) or 0)))
    status = job.get('status', 'unknown')
    resumable = status in {'queued', 'running', 'stopped', 'error', 'crashed'} and (
        total_shapes == 0 or completed_shapes < total_shapes
    )
    return {
        'exists': True,
        'id': job.get('id'),
        'created_at': job.get('created_at'),
        'updated_at': job.get('updated_at'),
        'status': status,
        'resumable': resumable,
        'copies': int(job.get('copies', 1) or 1),
        'next_copy': int(job.get('next_copy', 0) or 0),
        'next_path': int(job.get('next_path', 0) or 0),
        'total_paths': int(job.get('total_paths', 0) or 0),
        'total_shapes': total_shapes,
        'total_segments': total_segments,
        'completed_shapes': completed_shapes,
        'completed_segments': completed_segments,
        'shapes_remaining': max(0, total_shapes - completed_shapes),
        'segments_remaining': max(0, total_segments - completed_segments),
        'progress_fraction': round((completed_segments / total_segments) if total_segments else 0.0, 4),
    }

# ── Plotter driver ────────────────────────────────────────────────────────────

# ponytail: test-only Grbl stub so plot/manual flows run in e2e without hardware.
# Gated on PLOTTER_FAKE_SERIAL; never touches the real serial path in production.
_FAKE_SERIAL_WRITES = []  # decoded command lines captured for test assertions (K7)


class _FakeGrbl:
    """Minimal pyserial stand-in that speaks just enough Grbl to satisfy
    PlotterConn / the /api/manual handler: every command line gets an 'ok',
    and a '?' status query gets an Idle status report."""

    def __init__(self):
        self._out = bytearray()

    def write(self, data):
        if data == b'\x18':  # soft-reset: no reply expected
            return len(data)
        for line in bytes(data).decode('utf-8', 'replace').splitlines():
            line = line.strip()
            if not line:
                continue
            _FAKE_SERIAL_WRITES.append(line)
            if line == '?':
                self._out += b'<Idle|MPos:0.000,0.000,0.000|FS:0,0>\r\n'
            else:
                self._out += b'ok\r\n'
        return len(data)

    def readline(self):
        nl = self._out.find(b'\n')
        if nl < 0:
            chunk, self._out = bytes(self._out), bytearray()
            return chunk
        chunk, self._out = bytes(self._out[:nl + 1]), self._out[nl + 1:]
        return chunk

    def read(self, n=1):
        chunk, self._out = bytes(self._out[:n]), self._out[n:]
        return chunk

    @property
    def in_waiting(self):
        return len(self._out)

    def close(self):
        pass


def open_serial(port, timeout=0.1):
    """Open a plotter connection.

    Accepts a local device path ('/dev/ttyACM0', '/Users/me/.idraw-tty') or a
    pyserial URL — notably 'socket://HOST:PORT' to reach a plotter shared over
    the network (e.g. the Pi's socat bridge at socket://100.92.241.24:4000).
    """
    if os.environ.get('PLOTTER_FAKE_SERIAL'):
        return _FakeGrbl()
    if '://' in str(port):
        return serial.serial_for_url(port, baudrate=115200, timeout=timeout)
    return serial.Serial(port, 115200, timeout=timeout)


class PlotterConn:
    def __init__(self, port, settings):
        self.ser = open_serial(port, timeout=0.1)
        self.cfg = settings
        time.sleep(2)
        self.ser.read(self.ser.in_waiting or 0)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _send(self, cmd, timeout=60):
        self.ser.write((cmd + '\n').encode())
        t0 = time.time()
        while time.time() - t0 < timeout:
            if _stop_event.is_set():
                self.ser.write(b'\x18')  # Grbl soft-reset: clears motion queue instantly
                raise RuntimeError('__stopped__')
            line = self.ser.readline().decode('utf-8', 'replace').strip()
            if not line:
                continue
            if line.lower() == 'ok':
                return
            emit('log', msg=f'{cmd} → {line}')
            if 'ALARM' in line or 'error' in line:
                raise RuntimeError(f'Grbl: {line}')
        raise TimeoutError(f'No ok for: {cmd!r}')

    def home(self):
        self._send('$X', timeout=5)
        self.ser.write(b'$H\n')
        t0 = time.time()
        while time.time() - t0 < 30:
            if _stop_event.is_set():
                self.ser.write(b'\x18')
                raise RuntimeError('__stopped__')
            line = self.ser.readline().decode('utf-8', 'replace').strip()
            if not line:
                continue
            emit('log', msg=f'[homing] {line}')
            if line.lower() == 'ok':
                return
            if 'ALARM' in line or 'error' in line:
                raise RuntimeError(f'Homing: {line}')
        raise TimeoutError('Homing timed out')

    def init(self):
        self._send('G21')
        self._send('G90')

    def pen_up(self):
        z = self.cfg['pen_pos_up']
        r = self.cfg['pen_rate_raise']
        self._send(f'G00 Z{z} F{r}')
        d = self.cfg['pen_delay_up']
        if d > 0:
            self._send(f'G04 P{d / 1000:.3f}')

    def pen_down(self):
        z = self.cfg['pen_pos_down']
        r = self.cfg['pen_rate_lower']
        self._send(f'G00 Z{z} F{r}')
        d = self.cfg['pen_delay_down']
        if d > 0:
            self._send(f'G04 P{d / 1000:.3f}')

    def move(self, x, y):
        self._send(f'G00 X{x:.3f} Y{y:.3f} F{self.cfg["speed_penup"]}')

    def draw(self, x, y):
        self._send(f'G01 X{x:.3f} Y{y:.3f} F{self.cfg["speed_pendown"]}')

    def arc(self, cx, cy, r):
        """Draw a full circle as one native Grbl G2.

        Assumes the pen is already down at the ring's start point (cx + r, cy),
        so the centre offset is I=-r, J=0 and the move returns to the start.
        """
        self._send(f'G02 I{-r:.3f} J0 F{self.cfg["speed_pendown"]}')

# ── Plot worker ───────────────────────────────────────────────────────────────

def _plot_worker(job, request_id=None):
    plotter = None
    done = 0
    w = WideEvent('worker.plot', request_id)
    w.set(resumed=bool(job.get('next_path') or job.get('next_copy')))
    try:
        svg_bytes = _plot_job_svg_bytes(job)
        settings = job.get('settings') or cfg.copy()
        placement = job.get('placement') or {'x': 0.0, 'y': 0.0}
        w.set(port=settings.get('port'))
        _checkpoint_plot_job(job, status='running')

        emit('state', state='homing')
        plotter = PlotterConn(settings['port'], settings)
        emit('log', msg='Homing…')
        plotter.home()
        plotter.init()
        plotter.pen_up()
        emit('log', msg='Homed. Parsing SVG…')
        emit('state', state='parsing')

        def on_parse_progress(done, total):
            emit('progress', done=done, total=total)

        polylines = _resolve_polylines(svg_bytes, settings, placement,
                                       on_progress=on_parse_progress)
        if not polylines:
            _checkpoint_plot_job(job, status='error', error='No paths found in SVG.')
            emit('state', state='error')
            emit('error', msg='No paths found in SVG.')
            w.emit('error', level=logging.ERROR, error='No paths found in SVG.')
            return

        copies = max(1, int(settings.get('copies', 1) or 1))
        segments_by_path = [max(0, len(poly) - 1) for poly in polylines]
        prefix_segments = [0]
        for count in segments_by_path:
            prefix_segments.append(prefix_segments[-1] + count)
        total_per_copy = sum(len(p) - 1 for p in polylines)
        total = total_per_copy * copies
        total_shapes = len(polylines) * copies
        estimate = _estimate_polylines(polylines, settings)
        estimated_seconds = estimate.get('estimated_seconds')
        started_at = time.time()
        total_paths = len(polylines)
        w.set(copies=copies, paths=total_paths, shapes=total_shapes,
              segments=total, est_seconds=estimated_seconds)
        start_copy = max(0, min(copies, int(job.get('next_copy', 0) or 0)))
        start_path = max(0, int(job.get('next_path', 0) or 0))
        if total_paths and start_path >= total_paths:
            start_copy = min(copies, start_copy + start_path // total_paths)
            start_path = start_path % total_paths
        if start_copy >= copies:
            start_path = 0
        done_shapes = min(total_shapes, start_copy * total_paths + start_path)
        done = min(total, start_copy * total_per_copy + prefix_segments[start_path])

        _checkpoint_plot_job(
            job,
            status='running',
            copies=copies,
            total_paths=total_paths,
            total_shapes=total_shapes,
            total_segments=total,
            next_copy=start_copy,
            next_path=start_path,
            completed_shapes=done_shapes,
            completed_segments=done,
        )

        emit('state', state='plotting', total=total, done=done,
             shapes_total=total_shapes, shapes_done=done_shapes,
             estimated_seconds=estimated_seconds)
        emit('progress', phase='plotting',
             **_plot_progress_payload(done, total, done_shapes, total_shapes,
                                      started_at, estimated_seconds=estimated_seconds))
        if done_shapes:
            emit('log', msg=f'Resuming at copy {start_copy + 1}, path {start_path + 1}.')
        emit('log', msg=f'Plotting {len(polylines)} paths, {total_per_copy} segments per copy…')

        for copy_i in range(start_copy, copies):
            if _stop_event.is_set():
                raise RuntimeError('__stopped__')
            path_start = start_path if copy_i == start_copy else 0
            if copy_i > 0 and path_start == 0:
                delay = settings.get('page_delay', 15)
                emit('log', msg=f'Waiting {delay}s before copy {copy_i + 1}…')
                for _ in range(delay * 10):
                    if _stop_event.is_set():
                        raise RuntimeError('__stopped__')
                    time.sleep(0.1)

            for path_i, poly in enumerate(polylines[path_start:], start=path_start):
                if _stop_event.is_set():
                    raise RuntimeError('__stopped__')
                plotter.move(poly[0][0], poly[0][1])
                plotter.pen_down()
                arc = getattr(poly, 'arc', None)
                if arc is not None:
                    # one native G2 instead of len(poly)-1 straight segments
                    plotter.arc(arc['cx'], arc['cy'], arc['r'])
                    done += max(0, len(poly) - 1)
                    emit('progress', phase='plotting',
                         **_plot_progress_payload(done, total, done_shapes, total_shapes,
                                                  started_at, estimated_seconds=estimated_seconds))
                else:
                    for pt in poly[1:]:
                        if _stop_event.is_set():
                            raise RuntimeError('__stopped__')
                        plotter.draw(pt[0], pt[1])
                        done += 1
                        if done % 25 == 0:
                            emit('progress', phase='plotting',
                                 **_plot_progress_payload(done, total, done_shapes, total_shapes,
                                                          started_at, estimated_seconds=estimated_seconds))
                plotter.pen_up()
                next_copy = copy_i
                next_path = path_i + 1
                if next_path >= total_paths:
                    next_copy += 1
                    next_path = 0
                done_shapes = min(total_shapes, next_copy * total_paths + next_path)
                done = min(total, next_copy * total_per_copy + prefix_segments[next_path])
                _checkpoint_plot_job(
                    job,
                    status='running',
                    next_copy=next_copy,
                    next_path=next_path,
                    completed_shapes=done_shapes,
                    completed_segments=done,
                )
                emit('progress', phase='plotting',
                     **_plot_progress_payload(done, total, done_shapes, total_shapes,
                                              started_at, estimated_seconds=estimated_seconds))

        plotter.pen_up()
        emit('log', msg='Returning home…')
        plotter.move(0, 0)
        _checkpoint_plot_job(
            job,
            status='done',
            next_copy=copies,
            next_path=0,
            completed_shapes=total_shapes,
            completed_segments=total,
        )
        emit('state', state='done')
        emit('progress', phase='plotting',
             **_plot_progress_payload(total, total, total_shapes, total_shapes,
                                      started_at, estimated_seconds=estimated_seconds))
        emit('log', msg='Done!')
        w.emit('success', done_segments=total)

    except Exception as exc:
        if _stop_event.is_set() or '__stopped__' in str(exc):
            if job:
                _checkpoint_plot_job(job, status='stopped')
            emit('state', state='idle')
            emit('log', msg='Stopped.')
            w.emit('stopped', done_segments=done)
        else:
            if job:
                _checkpoint_plot_job(job, status='error', error=str(exc))
            emit('state', state='error')
            emit('error', msg=str(exc))
            w.emit('error', level=logging.ERROR, error=str(exc), done_segments=done)
    finally:
        if plotter:
            plotter.close()

# ── Routes ────────────────────────────────────────────────────────────────────

SPA_DIR = Path(app.static_folder) / 'app'

_FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#1a1a1c"/>'
    '<circle cx="16" cy="16" r="9" fill="none" stroke="#2e8bff" stroke-width="2"/>'
    '<circle cx="16" cy="16" r="2.4" fill="#2e8bff"/>'
    '<path d="M16 3v5M16 24v5M3 16h5M24 16h5" stroke="#2e8bff" stroke-width="2" stroke-linecap="round"/>'
    '</svg>'
)

@app.route('/favicon.ico')
def favicon():
    return Response(_FAVICON, mimetype='image/svg+xml',
                   headers={'Cache-Control': 'max-age=86400'})

@app.route('/')
def index():
    spa = SPA_DIR / 'index.html'
    if spa.exists():
        return send_file(spa)
    # Fallback to the legacy template until the SPA is built.
    return render_template('index.html', cfg=cfg)

@app.route('/api/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    if not f:
        return jsonify(error='No file'), 400
    if not f.filename.lower().endswith('.svg'):
        return jsonify(error='SVG files only'), 400
    svg = f.read().decode('utf-8', 'replace')
    _replace_selected_composition_layer(
        svg,
        f.filename,
        'svg',
        {'filename': f.filename},
    )
    return jsonify(
        name=f.filename,
        composition=_composition_payload(),
    )

@app.route('/api/placement', methods=['POST'])
def placement_route():
    global _placement
    data = request.json or {}
    _placement = {
        'x': float(data.get('x', 0)),
        'y': float(data.get('y', 0)),
    }
    return jsonify(ok=True)

@app.route('/api/plot/estimate')
def plot_estimate():
    _ensure_current_svg()
    if _current_svg is None:
        return jsonify(error='No SVG loaded'), 400
    try:
        settings = cfg.copy()
        polylines = _placed_polylines(
            _current_svg, settings, placement={'x': 0.0, 'y': 0.0}, respect_stop=False
        )
        if not polylines:
            return jsonify(error='No paths found in SVG.'), 400
        return jsonify(ok=True, **_estimate_polylines(polylines, settings))
    except Exception as exc:
        return jsonify(error=str(exc)), 500

@app.route('/api/plot/job')
def plot_job_route():
    return jsonify(_plot_job_public(_load_plot_job()))

@app.route('/api/plot', methods=['POST'])
def plot():
    global _plot_thread, _stop_event
    with _operation_lock:
        _ensure_current_svg()
        if _current_svg is None:
            return jsonify(error='No SVG loaded'), 400
        if _plot_thread and _plot_thread.is_alive():
            return jsonify(error='Already plotting'), 400
        _reset_events('state')
        _stop_event.clear()
        job = _create_plot_job(_current_svg, cfg.copy(), {'x': 0.0, 'y': 0.0})
        _plot_thread = threading.Thread(
            target=_plot_worker, args=(job, g.request_id), daemon=True
        )
        _plot_thread.start()
        return jsonify(ok=True, job=_plot_job_public(job))

@app.route('/api/plot/resume', methods=['POST'])
def resume_plot():
    global _plot_thread, _stop_event
    with _operation_lock:
        job = _normalised_plot_job(_load_plot_job())
        public = _plot_job_public(job)
        if not public.get('exists'):
            return jsonify(error='No saved plot job'), 404
        if not public.get('resumable'):
            return jsonify(error='Saved plot job is not resumable'), 400
        if _plot_thread and _plot_thread.is_alive():
            return jsonify(error='Already plotting'), 400
        _reset_events('state')
        _stop_event.clear()
        _plot_thread = threading.Thread(
            target=_plot_worker, args=(job, g.request_id), daemon=True
        )
        _plot_thread.start()
        return jsonify(ok=True, job=_plot_job_public(job))

@app.route('/api/plot/discard', methods=['POST'])
def discard_plot_job():
    if _plot_thread and _plot_thread.is_alive():
        return jsonify(error='Cannot discard while plotting'), 400
    _delete_plot_job()
    return jsonify(ok=True)

@app.route('/api/stop', methods=['POST'])
def stop_plot():
    _stop_event.set()
    emit('state', state='idle')
    emit('log', msg='Stopped by user.')
    return jsonify(ok=True)

@app.route('/api/stream')
def stream():
    def generate():
        q = _subscribe_events()
        try:
            while True:
                try:
                    evt = q.get(timeout=15)
                    yield f"data: {json.dumps(evt)}\n\n"
                except queue.Empty:
                    yield 'data: {"t":"ping"}\n\n'
        finally:
            _unsubscribe_events(q)
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )

# ── Projects ────────────────────────────────────────────────────────────────

@app.route('/api/projects')
def api_projects():
    return jsonify(projects=project_mod.list_projects(), current=_project_public(_project))

@app.route('/api/projects', methods=['POST'])
def api_project_create():
    with _operation_lock:
        blocked = _project_transition_blocked()
        if blocked:
            return blocked
        name = (request.json or {}).get('name') or 'Untitled'
        p = project_mod.create_project(name)
        _switch_project(p.id)
        return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())

@app.route('/api/projects/<pid>/open', methods=['POST'])
def api_project_open(pid):
    with _operation_lock:
        if not (project_mod.PROJECTS_DIR / pid / 'project.json').exists():
            return jsonify(error='Unknown project'), 404
        blocked = _project_transition_blocked()
        if blocked:
            return blocked
        _switch_project(pid)
        return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())

@app.route('/api/projects/<pid>', methods=['PATCH'])
def api_project_rename(pid):
    name = str((request.json or {}).get('name') or '').strip() or 'Untitled'
    if pid == _project.id:
        _project.name = name
        _project.save()
    elif (project_mod.PROJECTS_DIR / pid / 'project.json').exists():
        p = Project.load(pid)
        p.name = name
        p.save()
    else:
        return jsonify(error='Unknown project'), 404
    return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())

@app.route('/api/projects/<pid>', methods=['DELETE'])
def api_project_delete(pid):
    with _operation_lock:
        if pid == _project.id:
            blocked = _project_transition_blocked()
            if blocked:
                return blocked
        project_mod.delete_project(pid)
        if pid == _project.id:
            remaining = project_mod.list_projects()
            next_id = (remaining[0]['id'] if remaining
                       else project_mod.create_project('Untitled').id)
            _switch_project(next_id)
        return jsonify(ok=True, current=_project_public(_project), projects=project_mod.list_projects())

@app.route('/api/composition')
def api_composition():
    _sync_current_svg_from_composition()
    return jsonify(
        composition=_composition_payload(),
    )

@app.route('/api/composition/layers/<layer_id>', methods=['PATCH'])
def api_composition_layer(layer_id):
    data = request.json or {}
    layer = _layer_by_id(layer_id)
    if not layer:
        return jsonify(error='Unknown layer'), 404
    if 'name' in data:
        layer.name = str(data['name'])
    if 'visible' in data:
        layer.visible = bool(data['visible'])
    if 'x' in data:
        layer.x = float(data['x'])
    if 'y' in data:
        layer.y = float(data['y'])
    if 'scale' in data:
        layer.scale = max(0.01, float(data['scale']))
    if 'crop' in data:
        layer.crop = _validate_crop(data['crop'])
    if 'mask' in data:
        layer.mask = _validate_mask(data['mask'])
    if 'region_id' in data:
        region_id = data.get('region_id') or None
        if region_id and _project.get_region(region_id) is None:
            return jsonify(error='Unknown region'), 404
        layer.region_id = region_id
        region = _project.get_region(region_id)
        layer.occlusion_mask = _region_occlusion_mask(region, layer) if region else None
        _mark_layer_style_stale(layer)
    if 'display_mode' in data:
        try:
            layer.display_mode = _normalize_display_mode(data.get('display_mode'))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    if 'occlude_below' in data:
        layer.occlude_below = bool(data.get('occlude_below'))
    if 'occlusion_mask' in data:
        layer.occlusion_mask = _validate_mask(data['occlusion_mask'])
    if 'pathfinding_style' in data:
        before = json.dumps(layer.pathfinding_style or {}, sort_keys=True)
        style = _normalize_pathfinding_style(layer.pathfinding_style)
        style.update(dict(data.get('pathfinding_style') or {}))
        style = _normalize_pathfinding_style(style)
        after = json.dumps(style, sort_keys=True)
        if after != before and 'status' not in (data.get('pathfinding_style') or {}):
            style['status'] = 'stale'
        layer.pathfinding_style = style
    if data.get('selected'):
        _composition().selected_layer_id = layer.id
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(
        ok=True,
        composition=_composition_payload(),
    )


def _validate_crop(value):
    if not value:
        return None
    return {k: float(value[k]) for k in ('x', 'y', 'width', 'height')}


def _validate_mask(value):
    if not value:
        return None
    kind = value.get('type')
    if kind == 'rect':
        return {'type': 'rect', **{k: float(value[k]) for k in ('x', 'y', 'width', 'height')}}
    if kind == 'ellipse':
        return {'type': 'ellipse', **{k: float(value[k]) for k in ('cx', 'cy', 'rx', 'ry')}}
    if kind == 'path':
        return {'type': 'path', 'd': str(value.get('d') or '')}
    raise ValueError(f'Unknown mask type: {kind!r}')


@app.route('/api/composition/layers/<layer_id>/crop-to-content', methods=['POST'])
def api_crop_to_content(layer_id):
    from engine.layer_clip import layer_content_bbox
    layer = next((l for l in _composition().layers if l.id == layer_id), None)
    if not layer:
        return jsonify(error='Unknown layer'), 404
    box = layer_content_bbox(layer.svg)
    if not box:
        return jsonify(error='Layer has no content to crop'), 400
    x0, y0, x1, y1 = box
    x0 = max(0.0, x0)
    y0 = max(0.0, y0)
    x1 = min(float(layer.width), x1)
    y1 = min(float(layer.height), y1)
    layer.crop = {'x': x0, 'y': y0, 'width': max(0.0, x1 - x0), 'height': max(0.0, y1 - y0)}
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(ok=True, composition=_composition_payload())

@app.route('/api/composition/layers/<layer_id>/duplicate', methods=['POST'])
def api_duplicate_layer(layer_id):
    layer = _composition().duplicate_layer(layer_id)
    if not layer:
        return jsonify(error='Unknown layer'), 404
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(
        ok=True,
        composition=_composition_payload(),
    )

@app.route('/api/composition/new-layer', methods=['POST'])
def api_new_layer():
    # Clear the selection so the next generate / pathfinding / upload creates a
    # fresh layer instead of replacing the current one.
    _composition().selected_layer_id = None
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(ok=True, composition=_composition_payload())

@app.route('/api/composition/add-layer', methods=['POST'])
def api_add_layer():
    # Create a real, selectable empty path-finding layer the size of the page.
    # The floating Path Finding window then fills it via /pathfinding/generate.
    data = request.json or {}
    comp = _composition()
    page = comp.page or {}
    w = float(page.get('width') or 297)
    h = float(page.get('height') or 420)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" '
        f'height="{h}mm" viewBox="0 0 {w} {h}"></svg>'
    )
    name = (data.get('name') or '').strip() or f'Layer {len(comp.layers) + 1}'
    layer = comp.add_layer(svg, name, 'pathfinding', {})
    region_id = data.get('region_id') or None
    if region_id and _project.get_region(region_id):
        layer.region_id = region_id
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(ok=True, composition=_composition_payload())

@app.route('/api/composition/layers/<layer_id>', methods=['DELETE'])
def api_delete_layer(layer_id):
    if not _composition().delete_layer(layer_id):
        return jsonify(error='Unknown layer'), 404
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(
        ok=True,
        composition=_composition_payload(),
    )

@app.route('/api/composition/layers/<layer_id>/move', methods=['POST'])
def api_move_layer(layer_id):
    direction = int((request.json or {}).get('direction', 0))
    if not _composition().move_layer(layer_id, direction):
        return jsonify(error='Cannot move layer'), 400
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    return jsonify(
        ok=True,
        composition=_composition_payload(),
    )

@app.route('/api/composition/layers/<layer_id>/raster')
def api_composition_layer_raster(layer_id):
    layer = _layer_by_id(layer_id)
    if not layer:
        return jsonify(error='Unknown layer'), 404
    region_id = layer.region_id or (layer.source or {}).get('region_id')
    image = _project.open_region_image(region_id) if region_id else _project.open_image()
    if image is None:
        return jsonify(error='No region image available'), 404
    # Match what pathfinding analysed (area.prepare_image), so the displayed
    # raster lines up with the generated paths instead of being stretched to a
    # different aspect ratio. ponytail: reuses prepare_image, no separate path.
    image = _project.area.prepare_image(image)
    buf = io.BytesIO()
    image.convert('RGBA').save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

def _generate_pathfinding_for_layer(layer, data, wide=None):
    if _project.image_path is None or not _project.image_path.exists():
        return None, ('No image loaded', 400)
    style = _normalize_pathfinding_style(layer.pathfinding_style)
    pfm_id = data.get('pfm_id') or style.get('pfm_id') or _project.pfm_id
    if pfm_id not in REGISTRY:
        return None, ('Unknown PFM', 400)
    # When the request carries a region_id key (the UI always does), honour it
    # verbatim — including an explicit null meaning "whole image". Only fall back
    # to the layer's stored region when the key is absent, so switching a layer
    # back to the whole image actually takes effect instead of re-using the old
    # region from layer.source.
    if 'region_id' in data:
        region_id = data.get('region_id') or None
    else:
        region_id = layer.region_id or (layer.source or {}).get('region_id')
    region = _project.get_region(region_id) if region_id else None
    if region_id and region is None:
        return None, (f'Unknown region {region_id!r}', 404)
    _area_from(data.get('area'))
    _drawing_set_from(data.get('drawing_set'))
    pfm = get_pfm(pfm_id)
    params = validate(pfm.params, data.get('params') or style.get('params') or {})
    seed = int(data.get('seed', params.get('seed', 0)) or 0)
    if wide is not None:
        wide.set(pfm_id=pfm_id, region_id=region_id or '-', seed=seed,
                 params=_params_summary(params), backend=accel.backend_name())
    # No region -> the effect runs on the whole layer image.
    img = _project.open_region_image(region_id) if region else _project.open_image()
    if img is None:
        return None, ('No image available', 404)
    layer.pathfinding_style = {
        **style,
        'enabled': bool(data.get('enabled', style.get('enabled', True))),
        'pfm_id': pfm_id,
        'params': params,
        'status': 'generating',
        'error': '',
    }
    on_progress = wide.wrap_progress() if wide is not None else None
    drawing = pfm.run(img, _project.area, _project.drawing_set, params, seed=seed,
                      on_progress=on_progress)
    if wide is not None:
        try:  # logging is best-effort — never let metric extraction break generation
            wide.set(shapes=drawing.total(),
                     length_mm=round(svg_io.estimate_path_length_mm(drawing)))
        except Exception:
            pass
    svg = svg_io.to_svg(drawing)
    layer.svg = svg
    layer.width, layer.height = parse_svg_size_mm(svg)
    layer.kind = 'pathfinding'
    layer.region_id = region.id if region else None
    layer.display_mode = _normalize_display_mode(data.get('display_mode') or layer.display_mode)
    layer.source = {
        'pfm_id': pfm_id,
        'params': params,
        'area': _project.area.to_dict(),
        'drawing_set': _project.drawing_set.to_dict(),
        'region_id': region.id if region else None,
        'region_name': region.name if region else None,
    }
    # With a region, occlude only its bounding box; otherwise the layer occludes
    # everything beneath its full footprint.
    layer.occlusion_mask = (
        _region_occlusion_mask(region, layer) if region
        else {'type': 'rect', 'x': 0.0, 'y': 0.0,
              'width': round(layer.width, 4), 'height': round(layer.height, 4)}
    )
    layer.pathfinding_style = {
        'enabled': bool(data.get('enabled', style.get('enabled', True))),
        'pfm_id': pfm_id,
        'params': params,
        'status': 'clean',
        'error': '',
        'cache': {
            'generated_at': time.time(),
            'svg_path': layer.svg_path,
            'region_id': region.id if region else None,
        },
    }
    return drawing, None

@app.route('/api/composition/layers/<layer_id>/pathfinding/generate', methods=['POST'])
def api_composition_layer_pathfinding_generate(layer_id):
    global _drawing
    data = request.json or {}
    layer = _layer_by_id(layer_id)
    if not layer:
        return jsonify(error='Unknown layer'), 404
    w = WideEvent('worker.pathfinding', g.request_id)
    w.set(layer_id=layer_id)
    try:
        drawing, error = _generate_pathfinding_for_layer(layer, data, wide=w)
    except Exception as exc:
        # Never surface a blank error — some exceptions stringify to "".
        message = str(exc) or f'{type(exc).__name__} during path finding'
        style = _normalize_pathfinding_style(layer.pathfinding_style)
        style['status'] = 'error'
        style['error'] = message
        layer.pathfinding_style = style
        _project.save_composition_layers()
        w.emit('error', level=logging.ERROR, error=message)
        return jsonify(error=message, composition=_composition_payload()), 500
    if error:
        message, status = error
        w.emit('error', level=logging.WARNING, error=message)
        return jsonify(error=message), status
    _drawing = drawing
    _project.save_composition_layers()
    _sync_current_svg_from_composition()
    w.emit('success')
    return jsonify(ok=True, composition=_composition_payload())

@app.route('/api/settings', methods=['GET', 'POST'])
def settings_route():
    global cfg
    if request.method == 'POST':
        data = request.json or {}
        for k, v in data.items():
            if k in DEFAULTS:
                ref = DEFAULTS[k]
                if isinstance(ref, bool):
                    cfg[k] = bool(v)
                elif isinstance(ref, int):
                    cfg[k] = int(float(v))
                elif isinstance(ref, float):
                    cfg[k] = float(v)
                else:
                    cfg[k] = v
        save_cfg(cfg)
        return jsonify(ok=True, cfg=cfg)
    return jsonify(cfg)

@app.route('/api/manual', methods=['POST'])
def manual():
    data = request.json or {}
    cmd  = data.get('cmd')
    try:
        ser = open_serial(cfg['port'], timeout=5)
        time.sleep(2)
        if ser.in_waiting:
            ser.read(ser.in_waiting)

        def send(c, timeout=10):
            ser.write((c + '\n').encode())
            t0 = time.time()
            while time.time() - t0 < timeout:
                ln = ser.readline().decode('utf-8', 'replace').strip()
                if ln.lower() == 'ok':
                    return ln
            return ''

        send('$X')
        result = {}

        if cmd == 'home':
            ser.write(b'$H\n')
            t0 = time.time()
            while time.time() - t0 < 30:
                ln = ser.readline().decode('utf-8', 'replace').strip()
                if ln.lower() == 'ok':
                    break
        elif cmd == 'pen_up':
            send('G21'); send('G90')
            send(f"G00 Z{cfg['pen_pos_up']} F{cfg['pen_rate_raise']}")
        elif cmd == 'pen_down':
            send('G21'); send('G90')
            send(f"G00 Z{cfg['pen_pos_down']} F{cfg['pen_rate_lower']}")
        elif cmd == 'motors_off':
            send('$SLP')
        elif cmd == 'walk':
            dx = float(data.get('dx', 0))
            dy = float(data.get('dy', 0))
            send('G21'); send('G91')
            send(f'G00 X{dx:.2f} Y{-dy:.2f} F{cfg["speed_penup"]}')
            send('G90')
        elif cmd == 'status':
            ser.write(b'?\n')
            time.sleep(0.3)
            result['status'] = ser.read(ser.in_waiting).decode('utf-8', 'replace').strip()
        elif cmd == 'cycle_pen':
            send('G21'); send('G90')
            send(f"G00 Z{cfg['pen_pos_down']} F{cfg['pen_rate_lower']}")
            time.sleep(0.5)
            send(f"G00 Z{cfg['pen_pos_up']} F{cfg['pen_rate_raise']}")

        ser.close()
        return jsonify(ok=True, **result)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


# ponytail: test-only — exposes captured fake-serial G-code so e2e can assert
# emitted commands (K7). Only registered when the fake serial is active.
if os.environ.get('PLOTTER_FAKE_SERIAL'):
    @app.route('/api/_test/serial-log', methods=['GET', 'DELETE'])
    def _test_serial_log():
        if request.method == 'DELETE':
            _FAKE_SERIAL_WRITES.clear()
            return jsonify(ok=True)
        return jsonify(writes=list(_FAKE_SERIAL_WRITES))

# ── Studio: image → PFM → drawing ──────────────────────────────────────────────

def _area_from(data):
    """Update the project's drawing area from a request dict, persist, return it."""
    if data:
        _project.area = DrawingArea.from_dict({**_project.area.to_dict(), **data})
    return _project.area

def _drawing_set_from(data):
    if data:
        _project.drawing_set = DrawingSet.from_dict(data)
    return _project.drawing_set

@app.route('/api/image', methods=['POST'])
def api_image():
    f = request.files.get('file')
    if not f:
        return jsonify(error='No file'), 400
    data = f.read()
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        w, h = im.size
    except Exception as exc:
        return jsonify(error=f'Not a readable image: {exc}'), 400
    _project.set_image(data, f.filename)
    image_url = f'/api/source-image?v={int(time.time() * 1000)}'
    return jsonify(ok=True, width=w, height=h, name=f.filename,
                   image_url=image_url)

@app.route('/api/source-image')
def api_source_image():
    ip = _project.image_path
    if not ip or not ip.exists():
        return jsonify(error='No image loaded'), 404
    return send_file(ip)

@app.route('/api/segmentation/status')
def api_segmentation_status():
    return jsonify(_get_segmentation_adapter().status())

@app.route('/api/segmentation/model', methods=['POST'])
def api_segmentation_model():
    adapter = _get_segmentation_adapter()
    try:
        adapter.set_model((request.json or {}).get('model'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    cfg['sam_model'] = adapter.model
    save_cfg(cfg)
    return jsonify(adapter.status())

@app.route('/api/segmentation/predict', methods=['POST'])
def api_segmentation_predict():
    data = request.json or {}
    image = _project.open_image()
    if image is None:
        return jsonify(error='No image loaded'), 400
    positive = _clean_points(data.get('positive_points'))
    negative = _clean_points(data.get('negative_points'))
    if not positive:
        return jsonify(error='At least one positive point is required'), 400
    adapter = _get_segmentation_adapter()
    w = WideEvent('worker.segmentation', g.request_id)
    w.set(model=getattr(adapter, 'model', '-'), n_pos=len(positive), n_neg=len(negative))
    try:
        mask = adapter.predict(image, positive, negative)
    except Exception as exc:
        w.emit('error', level=logging.ERROR, error=str(exc))
        return jsonify(error=str(exc), status=adapter.status()), 503
    bbox = mask_bbox(mask)
    w.emit('success', bbox=str(bbox))
    return jsonify(
        ok=True,
        mask_png=_png_data_url(mask),
        bbox_px=bbox,
        positive_points=positive,
        negative_points=negative,
    )

@app.route('/api/regions')
def api_regions():
    return jsonify(_regions_payload())

@app.route('/api/regions', methods=['POST'])
def api_regions_create():
    data = request.json or {}
    try:
        mask = _image_from_data_url(data.get('mask_png'))
    except Exception as exc:
        return jsonify(error=f'Invalid mask: {exc}'), 400
    if data.get('invert'):
        from PIL import ImageOps

        mask = ImageOps.invert(mask)
    region = _project.add_region(
        name=str(data.get('name') or 'Region'),
        mask=mask,
        positive_points=_clean_points(data.get('positive_points')),
        negative_points=_clean_points(data.get('negative_points')),
        bbox_px=data.get('bbox_px') or mask_bbox(mask),
    )
    return jsonify(ok=True, region=region.to_dict(), **_regions_payload())

@app.route('/api/regions/<region_id>', methods=['PATCH'])
def api_regions_update(region_id):
    data = request.json or {}
    changes = {}
    if 'name' in data:
        changes['name'] = data.get('name')
    if 'mask_png' in data:
        try:
            changes['mask'] = _image_from_data_url(data.get('mask_png'))
        except Exception as exc:
            return jsonify(error=f'Invalid mask: {exc}'), 400
    if 'positive_points' in data:
        changes['positive_points'] = _clean_points(data.get('positive_points'))
    if 'negative_points' in data:
        changes['negative_points'] = _clean_points(data.get('negative_points'))
    if 'bbox_px' in data:
        changes['bbox_px'] = data.get('bbox_px')
    region = _project.update_region(region_id, **changes)
    if region is None:
        return jsonify(error='Unknown region'), 404
    return jsonify(ok=True, region=region.to_dict(), **_regions_payload())

@app.route('/api/regions/<region_id>', methods=['DELETE'])
def api_regions_delete(region_id):
    if not _project.delete_region(region_id):
        return jsonify(error='Unknown region'), 404
    return jsonify(ok=True, **_regions_payload())

@app.route('/api/regions/<region_id>/mask')
def api_regions_mask(region_id):
    region = _project.get_region(region_id)
    if region is None:
        return jsonify(error='Unknown region'), 404
    path = _project.dir / region.mask_path
    if not path.exists():
        return jsonify(error='Region mask missing'), 404
    return send_file(path, mimetype='image/png')

@app.route('/api/pfm/list')
def api_pfm_list():
    return jsonify(pfms=list_pfms(), backend=accel.backend_name())

@app.route('/api/pfm/<pfm_id>/schema')
def api_pfm_schema(pfm_id):
    if pfm_id not in REGISTRY:
        return jsonify(error='Unknown PFM'), 404
    p = get_pfm(pfm_id)
    return jsonify(id=p.id, name=p.name, family=p.family, style=p.style,
                   params=schema_json(p.params))

def _process_worker(pfm_id, params, seed, region_id=None, request_id=None):
    global _drawing, _current_svg
    w = WideEvent('worker.pfm', request_id)
    w.set(pfm_id=pfm_id, region_id=region_id or '-', seed=seed,
          params=_params_summary(params), backend=accel.backend_name())
    try:
        emit('proc', state='running', pfm=pfm_id)
        img = _project.open_region_image(region_id) if region_id else _project.open_image()
        if img is None:
            emit('proc', state='error', msg='No image loaded')
            w.emit('error', level=logging.ERROR, error='No image loaded')
            return
        pfm = get_pfm(pfm_id)
        region = _project.get_region(region_id) if region_id else None

        on_progress = w.wrap_progress(
            lambda stage, frac: emit('proc', state='progress', stage=stage, frac=frac))

        drawing = pfm.run(img, _project.area, _project.drawing_set,
                          params, seed=seed, on_progress=on_progress)
        svg = svg_io.to_svg(drawing)
        _drawing = drawing
        _project.pfm_id = pfm_id
        _project.params = validate(pfm.params, params)
        layer = _set_workflow_layer(
            svg,
            pfm.name,
            'pathfinding',
            {
                'pfm_id': pfm_id,
                'params': _project.params,
                'area': _project.area.to_dict(),
                'drawing_set': _project.drawing_set.to_dict(),
                'region_id': region.id if region else None,
                'region_name': region.name if region else None,
            },
        )
        layer.region_id = region.id if region else None
        layer.display_mode = 'pathfinding'
        layer.pathfinding_style = {
            'enabled': True,
            'pfm_id': pfm_id,
            'params': _project.params,
            'status': 'clean',
            'error': '',
            'cache': {
                'generated_at': time.time(),
                'svg_path': layer.svg_path,
                'region_id': region.id if region else None,
            },
        }
        layer.occlusion_mask = _region_occlusion_mask(region, layer) if region else None
        _project.save_composition_layers()
        _project.save()
        per_pen = [{'name': l.pen.name, 'colour': l.pen.colour, 'count': l.count()}
                   for l in drawing.layers if l.count()]
        total = drawing.total()
        length_mm = round(svg_io.estimate_path_length_mm(drawing))
        emit('proc', state='done',
             svg=_current_svg.decode('utf-8', 'replace') if _current_svg else svg,
             composition=_composition_payload(),
             total=total,
             length_mm=length_mm,
             backend=accel.backend_name(),
             per_pen=per_pen)
        w.emit('success', shapes=total, length_mm=length_mm)
    except Exception as exc:
        emit('proc', state='error', msg=str(exc))
        w.emit('error', level=logging.ERROR, error=str(exc))

@app.route('/api/process', methods=['POST'])
def api_process():
    global _process_thread
    with _operation_lock:
        data = request.json or {}
        pfm_id = data.get('pfm_id') or _project.pfm_id
        if pfm_id not in REGISTRY:
            return jsonify(error='Unknown PFM'), 400
        if _project.image_path is None or not _project.image_path.exists():
            return jsonify(error='No image loaded'), 400
        region_id = data.get('region_id') or None
        if region_id and _project.get_region(region_id) is None:
            return jsonify(error='Unknown region'), 404
        if _process_thread and _process_thread.is_alive():
            return jsonify(error='Already processing'), 409
        _area_from(data.get('area'))
        _drawing_set_from(data.get('drawing_set'))
        params = data.get('params') or {}
        seed = int(data.get('seed', params.get('seed', 0)) or 0)
        _clear_last_proc_events()
        _process_thread = threading.Thread(
            target=_process_worker,
            args=(pfm_id, params, seed, region_id, g.request_id),
            daemon=True,
        )
        _process_thread.start()
        return jsonify(ok=True)

# ── Generate step (rule-based drawing, no input image) ──────────────────────────

def _generate_worker(gid, params, seed, request_id=None):
    global _drawing, _current_svg
    ev = WideEvent('worker.generate', request_id)
    ev.set(gid=gid, seed=seed, params=_params_summary(params), backend='generator')
    try:
        emit('proc', state='running', pfm=gid)
        gen = get_generator(gid)
        vals = validate(gen['params'], params)
        emit('proc', state='progress', stage='generating', frac=0.3)
        with ev.time('generating'):
            lines, w_cm, h_cm = gen['fn'](vals, seed=seed)          # cm
        emit('proc', state='progress', stage='transforming', frac=0.6)
        with ev.time('transforming'):
            lines, extras = apply_framework(lines, w_cm, h_cm, vals, seed)
        lines = lines + extras
        lines = [[(x * 10.0, y * 10.0) for x, y in ln] for ln in lines]  # cm -> mm
        w_mm, h_mm = w_cm * 10.0, h_cm * 10.0
        pen = _project.drawing_set.active()[0]
        svg = svg_io.lines_to_svg(lines, w_mm, h_mm, colour=pen.colour, stroke_mm=pen.stroke_mm)
        _drawing = None                       # generators output flat polylines, not a Drawing
        _set_workflow_layer(
            svg,
            gen['name'],
            'generate',
            {'generator_id': gid, 'params': vals},
        )
        length_mm = round(svg_io.lines_length_mm(lines))
        emit('proc', state='done',
             svg=_current_svg.decode('utf-8', 'replace') if _current_svg else svg,
             composition=_composition_payload(),
             total=len(lines),
             length_mm=length_mm,
             backend='generator',
             per_pen=[{'name': pen.name, 'colour': pen.colour, 'count': len(lines)}])
        ev.emit('success', shapes=len(lines), length_mm=length_mm)
    except Exception as exc:
        emit('proc', state='error', msg=str(exc))
        ev.emit('error', level=logging.ERROR, error=str(exc))

@app.route('/api/generate/list')
def api_generate_list():
    return jsonify(generators=list_generators())

@app.route('/api/generate/<gid>/schema')
def api_generate_schema(gid):
    if gid not in GENERATORS:
        return jsonify(error='Unknown generator'), 404
    g = get_generator(gid)
    return jsonify(id=g['id'], name=g['name'], params=schema_json(g['params']))

@app.route('/api/generate', methods=['POST'])
def api_generate():
    global _process_thread
    with _operation_lock:
        data = request.json or {}
        gid = data.get('generator_id')
        if gid not in GENERATORS:
            return jsonify(error='Unknown generator'), 400
        if _process_thread and _process_thread.is_alive():
            return jsonify(error='Already busy'), 409
        params = data.get('params') or {}
        seed = int(data.get('seed', params.get('seed', 0)) or 0)
        _clear_last_proc_events()
        _process_thread = threading.Thread(
            target=_generate_worker, args=(gid, params, seed, g.request_id), daemon=True)
        _process_thread.start()
        return jsonify(ok=True)

@app.route('/api/area', methods=['GET', 'POST'])
def api_area():
    if request.method == 'POST':
        _area_from(request.json or {})
        _project.save()
    return jsonify(area=_project.area.to_dict(), presets=AREA_PRESETS)

@app.route('/api/pens', methods=['GET', 'POST'])
def api_pens():
    if request.method == 'POST':
        _drawing_set_from(request.json or {})
        _project.save()
    return jsonify(drawing_set=_project.drawing_set.to_dict(),
                   libraries=list(PEN_LIBRARIES.keys()))

@app.route('/api/pens/library/<name>')
def api_pen_library(name):
    return jsonify(pens=[p.to_dict() for p in library_pens(name)])

@app.route('/api/versions', methods=['GET', 'POST'])
def api_versions():
    if request.method == 'POST':
        data = request.json or {}
        if _drawing is not None:
            v = _project.add_version(_drawing, name=data.get('name', ''),
                                     notes=data.get('notes', ''))
        else:
            svg = _ensure_current_svg() if _composition_has_visible_layers() else None
            if svg is None:
                return jsonify(error='Nothing to save — process a drawing first'), 400
            polylines = svg_to_polylines(
                svg, {**cfg, 'reordering': 'none'}, respect_stop=False
            )
            if not polylines:
                return jsonify(error='Nothing to save — process a drawing first'), 400
            thumbnail = render_polyline_thumbnail(polylines)
            v = _project.add_version(
                None,
                name=data.get('name', ''),
                notes=data.get('notes', ''),
                thumbnail=thumbnail,
            )
        return jsonify(ok=True, version=v.to_dict())
    return jsonify(versions=[v.to_dict() for v in _project.versions])

@app.route('/api/versions/<vid>', methods=['DELETE', 'PATCH'])
def api_version(vid):
    v = _project.get_version(vid)
    if not v:
        return jsonify(error='Unknown version'), 404
    if request.method == 'DELETE':
        _project.delete_version(vid)
        return jsonify(ok=True)
    data = request.json or {}
    if 'rating' in data:
        v.rating = int(data['rating'])
    if 'name' in data:
        v.name = str(data['name'])
    if 'notes' in data:
        v.notes = str(data['notes'])
    _project.save()
    return jsonify(ok=True, version=v.to_dict())

@app.route('/api/versions/<vid>/load', methods=['POST'])
def api_version_load(vid):
    global _drawing
    version = _project.get_version(vid)
    if not version:
        return jsonify(error='Unknown version'), 404
    try:
        if not _project.load_version(vid):
            return jsonify(error='Unknown version'), 404
    except VersionSnapshotError as exc:
        return jsonify(error=str(exc)), 409
    p = get_pfm(_project.pfm_id)
    payload = dict(ok=True, pfm_id=_project.pfm_id,
                   params=_project.params, schema=schema_json(p.params),
                   area=_project.area.to_dict(),
                   drawing_set=_project.drawing_set.to_dict())
    if version.composition_snapshot:
        _drawing = None
        _recompose_current_svg()
        payload['composition'] = _composition_payload()
    return jsonify(payload)

@app.route('/api/versions/<vid>/move', methods=['POST'])
def api_version_move(vid):
    direction = int((request.json or {}).get('direction', 0))
    _project.reorder_version(vid, direction)
    return jsonify(ok=True, versions=[v.to_dict() for v in _project.versions])

@app.route('/api/versions/clear', methods=['POST'])
def api_versions_clear():
    _project.clear_versions()
    return jsonify(ok=True)

@app.route('/api/version-thumb/<vid>')
def api_version_thumb(vid):
    v = _project.get_version(vid)
    if not v:
        return jsonify(error='Unknown version'), 404
    return send_file(_project.dir / v.thumbnail)

@app.route('/api/export')
def api_export():
    if _composition_has_visible_layers():
        if request.args.get('split') == '1':
            return send_file(io.BytesIO(layer_svg_zip(_composition())),
                             mimetype='application/zip',
                             as_attachment=True,
                             download_name='plot_layers.zip')
        svg = compose_visible_svg(_composition())
        return send_file(io.BytesIO(svg.encode()), mimetype='image/svg+xml',
                         as_attachment=True, download_name='plot.svg')
    if _drawing is None:
        # generator output (or uploaded SVG): export the current SVG as-is
        _ensure_current_svg()
        if _current_svg is not None:
            return send_file(io.BytesIO(_current_svg), mimetype='image/svg+xml',
                             as_attachment=True, download_name='plot.svg')
        return jsonify(error='Nothing to export'), 400
    if request.args.get('split') == '1':
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for i, (name, svg) in enumerate(svg_io.to_svg_layers(_drawing)):
                safe = re.sub(r'[^A-Za-z0-9_-]+', '_', name)
                z.writestr(f'{i:02d}_{safe}.svg', svg)
        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name='plot_layers.zip')
    svg = svg_io.to_svg(_drawing)
    return send_file(io.BytesIO(svg.encode()), mimetype='image/svg+xml',
                     as_attachment=True, download_name='plot.svg')


if __name__ == '__main__':
    host = os.environ.get('PLOTTER_HOST', '127.0.0.1')
    port = int(os.environ.get('PLOTTER_PORT', '7438'))
    print(f'Plotter server running at http://{host}:{port}')
    LOG.info('server.start', extra={'fields': {'host': host, 'port': port}})
    app.run(host=host, port=port, debug=False, threaded=True)
