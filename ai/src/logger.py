"""
ai/src/logger.py
================
Project logging. Two sinks, one shared configuration:

1. Console (stdout) -- the live, human-readable view. UTF-8 safe (Windows consoles
   default to cp1252 and choke on non-ASCII). Lines carry a slide tag when work is
   happening inside a specific slide, so even interleaved parallel output stays
   grep-able.
2. Per-run JSON-lines file (runs/<thread_id>/run.log) -- a structured, timestamped,
   slide-tagged record of the whole run. Because every line is timestamped AND
   slide-tagged, an interleaved file can be sorted/grouped back into per-slide order
   (see write_slide_ordered_log).

Slide correlation uses a contextvar, so when per-slide work runs concurrently in a
thread pool, each worker sets the contextvar for its own thread and a logging filter
stamps every record with the right slide id automatically.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import sys
from pathlib import Path

_ROOT_NAME = "ai"                       # all module loggers are "ai.*" and propagate here
_slide_var: contextvars.ContextVar[str] = contextvars.ContextVar("slide", default="")


class _SlideFilter(logging.Filter):
    """Inject the current slide id (from the contextvar) onto every record."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.slide = _slide_var.get() or ""
        return True


class _ConsoleFormatter(logging.Formatter):
    """Console line; appends a slide tag only when one is set."""
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        slide = getattr(record, "slide", "")
        return f"{base}  «{slide}»" if slide else base


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "slide": getattr(record, "slide", ""),
            "msg": record.getMessage(),
        }, ensure_ascii=False)


def _ensure_root_configured(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger(_ROOT_NAME)
    if getattr(root, "_configured", False):
        return root
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ConsoleFormatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S"))
    handler.addFilter(_SlideFilter())
    with contextlib.suppress(Exception):       # force UTF-8 on Windows
        handler.stream.reconfigure(encoding="utf-8")
    root.addHandler(handler)
    root.propagate = False
    root._configured = True                    # type: ignore[attr-defined]
    return root


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a module logger. Module loggers ('ai.agents.base', 'ai.llm', ...) carry
    no handlers of their own and propagate to the configured 'ai' root, so adding a
    per-run file handler to the root captures everything."""
    _ensure_root_configured(level)
    lg = logging.getLogger(name)
    lg.setLevel(level)
    return lg                                  # propagate=True (default) -> bubbles to root


# ── slide correlation ──────────────────────────────────────────────────────────
@contextlib.contextmanager
def bind_slide(slide_id):
    """Tag every log line emitted within this block (and within the current thread)
    with `slide N`. Set inside each worker so concurrent slides stay distinguishable."""
    token = _slide_var.set(f"slide {slide_id}")
    try:
        yield
    finally:
        _slide_var.reset(token)


# ── per-run JSON-lines file sink ────────────────────────────────────────────────
def attach_run_log(thread_id: str, runs_dir: str | Path = "runs") -> logging.Handler:
    """Add a JSON-lines file handler (runs/<thread_id>/run.log) to the root logger.
    Returns the handler so it can be detached at run end."""
    root = _ensure_root_configured()
    path = Path(runs_dir) / str(thread_id) / "run.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(_JsonFormatter())
    fh.addFilter(_SlideFilter())
    fh._run_log_path = str(path)               # type: ignore[attr-defined]
    root.addHandler(fh)
    return fh


def detach_run_log(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logging.getLogger(_ROOT_NAME).removeHandler(handler)
    with contextlib.suppress(Exception):
        handler.close()


def write_slide_ordered_log(handler: logging.Handler | None) -> str | None:
    """Post-process a run's JSON-lines log into a clean, slide-ordered text file
    (run_by_slide.log): non-slide lines first (chronological), then each slide's lines
    grouped together. Lets you read one slide's story even if the live console
    interleaved them. Returns the output path."""
    path = getattr(handler, "_run_log_path", None) if handler else None
    if not path or not Path(path).exists():
        return None
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(Exception):
            rows.append(json.loads(line))
    def key(r):
        s = r.get("slide", "")
        n = int(s.split()[1]) if s.startswith("slide ") and s.split()[1].isdigit() else -1
        return (n, r.get("ts", ""))
    rows.sort(key=key)
    out = Path(path).with_name("run_by_slide.log")
    lines = [f'{r.get("ts","")} | {r.get("level",""):7s} | {r.get("slide") or "-":8s} | '
             f'{r.get("logger","")} | {r.get("msg","")}' for r in rows]
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)