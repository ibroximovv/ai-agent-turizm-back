"""System checks: catch a missing Tesseract at deploy time, not on the first
scanned book an operator uploads."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Warning, register

from apps.pipeline.ocr.base import OcrUnavailableError
from apps.pipeline.ocr.detect import SCRIPT_LANGUAGES

INSTALL_HINT = (
    "apt install tesseract-ocr tesseract-ocr-uzb tesseract-ocr-uzb-cyrl "
    "tesseract-ocr-rus — yoki OCR'ni o'chiring: OCR_BACKEND=none"
)


@register()
def check_ocr_engine(app_configs, **kwargs):
    config = settings.OCR
    if config.backend != "local":
        return []

    from apps.pipeline.ocr.tesseract import list_languages

    try:
        installed = set(list_languages(config.tesseract_cmd, config.tessdata_dir))
    except OcrUnavailableError as exc:
        return [
            Warning(
                f"OCR_BACKEND=local, lekin {exc}. Skanerlangan PDF'lar matnsiz qoladi.",
                hint=INSTALL_HINT,
                id="pipeline.W001",
            )
        ]

    needed = set(config.languages.split("+"))
    if config.auto_language:
        needed |= set(SCRIPT_LANGUAGES.values())
    missing = sorted(needed - installed)
    if missing:
        return [
            Warning(
                f"Tesseract til paketlari o'rnatilmagan: {', '.join(missing)}.",
                hint=INSTALL_HINT,
                id="pipeline.W002",
            )
        ]
    return []
