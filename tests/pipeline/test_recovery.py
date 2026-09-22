"""Materials a restart interrupted are picked up again."""

from __future__ import annotations

import pytest

from apps.catalog.models import Material, MaterialStatus
from apps.pipeline import recovery, runner

pytestmark = pytest.mark.django_db


def _material(topic, status: str) -> Material:
    return Material.objects.create(
        topic=topic,
        raw_file_path="/nonexistent.txt",
        original_filename=f"{status}.txt",
        status=status,
    )


def test_requeues_only_materials_left_mid_run(topic, monkeypatch):
    submitted: list[str] = []
    monkeypatch.setattr(runner, "submit", lambda material_id: submitted.append(material_id))

    stuck = [_material(topic, s) for s in ("queued", "converting", "uploading")]
    finished = [_material(topic, s) for s in ("indexed", "md_ready", "failed")]

    assert recovery.requeue_interrupted() == 3

    assert sorted(submitted) == sorted(str(m.id) for m in stuck)
    for material in stuck:
        material.refresh_from_db()
        assert material.status == MaterialStatus.QUEUED
    for material in finished:
        assert Material.objects.get(pk=material.pk).status == material.status


def test_leaves_alone_what_this_process_is_already_running(topic, monkeypatch):
    submitted: list[str] = []
    monkeypatch.setattr(runner, "submit", lambda material_id: submitted.append(material_id))
    material = _material(topic, "converting")

    assert runner.claim(str(material.id))
    try:
        assert recovery.requeue_interrupted() == 0
    finally:
        runner.release(str(material.id))
    assert submitted == []
