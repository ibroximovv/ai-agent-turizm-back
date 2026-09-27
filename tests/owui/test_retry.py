"""The embedding provider behind Open WebUI rate-limits large imports.

A refused indexing call must be retried with backoff instead of leaving the
material stranded in `md_ready`, and only transient refusals may be retried.
"""

from __future__ import annotations

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import AuditLog, Material, MaterialStatus
from apps.owui import client as owui_client
from apps.pipeline import service as pipeline_service
from config.app_config import build_owui_config
from tests.owui.fake_owui import FakeOwui

pytestmark = pytest.mark.django_db

#: What Open WebUI 0.11.3 answered while Gemini was rate-limiting.
RATE_LIMITED = (
    400,
    "400: 429, message='Too Many Requests', "
    "url='https://generativelanguage.googleapis.com/v1beta/openai/embeddings'",
)
UNAVAILABLE = (400, "400: 503, message='Service Unavailable', url='…/embeddings'")


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record backoff waits instead of sleeping through them."""
    waits: list[float] = []
    monkeypatch.setattr(owui_client.time, "sleep", waits.append)
    monkeypatch.setattr(owui_client, "_cooldown_until", 0.0)
    return waits


@pytest.fixture
def owui(settings, monkeypatch, sleeps) -> FakeOwui:
    fake = FakeOwui()
    settings.OWUI = build_owui_config(
        url="http://owui.test",
        api_key="test-key",
        timeout_ms=1000,
        retry_attempts=4,
        retry_base_seconds=20,
        retry_max_seconds=50,
    )

    def client(self):
        return httpx.Client(base_url=self.base_url, transport=fake.transport())

    monkeypatch.setattr(owui_client.OwuiClient, "_client", client)
    # The cooldown is shared process state; keep tests from waiting on it.
    monkeypatch.setattr(owui_client.time, "monotonic", lambda: 0.0)
    return fake


def _upload(api, topic, name="doc.txt") -> Material:
    upload = SimpleUploadedFile(
        name, ("Turizm to'g'risidagi qonun matni. " * 20).encode(), content_type="text/plain"
    )
    response = api.post(
        "/api/materials/upload",
        {"file": upload, "topic_id": str(topic.id), "type": "literature"},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    material = Material.objects.get(pk=response.json()["id"])
    material.refresh_from_db()
    return material


def test_rate_limited_indexing_is_retried_until_it_succeeds(owui, sleeps, auth_api, topic):
    owui.add_failures = [RATE_LIMITED, UNAVAILABLE]

    material = _upload(auth_api, topic)

    assert material.status == MaterialStatus.INDEXED
    assert material.error_message is None
    assert sleeps == [20, 40]
    kb = owui.kbs[material.topic.module.owui_kb_id]
    assert kb["files"] == [material.owui_file_id]
    retries = AuditLog.objects.filter(material=material, message__contains="qayta uriniladi")
    assert retries.count() == 2


def test_backoff_is_capped(owui, sleeps, auth_api, topic):
    owui.add_failures = [RATE_LIMITED, RATE_LIMITED, RATE_LIMITED]

    assert _upload(auth_api, topic).status == MaterialStatus.INDEXED
    assert sleeps == [20, 40, 50]


def test_gives_up_after_the_last_attempt_and_keeps_the_markdown(owui, sleeps, auth_api, topic):
    owui.add_failures = [RATE_LIMITED] * 4

    material = _upload(auth_api, topic)

    assert material.status == MaterialStatus.MD_READY
    assert "Too Many Requests" in material.error_message
    assert len(sleeps) == 3


def test_a_permanent_refusal_is_not_retried(owui, sleeps, auth_api, topic):
    owui.add_failures = [(400, "400: Extracted content is not available for this file.")]

    material = _upload(auth_api, topic)

    assert material.status == MaterialStatus.MD_READY
    assert sleeps == []


@pytest.mark.parametrize(
    "detail",
    [
        # A file id holding the digits must not read as a rate limit.
        "Faylni (a10526f3-4290-4c7f-9f89-503f1409b613) KB topilmadi",
        "400: File not found",
    ],
)
def test_ids_containing_status_digits_are_not_transient(detail):
    response = httpx.Response(400, json={"detail": detail}, request=httpx.Request("POST", "/"))
    exc = httpx.HTTPStatusError("x", request=response.request, response=response)
    assert owui_client._is_transient(exc) is False


def test_only_unindexed_materials_are_requeued(topic, monkeypatch):
    submitted: list[str] = []
    monkeypatch.setattr(pipeline_service.runner, "submit", submitted.append)

    def make(status: str) -> Material:
        return Material.objects.create(
            topic=topic, raw_file_path="/x", original_filename=f"{status}.pdf", status=status
        )

    stranded = [make(MaterialStatus.MD_READY), make(MaterialStatus.FAILED)]
    indexed = make(MaterialStatus.INDEXED)

    result = pipeline_service.queue_module_materials(topic.module, only_unindexed=True)

    assert result["totalQueued"] == 2
    assert sorted(submitted) == sorted(str(m.id) for m in stranded)
    indexed.refresh_from_db()
    assert indexed.status == MaterialStatus.INDEXED


def test_api_process_all_can_target_unindexed_only(auth_api, topic, monkeypatch):
    monkeypatch.setattr(pipeline_service.runner, "submit", lambda _id: True)
    Material.objects.create(
        topic=topic, raw_file_path="/x", original_filename="a.pdf", status=MaterialStatus.INDEXED
    )
    Material.objects.create(
        topic=topic, raw_file_path="/x", original_filename="b.pdf", status=MaterialStatus.MD_READY
    )

    response = auth_api.post(f"/api/modules/{topic.module_id}/process-all?unindexed=true")

    assert response.status_code == 200
    assert response.json()["totalQueued"] == 1
