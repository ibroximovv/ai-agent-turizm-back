"""Every admin page must render.

A misconfigured `fieldsets` / `readonly_fields` / form class only blows up when
the page is actually opened, so these tests walk the whole registry rather than
asserting on any single screen.
"""

from __future__ import annotations

import json

import pytest
from django.contrib import admin as django_admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.catalog.models import Material

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def _registered_models():
    return [
        (model._meta.app_label, model._meta.model_name)
        for model in django_admin.site._registry
    ]


def test_dashboard_renders_with_stats(admin_client, topic):
    response = admin_client.get(reverse("admin:index"))
    assert response.status_code == 200

    kpis = {kpi["title"]: kpi["value"] for kpi in response.context["kpis"]}
    assert kpis["Modullar"] == 1
    assert kpis["Mavzular"] == 1
    assert kpis["Materiallar"] == 0

    # The Chart.js payload must be well-formed JSON with one point per day.
    chart = json.loads(response.context["throughput_chart"])
    assert len(chart["labels"]) == 14
    assert len(chart["datasets"][0]["data"]) == 14

    assert response.context["module_rows"][0]["module"] == topic.module


def test_content_tree_renders(admin_client, topic):
    response = admin_client.get(reverse("admin:catalog_tree"))
    assert response.status_code == 200

    node = response.context["tree"][0]
    assert node["module"] == topic.module
    assert node["topics"][0]["topic"] == topic


def test_content_tree_search_filters_modules(admin_client, topic):
    from apps.catalog.models import Module

    Module.objects.create(code="module-99", name="Boshqa modul")

    assert len(admin_client.get(reverse("admin:catalog_tree")).context["tree"]) == 2

    filtered = admin_client.get(reverse("admin:catalog_tree"), {"q": "Boshqa"})
    assert [node["module"].code for node in filtered.context["tree"]] == ["module-99"]


@pytest.mark.parametrize(("app_label", "model_name"), _registered_models())
def test_changelist_renders(admin_client, app_label, model_name):
    response = admin_client.get(reverse(f"admin:{app_label}_{model_name}_changelist"))
    assert response.status_code == 200


@pytest.mark.parametrize(("app_label", "model_name"), _registered_models())
def test_add_form_renders(admin_client, app_label, model_name):
    response = admin_client.get(reverse(f"admin:{app_label}_{model_name}_add"))
    # MaterialAdmin redirects to its upload form; AuditLog forbids adding.
    assert response.status_code in {200, 302, 403}


def test_user_can_be_created_through_the_admin(admin_client):
    """Regression: `add_fieldsets` referenced `usable_password`, which only
    `AdminUserCreationForm` declares — the plain `UserCreationForm` raised
    `FieldError: Unknown field(s) (usable_password)` when the page opened."""
    add_url = reverse("admin:accounts_user_add")
    assert admin_client.get(add_url).status_code == 200

    response = admin_client.post(
        add_url,
        {
            "email": "yangi@example.com",
            "full_name": "Yangi Muharrir",
            "role": "editor",
            "usable_password": "true",
            "password1": "StrongPass!2026",
            "password2": "StrongPass!2026",
        },
    )
    assert response.status_code == 302, response.context["adminform"].form.errors

    from django.contrib.auth import get_user_model

    created = get_user_model().objects.get(email="yangi@example.com")
    assert created.role == "editor"
    assert created.check_password("StrongPass!2026")


def test_change_pages_render_for_existing_objects(admin_client, topic):
    for obj in (topic.module, topic):
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk]
        )
        assert admin_client.get(url).status_code == 200


def test_material_upload_and_markdown_views(admin_client, topic):
    upload_url = reverse("admin:catalog_material_upload")
    assert admin_client.get(upload_url).status_code == 200

    response = admin_client.post(
        upload_url,
        {
            "topic": str(topic.id),
            "type": "literature",
            "file": SimpleUploadedFile(
                "qonun.txt", b"Turizm asoslari matni.", content_type="text/plain"
            ),
        },
    )
    assert response.status_code == 302

    material = Material.objects.get()
    change_url = reverse("admin:catalog_material_change", args=[material.pk])
    assert admin_client.get(change_url).status_code == 200

    markdown_url = reverse("admin:catalog_material_markdown", args=[material.pk])
    markdown_page = admin_client.get(markdown_url)
    assert markdown_page.status_code == 200
    assert b"MANBA" in markdown_page.content


class TestDragAndDropUpload:
    """The uploader posts one file per request and reads a JSON reply."""

    @staticmethod
    def _post(admin_client, topic, name="qonun.txt", content=b"Turizm asoslari matni."):
        return admin_client.post(
            reverse("admin:catalog_material_upload"),
            {
                "topic": str(topic.id),
                "type": "literature",
                "file": SimpleUploadedFile(name, content, content_type="text/plain"),
            },
            headers={"x-requested-with": "XMLHttpRequest"},
        )

    def test_returns_json_for_an_xhr_upload(self, admin_client, topic):
        response = self._post(admin_client, topic)
        assert response.status_code == 200

        payload = response.json()
        assert payload["ok"] is True
        assert payload["name"] == "qonun.txt"
        assert payload["changeUrl"].endswith("/change/")
        assert Material.objects.filter(pk=payload["id"]).exists()

    def test_reports_a_duplicate_as_json_409(self, admin_client, topic):
        self._post(admin_client, topic)
        response = self._post(admin_client, topic)

        assert response.status_code == 409
        assert response.json()["ok"] is False
        assert "allaqachon biriktirilgan" in response.json()["error"]

    def test_reports_an_unsupported_format_as_json_400(self, admin_client, topic):
        response = self._post(admin_client, topic, name="report.xlsx")

        assert response.status_code == 400
        assert response.json()["ok"] is False

    def test_status_feed_reports_the_pipeline_result(self, admin_client, topic):
        material_id = self._post(admin_client, topic).json()["id"]

        response = admin_client.get(
            reverse("admin:catalog_material_statuses"), {"ids": material_id}
        )
        assert response.status_code == 200

        row = response.json()["items"][0]
        assert row["id"] == material_id
        # Open WebUI is unconfigured in tests, so the run stops at md_ready.
        assert row["status"] == "md_ready"
        assert row["label"] == "Markdown tayyor"
