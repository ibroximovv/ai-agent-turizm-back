"""External cleanup when catalog rows disappear.

Deletion reaches materials along many paths — the material endpoints, a topic
or module delete cascading down, an admin bulk action, a topic removed from the
module form's inline. Hooking the model signals covers all of them, where
per-view cleanup had missed every cascade and left files and knowledge bases
behind in Open WebUI.

The work runs on commit: a rolled-back delete must not have already destroyed
the files its rows still point to.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.catalog.models import Material, Module

logger = logging.getLogger(__name__)


def _unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Faylni o'chirib bo'lmadi (%s): %s", path, exc)


@receiver(post_delete, sender=Material, dispatch_uid="catalog.material_cleanup")
def cleanup_material(sender, instance: Material, **kwargs) -> None:
    raw_path, md_path, file_id = (
        instance.raw_file_path,
        instance.md_file_path,
        instance.owui_file_id,
    )

    def run() -> None:
        from apps.owui.sync import purge_files

        _unlink(raw_path)
        _unlink(md_path)
        if file_id:
            purge_files([file_id])

    transaction.on_commit(run)


@receiver(post_delete, sender=Module, dispatch_uid="catalog.module_cleanup")
def cleanup_module(sender, instance: Module, **kwargs) -> None:
    kb_id, model_id = instance.owui_kb_id, instance.owui_model_id

    def run() -> None:
        from apps.owui.sync import purge_module

        purge_module(kb_id, model_id)

    transaction.on_commit(run)
