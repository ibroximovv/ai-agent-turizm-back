from __future__ import annotations

from pathlib import Path

import pytest

from config.app_config import build_owui_config, build_uploads_config


@pytest.fixture(autouse=True)
def isolated_environment(settings, tmp_path: Path):
    """Keep tests off the network and out of the real uploads tree.

    The developer `.env` carries a working `OWUI_API_KEY`, so without this the
    pipeline tests would upload documents to a live Open WebUI instance.
    """
    settings.UPLOADS = build_uploads_config(
        uploads_dir=str(tmp_path / "uploads"), max_upload_mb=5, base_dir=tmp_path
    )
    settings.OWUI = build_owui_config(url="http://localhost:9", api_key="", timeout_ms=1000)
    # Pipeline runs inline, so a test can assert on the result immediately.
    settings.PIPELINE_RUN_SYNC = True
    return settings


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        email="admin@example.com", password="StrongPass!2026", full_name="Test Admin"
    )


@pytest.fixture
def viewer_user(db):
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Role

    return get_user_model().objects.create_user(
        email="viewer@example.com", password="StrongPass!2026", role=Role.VIEWER
    )


@pytest.fixture
def api(db):
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_api(api, admin_user):
    api.force_authenticate(admin_user)
    return api


@pytest.fixture
def module(db):
    from apps.catalog.models import Module

    return Module.objects.create(code="module-01", name="Turizm asoslari")


@pytest.fixture
def topic(module):
    from apps.catalog.models import Topic

    return Topic.objects.create(module=module, code="topic-01", name="Qonunchilik asoslari")
