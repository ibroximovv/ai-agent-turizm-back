"""Grounding-marker injection and Markdown assembly.

Open WebUI's vector chunking discards the surrounding context, so an answer
cannot cite where it came from. A `[MANBA: ...]` marker is therefore repeated
roughly every 600 characters, which guarantees that every vector chunk carries
its own attribution.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from apps.pipeline.services.parser import ParsedChunk

MARKER_INTERVAL = 600
#: How far past the interval we may look for a nicer split boundary.
NEWLINE_LOOKAHEAD = 150
SPACE_LOOKAHEAD = 100

_MARKER_UNSAFE = re.compile(r"[|\]\r\n]+")
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_LEADING_PATH_PUNCTUATION = re.compile(r"^[.-]+")
_FILENAME_EXTENSION = re.compile(r"\.[a-z0-9]+$")
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_SLUG_EDGES = re.compile(r"^_+|_+$")


@dataclass(frozen=True)
class GroundingMetadata:
    #: Discriminates the output file; two materials never share one.
    material_id: str
    module_code: str
    module_name: str
    topic_code: str
    topic_name: str
    material_type: str
    original_filename: str
    detected_script: str


@dataclass(frozen=True)
class ChunkerResult:
    markdown: str
    #: Number of source chunks (pages / slides / sections) in the document.
    chunk_count: int
    #: Number of `[MANBA: ...]` grounding markers injected into the body.
    marker_count: int
    char_count: int
    file_path: Path


def build_grounded_markdown(
    chunks: list[ParsedChunk],
    meta: GroundingMetadata,
    output_dir: Path | str,
) -> ChunkerResult:
    """Build grounded Markdown with `[MANBA: ...]` markers and YAML frontmatter."""
    lines: list[str] = []
    marker_count = 0

    # 1. YAML frontmatter
    lines.append("---")
    lines.append(f"module_id: {_yaml_string(meta.module_code)}")
    lines.append(f"module_name: {_yaml_string(meta.module_name)}")
    lines.append(f"topic_id: {_yaml_string(meta.topic_code)}")
    lines.append(f"topic_name: {_yaml_string(meta.topic_name)}")
    lines.append(f"type: {_yaml_string(meta.material_type)}")
    lines.append(f"source: {_yaml_string(meta.original_filename)}")
    lines.append(f"script: {_yaml_string(meta.detected_script)}")
    lines.append(f"chunks: {len(chunks)}")
    lines.append("---")
    lines.append("")

    # 2. Body with grounding markers injected every ~600 chars
    for chunk in chunks:
        marker = build_marker(meta, chunk.label)

        lines.append(f"\n## {chunk.label.upper()}\n")
        lines.append(marker)
        marker_count += 1
        lines.append("")

        # Repeat the marker before every follow-up segment so that no vector
        # chunk can end up without its source attribution.
        for index, segment in enumerate(split_for_grounding(chunk.text)):
            if index > 0:
                lines.append("")
                lines.append(marker)
                marker_count += 1
                lines.append("")
            lines.append(segment)
        lines.append("")

    full_markdown = "\n".join(lines)

    target_dir = Path(output_dir) / _path_segment(meta.module_code)
    target_dir.mkdir(parents=True, exist_ok=True)
    full_path = target_dir / build_filename(meta)
    full_path.write_text(full_markdown, encoding="utf-8")

    return ChunkerResult(
        markdown=full_markdown,
        chunk_count=len(chunks),
        marker_count=marker_count,
        char_count=len(full_markdown),
        file_path=full_path,
    )


def split_for_grounding(text: str) -> list[str]:
    """Split a chunk into ~600 character segments.

    A nearby newline or space boundary is preferred so that words are not cut
    in half.
    """
    segments: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = start + MARKER_INTERVAL

        if end < length:
            next_newline = text.find("\n", end)
            next_space = text.find(" ", end)
            if next_newline != -1 and next_newline - end < NEWLINE_LOOKAHEAD:
                end = next_newline
            elif next_space != -1 and next_space - end < SPACE_LOOKAHEAD:
                end = next_space

        # Guarantee forward progress even if a boundary search returns `start`.
        if end <= start:
            end = min(start + MARKER_INTERVAL, length)

        segment = text[start:end].strip()
        if segment:
            segments.append(segment)
        start = end

    return segments


def build_marker(meta: GroundingMetadata, label: str) -> str:
    """``[MANBA: source | page 14 | topic-01 | literature]``

    `|` and `]` are stripped from the components so that a marker can never be
    broken apart by a filename or label.
    """
    parts = [
        _MARKER_UNSAFE.sub(" ", part).strip()
        for part in (meta.original_filename, label, meta.topic_code, meta.material_type)
    ]
    return f"[MANBA: {' | '.join(parts)}]"


def build_filename(meta: GroundingMetadata) -> str:
    """``{topic}__{type}__{slug}-{fingerprint}.md``

    The fingerprint is derived from the material id, so two documents that
    share a filename inside one topic cannot overwrite each other's markdown —
    and a re-run of the same material always rewrites the same file. The slug
    is only there to keep the name readable; it degenerates to `document` for a
    filename with no ASCII characters.
    """
    slug = meta.original_filename.lower()
    slug = _FILENAME_EXTENSION.sub("", slug)
    slug = _NON_SLUG_CHARS.sub("_", slug)
    slug = _SLUG_EDGES.sub("", slug)[:40] or "document"

    fingerprint = hashlib.sha256(meta.material_id.encode("utf-8")).hexdigest()[:10]

    topic = _path_segment(meta.topic_code)
    material_type = _path_segment(meta.material_type)

    return f"{topic}__{material_type}__{slug}-{fingerprint}.md"


def _path_segment(value: str) -> str:
    """Codes come from user input, so never let them escape the output directory."""
    safe = _LEADING_PATH_PUNCTUATION.sub("", _UNSAFE_PATH_CHARS.sub("-", value))
    return safe or "unknown"


def _yaml_string(value: str) -> str:
    """Emit a double-quoted YAML scalar that cannot break the frontmatter."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = re.sub(r"[\r\n\t]+", " ", escaped)
    return f'"{escaped}"'
