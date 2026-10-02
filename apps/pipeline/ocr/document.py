"""OCR for the pages of one document: cache, language choice, progress.

Backend-independent on purpose — the same flow drives the local Tesseract
backend today and the remote OCR server later.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from apps.pipeline.ocr.base import OcrBackend, OcrError, PageResult
from apps.pipeline.ocr.cache import OcrCache
from apps.pipeline.ocr.detect import narrow_languages

#: Pages read with the full language set before narrowing it. Probing goes on
#: in batches of this size while the pages read so far hold too little text
#: to tell the script (covers, blank pages), up to `MAX_PROBE_BATCHES`.
PROBE_PAGES = 3
MAX_PROBE_BATCHES = 3


@dataclass
class OcrRequest:
    backend: OcrBackend
    languages: str
    cache: OcrCache | None = None
    auto_language: bool = True
    #: OCR every page, even those with a good text layer. (A fresh run that
    #: ignores earlier results is made by clearing the cache beforehand.)
    force: bool = False
    max_pages: int = 1000
    min_confidence: float = 60.0
    #: (pages done, pages total)
    on_progress: Callable[[int, int], None] | None = None
    #: (level, message) with level "info" / "warn"
    on_log: Callable[[str, str], None] | None = None
    cancel: threading.Event | None = None


@dataclass
class OcrOutcome:
    pages: dict[int, PageResult] = field(default_factory=dict)
    languages: str = ""
    cached: int = 0

    @property
    def confidence(self) -> float | None:
        scores = [result.confidence for result in self.pages.values() if result.text]
        return round(sum(scores) / len(scores), 1) if scores else None

    def failed(self) -> list[int]:
        return sorted(page for page, result in self.pages.items() if result.error)

    def low_confidence(self, threshold: float) -> list[int]:
        return sorted(
            page
            for page, result in self.pages.items()
            if result.text and result.confidence < threshold
        )


def ocr_document(pdf_path: Path, pages: list[int], request: OcrRequest) -> OcrOutcome:
    if len(pages) > request.max_pages:
        raise OcrError(
            f"Hujjatda OCR talab qiladigan {len(pages)} ta sahifa bor — ruxsat etilgan "
            f"chegara {request.max_pages} (OCR_MAX_PAGES)."
        )

    outcome = OcrOutcome(languages=request.languages)
    total = len(pages)

    if request.cache is not None:
        for page in pages:
            cached = request.cache.get(page)
            if cached is not None:
                outcome.pages[page] = cached
    outcome.cached = len(outcome.pages)

    def on_page(result: PageResult) -> None:
        outcome.pages[result.page] = result
        if request.cache is not None:
            request.cache.put(result)
        _progress(request, len(outcome.pages), total)

    todo = [page for page in pages if page not in outcome.pages]
    _progress(request, len(outcome.pages), total)
    if not todo:
        return outcome

    _log(
        request,
        "info",
        f"OCR boshlandi ({request.backend.name}): {len(todo)} ta sahifa"
        + (f", {outcome.cached} tasi keshdan olindi" if outcome.cached else ""),
    )

    languages = request.languages
    if request.auto_language:
        languages, todo = _choose_languages(pdf_path, todo, request, outcome, on_page)
    outcome.languages = languages

    request.backend.ocr_pages(pdf_path, todo, languages, on_page, request.cancel)
    return outcome


def _choose_languages(pdf_path, todo, request, outcome, on_page) -> tuple[str, list[int]]:
    """Read pages with every configured language until the script is clear,
    then narrow to that script's model for the rest."""
    from apps.pipeline.services.translit import detect_script  # see detect.py

    for batch in range(MAX_PROBE_BATCHES + 1):
        sample = " ".join(outcome.pages[page].text for page in sorted(outcome.pages))[:8000]
        if detect_script(sample) != "other":
            languages = narrow_languages(sample, request.languages)
            if languages != request.languages:
                _log(request, "info", f"OCR tili aniqlandi: {languages}")
            return languages, todo
        if batch == MAX_PROBE_BATCHES or not todo:
            break
        probe, todo = todo[:PROBE_PAGES], todo[PROBE_PAGES:]
        request.backend.ocr_pages(pdf_path, probe, request.languages, on_page, request.cancel)
    return request.languages, todo


def _progress(request: OcrRequest, done: int, total: int) -> None:
    if request.on_progress is not None:
        request.on_progress(done, total)


def _log(request: OcrRequest, level: str, message: str) -> None:
    if request.on_log is not None:
        request.on_log(level, message)
