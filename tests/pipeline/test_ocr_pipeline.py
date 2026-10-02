"""A scanned PDF through the whole pipeline: upload → OCR → Markdown."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog import services
from apps.catalog.models import AuditLog, Material, MaterialStatus
from apps.pipeline import runner
from apps.pipeline.ocr import OcrCancelledError
from apps.pipeline.service import lane_for
from config.app_config import build_ocr_config, uploads_config
from tests.pipeline.ocr_helpers import FakeBackend, scanned_pdf, text_pdf

pytestmark = pytest.mark.django_db

LONG_TEXT = "Ekoturizm barqaror rivojlanish tamoyillariga asoslanadi va tabiatni asraydi"


@pytest.fixture
def ocr_backend(settings, monkeypatch) -> FakeBackend:
    settings.OCR = build_ocr_config(backend="local", auto_language=False)
    backend = FakeBackend()
    monkeypatch.setattr("apps.pipeline.service.get_ocr_backend", lambda config=None: backend)
    return backend


def _upload(topic, pdf: Path) -> Material:
    upload = SimpleUploadedFile(pdf.name, pdf.read_bytes(), content_type="application/pdf")
    material = services.upload_material(
        upload=upload, topic_id=str(topic.id), material_type="literature", uploaded_by=None
    )
    material.refresh_from_db()
    return material


def test_a_scanned_pdf_becomes_grounded_markdown(topic, tmp_path, ocr_backend):
    material = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=3))

    assert material.status == MaterialStatus.MD_READY
    assert material.extraction_method == "ocr"
    assert material.ocr_page_count == 3
    assert material.ocr_confidence == 91.0
    assert material.progress_message is None

    markdown = Path(material.md_file_path).read_text(encoding="utf-8")
    assert "Sahifa 2 matni" in markdown
    assert "| page 2 |" in markdown
    assert AuditLog.objects.filter(material=material, stage="ocr").exists()


def test_the_ocr_results_are_cached_by_file_hash(topic, tmp_path, ocr_backend):
    material = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=2))

    cache_dir = uploads_config().ocr_cache_dir / material.file_hash
    assert sorted(path.name for path in cache_dir.iterdir()) == [
        "page-00001.json",
        "page-00002.json",
    ]

    services.retry_material(material)
    assert ocr_backend.pages_seen == [1, 2]  # the retry read everything from the cache


def test_without_ocr_a_scanned_pdf_fails_with_the_reason(topic, tmp_path):
    material = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=1))

    assert material.status == MaterialStatus.FAILED
    assert "OCR talab qiladi" in material.error_message


def test_reprocess_with_ocr_reads_every_page_afresh(topic, tmp_path, ocr_backend):
    material = _upload(topic, text_pdf(tmp_path / "matn.pdf", LONG_TEXT))
    assert material.extraction_method == "text"
    assert ocr_backend.calls == []

    services.reprocess_with_ocr(material)

    material.refresh_from_db()
    assert material.force_ocr
    assert material.extraction_method == "ocr"
    assert ocr_backend.pages_seen == [1]


def test_reprocess_with_ocr_refuses_other_formats(topic, ocr_backend):
    upload = SimpleUploadedFile("eslatma.txt", LONG_TEXT.encode(), content_type="text/plain")
    material = services.upload_material(
        upload=upload, topic_id=str(topic.id), material_type="literature", uploaded_by=None
    )

    with pytest.raises(services.ValidationError):
        services.reprocess_with_ocr(material)


def test_a_cancelled_run_is_marked_failed(topic, tmp_path, ocr_backend, monkeypatch):
    def cancelled(*args, **kwargs):
        raise OcrCancelledError("OCR to'xtatildi")

    monkeypatch.setattr(ocr_backend, "ocr_pages", cancelled)
    material = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=1))

    assert material.status == MaterialStatus.FAILED
    assert material.error_message.startswith("To'xtatildi")


def test_deleting_a_material_drops_its_ocr_cache(
    topic, tmp_path, ocr_backend, django_capture_on_commit_callbacks
):
    material = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=1))
    cache_dir = uploads_config().ocr_cache_dir / material.file_hash
    assert cache_dir.exists()

    with django_capture_on_commit_callbacks(execute=True):
        services.delete_material(material)

    assert not cache_dir.exists()


class TestLanes:
    def test_scanned_pdfs_go_to_the_ocr_lane(self, topic, tmp_path, ocr_backend):
        scanned = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=3))
        text = _upload(topic, text_pdf(tmp_path / "matn.pdf", LONG_TEXT))

        assert lane_for(str(scanned.id)) == runner.OCR_LANE
        assert lane_for(str(text.id)) == runner.DEFAULT_LANE

    def test_everything_uses_the_default_lane_when_ocr_is_off(self, topic, tmp_path):
        scanned = _upload(topic, scanned_pdf(tmp_path / "kitob.pdf", pages=3))
        assert lane_for(str(scanned.id)) == runner.DEFAULT_LANE

    def test_lanes_run_on_separate_pools(self, settings):
        settings.PIPELINE_RUN_SYNC = False
        threads: dict[str, str] = {}
        done = threading.Event()

        def task(material_id: str) -> None:
            threads[material_id] = threading.current_thread().name
            if len(threads) == 2:
                done.set()

        try:
            runner.submit("lane-a", task=task, lane=runner.OCR_LANE)
            runner.submit("lane-b", task=task, lane=runner.DEFAULT_LANE)
            assert done.wait(5)
        finally:
            runner.shutdown(wait=True)

        assert threads["lane-a"].startswith("pipeline-ocr")
        assert not threads["lane-b"].startswith("pipeline-ocr")

    def test_cancel_reaches_a_queued_or_running_material(self, settings):
        settings.PIPELINE_RUN_SYNC = False
        started, seen = threading.Event(), {}

        def task(material_id: str) -> None:
            assert runner.claim(material_id)
            try:
                started.set()
                deadline = time.monotonic() + 5
                while not runner.is_cancelled(material_id) and time.monotonic() < deadline:
                    time.sleep(0.01)
                seen["cancelled"] = runner.is_cancelled(material_id)
            finally:
                runner.release(material_id)

        try:
            assert not runner.cancel("cancel-me")  # nothing in flight yet
            runner.submit("cancel-me", task=task, lane=runner.OCR_LANE)
            assert started.wait(5)
            assert runner.cancel("cancel-me")
        finally:
            runner.shutdown(wait=True)

        assert seen["cancelled"] is True
        assert runner.cancel_event("cancel-me") is None


FONTS = [
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
FONT = next((font for font in FONTS if Path(font).exists()), None)


@pytest.mark.skipif(
    shutil.which("tesseract") is None or FONT is None,
    reason="Tesseract yoki o'zbek kirill harflari bor shrift o'rnatilmagan",
)
def test_a_real_uzbek_cyrillic_scan_ends_up_as_latin_markdown(topic, tmp_path, settings):
    """End to end with the real engine: render → Tesseract → cleanup →
    transliteration → grounded Markdown."""
    from PIL import Image, ImageDraw, ImageFont

    settings.OCR = build_ocr_config(backend="local", page_workers=2)
    font = ImageFont.truetype(FONT, 50)
    pages = []
    for number, line in enumerate(
        ["Самарқанд шаҳри қадимий ва гўзал.", "Хива меҳмонлари ғурур билан кутилади."], 1
    ):
        image = Image.new("L", (2480, 1600), 255)
        draw = ImageDraw.Draw(image)
        draw.text((220, 120), "ТУРИЗМ АСОСЛАРИ", font=font, fill=0)
        draw.text((220, 500), line, font=font, fill=0)
        draw.text((1220, 1400), str(number), font=font, fill=0)
        pages.append(image)
    pdf = tmp_path / "kitob.pdf"
    pages[0].save(pdf, "PDF", resolution=300, save_all=True, append_images=pages[1:])

    material = _upload(topic, pdf)

    assert material.status == MaterialStatus.MD_READY, material.error_message
    assert material.extraction_method == "ocr"
    assert material.detected_script == "uz-cyrl"
    assert material.ocr_confidence > 80
    markdown = Path(material.md_file_path).read_text(encoding="utf-8")
    assert "Samarqand shahri qadimiy" in markdown
    assert "mehmonlari g‘urur" in markdown
    assert "| page 2 |" in markdown
