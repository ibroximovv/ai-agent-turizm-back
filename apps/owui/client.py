"""Open WebUI REST client.

Pure HTTP against ``OWUI_URL`` with a Bearer ``OWUI_API_KEY``:

====================================================  ==========================
``GET  /api/v1/knowledge/``                           list knowledge bases
``POST /api/v1/knowledge/create``                     create a knowledge base
``POST /api/v1/files/``                               upload a Markdown file
``POST /api/v1/knowledge/{kb_id}/file/add``           link a file to a KB
``POST /api/v1/knowledge/{kb_id}/file/remove``        unlink a file from a KB
``DELETE /api/v1/files/{file_id}``                    purge a file
====================================================  ==========================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from config.app_config import OwuiConfig, owui_config

logger = logging.getLogger(__name__)


class OwuiError(RuntimeError):
    """Open WebUI rejected a call; the message carries the reason."""


@dataclass(frozen=True)
class OwuiKnowledgeBase:
    id: str
    name: str
    description: str = ""
    files: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OwuiKnowledgeBase:
        return cls(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            description=str(payload.get("description") or ""),
            files=tuple(payload.get("files") or ()),
        )


@dataclass(frozen=True)
class OwuiFileUploadResult:
    id: str
    filename: str


@dataclass(frozen=True)
class OwuiConnectionStatus:
    connected: bool
    base_url: str
    has_api_key: bool
    message: str
    knowledge_bases_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connected": self.connected,
            "baseUrl": self.base_url,
            "hasApiKey": self.has_api_key,
            "message": self.message,
        }
        if self.knowledge_bases_count is not None:
            payload["knowledgeBasesCount"] = self.knowledge_bases_count
        return payload


def _describe_error(exc: Exception) -> str:
    """Keep the reason Open WebUI rejected a call attached to the error.

    An httpx status error otherwise reads as a bare "Client error '401'", which
    hides the `detail` Open WebUI actually returned.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        detail: Any = None
        try:
            body = exc.response.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("message")
        except ValueError:
            detail = exc.response.text[:300]
        return f"HTTP {exc.response.status_code}: {detail or exc.response.reason_phrase}"
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__}: {exc}"
    return str(exc)


class OwuiClient:
    def __init__(self, config: OwuiConfig | None = None) -> None:
        self.config = config or owui_config()
        self.base_url = self.config.url
        self.api_key = self.config.api_key

    # -- plumbing ---------------------------------------------------------

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.config.timeout_seconds,
            headers=headers,
            follow_redirects=True,
        )

    def _request(self, label: str, method: str, url: str, **kwargs) -> Any:
        try:
            with self._client() as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
        except Exception as exc:
            raise OwuiError(f"{label}: {_describe_error(exc)}") from exc

    @property
    def is_configured(self) -> bool:
        """True when an API key is present, i.e. calls have a chance of succeeding."""
        return self.config.is_configured

    # -- diagnostics ------------------------------------------------------

    def check_connection(self) -> OwuiConnectionStatus:
        if not self.is_configured:
            return OwuiConnectionStatus(
                connected=False,
                base_url=self.base_url,
                has_api_key=False,
                message="OWUI_API_KEY .env faylda sozlanmagan",
            )

        try:
            knowledge_bases = self.list_knowledge_bases()
        except OwuiError as exc:
            logger.warning("Open WebUI ulanish tekshiruvi muvaffaqiyatsiz: %s", exc)
            return OwuiConnectionStatus(
                connected=False,
                base_url=self.base_url,
                has_api_key=True,
                message=f"{self.base_url} ga ulanib bo'lmadi: {exc}",
            )

        return OwuiConnectionStatus(
            connected=True,
            base_url=self.base_url,
            has_api_key=True,
            knowledge_bases_count=len(knowledge_bases),
            message=(
                f"Open WebUI ga muvaffaqiyatli ulandi "
                f"({len(knowledge_bases)} ta Knowledge Base topildi)"
            ),
        )

    # -- knowledge bases --------------------------------------------------

    def list_knowledge_bases(self) -> list[OwuiKnowledgeBase]:
        data = self._request("Knowledge base ro'yxati", "GET", "/api/v1/knowledge/")
        if isinstance(data, dict):
            data = data.get("items") or []
        if not isinstance(data, list):
            return []
        return [OwuiKnowledgeBase.from_payload(item) for item in data if isinstance(item, dict)]

    def create_knowledge_base(self, name: str, description: str = "") -> OwuiKnowledgeBase:
        data = self._request(
            f'Knowledge base yaratish "{name}"',
            "POST",
            "/api/v1/knowledge/create",
            json={"name": name, "description": description or name},
        )
        return OwuiKnowledgeBase.from_payload(data or {})

    def get_knowledge_base(self, kb_id: str) -> OwuiKnowledgeBase:
        data = self._request(
            f"Knowledge base {kb_id}",
            "GET",
            f"/api/v1/knowledge/{quote(kb_id, safe='')}",
        )
        return OwuiKnowledgeBase.from_payload(data or {})

    # -- files ------------------------------------------------------------

    def upload_markdown_file(self, filename: str, content: str | bytes) -> OwuiFileUploadResult:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        data = self._request(
            f'Yuklash "{filename}"',
            "POST",
            "/api/v1/files/",
            files={"file": (filename, payload, "text/markdown")},
            params={"process": "true"},
        )
        data = data or {}
        return OwuiFileUploadResult(
            id=str(data.get("id", "")), filename=str(data.get("filename", filename))
        )

    def add_file_to_knowledge_base(self, kb_id: str, file_id: str) -> bool:
        self._request(
            f"Faylni ({file_id}) KB ({kb_id}) ga bog'lash",
            "POST",
            f"/api/v1/knowledge/{quote(kb_id, safe='')}/file/add",
            json={"file_id": file_id},
        )
        return True

    def remove_file_from_knowledge_base(self, kb_id: str, file_id: str) -> bool:
        """Best effort — a failed cleanup must not abort the caller's own work."""
        try:
            self._request(
                "unlink",
                "POST",
                f"/api/v1/knowledge/{quote(kb_id, safe='')}/file/remove",
                json={"file_id": file_id},
            )
            return True
        except OwuiError as exc:
            logger.warning("Fayl %s ni KB %s dan uzib bo'lmadi: %s", file_id, kb_id, exc)
            return False

    def delete_file(self, file_id: str) -> bool:
        """Best effort, for the same reason as :meth:`remove_file_from_knowledge_base`."""
        try:
            self._request("delete", "DELETE", f"/api/v1/files/{quote(file_id, safe='')}")
            return True
        except OwuiError as exc:
            logger.warning("Open WebUI'da fayl %s o'chirilmadi: %s", file_id, exc)
            return False


def get_owui_client() -> OwuiClient:
    """A fresh client per call — configuration is cheap and this stays thread-safe."""
    return OwuiClient()
