"""Resume pipeline runs a restart interrupted.

The queue lives in process memory (see ``runner``), so a deploy or crash drops
every queued and running material while their rows still read ``queued``,
``converting`` or ``uploading`` — states nothing would ever move them out of.
On start-up those rows are submitted again; the pipeline is idempotent per
material (same markdown path, previous Open WebUI copy replaced).
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import close_old_connections

from apps.catalog.models import IN_PROGRESS_STATUSES, Material, MaterialStatus
from apps.pipeline import runner

logger = logging.getLogger(__name__)


def requeue_interrupted() -> int:
    """Submit every material left mid-run. Returns how many were queued."""
    ids = [
        str(pk)
        for pk in Material.objects.filter(status__in=IN_PROGRESS_STATUSES).values_list(
            "id", flat=True
        )
    ]
    ids = [material_id for material_id in ids if not runner.is_processing(material_id)]
    if not ids:
        return 0

    Material.objects.filter(pk__in=ids).update(status=MaterialStatus.QUEUED)
    for material_id in ids:
        runner.submit(material_id)
    logger.info("Uzilib qolgan %d ta material qayta navbatga qo'yildi.", len(ids))
    return len(ids)


def resume_in_background() -> None:
    """Called once per server process, off the start-up path so a slow or
    unreachable database cannot delay the worker from accepting requests."""
    if not getattr(settings, "PIPELINE_RESUME_ON_START", True):
        return

    def run() -> None:
        close_old_connections()
        try:
            requeue_interrupted()
        except Exception as exc:
            logger.warning("Uzilgan materiallarni tiklab bo'lmadi: %s", exc)
        finally:
            close_old_connections()

    threading.Thread(target=run, name="pipeline-resume", daemon=True).start()
