"""Document text extraction for PDF, PPTX, DOCX, TXT and MD."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from apps.pipeline.ocr import OcrUnavailableError
from apps.pipeline.ocr.cleanup import clean_ocr_pages
from apps.pipeline.ocr.detect import SPARSE_PAGE_THRESHOLD, page_needs_ocr
from apps.pipeline.ocr.document import OcrOutcome, OcrRequest, ocr_document

logger = logging.getLogger(__name__)


_MARKDOWN_HEADING_SPLIT = re.compile(r"(?m)(?=^#{1,3}\s)")
_BLANK_LINE_SPLIT = re.compile(r"(?:\r?\n){3,}")


class UnsupportedFormatError(ValueError):
    """Raised for an extension the pipeline has no parser for."""


@dataclass(frozen=True)
class ParsedChunk:
    #: e.g. "page 1", "slide 3", "section 1"
    label: str
    text: str


@dataclass(frozen=True)
class OcrStats:
    #: Pages whose text came from OCR.
    pages: int
    #: Mean word confidence over those pages, 0–100.
    confidence: float | None
    languages: str
    engine: str


@dataclass
class ParsedDocument:
    chunks: list[ParsedChunk] = field(default_factory=list)
    total_chars: int = 0
    warnings: list[str] = field(default_factory=list)
    #: Set when OCR ran on at least one page.
    ocr: OcrStats | None = None

    @property
    def extraction_method(self) -> str:
        """"text", "ocr" (every page) or "mixed"."""
        if self.ocr is None or self.ocr.pages == 0:
            return "text"
        return "ocr" if self.ocr.pages >= len(self.chunks) else "mixed"


def parse_file(file_path: Path | str, ocr: OcrRequest | None = None) -> ParsedDocument:
    """`ocr` enables OCR for PDF pages without a usable text layer; without it
    such pages are skipped with a warning."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path, ocr)
    if suffix == ".pptx":
        return _parse_pptx(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in (".txt", ".md"):
        return _parse_text_file(path)

    raise UnsupportedFormatError(
        f"Qo'llab-quvvatlanmaydigan fayl formati: {suffix}. "
        "Faqat .pdf, .pptx, .docx, .txt va .md qabul qilinadi."
    )


def _parse_pdf(path: Path, ocr: OcrRequest | None = None) -> ParsedDocument:
    warnings: list[str] = []
    texts, ocr_pages = _read_text_layer(path, ocr)

    stats: OcrStats | None = None
    if ocr_pages:
        try:
            outcome = ocr_document(path, ocr_pages, ocr)
        except OcrUnavailableError as exc:
            # Not the document's fault: keep whatever text layer there is, as
            # before OCR existed, rather than failing a mostly-text PDF.
            warnings.append(f"OCR ishlamadi, sahifalar matn qatlamidan olindi: {exc}")
            ocr_pages = []
        else:
            stats = _apply_ocr(outcome, texts, ocr, warnings)

    for index in sorted(texts):
        if index not in ocr_pages and len(texts[index]) < SPARSE_PAGE_THRESHOLD:
            warnings.append(
                f"{index}-sahifada juda kam matn bor ({len(texts[index])} belgi) — "
                "skanerlangan rasm bo'lishi mumkin."
            )

    chunks = [ParsedChunk(label=f"page {index}", text=texts[index]) for index in sorted(texts)]
    if not chunks:
        warnings.append(
            "PDF ichidan matn topilmadi — hujjat skanerlangan va OCR talab qiladi."
        )

    return ParsedDocument(
        chunks=chunks,
        total_chars=sum(len(chunk.text) for chunk in chunks),
        warnings=warnings,
        ocr=stats,
    )


def _read_text_layer(path: Path, ocr: OcrRequest | None) -> tuple[dict[int, str], list[int]]:
    """Text of every page, and the pages that need OCR instead.

    A function of its own so the reader is freed before OCR starts, and fed a
    file handle: given a path, pypdf reads the whole file into memory — for a
    400 MB scanned book, for the half hour its OCR takes.
    """
    from pypdf import PdfReader

    texts: dict[int, str] = {}
    ocr_pages: list[int] = []
    try:
        with path.open("rb") as handle:
            reader = PdfReader(handle)
            for index, page in enumerate(reader.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if ocr is not None and (ocr.force or page_needs_ocr(page, page_text)):
                    ocr_pages.append(index)
                if page_text:
                    texts[index] = page_text
    except Exception as exc:
        logger.error("PDF parse xatosi %s: %s", path, exc)
        raise RuntimeError(f"PDF o'qib bo'lmadi: {exc}") from exc
    return texts, ocr_pages


def _apply_ocr(
    outcome: OcrOutcome, texts: dict[int, str], ocr: OcrRequest, warnings: list[str]
) -> OcrStats:
    """Replace the text layer of every OCR'd page that produced text."""
    recognised = clean_ocr_pages(
        {page: result.text for page, result in outcome.pages.items() if result.text}
    )
    replaced = 0
    for page, text in recognised.items():
        if text:
            texts[page] = text
            replaced += 1

    failed = outcome.failed()
    if failed:
        warnings.append(f"OCR: {len(failed)} ta sahifa o'qilmadi: {_page_list(failed)}")
    low = outcome.low_confidence(ocr.min_confidence)
    if low:
        warnings.append(
            f"OCR: {len(low)} ta sahifa past ishonch bilan o'qildi "
            f"(< {ocr.min_confidence:.0f}%): {_page_list(low)}"
        )

    return OcrStats(
        pages=replaced,
        confidence=outcome.confidence,
        languages=outcome.languages,
        engine=ocr.backend.name,
    )


def _page_list(pages: list[int], limit: int = 30) -> str:
    shown = ", ".join(str(page) for page in pages[:limit])
    return shown + (f" … (+{len(pages) - limit})" if len(pages) > limit else "")


def _parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation

    warnings: list[str] = []
    chunks: list[ParsedChunk] = []
    total_chars = 0

    presentation = Presentation(str(path))
    slides = list(presentation.slides)
    if not slides:
        warnings.append("Taqdimotda slaydlar topilmadi.")

    for index, slide in enumerate(slides, start=1):
        slide_text = "\n".join(_shape_paragraphs(slide.shapes))

        notes_text = ""
        if slide.has_notes_slide:
            notes_frame = slide.notes_slide.notes_text_frame
            if notes_frame is not None:
                notes_text = " ".join(notes_frame.text.split())

        combined = slide_text
        if notes_text:
            combined += f"\n\n[Presenter Notes: {notes_text}]"
        combined = combined.strip()

        if combined:
            chunks.append(ParsedChunk(label=f"slide {index}", text=combined))
            total_chars += len(combined)

    return ParsedDocument(chunks=chunks, total_chars=total_chars, warnings=warnings)


def _shape_paragraphs(shapes) -> list[str]:
    """One entry per paragraph, preserving each shape's line structure.

    Group shapes are walked recursively; tables contribute one line per row.
    """
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    lines: list[str] = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            lines.extend(_shape_paragraphs(shape.shapes))
            continue

        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                row_text = " | ".join(cell for cell in cells if cell)
                if row_text:
                    lines.append(row_text)
            continue

        if not getattr(shape, "has_text_frame", False):
            continue

        for paragraph in shape.text_frame.paragraphs:
            text = "".join(run.text for run in paragraph.runs).strip()
            if text:
                lines.append(text)

    return lines


def _parse_docx(path: Path) -> ParsedDocument:
    import mammoth

    try:
        with path.open("rb") as handle:
            result = mammoth.convert_to_markdown(handle)
    except Exception as exc:
        raise RuntimeError(f"DOCX o'qib bo'lmadi: {exc}") from exc

    markdown = result.value or ""
    warnings = [message.message for message in result.messages if getattr(message, "message", None)]

    # Split into sections at markdown headings.
    chunks = _to_sequential_chunks(_MARKDOWN_HEADING_SPLIT.split(markdown), "section")
    if not chunks and markdown.strip():
        chunks = [ParsedChunk(label="section 1", text=markdown.strip())]

    return ParsedDocument(
        chunks=chunks,
        total_chars=sum(len(chunk.text) for chunk in chunks),
        warnings=warnings,
    )


def _parse_text_file(path: Path) -> ParsedDocument:
    content = path.read_text(encoding="utf-8", errors="replace")
    chunks = _to_sequential_chunks(_BLANK_LINE_SPLIT.split(content), "part")
    if not chunks and content.strip():
        chunks = [ParsedChunk(label="part 1", text=content.strip())]

    return ParsedDocument(
        chunks=chunks,
        total_chars=sum(len(chunk.text) for chunk in chunks),
        warnings=[],
    )


def _to_sequential_chunks(raw_sections: list[str], label_prefix: str) -> list[ParsedChunk]:
    """Number the labels over the kept sections only.

    Otherwise the emitted grounding markers would reference a section that is
    missing from the document.
    """
    chunks: list[ParsedChunk] = []
    for raw in raw_sections:
        text = raw.strip()
        if not text:
            continue
        chunks.append(ParsedChunk(label=f"{label_prefix} {len(chunks) + 1}", text=text))
    return chunks
