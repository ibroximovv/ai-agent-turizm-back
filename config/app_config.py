"""Typed, pre-parsed application configuration.

Port of the NestJS `config/configuration.ts`. Feature code reads these objects
through :func:`uploads_config` / :func:`owui_config` instead of touching
``os.environ`` directly, so every default lives in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadsConfig:
    """Absolute roots for the raw uploads and the generated Markdown."""

    root_dir: Path
    raw_dir: Path
    ready_dir: Path
    max_bytes: int

    @property
    def max_mb(self) -> int:
        return self.max_bytes // (1024 * 1024)


@dataclass(frozen=True)
class OwuiConfig:
    url: str
    api_key: str | None
    timeout_seconds: float
    #: Uploading and linking a file embeds it synchronously, which for a large
    #: document takes minutes rather than the seconds a metadata call needs.
    index_timeout_seconds: float = 600.0
    #: Pipe model every generated agent runs on.
    agent_base_model: str = "turizm_router.avto"
    agent_tool_ids: tuple[str, ...] = ("ofis_saqlash_tool",)
    #: Hand-tuned preset whose settings (capabilities, built-in tools, params)
    #: new agents copy; the system prompt still comes from our own template.
    agent_template_model_id: str = ""
    #: Agent that searches every module's knowledge base at once.
    master_model_id: str = "turizm-umumiy-agent"
    master_model_name: str = "Turizm — umumiy gid yordamchisi"
    #: Grant every Open WebUI user read access to the agents and their KBs.
    share_with_users: bool = True

    @property
    def is_configured(self) -> bool:
        """True when an API key is present, i.e. calls have a chance to succeed."""
        return bool(self.api_key)


def build_uploads_config(
    uploads_dir: str | None, max_upload_mb: int, base_dir: Path
) -> UploadsConfig:
    root = (
        Path(uploads_dir).expanduser().resolve()
        if uploads_dir
        else (base_dir / "uploads").resolve()
    )
    return UploadsConfig(
        root_dir=root,
        raw_dir=root / "raw",
        ready_dir=root / "ready",
        max_bytes=max_upload_mb * 1024 * 1024,
    )


def build_owui_config(
    url: str,
    api_key: str,
    timeout_ms: int,
    index_timeout_ms: int = 600000,
    agent_base_model: str = "turizm_router.avto",
    agent_tool_ids: list[str] | tuple[str, ...] = ("ofis_saqlash_tool",),
    agent_template_model_id: str = "",
    master_model_id: str = "turizm-umumiy-agent",
    master_model_name: str = "Turizm — umumiy gid yordamchisi",
    share_with_users: bool = True,
) -> OwuiConfig:
    """Knowledge Base ids are deliberately absent here: each module owns its
    own KB in `modules.owui_kb_id`, so there is no single global one."""
    return OwuiConfig(
        url=url.rstrip("/") or "http://localhost:8080",
        api_key=api_key.strip() or None,
        # The rest of the stack speaks milliseconds; httpx wants seconds.
        timeout_seconds=timeout_ms / 1000,
        index_timeout_seconds=max(index_timeout_ms, timeout_ms) / 1000,
        agent_base_model=agent_base_model.strip(),
        agent_tool_ids=tuple(tool.strip() for tool in agent_tool_ids if tool.strip()),
        agent_template_model_id=agent_template_model_id.strip(),
        master_model_id=master_model_id.strip(),
        master_model_name=master_model_name.strip() or master_model_id.strip(),
        share_with_users=share_with_users,
    )


def uploads_config() -> UploadsConfig:
    from django.conf import settings

    return settings.UPLOADS


def owui_config() -> OwuiConfig:
    from django.conf import settings

    return settings.OWUI
