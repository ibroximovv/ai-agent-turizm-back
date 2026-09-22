import re
from dataclasses import replace
from pathlib import Path

import pytest

from apps.pipeline.services.chunker import GroundingMetadata, build_grounded_markdown
from apps.pipeline.services.parser import ParsedChunk

META = GroundingMetadata(
    material_id="11111111-1111-4111-8111-111111111111",
    module_code="module-01",
    module_name="Turizm asoslari",
    topic_code="topic-01",
    topic_name="Qonunchilik asoslari",
    material_type="literature",
    original_filename="Constitution.pdf",
    detected_script="uz-latn",
)


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_writes_frontmatter_and_a_marker_for_a_short_chunk(out_dir: Path):
    result = build_grounded_markdown(
        [ParsedChunk(label="page 14", text="Qisqa matn.")], META, out_dir
    )

    assert 'module_id: "module-01"' in result.markdown
    assert 'topic_id: "topic-01"' in result.markdown
    assert 'source: "Constitution.pdf"' in result.markdown
    assert "chunks: 1" in result.markdown
    assert "[MANBA: Constitution.pdf | page 14 | topic-01 | literature]" in result.markdown
    assert result.chunk_count == 1
    assert result.marker_count == 1

    assert result.file_path.read_text(encoding="utf-8") == result.markdown


def test_repeats_the_marker_roughly_every_600_characters(out_dir: Path):
    text = "abcdefghij " * 300  # ~3300 chars, no newlines
    result = build_grounded_markdown([ParsedChunk(label="page 1", text=text)], META, out_dir)

    markers = re.findall(r"\[MANBA: ", result.markdown)
    assert len(markers) == result.marker_count
    assert len(markers) >= 5


def test_never_loses_text_while_splitting(out_dir: Path):
    text = "x" * 2500
    result = build_grounded_markdown([ParsedChunk(label="page 1", text=text)], META, out_dir)

    body = "---".join(result.markdown.split("---")[2:])
    body = re.sub(r"\[MANBA:[^\]]*\]", "", body)
    body = re.sub(r"##.*", "", body)
    body = re.sub(r"\s", "", body)
    assert body == text


def test_gives_non_ascii_filenames_distinct_stable_output_paths(out_dir: Path):
    first = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="matn")],
        replace(
            META,
            material_id="22222222-2222-4222-8222-222222222222",
            original_filename="Ўзбекистон Конституцияси.pdf",
        ),
        out_dir,
    )
    second = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="matn")],
        replace(
            META,
            material_id="33333333-3333-4333-8333-333333333333",
            original_filename="Меҳнат кодекси.pdf",
        ),
        out_dir,
    )
    assert first.file_path != second.file_path

    # Re-processing the same material must overwrite the same file.
    again = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="boshqa matn")],
        replace(
            META,
            material_id="22222222-2222-4222-8222-222222222222",
            original_filename="Ўзбекистон Конституцияси.pdf",
        ),
        out_dir,
    )
    assert again.file_path == first.file_path
    assert len(list((out_dir / "module-01").iterdir())) == 2


def test_keeps_two_materials_that_share_a_filename_in_separate_files(out_dir: Path):
    shared = replace(META, original_filename="Qonun.pdf")

    first = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="birinchi hujjat")],
        replace(shared, material_id="44444444-4444-4444-8444-444444444444"),
        out_dir,
    )
    second = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="ikkinchi hujjat")],
        replace(shared, material_id="55555555-5555-4555-8555-555555555555"),
        out_dir,
    )

    assert first.file_path != second.file_path
    assert "birinchi hujjat" in first.file_path.read_text(encoding="utf-8")
    assert "ikkinchi hujjat" in second.file_path.read_text(encoding="utf-8")


def test_keeps_codes_from_escaping_the_output_directory(out_dir: Path):
    result = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="matn")],
        replace(META, module_code="../../etc", topic_code="../evil"),
        out_dir,
    )

    assert result.file_path.resolve().is_relative_to(out_dir.resolve())
    assert ".." not in str(result.file_path)


def test_escapes_quotes_and_backslashes_in_frontmatter(out_dir: Path):
    result = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="matn")],
        replace(META, topic_name='He said "hi"\\done', module_name="Line\nbreak"),
        out_dir,
    )

    assert 'topic_name: "He said \\"hi\\"\\\\done"' in result.markdown
    assert 'module_name: "Line break"' in result.markdown

    frontmatter = result.markdown.split("---")[1]
    assert len([line for line in frontmatter.split("\n") if line.strip()]) == 8


def test_strips_marker_delimiters_out_of_the_source_filename(out_dir: Path):
    result = build_grounded_markdown(
        [ParsedChunk(label="page 1", text="matn")],
        replace(META, original_filename="we|ird]name.pdf"),
        out_dir,
    )

    marker = re.search(r"\[MANBA:[^\]]*\]", result.markdown).group(0)
    assert len(marker.split("|")) == 4
    assert marker.endswith("literature]")
