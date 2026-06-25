import os, json, threading, queue, time, tempfile, re, io, zipfile, math, base64, uuid, pickle, hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

import serial
from flask import (
    Flask, render_template, request, jsonify, Response, stream_with_context,
    send_file, send_from_directory,
)

from engine import accel, svg_io
from engine.canvas import DrawingArea, AREA_PRESETS
from engine.pens import DrawingSet, PEN_LIBRARIES, library_pens
from engine.params import schema_json, validate
from engine.pfm import REGISTRY, get as get_pfm, list_pfms
from engine.generate import GENERATORS, get_generator, list_generators
from engine.project import get_or_create

app = Flask(__name__)

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
_current_svg = None   # bytes
_placement   = {'x': 0.0, 'y': 0.0}  # mm offset from page top-left

# ── Studio state (image → PFM → drawing) ───────────────────────────────────────
_project        = get_or_create('default')
_drawing        = None    # last engine.Drawing produced
_process_thread = None
_process_lock   = threading.Lock()

def emit(t, **kw):
    evt = {'t': t, **kw}
    if t in ('proc', 'state'):
        _last_events[t] = evt
    try:
        with _subscribers_lock:
            subscribers = list(_subscribers)
    except Exception:
        subscribers = []
    for q in subscribers:
        try:
            q.put_nowait(evt)
        except queue.Full:
            pass

def _subscribe_events():
    q = queue.Queue(maxsize=300)
    for key in ('proc', 'state'):
        evt = _last_events.get(key)
        if evt:
            try:
                q.put_nowait(evt)
            except queue.Full:
                pass
    with _subscribers_lock:
        _subscribers.add(q)
    return q

def _unsubscribe_events(q):
    with _subscribers_lock:
        _subscribers.discard(q)

def _clear_events():
    with _subscribers_lock:
        subscribers = list(_subscribers)
    for q in subscribers:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

def _clear_last_plot_events():
    for key in ('state',):
        _last_events.pop(key, None)

def _clear_last_proc_events():
    for key in ('proc',):
        _last_events.pop(key, None)

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


def svg_to_polylines(svg_bytes, settings, on_progress=None):
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
        if _stop_event.is_set():
            break

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
    ordered = [polylines[0]]
    remaining = polylines[1:]
    while remaining:
        last = ordered[-1][-1]
        best_i = min(range(len(remaining)),
                     key=lambda i: _dist2(last, remaining[i][0]))
        ordered.append(remaining.pop(best_i))
    return ordered

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

def _placed_polylines(svg_bytes, settings, on_progress=None, placement=None):
    polylines = svg_to_polylines(svg_bytes, settings, on_progress=on_progress)
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
    tmp.replace(PLOT_JOB_PATH)
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

def open_serial(port, timeout=0.1):
    """Open a plotter connection.

    Accepts a local device path ('/dev/ttyACM0', '/Users/me/.idraw-tty') or a
    pyserial URL — notably 'socket://HOST:PORT' to reach a plotter shared over
    the network (e.g. the Pi's socat bridge at socket://100.92.241.24:4000).
    """
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

def _plot_worker(job):
    plotter = None
    try:
        svg_bytes = _plot_job_svg_bytes(job)
        settings = job.get('settings') or cfg.copy()
        placement = job.get('placement') or {'x': 0.0, 'y': 0.0}
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

    except Exception as exc:
        if _stop_event.is_set() or '__stopped__' in str(exc):
            if job:
                _checkpoint_plot_job(job, status='stopped')
            emit('state', state='idle')
            emit('log', msg='Stopped.')
        else:
            if job:
                _checkpoint_plot_job(job, status='error', error=str(exc))
            emit('state', state='error')
            emit('error', msg=str(exc))
    finally:
        if plotter:
            plotter.close()

# ── Routes ────────────────────────────────────────────────────────────────────

SPA_DIR = Path(app.static_folder) / 'app'

@app.route('/')
def index():
    spa = SPA_DIR / 'index.html'
    if spa.exists():
        return send_file(spa)
    # Fallback to the legacy template until the SPA is built.
    return render_template('index.html', cfg=cfg)

@app.route('/api/upload', methods=['POST'])
def upload():
    global _current_svg, _placement
    f = request.files.get('file')
    if not f:
        return jsonify(error='No file'), 400
    if not f.filename.lower().endswith('.svg'):
        return jsonify(error='SVG files only'), 400
    _current_svg = f.read()
    _placement = {'x': 0.0, 'y': 0.0}
    return jsonify(svg=_current_svg.decode('utf-8', 'replace'), name=f.filename)

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
    if _current_svg is None:
        return jsonify(error='No SVG loaded'), 400
    try:
        settings = cfg.copy()
        polylines = _placed_polylines(_current_svg, settings)
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
    if _current_svg is None:
        return jsonify(error='No SVG loaded'), 400
    if _plot_thread and _plot_thread.is_alive():
        return jsonify(error='Already plotting'), 400
    _clear_events()
    _clear_last_plot_events()
    _stop_event.clear()
    job = _create_plot_job(_current_svg, cfg.copy(), _placement.copy())
    _plot_thread = threading.Thread(
        target=_plot_worker, args=(job,), daemon=True
    )
    _plot_thread.start()
    return jsonify(ok=True, job=_plot_job_public(job))

