"""OCR on this machine: PDFium renders each page, Tesseract reads it.

Memory is bounded by rendering inside the page task, so at most
`page_workers` page images exist at once — a 500-page book never sits in
memory as images. Tesseract runs as a separate process, so the page threads do
not contend for the GIL.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from apps.pipeline.ocr import tesseract
from apps.pipeline.ocr.base import (
    OcrCancelledError,
    OcrError,
    OcrUnavailableError,
    PageResult,
)
from config.app_config import OcrConfig

logger = logging.getLogger(__name__)

#: PDFium is not thread-safe, not even across separate documents, so every
#: call into it is serialised. Rendering takes a fraction of the time
#: Tesseract needs for the same page, so this costs little parallelism.
_PDFIUM_LOCK = threading.Lock()

#: How often a waiting caller wakes up to look at the cancel flag.
_CANCEL_POLL_SECONDS = 1.0


class LocalBackend:
    name = "tesseract"

    def __init__(self, config: OcrConfig):
        self.config = config

    def ocr_pages(
        self,
        pdf_path: Path,
        pages: list[int],
        languages: str,
        on_page: Callable[[PageResult], None],
        cancel: threading.Event | None = None,
    ) -> None:
        if not pages:
            return

        import pypdfium2 as pdfium

        with _PDFIUM_LOCK:
            try:
                document = pdfium.PdfDocument(str(pdf_path))
            except pdfium.PdfiumError as exc:
                raise OcrError(f"PDF'ni rasmga aylantirib bo'lmadi: {exc}") from exc

        handle = _Document(document)
        try:
            self._run(handle, pages, languages, on_page, cancel)
        finally:
            handle.close()

    def _run(self, document, pages, languages, on_page, cancel) -> None:
        remaining = iter(pages)
        in_flight: dict[Future, int] = {}

        pool = ThreadPoolExecutor(
            max_workers=self.config.page_workers, thread_name_prefix="ocr-page"
        )
        try:
            # Keep exactly `page_workers` pages in flight rather than
            # submitting the whole book up front: cancelling then never has
            # hundreds of queued futures to unwind.
            for _ in range(self.config.page_workers):
                self._submit_next(pool, document, remaining, languages, in_flight)

            while in_flight:
                done, _ = wait(in_flight, timeout=_CANCEL_POLL_SECONDS, return_when=FIRST_COMPLETED)
                if cancel is not None and cancel.is_set():
                    raise OcrCancelledError("OCR to'xtatildi")
                for future in done:
                    in_flight.pop(future)
                    # Unavailable / unexpected errors propagate from here.
                    on_page(future.result())
                    self._submit_next(pool, document, remaining, languages, in_flight)
        except BaseException:
            # Do not wait for the pages still being read: their results are
            # no longer wanted, and a stuck page could hold us for minutes.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)

    def _submit_next(self, pool, document, remaining, languages, in_flight) -> None:
        page = next(remaining, None)
        if page is not None:
            in_flight[pool.submit(self._ocr_page, document, page, languages)] = page

    def _ocr_page(self, document, page: int, languages: str) -> PageResult:
        try:
            image = _render(document, page, self.config.dpi)
            result = tesseract.recognize(
                image,
                languages,
                dpi=self.config.dpi,
                timeout=self.config.page_timeout_seconds,
                cmd=self.config.tesseract_cmd,
                tessdata_dir=self.config.tessdata_dir,
            )
        except OcrUnavailableError:
            raise
        except Exception as exc:
            # One bad page (timeout, broken image) must not cost the other 499.
            logger.warning("OCR: %d-sahifa o'qilmadi: %s", page, exc)
            return PageResult(
                page=page,
                text="",
                confidence=0.0,
                engine=self.name,
                languages=languages,
                error=str(exc),
            )
        return PageResult(
            page=page,
            text=result.text,
            confidence=result.confidence,
            engine=self.name,
            languages=languages,
        )


class _Document:
    """A PDFium document that page threads outliving a cancelled run cannot
    touch after it is closed — PDFium would crash the process, not raise."""

    def __init__(self, pdf):
        self.pdf = pdf
        self.closed = False

    def close(self) -> None:
        with _PDFIUM_LOCK:
            if not self.closed:
                self.closed = True
                self.pdf.close()


def _render(document: _Document, page: int, dpi: int) -> bytearray:
    """One page as an 8-bit grayscale PGM — a third of RGB's memory, and no
    compression step, since it only travels through a pipe to Tesseract.

    Written straight from PDFium's buffer: going through a PIL image costs two
    more full-page copies per worker (~9 MB each at 300 DPI).
    """
    with _PDFIUM_LOCK:
        if document.closed:
            raise OcrCancelledError("OCR to'xtatildi")
        pdf_page = document.pdf[page - 1]
        try:
            bitmap = pdf_page.render(scale=dpi / 72, grayscale=True)
            width, height, stride = bitmap.width, bitmap.height, bitmap.stride
            image = bytearray(f"P5\n{width} {height}\n255\n".encode())
            pixels = memoryview(bitmap.buffer).cast("B")
            if stride == width:
                image += pixels
            else:  # rows are padded to an alignment boundary
                for row in range(height):
                    image += pixels[row * stride : row * stride + width]
            bitmap.close()
        finally:
            pdf_page.close()
    return image
