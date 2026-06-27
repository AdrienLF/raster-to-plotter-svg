"""Wide-event (logfmt) structured logging.

One context-rich line per operation, optimized for two readers:
  * an LLM debugging a problem (flat key=value, correlated by request_id), and
  * a human/script benchmarking performance (duration_ms + per-stage timings).

This is a separate, additive channel from the SSE ``emit()`` bus in server.py —
that bus drives the live UI; this writes durable log lines to stderr (and an
optional rotating file). Stdlib only; no structlog/OTel.

Usage:
    LOG = configure()
    w = WideEvent("worker.pfm", request_id)
    w.set(pfm_id="voronoi", backend="torch-cuda")
    on_progress = w.wrap_progress(lambda s, f: emit('proc', state='progress', stage=s, frac=f))
    ...
    w.set(shapes=2847, length_mm=18443)
    w.emit("success")            # -> one logfmt line with duration_ms
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from time import perf_counter

LOGGER_NAME = "plotter"


def _fmt(v) -> str:
    """Render one logfmt value. Quote when it would otherwise break parsing."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        v = round(v, 3)
    s = str(v)
    if s == "":
        return '""'
    if any(c in s for c in ' ="') or "\n" in s:
        s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        return f'"{s}"'
    return s


class LogfmtFormatter(logging.Formatter):
    """`TS LEVEL event key=value ...` — one line, fields sorted, ms timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"
        head = f"{ts} {record.levelname} {record.getMessage()}"
        fields = getattr(record, "fields", None)
        if not fields:
            return head
        pairs = " ".join(f"{k}={_fmt(fields[k])}" for k in sorted(fields))
        return f"{head} {pairs}"


def configure(level: str | int | None = None) -> logging.Logger:
    """Install the logfmt handler(s) on the ``plotter`` logger. Idempotent."""
    log = logging.getLogger(LOGGER_NAME)
    if getattr(log, "_obslog_configured", False):
        return log

    if level is None:
        level = os.environ.get("PLOTTER_LOG_LEVEL", "INFO")
    log.setLevel(level)
    log.propagate = False

    fmt = LogfmtFormatter()
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    log.addHandler(stream)

    # Optional rotating file sink. Off by default; never let it break startup.
    if os.environ.get("PLOTTER_LOG_FILE", "1") not in ("0", "false", "False"):
        try:
            from engine.project import WORKSPACE

            log_dir = WORKSPACE / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_dir / "plotter.log", maxBytes=2_000_000, backupCount=3,
                encoding="utf-8",
            )
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except Exception as exc:  # pragma: no cover - FS-dependent
            log.warning("obslog.file_sink_failed", extra={"fields": {"err": str(exc)}})

    # Silence werkzeug's per-request access log — the http.request wide event replaces it.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    log._obslog_configured = True  # type: ignore[attr-defined]
    return log


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:8]


class WideEvent:
    """Accumulates fields over an operation, then emits one canonical line.

    ``request_id`` ties a worker run back to the HTTP request that spawned it.
    ``.time()`` / ``.wrap_progress()`` record per-stage durations for benchmarking.
    ``.emit()`` is idempotent — a second call (e.g. teardown after after_request)
    is a no-op.
    """

    def __init__(self, event: str, request_id: str | None = None, logger=None):
        self.event = event
        self.fields: dict = {"request_id": request_id}
        self._t0 = perf_counter()
        self._emitted = False
        self._log = logger or logging.getLogger(LOGGER_NAME)
        self._stage = None
        self._stage_t0 = 0.0

    def set(self, **kw) -> "WideEvent":
        self.fields.update(kw)
        return self

    @contextmanager
    def time(self, stage: str):
        t0 = perf_counter()
        try:
            yield
        finally:
            self.fields[f"stage_{stage}_ms"] = round((perf_counter() - t0) * 1000, 1)

    def _close_stage(self):
        if self._stage is not None:
            self.fields[f"stage_{self._stage}_ms"] = round(
                (perf_counter() - self._stage_t0) * 1000, 1)
            self._stage = None

    def wrap_progress(self, inner=None):
        """Return an ``on_progress(stage, frac)`` that times each stage transition
        and forwards to ``inner`` (the existing SSE emit), if given."""
        def on_progress(stage, frac):
            if stage != self._stage:
                self._close_stage()
                # The terminal 'done' stage has no work of its own to time.
                if stage not in (None, "done"):
                    self._stage = stage
                    self._stage_t0 = perf_counter()
            if inner is not None:
                inner(stage, frac)
        return on_progress

    def emit(self, outcome: str = "success", level: int = logging.INFO, **kw):
        if self._emitted:
            return
        self._emitted = True
        self._close_stage()
        self.fields.update(kw)
        self.fields["outcome"] = outcome
        self.fields["duration_ms"] = round((perf_counter() - self._t0) * 1000, 1)
        self._log.log(level, self.event, extra={"fields": self.fields})
