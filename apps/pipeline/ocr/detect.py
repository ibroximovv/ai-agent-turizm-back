"""Which PDF pages need OCR, and which Tesseract languages to read them with."""

from __future__ import annotations

import logging
from pathlib import Path

import regex

logger = logging.getLogger(__name__)

#: Below this, a PDF page is most likely a scanned image rather than text.
SPARSE_PAGE_THRESHOLD = 40

#: A text layer this short of letters is junk: a broken font encoding or an
#: old OCR layer made with the wrong language.
MIN_LETTER_RATIO = 0.5
MAX_REPLACEMENT_RATIO = 0.05

#: `pdf_needs_ocr` samples at most this many pages, spread over the document.
SAMPLE_PAGES = 10
#: Estimated OCR pages from which a document goes to the OCR queue. A text
#: PDF with a scanned cover is not worth a slot there.
OCR_QUEUE_MIN_PAGES = 10

#: Form XObjects nest; real documents rarely go deeper than this.
_MAX_XOBJECT_DEPTH = 4

_LETTER = regex.compile(r"\p{L}")
_VISIBLE = regex.compile(r"\S")

#: Tesseract languages that read each script `detect_script` reports.
SCRIPT_LANGUAGES = {
    "uz-cyrl": "uzb_cyrl",
    "ru": "rus",
    "uz-latn": "uzb",
}


def is_garbled(text: str) -> bool:
    visible = len(_VISIBLE.findall(text))
    if visible == 0:
        return False
    letters = len(_LETTER.findall(text))
    replacements = text.count("�")
    return letters / visible < MIN_LETTER_RATIO or replacements / visible > MAX_REPLACEMENT_RATIO


def page_needs_ocr(page, text: str) -> bool:
    """True for a page whose text layer is missing, too thin or junk, and which
    holds an image that the missing text could be in."""
    stripped = text.strip()
    if len(stripped) >= SPARSE_PAGE_THRESHOLD and not is_garbled(stripped):
        return False
    return has_image(page)


def has_image(page) -> bool:
    """Look for an image XObject without decoding it (`page.images` would
    decompress every scan just to answer yes)."""
    try:
        resources = page.get("/Resources")
        return _resources_have_image(resources, depth=0)
    except Exception as exc:  # malformed resources: assume a scan, let OCR decide
        logger.debug("Sahifa resurslarini o'qib bo'lmadi: %s", exc)
        return True


def _resources_have_image(resources, depth: int) -> bool:
    if resources is None or depth > _MAX_XOBJECT_DEPTH:
        return False
    resources = resources.get_object()
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return False
    for ref in xobjects.get_object().values():
        xobject = ref.get_object()
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            return True
        if subtype == "/Form" and _resources_have_image(xobject.get("/Resources"), depth + 1):
            return True
    return False


def pdf_needs_ocr(path: Path | str, force: bool = False) -> bool:
    """Cheap guess, made before queueing, whether a PDF is mostly scanned.

    Samples pages spread across the document instead of the first few, whose
    cover and title pages are often images even in a text PDF.
    """
    from pypdf import PdfReader

    # A file handle, not a path: given a path pypdf reads the whole file into
    # memory, and this runs on the upload request for books of hundreds of MB.
    try:
        with open(path, "rb") as handle:
            reader = PdfReader(handle)
            total = len(reader.pages)
            if total == 0:
                return False
            if force:
                return True

            count = min(total, SAMPLE_PAGES)
            indexes = sorted({round(i * (total - 1) / max(count - 1, 1)) for i in range(count)})
            needing = sum(1 for index in indexes if _sampled_page_needs_ocr(reader, index))
    except Exception as exc:
        logger.debug("PDF'ni tekshirib bo'lmadi (%s): %s", path, exc)
        return False

    estimated = needing / len(indexes) * total
    return estimated >= min(OCR_QUEUE_MIN_PAGES, total)


def _sampled_page_needs_ocr(reader, index: int) -> bool:
    page = reader.pages[index]
    try:
        text = page.extract_text() or ""
    except Exception:
        text = ""
    return page_needs_ocr(page, text)


def narrow_languages(sample_text: str, fallback: str) -> str:
    """Pick the Tesseract languages for the rest of a document from what its
    first OCR'd pages turned out to be. Reading every page with all three
    models is slower and mixes Cyrillic and Latin look-alike letters."""
    # Imported here: `apps.pipeline.services` imports the parser, which
    # imports this module.
    from apps.pipeline.services.translit import detect_script

    return SCRIPT_LANGUAGES.get(detect_script(sample_text), fallback)
