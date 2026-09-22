"""Background execution for pipeline runs.

Uploads must return promptly, so conversion happens off the request thread. A
fixed-size pool bounds the fan-out: parsing keeps whole documents in memory, and
an unbounded pool over a large module would exhaust the process.

The in-flight registry exists because upload, retry and batch processing can all
target the same material — running the pipeline twice at once would have the two
runs overwrite each other's status and Open WebUI file ids.
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

_lock = threading.RLock()
_executor: ThreadPoolExecutor | None = None
#: Materials submitted to the pool but not yet picked up by a worker.
_pending: set[str] = set()
#: Materials a worker is running right now.
_running: set[str] = set()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            workers = max(1, getattr(settings, "PIPELINE_CONCURRENCY", 2))
            _executor = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="pipeline"
            )
            atexit.register(shutdown)
        return _executor


def shutdown(wait: bool = False) -> None:
    global _executor
    with _lock:
        executor, _executor = _executor, None
    if executor is not None:
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
        return True


def release(material_id: str) -> None:
    key = str(material_id)
    with _lock:
        _running.discard(key)
        _pending.discard(key)


def submit(material_id: str, task: Callable[[str], object] | None = None) -> bool:
    """Queue a pipeline run. False when one is already queued or executing.

    With ``PIPELINE_RUN_SYNC`` the run happens inline instead — the tests and
    management commands need the result before they continue.
    """
    key = str(material_id)

    if task is None:
        from apps.pipeline.service import process_material

        task = process_material

    if getattr(settings, "PIPELINE_RUN_SYNC", False):
        _safe_run(task, key)
        return True

    with _lock:
        if key in _pending or key in _running:
            return False
        _pending.add(key)

    try:
        _get_executor().submit(_worker, task, key)
    except RuntimeError:
        # The pool was shut down (interpreter exit); do not leave a stale claim.
        with _lock:
            _pending.discard(key)
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
