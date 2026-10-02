"""Scanned-PDF fixtures and a fake OCR backend for the OCR tests."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from apps.pipeline.ocr.base import PageResult

UZ_CYRILLIC = "Ўзбекистон туризми қадимий шаҳарлар ғурури ва меҳмондўстлик анъаналари. "


def scanned_pdf(path: Path, pages: int = 3) -> Path:
    """A PDF whose pages are images only — no text layer, like a scanner's."""
    from PIL import Image, ImageDraw

    images = []
    for number in range(1, pages + 1):
        image = Image.new("L", (620, 877), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 60, 560, 120), outline=0, width=3)
        draw.text((80, 80), f"page {number}", fill=0)
        images.append(image)
    images[0].save(path, "PDF", resolution=75, save_all=True, append_images=images[1:])
    return path


def text_pdf(path: Path, text: str) -> Path:
    from tests.pipeline.test_parser import TestPdf

    return TestPdf._build_pdf(path, text)


def merge_pdfs(path: Path, *parts: Path) -> Path:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        for page in PdfReader(part).pages:
            writer.add_page(page)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


class FakeBackend:
    """Answers every page with `text_for(page)`; records what it was asked."""

    name = "fake"

    def __init__(
        self,
        text_for: Callable[[int], str] | None = None,
        confidence: float = 91.0,
        fail_pages: frozenset[int] = frozenset(),
    ):
        self.text_for = text_for or (lambda page: f"Sahifa {page} matni: ekoturizm asoslari.")
        self.confidence = confidence
        self.fail_pages = fail_pages
        self.calls: list[tuple[list[int], str]] = []

    def ocr_pages(
        self,
        pdf_path: Path,
        pages: list[int],
        languages: str,
        on_page: Callable[[PageResult], None],
        cancel: threading.Event | None = None,
    ) -> None:
        self.calls.append((list(pages), languages))
        for page in pages:
            failed = page in self.fail_pages
            on_page(
                PageResult(
                    page=page,
                    text="" if failed else self.text_for(page),
                    confidence=0.0 if failed else self.confidence,
                    engine=self.name,
                    languages=languages,
                    error="timeout" if failed else None,
                )
            )

    @property
    def pages_seen(self) -> list[int]:
        return sorted(page for pages, _ in self.calls for page in pages)
