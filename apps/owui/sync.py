"""Keep Open WebUI's knowledge bases and agents in step with the catalog.

The admin panel is the single source of truth. Every module owns

* one Knowledge Base (``modules.owui_kb_id``) holding its indexed materials, and
* one agent — a workspace model preset (``modules.owui_model_id``) that
  answers only from that KB.

On top of those, one *master* agent (``OWUI_MASTER_MODEL_ID``) searches the KBs
of every active module at once. Its knowledge list is rebuilt from the database
on every sync, so it never drifts from what the admin panel shows.

Agents are only ever *created* from our prompt templates. An existing agent —
for instance a hand-tuned preset adopted by a module — keeps its prompt and
settings; a sync rewrites only its knowledge list, activity flag and sharing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.catalog.models import Module
from apps.owui.client import OwuiClient, OwuiError, get_owui_client

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

#: Open WebUI's "every user may read" grant.
PUBLIC_READ = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]

#: Template-model settings a new agent inherits (everything but the prompt).
_INHERITED_META_KEYS = ("capabilities", "builtinTools", "profile_image_url")

#: Settings used when no template preset exists in Open WebUI.
_DEFAULT_PARAMS = {"function_calling": "native", "temperature": 0}
_DEFAULT_META: dict[str, Any] = {
    "capabilities": {"builtin_tools": True, "citations": True, "file_upload": True},
    # Only knowledge search: other built-in tools lure the model into burning
    # its tool-call rounds on chats, memory and notes instead of the KB.
    "builtinTools": {"knowledge": True, "time": True},
}

_MODEL_ID_UNSAFE = re.compile(r"[^a-z0-9-]+")


@dataclass
class SyncReport:
    """What a sync did, for admin messages and the audit log."""

    kb_id: str | None = None
    kb_created: bool = False
    agent_id: str | None = None
    agent_created: bool = False
    master_id: str | None = None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.kb_id:
            parts.append(f"KB {'yaratildi' if self.kb_created else 'ulangan'} ({self.kb_id})")
        if self.agent_id:
            verb = "yaratildi" if self.agent_created else "yangilandi"
            parts.append(f"agent {verb} ({self.agent_id})")
        if self.master_id:
            parts.append(f"umumiy agent yangilandi ({self.master_id})")
        return ", ".join(parts) or "o'zgarish yo'q"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@cache
def _template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def module_prompt(module: Module) -> str:
    return (
        _template("module_agent.md")
        .replace("{{MODUL_NOMI}}", module.name)
        .replace("{{MODUL}}", f'"{module.name}" moduli')
    )


def master_prompt() -> str:
    return _template("master_agent.md")


# ---------------------------------------------------------------------------
# Knowledge bases
# ---------------------------------------------------------------------------


def _kb_name(module: Module) -> str:
    return f"{module.code} - {module.name}"


def ensure_module_kb(module: Module, client: OwuiClient | None = None) -> tuple[str, bool]:
    """Return the module's KB id, creating the KB on first use.

    The module row is locked while the KB is created: two materials of a new
    module indexed in parallel would otherwise both see an empty
    ``owui_kb_id`` and create two KBs, one of which no agent would ever read.
    """
    if module.owui_kb_id:
        return module.owui_kb_id, False

    client = client or get_owui_client()
    with transaction.atomic():
        locked = Module.objects.select_for_update().get(pk=module.pk)
        if locked.owui_kb_id:
            module.owui_kb_id = locked.owui_kb_id
            return locked.owui_kb_id, False

        created = client.create_knowledge_base(
            _kb_name(module),
            module.description or module.name,
            access_grants=PUBLIC_READ if client.config.share_with_users else None,
        )
        if not created.id:
            raise OwuiError(f"Open WebUI {module.code} uchun KB ID qaytarmadi")
        locked.owui_kb_id = created.id
        locked.save(update_fields=["owui_kb_id", "updated_at"])

    module.owui_kb_id = created.id
    return created.id, True


def _knowledge_entry(kb_id: str, name: str, description: str = "") -> dict[str, Any]:
    # The shape Open WebUI's own model editor stores in `meta.knowledge`.
    return {"id": kb_id, "name": name, "type": "collection", "description": description}


def _knowledge_index(client: OwuiClient) -> dict[str, dict[str, Any]]:
    """KB id -> knowledge entry, for everything that currently exists."""
    return {
        kb.id: _knowledge_entry(kb.id, kb.name, kb.description)
        for kb in client.list_knowledge_bases()
        if kb.id
    }


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def default_module_agent_id(module: Module) -> str:
    slug = _MODEL_ID_UNSAFE.sub("-", module.code.lower()).strip("-") or str(module.pk)
    return f"turizm-{slug}"[:100]


def _template_settings(client: OwuiClient) -> dict[str, Any]:
    """base model, params and meta a new agent starts from."""
    config = client.config
    settings: dict[str, Any] = {
        "base_model_id": config.agent_base_model,
        "params": dict(_DEFAULT_PARAMS),
        "meta": {**_DEFAULT_META, "toolIds": list(config.agent_tool_ids)},
    }

    template_id = config.agent_template_model_id
    if not template_id:
        return settings
    try:
        template = client.get_model(template_id)
    except OwuiError as exc:
        logger.warning("Shablon agent %s o'qilmadi: %s", template_id, exc)
        return settings
    if not template:
        return settings

    params = {k: v for k, v in (template.get("params") or {}).items() if k != "system"}
    meta = template.get("meta") or {}
    settings["base_model_id"] = template.get("base_model_id") or config.agent_base_model
    settings["params"] = params or settings["params"]
    for key in _INHERITED_META_KEYS:
        if meta.get(key) is not None:
            settings["meta"][key] = meta[key]
    if meta.get("toolIds"):
        settings["meta"]["toolIds"] = meta["toolIds"]
    return settings


def _upsert_agent(
    client: OwuiClient,
    *,
    model_id: str,
    name: str,
    description: str,
    prompt: str,
    knowledge: list[dict[str, Any]],
    is_active: bool,
) -> bool:
    """Create the agent, or update the parts of it we own. True when created."""
    grants = PUBLIC_READ if client.config.share_with_users else None
    existing = client.get_model(model_id)

    if existing is None:
        settings = _template_settings(client)
        payload: dict[str, Any] = {
            "id": model_id,
            "base_model_id": settings["base_model_id"],
            "name": name,
            "params": {**settings["params"], "system": prompt},
            "meta": {**settings["meta"], "description": description, "knowledge": knowledge},
            "is_active": is_active,
        }
        if grants is not None:
            payload["access_grants"] = grants
        client.create_model(payload)
        return True

    # Send back everything Open WebUI gave us so nothing else is reset; the
    # update endpoint replaces the whole preset.
    payload = {
        "id": model_id,
        "base_model_id": existing.get("base_model_id"),
        "name": existing.get("name") or name,
        "params": existing.get("params") or {},
        "meta": {**(existing.get("meta") or {}), "knowledge": knowledge},
        "is_active": is_active,
    }
    if grants is not None:
        payload["access_grants"] = grants
    client.update_model(payload)
    return False


def sync_module_agent(module: Module, client: OwuiClient | None = None) -> tuple[str, bool]:
    """Point the module's agent at the module's KB (creating either as needed)."""
    client = client or get_owui_client()
    kb_id, _ = ensure_module_kb(module, client)
    kb = client.get_knowledge_base(kb_id)

    model_id = module.owui_model_id or default_module_agent_id(module)
    created = _upsert_agent(
        client,
        model_id=model_id,
        name=f"{module.name} — gid yordamchisi",
        description=(
            f'Gid tayyorlash kursi, "{module.name}" moduli. Faqat modul materiallari '
            "asosida javob beradi, har javobda manba ko'rsatadi."
        ),
        prompt=module_prompt(module),
        knowledge=[_knowledge_entry(kb_id, kb.name or _kb_name(module), kb.description)],
        is_active=module.is_active,
    )

    if module.owui_model_id != model_id:
        module.owui_model_id = model_id
        Module.objects.filter(pk=module.pk).update(owui_model_id=model_id)
    return model_id, created


def sync_master_agent(client: OwuiClient | None = None) -> str | None:
    """Rebuild the master agent's knowledge list from every active module."""
    client = client or get_owui_client()
    model_id = client.config.master_model_id
    if not model_id:
        return None

    available = _knowledge_index(client)
    kb_ids = (
        Module.objects.filter(is_active=True)
        .exclude(owui_kb_id__isnull=True)
        .exclude(owui_kb_id="")
        .order_by("order_index", "code")
        .values_list("owui_kb_id", flat=True)
    )
    knowledge = [available[kb_id] for kb_id in kb_ids if kb_id in available]

    # Nothing to search yet: do not create an agent that can only say
    # "not found", but do empty an existing one.
    if not knowledge and client.get_model(model_id) is None:
        return None

    _upsert_agent(
        client,
        model_id=model_id,
        name=client.config.master_model_name,
        description=(
            "Gid tayyorlash kursi — barcha modullar bo'yicha umumiy yordamchi. "
            "Faqat kurs materiallari asosida javob beradi, har javobda manba ko'rsatadi."
        ),
        prompt=master_prompt(),
        knowledge=knowledge,
        is_active=True,
    )
    return model_id


