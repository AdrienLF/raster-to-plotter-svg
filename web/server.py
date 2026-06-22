import os, json, threading, queue, time, tempfile, re
from pathlib import Path
from xml.etree import ElementTree as ET

import serial
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

# ── Settings ──────────────────────────────────────────────────────────────────

SETTINGS_PATH = Path.home() / '.plotter_settings.json'

DEFAULTS = {
    'port':            '/dev/ttyACM0',
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
    'reordering':      1,
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
    return s

def save_cfg(s):
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))

cfg = load_cfg()

# ── Global state ──────────────────────────────────────────────────────────────

_plot_thread = None
_stop_event  = threading.Event()
_events      = queue.Queue(maxsize=300)
_current_svg = None   # bytes
_placement   = {'x': 0.0, 'y': 0.0}  # mm offset from page top-left

def emit(t, **kw):
    try:
        _events.put_nowait({'t': t, **kw})
    except queue.Full:
        pass

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

    if settings.get('reordering', 0) >= 1:
        polylines = _reorder(polylines)

    return polylines

def _reorder(polylines):
    """Greedy nearest-neighbour reorder to minimise pen-up travel."""
    if not polylines:
        return polylines
    ordered = [polylines[0]]
    remaining = polylines[1:]
    while remaining:
        last = ordered[-1][-1]
        best_i = min(range(len(remaining)),
                     key=lambda i: _dist2(last, remaining[i][0]))
        ordered.append(remaining.pop(best_i))
    return ordered

def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

# ── Plotter driver ────────────────────────────────────────────────────────────

class PlotterConn:
    def __init__(self, port, settings):
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        self.cfg = settings
        time.sleep(2)
        self.ser.read(self.ser.in_waiting)

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

# ── Plot worker ───────────────────────────────────────────────────────────────

def _plot_worker(svg_bytes, settings):
    plotter = None
    try:
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

        polylines = svg_to_polylines(svg_bytes, settings, on_progress=on_parse_progress)
        if not polylines:
            emit('error', msg='No paths found in SVG.')
            return

        ox, oy = _placement.get('x', 0.0), _placement.get('y', 0.0)
        if ox or oy:
            polylines = [[(x + ox, y - oy) for x, y in poly] for poly in polylines]

        total = sum(len(p) - 1 for p in polylines)
        done  = 0
        emit('state', state='plotting', total=total, done=0)
        emit('log', msg=f'Plotting {len(polylines)} paths, {total} segments…')

        for copy_i in range(settings.get('copies', 1)):
            if _stop_event.is_set():
                break
            if copy_i > 0:
                delay = settings.get('page_delay', 15)
                emit('log', msg=f'Waiting {delay}s before copy {copy_i + 1}…')
                for _ in range(delay * 10):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)

            for poly in polylines:
                if _stop_event.is_set():
                    break
                plotter.move(poly[0][0], poly[0][1])
                plotter.pen_down()
                for pt in poly[1:]:
                    if _stop_event.is_set():
                        break
                    plotter.draw(pt[0], pt[1])
                    done += 1
                    if done % 25 == 0:
                        emit('progress', done=done, total=total)
                plotter.pen_up()

        plotter.pen_up()
        emit('log', msg='Returning home…')
        plotter.move(0, 0)
        emit('state', state='done')
        emit('progress', done=total, total=total)
        emit('log', msg='Done!')

    except Exception as exc:
        if _stop_event.is_set() or '__stopped__' in str(exc):
            emit('state', state='idle')
            emit('log', msg='Stopped.')
        else:
            emit('state', state='error')
            emit('error', msg=str(exc))
    finally:
        if plotter:
            plotter.close()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
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

@app.route('/api/plot', methods=['POST'])
def plot():
    global _plot_thread, _stop_event
    if _current_svg is None:
        return jsonify(error='No SVG loaded'), 400
    if _plot_thread and _plot_thread.is_alive():
        return jsonify(error='Already plotting'), 400
    while not _events.empty():
        try:
            _events.get_nowait()
        except queue.Empty:
            break
    _stop_event.clear()
    _plot_thread = threading.Thread(
        target=_plot_worker, args=(_current_svg, cfg.copy()), daemon=True
    )
    _plot_thread.start()
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
        while True:
            try:
                evt = _events.get(timeout=15)
                yield f"data: {json.dumps(evt)}\n\n"
            except queue.Empty:
                yield 'data: {"t":"ping"}\n\n'
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
        ser = serial.Serial(cfg['port'], 115200, timeout=5)
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

if __name__ == '__main__':
    print('Plotter server running at http://0.0.0.0:5000')
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
