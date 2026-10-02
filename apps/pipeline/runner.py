"""Background execution for pipeline runs.

Uploads must return promptly, so conversion happens off the request thread. A
fixed-size pool bounds the fan-out: parsing keeps whole documents in memory, and
an unbounded pool over a large module would exhaust the process.

The in-flight registry exists because upload, retry and batch processing can all
target the same material — running the pipeline twice at once would have the two
runs overwrite each other's status and Open WebUI file ids.

Scanned PDFs run on a pool of their own ("ocr" lane): OCR'ing a 500-page book
takes tens of minutes, and on a shared pool two of them would leave a five-page
DOCX waiting behind them. The registry is shared by both lanes, so a material is
still never run twice at once.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

DEFAULT_LANE = "default"
OCR_LANE = "ocr"

_lock = threading.RLock()
_executors: dict[str, ThreadPoolExecutor] = {}
_atexit_registered = False
#: Materials submitted to a pool but not yet picked up by a worker.
_pending: set[str] = set()
#: Materials a worker is running right now.
_running: set[str] = set()
#: Set to stop a queued or running material (deleted, or stopped by an operator).
_cancel_events: dict[str, threading.Event] = {}


def _lane_size(lane: str) -> int:
    if lane == OCR_LANE:
        return max(1, settings.OCR.concurrency)
    return max(1, getattr(settings, "PIPELINE_CONCURRENCY", 2))


def _get_executor(lane: str = DEFAULT_LANE) -> ThreadPoolExecutor:
    global _atexit_registered
    with _lock:
        executor = _executors.get(lane)
        if executor is None:
            executor = _executors[lane] = ThreadPoolExecutor(
                max_workers=_lane_size(lane),
                thread_name_prefix="pipeline" if lane == DEFAULT_LANE else f"pipeline-{lane}",
            )
            if not _atexit_registered:
                atexit.register(shutdown)
                _atexit_registered = True
        return executor


def shutdown(wait: bool = False) -> None:
    with _lock:
        executors = list(_executors.values())
        _executors.clear()
    for executor in executors:
        executor.shutdown(wait=wait, cancel_futures=not wait)


def is_processing(material_id: str) -> bool:
    """True while a run is queued or executing for this material."""
    key = str(material_id)
    with _lock:
        return key in _pending or key in _running


def claim(material_id: str) -> bool:
    """Mark a material as running. False when another run already holds it."""
    key = str(material_id)
    with _lock:
        if key in _running:
            return False
        _running.add(key)
        _pending.discard(key)
        _cancel_events.setdefault(key, threading.Event())
        return True


def release(material_id: str) -> None:
    key = str(material_id)
    with _lock:
        _running.discard(key)
        _pending.discard(key)
        _cancel_events.pop(key, None)


def cancel_event(material_id: str) -> threading.Event | None:
    """The flag a run polls to stop early; None when nothing is in flight."""
    with _lock:
        return _cancel_events.get(str(material_id))


def cancel(material_id: str) -> bool:
    """Ask a queued or running material to stop. False when nothing is in flight.

    A queued run is skipped when its turn comes; a running one stops at its
    next checkpoint (between OCR pages).
    """
    with _lock:
        event = _cancel_events.get(str(material_id))
    if event is None:
        return False
    event.set()
    return True


def is_cancelled(material_id: str) -> bool:
    event = cancel_event(material_id)
    return event is not None and event.is_set()


def submit(
    material_id: str,
    task: Callable[[str], object] | None = None,
    lane: str | None = None,
) -> bool:
    """Queue a pipeline run. False when one is already queued or executing.

    Without an explicit `lane`, a pipeline run (no custom `task`) is routed by
    `apps.pipeline.service.lane_for` — scanned PDFs to the OCR lane.

    With ``PIPELINE_RUN_SYNC`` the run happens inline instead — the tests and
    management commands need the result before they continue.
    """
    key = str(material_id)

    route = task is None and lane is None
    if task is None:
        from apps.pipeline.service import process_material

        task = process_material

    if getattr(settings, "PIPELINE_RUN_SYNC", False):
        _safe_run(task, key)
        return True

    if route:
        from apps.pipeline.service import lane_for

        lane = lane_for(key)

    with _lock:
        if key in _pending or key in _running:
            return False
        _pending.add(key)
        _cancel_events[key] = threading.Event()

    try:
        _get_executor(lane or DEFAULT_LANE).submit(_worker, task, key)
    except RuntimeError:
        # The pool was shut down (interpreter exit); do not leave a stale claim.
        with _lock:
            _pending.discard(key)
            _cancel_events.pop(key, None)
        raise
    return True


def _worker(task: Callable[[str], object], material_id: str) -> None:
    # Each pool thread gets its own database connection; recycle anything the
    # previous task left behind before and after the run.
    close_old_connections()
    try:
        _safe_run(task, material_id)
    finally:
        close_old_connections()


def _safe_run(task: Callable[[str], object], material_id: str) -> None:
    """Failures are already recorded on the material and in the audit log; they
    are logged here as well so an unattended run is never silently lost."""
    try:
        task(material_id)
    except Exception as exc:
        logger.error("Fon rejimidagi pipeline xatosi (%s): %s", material_id, exc)
    finally:
        with _lock:
            _pending.discard(material_id)
            if material_id not in _running:
                _cancel_events.pop(material_id, None)
