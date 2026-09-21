"""Filename decoding and path-safe name helpers."""

from __future__ import annotations

import os
import re

_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_LEADING_PUNCTUATION = re.compile(r"^[.\-_]+")


def decode_multipart_filename(name: str) -> str:
    """Recover a UTF-8 filename that was decoded as latin-1 by the parser.

    Some clients send the `filename` in a Content-Disposition header without a
    charset, so a name such as ``Ўзбекистон.pdf`` can arrive as the mojibake
    ``ÐÐ·Ð±ÐµÐºÐ¸ÑÑÐ¾Ð½.pdf``. Storing that would corrupt the ``source:``
    frontmatter and every ``[MANBA: ...]`` grounding marker built from it.

    Only strings entirely within the latin-1 range are reinterpreted, and only
    when the result is valid UTF-8 — so genuine latin-1 names (``café.pdf``)
    and already-correct names are returned unchanged.
    """
    if not name:
        return name

    # A character above U+00FF means the name was already decoded as UTF-8.
    if any(ord(char) > 0xFF for char in name):
        return name

    try:
        reinterpreted = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        # The bytes were not UTF-8 after all.
        return name

    return reinterpreted if reinterpreted != name else name


def sanitize_path_segment(value: str, fallback: str = "unnamed") -> str:
    """Reduce a name to characters that are safe inside a single path segment.

    The extension is preserved separately by the caller, because the pipeline
    selects its parser from the stored file's extension.
    """
    safe = _UNSAFE_SEGMENT_CHARS.sub("_", value)
    safe = _LEADING_PUNCTUATION.sub("", safe)[:120]
    return safe or fallback


def build_stored_filename(original_name: str, extension: str, content_hash: str) -> str:
    """``{hash12}__{safe-base}{ext}``.

    The hash prefix keeps two different documents that happen to share a
    filename from overwriting each other, and the extension is always kept so
    the parser can be selected from the path.
    """
    base = os.path.basename(original_name)
    if extension and base.lower().endswith(extension.lower()):
        base = base[: -len(extension)]
    return f"{content_hash[:12]}__{sanitize_path_segment(base)}{extension}"
