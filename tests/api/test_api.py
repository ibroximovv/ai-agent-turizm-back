from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import AuditLog, Material, MaterialStatus, Module, Topic

pytestmark = pytest.mark.django_db


class TestHealthAndAuth:
    def test_health_is_public(self, api):
        response = api.get("/api/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_api_requires_authentication(self, api):
        assert api.get("/api/modules").status_code == 401

    def test_login_returns_tokens_and_profile(self, api, admin_user):
        response = api.post(
            "/api/auth/login",
            {"email": "admin@example.com", "password": "StrongPass!2026"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["user"]["email"] == "admin@example.com"
        assert body["user"]["role"] == "admin"

    def test_bearer_token_grants_access(self, api, admin_user):
        token = api.post(
            "/api/auth/login",
            {"email": "admin@example.com", "password": "StrongPass!2026"},
            format="json",
        ).json()["access"]

        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api.get("/api/modules").status_code == 200

    def test_viewer_role_cannot_write(self, api, viewer_user):
        api.force_authenticate(viewer_user)
        assert api.get("/api/modules").status_code == 200
        response = api.post("/api/modules", {"code": "m-02", "name": "Test"}, format="json")
        assert response.status_code == 403

    def test_editor_cannot_delete(self, api, db, module):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import Role

        editor = get_user_model().objects.create_user(
            email="editor@example.com", password="StrongPass!2026", role=Role.EDITOR
        )
        api.force_authenticate(editor)
        patched = api.patch(f"/api/modules/{module.id}", {"name": "Yangi"}, format="json")
        assert patched.status_code == 200
        assert api.delete(f"/api/modules/{module.id}").status_code == 403


class TestModules:
    def test_list_reports_topic_and_material_counts(self, auth_api, topic):
        response = auth_api.get("/api/modules")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "total", "page", "limit", "totalPages"}
        assert body["total"] == 1
        assert body["items"][0]["topicsCount"] == 1
        assert body["items"][0]["materialsCount"] == 0

    def test_create_rejects_a_duplicate_code(self, auth_api, module):
        response = auth_api.post(
            "/api/modules", {"code": module.code, "name": "Nusxa"}, format="json"
        )
        assert response.status_code == 400
        assert "allaqachon mavjud" in str(response.json()["message"])

    def test_create_rejects_a_path_traversing_code(self, auth_api):
        response = auth_api.post(
            "/api/modules", {"code": "../../etc", "name": "Yomon"}, format="json"
        )
        assert response.status_code == 400

    def test_delete_cascades_to_topics(self, auth_api, topic):
        response = auth_api.delete(f"/api/modules/{topic.module_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert Topic.objects.count() == 0

    def test_search_filters_by_name(self, auth_api, module):
        Module.objects.create(code="module-02", name="Mehmonxona xizmati")
        assert auth_api.get("/api/modules?search=Mehmonxona").json()["total"] == 1
        assert auth_api.get("/api/modules?search=yoq").json()["total"] == 0

    def test_unknown_uuid_is_a_404(self, auth_api):
        response = auth_api.get("/api/modules/11111111-1111-4111-8111-111111111111")
        assert response.status_code == 404
        assert response.json()["statusCode"] == 404


class TestTopics:
    def test_create_requires_a_unique_code_within_the_module(self, auth_api, topic):
        response = auth_api.post(
            "/api/topics",
            {"module_id": str(topic.module_id), "code": topic.code, "name": "Nusxa"},
            format="json",
        )
        assert response.status_code == 400

    def test_same_code_is_allowed_in_another_module(self, auth_api, topic):
        other = Module.objects.create(code="module-02", name="Boshqa")
        response = auth_api.post(
            "/api/topics",
            {"module_id": str(other.id), "code": topic.code, "name": "Ruxsat"},
            format="json",
        )
        assert response.status_code == 201

    def test_filter_by_module(self, auth_api, topic):
        other = Module.objects.create(code="module-02", name="Boshqa")
        Topic.objects.create(module=other, code="topic-01", name="Boshqa mavzu")

        assert auth_api.get(f"/api/topics?module_id={topic.module_id}").json()["total"] == 1
        assert auth_api.get("/api/topics").json()["total"] == 2


class TestMaterialUpload:
    CONTENT = (
        "Ўзбекистон Республикасининг туризм тўғрисидаги қонуни.\n\n\n"
        "Иккинчи боб: асосий тушунчалар ва таърифлар."
    )

    def _upload(self, api, topic, name="qonun.txt", content: str | None = None):
        upload = SimpleUploadedFile(
            name, (content or self.CONTENT).encode("utf-8"), content_type="text/plain"
        )
        return api.post(
            "/api/materials/upload",
            {"topic_id": str(topic.id), "type": "literature", "file": upload},
            format="multipart",
        )

    def test_upload_runs_the_whole_pipeline(self, auth_api, topic):
        response = self._upload(auth_api, topic)
        assert response.status_code == 201

        material = Material.objects.get(pk=response.json()["id"])
        # Open WebUI is unconfigured in tests, so the run stops at md_ready.
        assert material.status == MaterialStatus.MD_READY
        assert material.detected_script == "uz-cyrl"
        assert material.chunk_count == 2
        assert material.uploaded_by is not None

    def test_converted_markdown_is_transliterated_and_grounded(self, auth_api, topic):
        material_id = self._upload(auth_api, topic).json()["id"]

        response = auth_api.get(f"/api/materials/{material_id}/content")
        assert response.status_code == 200
        markdown = response.json()["markdown"]

        assert 'module_id: "module-01"' in markdown
        assert 'topic_id: "topic-01"' in markdown
        assert "[MANBA: qonun.txt | part 1 | topic-01 | literature]" in markdown
        assert "O‘zbekiston Respublikasining" in markdown
        # Nothing Cyrillic may survive into the knowledge base.
        assert not any("Ѐ" <= ch <= "ӿ" for ch in markdown)

    def test_upload_writes_an_audit_trail(self, auth_api, topic):
        material_id = self._upload(auth_api, topic).json()["id"]

        logs = AuditLog.objects.filter(material_id=material_id)
        stages = set(logs.values_list("stage", flat=True))
        assert "conversion" in stages
        assert "indexing" in stages

    def test_identical_reupload_is_rejected(self, auth_api, topic):
        self._upload(auth_api, topic)
        response = self._upload(auth_api, topic)
        assert response.status_code == 409
        assert "allaqachon biriktirilgan" in str(response.json()["message"])

    def test_unsupported_extension_is_rejected(self, auth_api, topic):
        response = self._upload(auth_api, topic, name="report.xlsx")
        assert response.status_code == 400

    def test_oversized_upload_is_rejected_with_413(self, auth_api, topic):
        # The conftest caps uploads at 5 MB.
        response = self._upload(auth_api, topic, name="big.txt", content="x" * (6 * 1024 * 1024))
        assert response.status_code == 413

    def test_delete_removes_the_files_from_disk(self, auth_api, topic):
        from pathlib import Path

        material = Material.objects.get(pk=self._upload(auth_api, topic).json()["id"])
        raw_path, md_path = Path(material.raw_file_path), Path(material.md_file_path)
        assert raw_path.exists() and md_path.exists()

        assert auth_api.delete(f"/api/materials/{material.id}").status_code == 200
        assert not raw_path.exists()
        assert not md_path.exists()
        assert Material.objects.count() == 0

    def test_retry_reruns_the_pipeline(self, auth_api, topic):
        material_id = self._upload(auth_api, topic).json()["id"]
        Material.objects.filter(pk=material_id).update(status=MaterialStatus.FAILED)

        response = auth_api.post(f"/api/materials/{material_id}/retry")
        assert response.status_code == 200
        assert Material.objects.get(pk=material_id).status == MaterialStatus.MD_READY

    def test_a_failed_document_records_its_error(self, auth_api, topic):
        response = self._upload(auth_api, topic, name="bosh.txt", content="   ")
        material = Material.objects.get(pk=response.json()["id"])

        assert material.status == MaterialStatus.FAILED
        assert "matn ajratib bo'lmadi" in material.error_message
        assert AuditLog.objects.filter(material=material, level="error").exists()


class TestModuleBatchProcessing:
    def test_process_all_queues_every_material(self, auth_api, topic):
        upload = SimpleUploadedFile("a.txt", b"Turizm asoslari matni", content_type="text/plain")
        auth_api.post(
            "/api/materials/upload",
            {"topic_id": str(topic.id), "type": "literature", "file": upload},
            format="multipart",
        )

        response = auth_api.post(f"/api/modules/{topic.module_id}/process-all")
        assert response.status_code == 200
        assert response.json()["totalQueued"] == 1


class TestAuditLogs:
    def test_filter_by_level(self, auth_api, module):
        AuditLog.objects.create(module=module, stage="conversion", level="info", message="ok")
        AuditLog.objects.create(module=module, stage="indexing", level="error", message="xato")

        assert auth_api.get("/api/audit-logs").json()["total"] == 2
        assert auth_api.get("/api/audit-logs?level=error").json()["total"] == 1
        assert auth_api.get("/api/audit-logs?search=xato").json()["total"] == 1