@app.route('/api/plot/resume', methods=['POST'])
def resume_plot():
    global _plot_thread, _stop_event
    job = _normalised_plot_job(_load_plot_job())
    public = _plot_job_public(job)
    if not public.get('exists'):
        return jsonify(error='No saved plot job'), 404
    if not public.get('resumable'):
        return jsonify(error='Saved plot job is not resumable'), 400
    if _plot_thread and _plot_thread.is_alive():
        return jsonify(error='Already plotting'), 400
    _clear_events()
    _clear_last_plot_events()
    _stop_event.clear()
    _plot_thread = threading.Thread(
        target=_plot_worker, args=(job,), daemon=True
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

def _process_worker(pfm_id, params, seed):
    global _drawing, _current_svg
    try:
        emit('proc', state='running', pfm=pfm_id)
        img = _project.open_image()
        if img is None:
            emit('proc', state='error', msg='No image loaded')
            return
        pfm = get_pfm(pfm_id)

        def on_progress(stage, frac):
            emit('proc', state='progress', stage=stage, frac=frac)

        drawing = pfm.run(img, _project.area, _project.drawing_set,
                          params, seed=seed, on_progress=on_progress)
        svg = svg_io.to_svg(drawing)
        _drawing = drawing
        _current_svg = svg.encode()           # so /api/plot can plot it directly
        _project.pfm_id = pfm_id
        _project.params = validate(pfm.params, params)
        _project.save()
        per_pen = [{'name': l.pen.name, 'colour': l.pen.colour, 'count': l.count()}
                   for l in drawing.layers if l.count()]
        emit('proc', state='done',
             svg=svg,
             total=drawing.total(),
             length_mm=round(svg_io.estimate_path_length_mm(drawing)),
             backend=accel.backend_name(),
             per_pen=per_pen)
    except Exception as exc:
        emit('proc', state='error', msg=str(exc))

@app.route('/api/process', methods=['POST'])
def api_process():
    global _process_thread
    data = request.json or {}
    pfm_id = data.get('pfm_id') or _project.pfm_id
    if pfm_id not in REGISTRY:
        return jsonify(error='Unknown PFM'), 400
    if _project.image_path is None or not _project.image_path.exists():
        return jsonify(error='No image loaded'), 400
    if _process_thread and _process_thread.is_alive():
        return jsonify(error='Already processing'), 409
    _area_from(data.get('area'))
    _drawing_set_from(data.get('drawing_set'))
    params = data.get('params') or {}
    seed = int(data.get('seed', params.get('seed', 0)) or 0)
    _clear_last_proc_events()
    _process_thread = threading.Thread(
        target=_process_worker, args=(pfm_id, params, seed), daemon=True)
    _process_thread.start()
    return jsonify(ok=True)

# ── Generate step (rule-based drawing, no input image) ──────────────────────────

def _generate_worker(gid, params, seed):
    global _drawing, _current_svg
    try:
        emit('proc', state='running', pfm=gid)
        gen = get_generator(gid)
        vals = validate(gen['params'], params)
        emit('proc', state='progress', stage='generating', frac=0.3)
        lines, w_mm, h_mm = gen['fn'](vals, seed=seed)
        pen = _project.drawing_set.active()[0]
        svg = svg_io.lines_to_svg(lines, w_mm, h_mm, colour=pen.colour, stroke_mm=pen.stroke_mm)
        _drawing = None                       # generators output flat polylines, not a Drawing
        _current_svg = svg.encode()           # so /api/plot and /api/export work
        emit('proc', state='done',
             svg=svg, total=len(lines),
             length_mm=round(svg_io.lines_length_mm(lines)),
             backend='generator',
             per_pen=[{'name': pen.name, 'colour': pen.colour, 'count': len(lines)}])
    except Exception as exc:
        emit('proc', state='error', msg=str(exc))

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
        target=_generate_worker, args=(gid, params, seed), daemon=True)
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
        if _drawing is None:
            return jsonify(error='Nothing to save — process a drawing first'), 400
        data = request.json or {}
        v = _project.add_version(_drawing, name=data.get('name', ''),
                                 notes=data.get('notes', ''))
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
    if not _project.load_version(vid):
        return jsonify(error='Unknown version'), 404
    p = get_pfm(_project.pfm_id)
    return jsonify(ok=True, pfm_id=_project.pfm_id,
                   params=_project.params, schema=schema_json(p.params),
                   area=_project.area.to_dict(),
                   drawing_set=_project.drawing_set.to_dict())

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
    if _drawing is None:
        # generator output (or uploaded SVG): export the current SVG as-is
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
    host = '100.111.89.104'
    port = 7438
    print(f'Plotter server running at http://{host}:{port}')
    app.run(host=host, port=port, debug=False, threaded=True)
