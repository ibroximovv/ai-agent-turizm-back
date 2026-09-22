"""Admin-driven knowledge bases and agents, end to end against a fake Open WebUI.

The contract under test: whatever the admin panel holds is what the agents
see. Every module gets its own KB and agent, the master agent reads every
active module's KB, and deletions leave nothing behind in Open WebUI.
"""

from __future__ import annotations

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.catalog.models import Material, MaterialStatus, Module, Topic
from apps.owui import client as owui_client
from apps.owui.sync import PUBLIC_READ, ensure_module_kb, sync_master_agent
from config.app_config import build_owui_config
from tests.owui.fake_owui import FakeOwui

pytestmark = pytest.mark.django_db

MASTER = "turizm-umumiy-agent"


@pytest.fixture
def owui(settings, monkeypatch) -> FakeOwui:
    fake = FakeOwui()
    settings.OWUI = build_owui_config(
        url="http://owui.test",
        api_key="test-key",
        timeout_ms=1000,
        agent_template_model_id="template-agent",
        master_model_id=MASTER,
    )

    def client(self):
        return httpx.Client(base_url=self.base_url, transport=fake.transport())

    monkeypatch.setattr(owui_client.OwuiClient, "_client", client)
    return fake


def _upload(api, topic, name="doc.txt", content="Turizm to'g'risidagi qonun matni. " * 20):
    upload = SimpleUploadedFile(name, content.encode(), content_type="text/plain")
    response = api.post(
        "/api/materials/upload",
        {"file": upload, "topic_id": str(topic.id), "type": "literature"},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    return Material.objects.get(pk=response.json()["id"])


class TestFirstUpload:
    def test_creates_kb_module_agent_and_master_agent(self, owui, auth_api, topic):
        material = _upload(auth_api, topic)

        material.refresh_from_db()
        module = Module.objects.get(pk=topic.module_id)
        assert material.status == MaterialStatus.INDEXED
        assert list(owui.kbs) == [module.owui_kb_id]
        assert owui.kbs[module.owui_kb_id]["files"] == [material.owui_file_id]
        assert owui.kbs[module.owui_kb_id]["access_grants"] == PUBLIC_READ

        agent = owui.models[module.owui_model_id]
        assert module.owui_model_id == "turizm-module-01"
        assert owui.knowledge_ids(module.owui_model_id) == [module.owui_kb_id]
        assert '"Turizm asoslari" moduli' in agent["params"]["system"]
        assert "{{" not in agent["params"]["system"]
        assert agent["access_grants"] == PUBLIC_READ

        assert owui.knowledge_ids(MASTER) == [module.owui_kb_id]
        assert "{{" not in owui.models[MASTER]["params"]["system"]

    def test_new_agent_inherits_template_settings_but_not_its_prompt(self, owui, auth_api, topic):
        owui.add_model(
            "template-agent",
            params={"system": "Modul 1 uchun qo'lda yozilgan prompt", "temperature": 0.3},
            meta={
                "knowledge": [],
                "toolIds": ["ofis_saqlash_tool", "boshqa_tool"],
                "builtinTools": {"knowledge": True},
            },
        )

        _upload(auth_api, topic)

        agent = owui.models["turizm-module-01"]
        assert agent["params"]["temperature"] == 0.3
        assert agent["meta"]["toolIds"] == ["ofis_saqlash_tool", "boshqa_tool"]
        assert "qo'lda yozilgan" not in agent["params"]["system"]

    def test_file_is_extracted_before_it_is_linked(self, owui, auth_api, topic):
        # Background extraction used to lose the race against file/add.
        _upload(auth_api, topic)

        upload = next(r for r in owui.requests if r.url.path == "/api/v1/files/")
        assert upload.url.params["process_in_background"] == "false"

    def test_second_upload_reuses_the_kb(self, owui, auth_api, topic):
        _upload(auth_api, topic, name="a.txt")
        _upload(auth_api, topic, name="b.txt", content="Boshqa hujjat matni. " * 30)

        module = Module.objects.get(pk=topic.module_id)
        assert len(owui.kbs) == 1
        assert len(owui.kbs[module.owui_kb_id]["files"]) == 2


class TestAdoptingExistingResources:
    def test_module_adopts_kb_and_hand_tuned_agent(self, owui, auth_api):
        kb_id = owui.add_kb("Modul 1 - eski baza")
        owui.add_model("modul-1---gid-yordamchisi", params={"system": "QO'LDA SOZLANGAN"})

        response = auth_api.post(
            "/api/modules",
            {
                "code": "module-01",
                "name": "Modul 1",
                "owui_kb_id": kb_id,
                "owui_model_id": "modul-1---gid-yordamchisi",
            },
            format="json",
        )

        assert response.status_code == 201, response.content
        assert list(owui.kbs) == [kb_id]
        agent = owui.models["modul-1---gid-yordamchisi"]
        assert agent["params"]["system"] == "QO'LDA SOZLANGAN"
        assert owui.knowledge_ids("modul-1---gid-yordamchisi") == [kb_id]
        assert owui.kbs[kb_id]["access_grants"] == PUBLIC_READ
        assert owui.knowledge_ids(MASTER) == [kb_id]

    def test_a_kb_cannot_belong_to_two_modules(self, owui, auth_api, module):
        module.owui_kb_id = "kb-shared"
        module.save()

        response = auth_api.post(
            "/api/modules", {"code": "module-02", "name": "Ikki", "owui_kb_id": "kb-shared"}
        )

        assert response.status_code == 400
        assert "module-01" in " ".join(response.json()["message"])

    def test_the_master_agent_cannot_be_a_module_agent(self, owui, auth_api):
        response = auth_api.post(
            "/api/modules", {"code": "module-02", "name": "Ikki", "owui_model_id": MASTER}
        )
        assert response.status_code == 400


class TestMasterAgent:
    def test_reads_every_active_module_and_skips_inactive_ones(self, owui, db):
        first = Module.objects.create(code="module-01", name="Bir", order_index=1)
        second = Module.objects.create(code="module-02", name="Ikki", order_index=2)
        hidden = Module.objects.create(code="module-03", name="Uch", is_active=False)
        for module in (first, second, hidden):
            ensure_module_kb(module)

        sync_master_agent()

        assert owui.knowledge_ids(MASTER) == [first.owui_kb_id, second.owui_kb_id]

    def test_is_not_created_while_there_is_nothing_to_search(self, owui, db):
        assert sync_master_agent() is None
        assert MASTER not in owui.models


class TestDeletion:
    def test_module_delete_removes_files_kb_and_agent(
        self, owui, auth_api, topic, django_capture_on_commit_callbacks
    ):
        other = Module.objects.create(code="module-02", name="Ikki")
        _upload(auth_api, Topic.objects.create(module=other, code="t", name="t"))
        _upload(auth_api, topic)
        module = Module.objects.get(pk=topic.module_id)
        kb_id, agent_id = module.owui_kb_id, module.owui_model_id

        with django_capture_on_commit_callbacks(execute=True):
            assert auth_api.delete(f"/api/modules/{module.id}").status_code == 200

        assert kb_id not in owui.kbs
        assert agent_id not in owui.models
        assert len(owui.files) == 1  # only the other module's document is left
        other.refresh_from_db()
        assert owui.knowledge_ids(MASTER) == [other.owui_kb_id]

    def test_topic_delete_removes_its_files_but_keeps_the_kb(
        self, owui, auth_api, topic, django_capture_on_commit_callbacks
    ):
        _upload(auth_api, topic)
        kb_id = Module.objects.get(pk=topic.module_id).owui_kb_id

        with django_capture_on_commit_callbacks(execute=True):
            assert auth_api.delete(f"/api/topics/{topic.id}").status_code == 200

        assert owui.files == {}
        assert owui.kbs[kb_id]["files"] == []


class TestAdminPanel:
    @pytest.fixture
    def admin_client(self, client, admin_user):
        client.force_login(admin_user)
        return client

    def test_module_form_offers_open_webui_kbs_and_agents(self, owui, admin_client):
        owui.add_kb("Modul 1 - eski baza", kb_id="kb-legacy")
        owui.add_model("modul-1---gid-yordamchisi")
        owui.add_model(MASTER)

        form = admin_client.get(reverse("admin:catalog_module_add")).context["adminform"].form

        assert ("kb-legacy", "Modul 1 - eski baza (kb-legac)") in form.fields["owui_kb_id"].choices
        agent_ids = [value for value, _ in form.fields["owui_model_id"].choices]
        assert "modul-1---gid-yordamchisi" in agent_ids
        assert MASTER not in agent_ids

    def test_saving_a_module_wires_it_to_open_webui(self, owui, admin_client):
        kb_id = owui.add_kb("Modul 1 - eski baza")

        response = admin_client.post(
            reverse("admin:catalog_module_add"),
            {
                "code": "module-01",
                "name": "Modul 1",
                "description": "",
                "order_index": 0,
                "is_active": "on",
                "owui_kb_id": kb_id,
                "owui_model_id": "",
                "topics-TOTAL_FORMS": 0,
                "topics-INITIAL_FORMS": 0,
            },
        )

        assert response.status_code == 302
        module = Module.objects.get(code="module-01")
        assert module.owui_kb_id == kb_id
        assert module.owui_model_id == "turizm-module-01"
        assert owui.knowledge_ids("turizm-module-01") == [kb_id]
        assert owui.knowledge_ids(MASTER) == [kb_id]

    def test_module_form_still_renders_without_open_webui(self, admin_client):
        # conftest leaves OWUI_API_KEY blank: plain text inputs, no HTTP.
        response = admin_client.get(reverse("admin:catalog_module_add"))
        assert response.status_code == 200
