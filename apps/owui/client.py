"""Open WebUI REST client.

Pure HTTP against ``OWUI_URL`` with a Bearer ``OWUI_API_KEY``:

====================================================  ==========================
``GET  /api/v1/knowledge/``                           list knowledge bases
``POST /api/v1/knowledge/create``                     create a knowledge base
``POST /api/v1/files/``                               upload a Markdown file
``POST /api/v1/knowledge/{kb_id}/file/add``           link a file to a KB
``GET  /api/v1/knowledge/{kb_id}/files``              list a KB's files
``POST /api/v1/knowledge/{kb_id}/access/update``      share a KB
``DELETE /api/v1/knowledge/{kb_id}/delete``           delete a KB
``DELETE /api/v1/files/{file_id}``                    purge a file (and its KB links)
``GET  /api/v1/models/list``                          list agent presets
``GET  /api/v1/models/model?id=``                     read an agent preset
``POST /api/v1/models/create``                        create an agent preset
``POST /api/v1/models/model/update``                  update an agent preset
``POST /api/v1/models/model/delete``                  delete an agent preset
====================================================  ==========================
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from config.app_config import OwuiConfig, owui_config

logger = logging.getLogger(__name__)


class OwuiError(RuntimeError):
    """Open WebUI rejected a call; the message carries the reason.

    `transient` marks failures worth retrying: the embedding provider behind
    Open WebUI rate-limited (429) or was briefly unavailable (5xx).
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


#: Open WebUI wraps the embedding provider's error in its own HTTP 400, e.g.
#: ``400: 429, message='Too Many Requests', url='…/embeddings'``. Matched
#: against the response detail only — never the call label, whose file and
#: KB UUIDs could contain the same digits.
_TRANSIENT_DETAIL = re.compile(
    r"(?<![\w-])(?:429|502|503|504)(?![\w-])"
    r"|too many requests|service unavailable|resource[_ ]exhausted"
    r"|rate.?limit|temporarily unavailable|overloaded",
    re.IGNORECASE,
)
_TRANSIENT_STATUS = frozenset({429, 502, 503, 504})

#: While the provider is rate-limiting, every pipeline worker waits — not only
#: the one that was refused — so the pool stops hammering it in parallel.
_cooldown_lock = threading.Lock()
_cooldown_until = 0.0


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in _TRANSIENT_STATUS:
            return True
        try:
            body = exc.response.json()
            detail = body.get("detail") or body.get("message") if isinstance(body, dict) else body
        except ValueError:
            detail = exc.response.text[:500]
        return bool(_TRANSIENT_DETAIL.search(str(detail or "")))
    return False