def sync_module(module: Module, client: OwuiClient | None = None) -> SyncReport:
    """KB, module agent and master agent — the full chain for one module."""
    client = client or get_owui_client()
    report = SyncReport()

    kb_id, report.kb_created = ensure_module_kb(module, client)
    report.kb_id = kb_id
    if client.config.share_with_users and not report.kb_created:
        # An adopted KB may still be private to whoever created it.
        client.update_knowledge_access(kb_id, PUBLIC_READ)

    report.agent_id, report.agent_created = sync_module_agent(module, client)
    report.master_id = sync_master_agent(client)
    return report


def sync_module_safely(module: Module) -> SyncReport | None:
    """sync_module for callers that must not fail because Open WebUI did.

    Returns None when Open WebUI is not configured or the sync failed; the
    failure is logged so it can be retried from the admin panel.
    """
    client = get_owui_client()
    if not client.is_configured:
        return None
    try:
        return sync_module(module, client)
    except OwuiError as exc:
        logger.warning("Modul %s Open WebUI bilan sinxronlanmadi: %s", module.code, exc)
        return None


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def purge_files(file_ids: list[str], client: OwuiClient | None = None) -> None:
    """Delete files; Open WebUI also unlinks them from every KB."""
    client = client or get_owui_client()
    if not client.is_configured:
        return
    for file_id in file_ids:
        client.delete_file(file_id)


def purge_module(kb_id: str | None, model_id: str | None, client: OwuiClient | None = None) -> None:
    """Remove what a deleted module owned in Open WebUI, then refresh the master.

    The KB's files go first: deleting a KB leaves its files behind.
    """
    client = client or get_owui_client()
    if not client.is_configured:
        return

    if kb_id:
        try:
            purge_files(client.list_knowledge_file_ids(kb_id), client)
        except OwuiError as exc:
            logger.warning("KB %s fayllari o'qilmadi: %s", kb_id, exc)
        client.delete_knowledge_base(kb_id)
    if model_id and model_id != client.config.master_model_id:
        client.delete_model(model_id)

    try:
        sync_master_agent(client)
    except OwuiError as exc:
        logger.warning("Umumiy agent yangilanmadi: %s", exc)
