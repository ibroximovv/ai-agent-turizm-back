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


def build_owui_config(url: str, api_key: str, timeout_ms: int) -> OwuiConfig:
    """Knowledge Base ids are deliberately absent here: each module owns its
    own KB in `modules.owui_kb_id`, so there is no single global one."""
    return OwuiConfig(
        url=url.rstrip("/") or "http://localhost:8080",
        api_key=api_key.strip() or None,
        # The rest of the stack speaks milliseconds; httpx wants seconds.
        timeout_seconds=timeout_ms / 1000,
    )


def uploads_config() -> UploadsConfig:
    from django.conf import settings

    return settings.UPLOADS


def owui_config() -> OwuiConfig:
    from django.conf import settings

    return settings.OWUI
