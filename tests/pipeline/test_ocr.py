"""OCR for scanned PDF pages: detection, orchestration, cleanup, backends.

Everything here runs without Tesseract (a fake backend, or a stubbed
`tesseract.recognize`), except the one test marked as needing it.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from apps.pipeline.ocr import OcrCancelledError, OcrError, OcrUnavailableError
from apps.pipeline.ocr.cache import OcrCache
from apps.pipeline.ocr.cleanup import (
    clean_ocr_pages,
    fix_mixed_script_words,
    normalise_apostrophes,
)
from apps.pipeline.ocr.detect import is_garbled, page_needs_ocr, pdf_needs_ocr
from apps.pipeline.ocr.document import OcrRequest
from apps.pipeline.ocr.tesseract import TesseractResult, parse_tsv
from apps.pipeline.services.parser import parse_file
from config.app_config import build_ocr_config
from tests.pipeline.ocr_helpers import (
    UZ_CYRILLIC,
    FakeBackend,
    merge_pdfs,
    scanned_pdf,
    text_pdf,
)

HASH = "a" * 64
LONG_TEXT = "Ekoturizm barqaror rivojlanish tamoyillariga asoslanadi va tabiatni asraydi"


def _request(backend, **overrides) -> OcrRequest:
    options = {"languages": "uzb+uzb_cyrl+rus", "auto_language": False}
    options.update(overrides)
    return OcrRequest(backend=backend, **options)


# -- Tesseract output ------------------------------------------------------


class TestTsv:
    HEADER = "\t".join(
        "level page_num block_num par_num line_num word_num left top width height conf text".split()
    )

    def _row(self, block, par, line, word, conf, text, level=5):
        return f"{level}\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t10\t10\t{conf}\t{text}"

    def test_rebuilds_lines_and_paragraphs(self):
        tsv = "\n".join(
            [
                self.HEADER,
                self._row(1, 1, 0, 0, -1, "", level=4),
                self._row(1, 1, 1, 1, 90, "Toshkent"),
                self._row(1, 1, 1, 2, 80, "shahri"),
                self._row(1, 1, 2, 1, 70, "qadimiy"),
                self._row(1, 2, 1, 1, 60, "Yangi"),
                self._row(2, 1, 1, 1, 50, "blok"),
            ]
        )

        result = parse_tsv(tsv)

        assert result.text == "Toshkent shahri\nqadimiy\n\nYangi\n\nblok"
        assert result.confidence == 70.0

    def test_ignores_blank_words_and_unscored_rows(self):
        tsv = "\n".join(
            [self.HEADER, self._row(1, 1, 1, 1, 95, " "), self._row(1, 1, 1, 2, -1, "so'z")]
        )

        result = parse_tsv(tsv)
        assert result.text == "so'z"
        assert result.confidence == 0.0


# -- Which pages need OCR ----------------------------------------------------


class TestDetection:
    def test_a_text_layer_of_letters_is_trusted(self):
        assert not is_garbled(LONG_TEXT)

    def test_a_text_layer_of_symbols_is_junk(self):
        assert is_garbled("@#$ %^& *() 123 ][ {} <> ?? !! ~~ ++ ==")
        assert is_garbled("�" * 10 + "abc")

    def test_scanned_pages_need_ocr_and_text_pages_do_not(self, tmp_path: Path):
        from pypdf import PdfReader

        scan = PdfReader(scanned_pdf(tmp_path / "scan.pdf", pages=1)).pages[0]
        text = PdfReader(text_pdf(tmp_path / "text.pdf", LONG_TEXT)).pages[0]

        assert page_needs_ocr(scan, "")
        assert not page_needs_ocr(text, text.extract_text())

    def test_a_short_page_without_images_is_not_sent_to_ocr(self, tmp_path: Path):
        from pypdf import PdfReader

        page = PdfReader(text_pdf(tmp_path / "short.pdf", "12")).pages[0]
        assert not page_needs_ocr(page, "12")

    def test_routes_scanned_documents_to_the_ocr_queue(self, tmp_path: Path):
        assert pdf_needs_ocr(scanned_pdf(tmp_path / "scan.pdf", pages=4))
        assert not pdf_needs_ocr(text_pdf(tmp_path / "text.pdf", LONG_TEXT))
        assert pdf_needs_ocr(text_pdf(tmp_path / "forced.pdf", LONG_TEXT), force=True)

    def test_a_scanned_cover_does_not_send_a_long_text_pdf_to_the_ocr_queue(self, tmp_path: Path):
        parts = [scanned_pdf(tmp_path / "cover.pdf", pages=1)]
        parts += [text_pdf(tmp_path / f"t{i}.pdf", LONG_TEXT) for i in range(30)]
        assert not pdf_needs_ocr(merge_pdfs(tmp_path / "book.pdf", *parts))


# -- Parser integration -------------------------------------------------------


class TestParsePdfWithOcr:
    def test_without_ocr_a_scanned_pdf_yields_only_a_warning(self, tmp_path: Path):
        parsed = parse_file(scanned_pdf(tmp_path / "scan.pdf"))

        assert parsed.chunks == []
        assert any("OCR talab qiladi" in warning for warning in parsed.warnings)
        assert parsed.extraction_method == "text"

    def test_ocrs_only_the_scanned_pages_of_a_mixed_pdf(self, tmp_path: Path):
        pdf = merge_pdfs(
            tmp_path / "mixed.pdf",
            text_pdf(tmp_path / "t.pdf", LONG_TEXT),
            scanned_pdf(tmp_path / "s.pdf", pages=2),
        )
        backend = FakeBackend()

        parsed = parse_file(pdf, ocr=_request(backend))

        assert backend.pages_seen == [2, 3]
        assert [chunk.label for chunk in parsed.chunks] == ["page 1", "page 2", "page 3"]
        assert parsed.chunks[0].text == LONG_TEXT
        assert parsed.chunks[2].text == "Sahifa 3 matni: ekoturizm asoslari."
        assert parsed.extraction_method == "mixed"
        assert parsed.ocr.pages == 2
        assert parsed.ocr.confidence == 91.0

    def test_force_ocrs_pages_that_have_a_text_layer(self, tmp_path: Path):
        backend = FakeBackend()
        parsed = parse_file(
            text_pdf(tmp_path / "t.pdf", LONG_TEXT), ocr=_request(backend, force=True)
        )

        assert backend.pages_seen == [1]
        assert parsed.extraction_method == "ocr"
        assert parsed.chunks[0].text.startswith("Sahifa 1")

    def test_reports_unreadable_and_low_confidence_pages(self, tmp_path: Path):
        backend = FakeBackend(confidence=35.0, fail_pages=frozenset({2}))

        parsed = parse_file(
            scanned_pdf(tmp_path / "scan.pdf", pages=3),
            ocr=_request(backend, min_confidence=60.0),
        )

        assert [chunk.label for chunk in parsed.chunks] == ["page 1", "page 3"]
        assert any("o'qilmadi: 2" in warning for warning in parsed.warnings)
        assert any("past ishonch" in warning and "1, 3" in warning for warning in parsed.warnings)

    def test_falls_back_to_the_text_layer_when_the_engine_is_missing(self, tmp_path: Path):
        class Missing(FakeBackend):
            def ocr_pages(self, *args, **kwargs):
                raise OcrUnavailableError("Tesseract o'rnatilmagan")

        pdf = merge_pdfs(
            tmp_path / "mixed.pdf",
            text_pdf(tmp_path / "t.pdf", LONG_TEXT),
            scanned_pdf(tmp_path / "s.pdf", pages=1),
        )

        parsed = parse_file(pdf, ocr=_request(Missing()))

        assert [chunk.label for chunk in parsed.chunks] == ["page 1"]
        assert parsed.ocr is None
        assert any("Tesseract o'rnatilmagan" in warning for warning in parsed.warnings)

    def test_refuses_more_ocr_pages_than_allowed(self, tmp_path: Path):
        with pytest.raises(OcrError, match="OCR_MAX_PAGES"):
            parse_file(
                scanned_pdf(tmp_path / "scan.pdf", pages=3),
                ocr=_request(FakeBackend(), max_pages=2),
            )

    def test_cancellation_propagates(self, tmp_path: Path):
        class Cancelled(FakeBackend):
            def ocr_pages(self, *args, **kwargs):
                raise OcrCancelledError("OCR to'xtatildi")

        with pytest.raises(OcrCancelledError):
            parse_file(scanned_pdf(tmp_path / "scan.pdf"), ocr=_request(Cancelled()))


class TestCacheAndLanguages:
    def test_a_second_run_reads_finished_pages_from_the_cache(self, tmp_path: Path):
        pdf = scanned_pdf(tmp_path / "scan.pdf", pages=3)
        cache = OcrCache(tmp_path / "cache", HASH, dpi=300)

        first = FakeBackend(fail_pages=frozenset({3}))
        parse_file(pdf, ocr=_request(first, cache=cache))
        second = FakeBackend()
        parsed = parse_file(pdf, ocr=_request(second, cache=cache))

        # Pages 1–2 came from the cache; the failed page 3 is retried.
        assert second.pages_seen == [3]
        assert len(parsed.chunks) == 3

    def test_a_cache_made_at_another_resolution_is_not_reused(self, tmp_path: Path):
        pdf = scanned_pdf(tmp_path / "scan.pdf", pages=1)
        parse_file(pdf, ocr=_request(FakeBackend(), cache=OcrCache(tmp_path, HASH, dpi=300)))

        backend = FakeBackend()
        parse_file(pdf, ocr=_request(backend, cache=OcrCache(tmp_path, HASH, dpi=200)))
        assert backend.pages_seen == [1]

    def test_the_cache_rejects_anything_but_a_sha256(self, tmp_path: Path):
        with pytest.raises(ValueError):
            OcrCache(tmp_path, "../../etc", dpi=300)

    def test_narrows_the_languages_once_the_script_is_known(self, tmp_path: Path):
        backend = FakeBackend(text_for=lambda page: UZ_CYRILLIC * 3)

        parse_file(
            scanned_pdf(tmp_path / "scan.pdf", pages=5),
            ocr=_request(backend, auto_language=True),
        )

        assert backend.calls == [([1, 2, 3], "uzb+uzb_cyrl+rus"), ([4, 5], "uzb_cyrl")]

    def test_keeps_probing_past_pages_without_text(self, tmp_path: Path):
        backend = FakeBackend(text_for=lambda page: "" if page <= 3 else "Ekoturizm " * 20)

        parse_file(
            scanned_pdf(tmp_path / "scan.pdf", pages=8),
            ocr=_request(backend, auto_language=True),
        )

        assert [languages for _, languages in backend.calls] == [
            "uzb+uzb_cyrl+rus",
            "uzb+uzb_cyrl+rus",
            "uzb",
        ]

    def test_reports_progress(self, tmp_path: Path):
        seen: list[tuple[int, int]] = []

        parse_file(
            scanned_pdf(tmp_path / "scan.pdf", pages=2),
            ocr=_request(FakeBackend(), on_progress=lambda done, total: seen.append((done, total))),
        )

        assert seen == [(0, 2), (1, 2), (2, 2)]


# -- Cleanup ----------------------------------------------------------------


class TestCleanup:
    def test_repairs_latin_look_alikes_inside_cyrillic_words(self):
        # "Тoшкeнт" with Latin o and e, as multi-language OCR returns it.
        assert fix_mixed_script_words("Тoшкeнт shahri") == "Тошкент shahri"
        assert fix_mixed_script_words("Samarqаnd") == "Samarqand"

    def test_leaves_words_without_a_look_alike_fix_alone(self):
        assert fix_mixed_script_words("Жizzax") == "Жizzax"

    def test_removes_page_numbers_running_headers_and_scan_noise(self):
        bodies = ["Samarqand", "Buxoro", "Xiva", "Termiz", "Qo'qon", "Nukus"]
        pages = {
            number: f"TURIZM ASOSLARI {number}\n{body} tarixi.\n|~|\n— {number} —"
            for number, body in enumerate(bodies, start=1)
        }

        cleaned = clean_ocr_pages(pages)

        assert cleaned[4] == "Termiz tarixi."

    def test_a_scan_speck_does_not_hide_a_running_header(self):
        cities = ["Samarqand", "Buxoro", "Xiva", "Termiz", "Qo‘qon", "Nukus"]
        pages = {n: f"TURIZM ASOSLARI\n{city} tarixi." for n, city in enumerate(cities, 1)}
        pages[5] = "TURIZM ASOSLARI €\nQo‘qon tarixi."

        assert clean_ocr_pages(pages)[5] == "Qo‘qon tarixi."

    def test_unifies_the_apostrophes_ocr_mixes_up(self):
        text = "ko'plab koʻrsatish ko`plab g'oya me'moriy Oʻzbekiston"

        assert normalise_apostrophes(text) == (
            "ko‘plab ko‘rsatish ko‘plab g‘oya meʼmoriy O‘zbekiston"
        )

    def test_leaves_apostrophes_outside_latin_words_alone(self):
        assert normalise_apostrophes("'Ipak yo'li' va «Самарқанд'") == (
            "'Ipak yo‘li' va «Самарқанд'"
        )

    def test_keeps_numbers_in_the_middle_of_a_page(self):
        cleaned = clean_ocr_pages({1: "Sarlavha\n1991\nMatn davomi\nOxiri"})
        assert "1991" in cleaned[1]


# -- Local backend (PDFium rendering, stubbed Tesseract) ----------------------


class TestLocalBackend:
    @pytest.fixture
    def backend(self):
        from apps.pipeline.ocr.local import LocalBackend

        return LocalBackend(build_ocr_config(backend="local", page_workers=2, dpi=150))

    def test_renders_each_page_and_reports_it(self, backend, tmp_path: Path, monkeypatch):
        images: list[bytes] = []

        def recognize(image, languages, **kwargs):
            images.append(image)
            return TesseractResult(text=f"matn ({languages})", confidence=88.0)

        monkeypatch.setattr("apps.pipeline.ocr.tesseract.recognize", recognize)
        results = []

        pdf = scanned_pdf(tmp_path / "s.pdf", pages=3)
        backend.ocr_pages(pdf, [1, 2, 3], "uzb", results.append)

        assert sorted(result.page for result in results) == [1, 2, 3]
        assert all(result.text == "matn (uzb)" for result in results)
        # 8-bit grayscale PNM, at the configured resolution.
        assert all(image.startswith(b"P5") for image in images)

    def test_one_failing_page_does_not_stop_the_others(self, backend, tmp_path: Path, monkeypatch):
        from apps.pipeline.ocr.tesseract import PageTimeoutError

        calls = {"n": 0}

        def recognize(image, languages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PageTimeoutError("sahifa 120 s ichida o'qilmadi")
            return TesseractResult(text="matn", confidence=80.0)

        monkeypatch.setattr("apps.pipeline.ocr.tesseract.recognize", recognize)
        results = []
        pdf = scanned_pdf(tmp_path / "s.pdf", pages=3)
        backend.ocr_pages(pdf, [1, 2, 3], "uzb", results.append)

        assert len(results) == 3
        assert sum(1 for result in results if result.error) == 1

    def test_a_missing_engine_fails_the_whole_run(self, backend, tmp_path: Path, monkeypatch):
        def recognize(image, languages, **kwargs):
            raise OcrUnavailableError("Tesseract o'rnatilmagan")

        monkeypatch.setattr("apps.pipeline.ocr.tesseract.recognize", recognize)
        with pytest.raises(OcrUnavailableError):
            backend.ocr_pages(scanned_pdf(tmp_path / "s.pdf", pages=2), [1, 2], "uzb", print)

    def test_stops_when_cancelled(self, backend, tmp_path: Path, monkeypatch):
        cancel = threading.Event()

        def recognize(image, languages, **kwargs):
            cancel.set()
            return TesseractResult(text="matn", confidence=80.0)

        monkeypatch.setattr("apps.pipeline.ocr.tesseract.recognize", recognize)
        results = []
        with pytest.raises(OcrCancelledError):
            backend.ocr_pages(
                scanned_pdf(tmp_path / "s.pdf", pages=10),
                list(range(1, 11)),
                "uzb",
                results.append,
                cancel,
            )
        assert len(results) < 10


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract o'rnatilmagan")
def test_reads_a_real_scan_with_tesseract(tmp_path: Path):
    from PIL import Image, ImageDraw, ImageFont

    from apps.pipeline.ocr.local import LocalBackend

    image = Image.new("L", (2480, 1200), 255)
    font = ImageFont.load_default(size=90)
    ImageDraw.Draw(image).text((150, 400), "Ekoturizm va madaniy meros", fill=0, font=font)
    pdf = tmp_path / "real.pdf"
    image.save(pdf, "PDF", resolution=300)

    parsed = parse_file(
        pdf,
        ocr=_request(LocalBackend(build_ocr_config(backend="local")), languages="uzb+eng"),
    )

    assert "Ekoturizm" in parsed.chunks[0].text
    assert parsed.ocr.confidence > 50
