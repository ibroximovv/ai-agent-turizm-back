"""Types shared by every OCR backend.

A backend is asked for *pages of a PDF*, not for page images: the planned
remote backend (a separate OCR server, see ocr-plan.md) is then sent the PDF
once instead of hundreds of rendered pages, and the pipeline code above it does
not change when the backend does.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class OcrError(RuntimeError):
    """OCR failed for the whole document."""


class OcrUnavailableError(OcrError):
    """The configured engine cannot run at all (e.g. Tesseract not installed).

    Unlike other failures this one is not the document's fault, so the parser
    degrades to the text layer instead of failing a PDF that barely needed OCR.
    """


class OcrCancelledError(OcrError):
    """The run was cancelled (the material was deleted or stopped)."""


@dataclass(frozen=True)
class PageResult:
    #: 1-based page number, matching the "page N" grounding labels.
    page: int
    text: str
    #: Mean word confidence, 0–100. 0 when nothing was recognised.
    confidence: float
    #: Which engine produced the text, e.g. "tesseract".
    engine: str
    #: Tesseract languages the page was read with.
    languages: str
    #: Set when this one page could not be recognised (timeout, render error).
    #: The rest of the document is still processed.
    error: str | None = None


class OcrBackend(Protocol):
    name: str

    def ocr_pages(
        self,
        pdf_path: Path,
        pages: list[int],
        languages: str,
        on_page: Callable[[PageResult], None],
        cancel: threading.Event | None = None,
    ) -> None:
        """Recognise `pages` (1-based) and report each through `on_page`.

        `on_page` is called on the caller's thread, in completion order, so it
        may write to the database and the cache. Raises `OcrCancelledError`
        once `cancel` is set, `OcrUnavailableError` when the engine is
        missing.
        """
        ...
