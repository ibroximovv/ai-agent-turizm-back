"""OCR for scanned PDF pages. See ocr-plan.md for the design."""

from __future__ import annotations

from apps.pipeline.ocr.base import (
    OcrBackend,
    OcrCancelledError,
    OcrError,
    OcrUnavailableError,
    PageResult,
)
from config.app_config import OcrConfig, ocr_config

__all__ = [
    "OcrBackend",
    "OcrCancelledError",
    "OcrError",
    "OcrUnavailableError",
    "PageResult",
    "get_ocr_backend",
]


def get_ocr_backend(config: OcrConfig | None = None) -> OcrBackend | None:
    """The configured backend, or None when OCR is switched off."""
    config = config or ocr_config()
    if config.backend == "local":
        from apps.pipeline.ocr.local import LocalBackend

        return LocalBackend(config)
    return None
