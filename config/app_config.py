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
    #: Per-page OCR results, keyed by the raw file's SHA-256, so a restart or a
    #: retry resumes a long OCR run instead of starting it over.
    ocr_cache_dir: Path

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
    #: Linking a file to a KB embeds it; the embedding provider rate-limits
    #: (429) or is briefly unavailable (503). How often to try, and the first
    #: wait — each following wait doubles, capped at `retry_max_seconds`.
    retry_attempts: int = 6
    retry_base_seconds: float = 20.0
    retry_max_seconds: float = 300.0

    @property
    def is_configured(self) -> bool:
        """True when an API key is present, i.e. calls have a chance to succeed."""
        return bool(self.api_key)


#: Values `OCR_BACKEND` accepts. "remote" (a separate OCR server) is planned —
#: see ocr-plan.md — and will be added here together with its backend.
OCR_BACKENDS = ("none", "local")


@dataclass(frozen=True)
class OcrConfig:
    """How pages without a usable text layer are turned into text."""

    #: "none" keeps the old behaviour (scanned pages are skipped with a
    #: warning); "local" runs Tesseract on this machine.
    backend: str = "local"
    #: Tesseract languages the first pages are read with. With
    #: `auto_language` the rest of the document is narrowed to the script the
    #: first pages turned out to be in.
    languages: str = "uzb+uzb_cyrl+rus"
    auto_language: bool = True
    dpi: int = 300
    #: Documents OCR'd at the same time, on their own queue so short documents
    #: never wait behind a 500-page book.
    concurrency: int = 1
    #: Pages of one document recognised in parallel (one Tesseract process each).
    page_workers: int = 2
    page_timeout_seconds: float = 120.0
    #: Pages whose mean word confidence (0–100) falls below this are reported.
    min_confidence: float = 60.0
    #: Refuse documents that would need more OCR pages than this.
    max_pages: int = 1000
    tesseract_cmd: str = "tesseract"
    #: Directory holding *.traineddata, e.g. a tessdata_best checkout. Empty
    #: means Tesseract's own default.
    tessdata_dir: str = ""

    @property
    def enabled(self) -> bool:
        return self.backend != "none"


def build_ocr_config(
    backend: str = "local",
    languages: str = "uzb+uzb_cyrl+rus",
    auto_language: bool = True,
    dpi: int = 300,
    concurrency: int = 1,
    page_workers: int = 2,
    page_timeout_seconds: float = 120.0,
    min_confidence: float = 60.0,
    max_pages: int = 1000,
    tesseract_cmd: str = "tesseract",
    tessdata_dir: str = "",
) -> OcrConfig:
    backend = (backend or "none").strip().lower()
    if backend not in OCR_BACKENDS:
        raise ValueError(
            f"OCR_BACKEND noto'g'ri: {backend!r}. Ruxsat etilgan: {', '.join(OCR_BACKENDS)}"
        )
    return OcrConfig(
        backend=backend,
        languages=languages.strip() or "uzb+uzb_cyrl+rus",
        auto_language=auto_language,
        # Below ~150 DPI recognition falls apart; above 600 only memory grows.
        dpi=min(max(dpi, 150), 600),
        concurrency=max(1, concurrency),
        page_workers=max(1, page_workers),
        page_timeout_seconds=max(5.0, page_timeout_seconds),
        min_confidence=min(max(min_confidence, 0.0), 100.0),
        max_pages=max(1, max_pages),
        tesseract_cmd=tesseract_cmd.strip() or "tesseract",
        tessdata_dir=tessdata_dir.strip(),
    )


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
        ocr_cache_dir=root / "ocr-cache",
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
    retry_attempts: int = 6,
    retry_base_seconds: float = 20.0,
    retry_max_seconds: float = 300.0,
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
        retry_attempts=max(1, retry_attempts),
        retry_base_seconds=max(0.0, retry_base_seconds),
        retry_max_seconds=max(retry_base_seconds, retry_max_seconds),
    )


def uploads_config() -> UploadsConfig:
    from django.conf import settings

    return settings.UPLOADS


def owui_config() -> OwuiConfig:
    from django.conf import settings

    return settings.OWUI


def ocr_config() -> OcrConfig:
    from django.conf import settings

    return settings.OCR
