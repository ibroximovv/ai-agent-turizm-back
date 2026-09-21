from pathlib import Path

import pytest

from apps.pipeline.services.parser import UnsupportedFormatError, parse_file


def test_rejects_unsupported_formats(tmp_path: Path):
    with pytest.raises(UnsupportedFormatError, match="Qo'llab-quvvatlanmaydigan"):
        parse_file(tmp_path / "report.xlsx")


class TestTextFiles:
    def test_splits_on_blank_line_runs_and_numbers_kept_parts_sequentially(self, tmp_path: Path):
        file = tmp_path / "notes.txt"
        file.write_text("birinchi\n\n\n\n\nikkinchi\n\n\nuchinchi", encoding="utf-8")

        parsed = parse_file(file)

        assert [chunk.label for chunk in parsed.chunks] == ["part 1", "part 2", "part 3"]
        assert parsed.chunks[1].text == "ikkinchi"
        assert parsed.total_chars == len("birinchi") + len("ikkinchi") + len("uchinchi")

    def test_falls_back_to_a_single_part_without_blank_line_runs(self, tmp_path: Path):
        file = tmp_path / "flat.md"
        file.write_text("# Sarlavha\nmatn", encoding="utf-8")

        parsed = parse_file(file)
        assert len(parsed.chunks) == 1
        assert parsed.chunks[0].label == "part 1"


class TestPptxFiles:
    @staticmethod
    def _build_deck(path: Path, slides: list[tuple[list[str], str | None]]) -> Path:
        """Write a real .pptx whose slides hold the given paragraphs and notes."""
        from pptx import Presentation
        from pptx.util import Inches

        presentation = Presentation()
        blank_layout = presentation.slide_layouts[6]

        for paragraphs, notes in slides:
            slide = presentation.slides.add_slide(blank_layout)
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(3))
            frame = box.text_frame
            for index, line in enumerate(paragraphs):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.text = line
            if notes:
                slide.notes_slide.notes_text_frame.text = notes

        presentation.save(str(path))
        return path

    def test_keeps_paragraphs_on_separate_lines(self, tmp_path: Path):
        deck = self._build_deck(tmp_path / "deck.pptx", [(["Sarlavha", "Ikkinchi qator"], None)])

        parsed = parse_file(deck)
        assert parsed.chunks[0].text == "Sarlavha\nIkkinchi qator"

    def test_numbers_slides_in_presentation_order(self, tmp_path: Path):
        deck = self._build_deck(
            tmp_path / "deck.pptx",
            [(["bir"], None), (["ikki"], None), (["o‘n"], None)],
        )

        parsed = parse_file(deck)
        assert [chunk.label for chunk in parsed.chunks] == ["slide 1", "slide 2", "slide 3"]

    def test_attaches_presenter_notes_to_their_own_slide(self, tmp_path: Path):
        deck = self._build_deck(
            tmp_path / "deck.pptx",
            [(["birinchi slayd"], None), (["uchinchi slayd"], "uchinchi izoh")],
        )

        parsed = parse_file(deck)
        assert parsed.chunks[0].text == "birinchi slayd"
        assert "[Presenter Notes: uchinchi izoh]" in parsed.chunks[1].text

    def test_warns_when_a_presentation_holds_no_slides(self, tmp_path: Path):
        deck = self._build_deck(tmp_path / "empty.pptx", [])

        parsed = parse_file(deck)
        assert parsed.chunks == []
        assert "Taqdimotda slaydlar topilmadi." in parsed.warnings