def _wait_for_cooldown() -> None:
    delay = _cooldown_until - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _extend_cooldown(seconds: float) -> None:
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


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

    def _request(
        self, label: str, method: str, url: str, *, timeout: float | None = None, **kwargs
    ) -> Any:
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            with self._client() as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
        except Exception as exc:
            raise OwuiError(
                f"{label}: {_describe_error(exc)}", transient=_is_transient(exc)
            ) from exc

    def _with_retry(
        self,
        call: Callable[[], Any],
        on_retry: Callable[[int, int, float, OwuiError], None] | None = None,
    ) -> Any:
        """Run `call`, retrying transient failures with exponential backoff.

        Anything else — and the last transient failure — is raised as is.
        """
        attempts = self.config.retry_attempts
        for attempt in range(1, attempts + 1):
            _wait_for_cooldown()
            try:
                return call()
            except OwuiError as exc:
                if not exc.transient or attempt == attempts:
                    raise
                delay = min(
                    self.config.retry_base_seconds * 2 ** (attempt - 1),
                    self.config.retry_max_seconds,
                )
                logger.warning(
                    "Open WebUI vaqtincha rad etdi (%d/%d), %.0f s kutiladi: %s",
                    attempt, attempts, delay, exc,
                )
                if on_retry is not None:
                    on_retry(attempt, attempts, delay, exc)
                _extend_cooldown(delay)
        raise AssertionError("unreachable")

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

    def create_knowledge_base(
        self, name: str, description: str = "", access_grants: list[dict] | None = None
    ) -> OwuiKnowledgeBase:
        payload: dict[str, Any] = {"name": name, "description": description or name}
        if access_grants is not None:
            payload["access_grants"] = access_grants
        data = self._request(
            f'Knowledge base yaratish "{name}"',
            "POST",
            "/api/v1/knowledge/create",
            json=payload,
        )
        return OwuiKnowledgeBase.from_payload(data or {})

    def update_knowledge_access(self, kb_id: str, access_grants: list[dict]) -> None:
        self._request(
            f"Knowledge base {kb_id} ruxsatlari",
            "POST",
            f"/api/v1/knowledge/{quote(kb_id, safe='')}/access/update",
            json={"access_grants": access_grants},
        )

    def list_knowledge_file_ids(self, kb_id: str) -> list[str]:
        """Every file linked to a KB; the endpoint pages 30 at a time."""
        ids: list[str] = []
        page = 1
        while True:
            data = self._request(
                f"Knowledge base {kb_id} fayllari",
                "GET",
                f"/api/v1/knowledge/{quote(kb_id, safe='')}/files",
                params={"page": page},
            )
            items = (data or {}).get("items") or [] if isinstance(data, dict) else []
            ids.extend(str(item["id"]) for item in items if item.get("id"))
            total = (data or {}).get("total") if isinstance(data, dict) else None
            if not items or (isinstance(total, int) and len(ids) >= total):
                return ids
            page += 1

    def delete_knowledge_base(self, kb_id: str) -> bool:
        """Best effort. Open WebUI also strips the KB from every agent that used it."""
        try:
            self._request(
                "KB o'chirish", "DELETE", f"/api/v1/knowledge/{quote(kb_id, safe='')}/delete"
            )
            return True
        except OwuiError as exc:
            logger.warning("Open WebUI'da KB %s o'chirilmadi: %s", kb_id, exc)
            return False

    def get_knowledge_base(self, kb_id: str) -> OwuiKnowledgeBase:
        data = self._request(
            f"Knowledge base {kb_id}",
            "GET",
            f"/api/v1/knowledge/{quote(kb_id, safe='')}",
        )
        return OwuiKnowledgeBase.from_payload(data or {})

    # -- files ------------------------------------------------------------

    def upload_markdown_file(self, filename: str, content: str | bytes) -> OwuiFileUploadResult:
        """Upload and extract the file before returning.

        Open WebUI processes uploads in the background by default, and linking
        a file whose extraction has not finished yet fails with "empty
        content" — large documents lost that race. Processing inline removes
        it, at the cost of a longer request, hence the indexing timeout.
        """
        payload = content.encode("utf-8") if isinstance(content, str) else content
        data = self._request(
            f'Yuklash "{filename}"',
            "POST",
            "/api/v1/files/",
            files={"file": (filename, payload, "text/markdown")},
            params={"process": "true", "process_in_background": "false"},
            timeout=self.config.index_timeout_seconds,
        )
        data = data or {}
        return OwuiFileUploadResult(
            id=str(data.get("id", "")), filename=str(data.get("filename", filename))
        )

    def add_file_to_knowledge_base(
        self,
        kb_id: str,
        file_id: str,
        on_retry: Callable[[int, int, float, OwuiError], None] | None = None,
    ) -> bool:
        """Link a file to a KB, which embeds it into the KB's collection.

        This is the step the embedding provider rate-limits. Retrying it is
        safe: Open WebUI embeds everything before writing, so a refused call
        leaves nothing half-linked, and a retry rebuilds from the file's
        stored text.
        """
        self._with_retry(
            lambda: self._request(
                f"Faylni ({file_id}) KB ({kb_id}) ga bog'lash",
                "POST",
                f"/api/v1/knowledge/{quote(kb_id, safe='')}/file/add",
                json={"file_id": file_id},
                timeout=self.config.index_timeout_seconds,
            ),
            on_retry,
        )
        return True

    def delete_file(self, file_id: str) -> bool:
        """Best effort — a failed cleanup must not abort the caller's own work.
        Open WebUI also unlinks the file from every KB that held it."""
        try:
            self._request("delete", "DELETE", f"/api/v1/files/{quote(file_id, safe='')}")
            return True
        except OwuiError as exc:
            logger.warning("Open WebUI'da fayl %s o'chirilmadi: %s", file_id, exc)
            return False


    # -- agents (workspace model presets) ----------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        """Workspace presets — the agents — not the raw provider models."""
        models: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "Agentlar ro'yxati", "GET", "/api/v1/models/list", params={"page": page}
            )
            items = data.get("items") or [] if isinstance(data, dict) else []
            models.extend(item for item in items if isinstance(item, dict))
            total = data.get("total") if isinstance(data, dict) else None
            if not items or (isinstance(total, int) and len(models) >= total):
                return models
            page += 1

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        """None when the preset does not exist (Open WebUI answers 404)."""
        try:
            with self._client() as client:
                response = client.get("/api/v1/models/model", params={"id": model_id})
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise OwuiError(f"Agent {model_id}: {_describe_error(exc)}") from exc
        return data if isinstance(data, dict) else None

    def create_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            f'Agent yaratish "{payload.get("id")}"', "POST", "/api/v1/models/create", json=payload
        ) or {}

    def update_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            f'Agentni yangilash "{payload.get("id")}"',
            "POST",
            "/api/v1/models/model/update",
            json=payload,
        ) or {}

    def delete_model(self, model_id: str) -> bool:
        """Best effort, like the other cleanup calls."""
        try:
            self._request(
                "Agent o'chirish", "POST", "/api/v1/models/model/delete", json={"id": model_id}
            )
            return True
        except OwuiError as exc:
            logger.warning("Open WebUI'da agent %s o'chirilmadi: %s", model_id, exc)
            return False


def get_owui_client() -> OwuiClient:
    """A fresh client per call — configuration is cheap and this stays thread-safe."""
    return OwuiClient()
