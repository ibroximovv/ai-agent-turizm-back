"""Repairs specific to OCR output, applied before the shared `clean_text`.

Runs on the raw recognised text, while each line is still its own line —
`clean_text` unwraps lines into paragraphs, after which a running header can
no longer be told apart from the sentence it got glued onto.
"""

from __future__ import annotations

from collections import Counter

import regex

# Letters that look identical in Latin and Cyrillic. OCR with several language
# models loaded picks per glyph, so `Тошкент` comes back as `Тoшкeнт` — which
# neither the RAG search nor the transliterator recognises as one word.
_LATIN_LOOKALIKES = "aceopxyAEKMHOPCTXB"
_CYRILLIC_LOOKALIKES = "асеорхуАЕКМНОРСТХВ"
_TO_CYRILLIC = str.maketrans(_LATIN_LOOKALIKES, _CYRILLIC_LOOKALIKES)
_TO_LATIN = str.maketrans(_CYRILLIC_LOOKALIKES, _LATIN_LOOKALIKES)

_WORD = regex.compile(r"\p{L}+")
_CYRILLIC = regex.compile(r"\p{Script=Cyrillic}")
_LATIN = regex.compile(r"\p{Script=Latin}")
_HAS_CONTENT = regex.compile(r"[\p{L}\p{N}]")
_PAGE_NUMBER = regex.compile(r"^[\s\-–—.·•|()\[\]]*\d{1,4}[\s\-–—.·•|()\[\]]*$")
_DIGITS = regex.compile(r"\d+")
_SPACES = regex.compile(r"\s+")
_NOT_WORDLIKE = regex.compile(r"[^\p{L}\p{N}#\s]+")

# OCR reads the Uzbek Latin apostrophe as any of ' ` ʻ ʼ ’ ‘, so one book
# spells "ko'plab", "koʻplab" and "ko`plab" — three different words to a
# search. Normalise to what `to_latin` writes: o‘ / g‘ and the ʼ tutuq belgisi.
_APOSTROPHES = "'`ʻʼ’‘"
_LATIN_APOSTROPHE = regex.compile(rf"(\p{{Latin}})[{_APOSTROPHES}](?=\p{{Latin}})")

#: A first/last line repeated on this share of pages is a running header/footer.
RUNNING_LINE_SHARE = 0.2
RUNNING_LINE_MIN_PAGES = 3
#: Below this many pages there is no repetition to learn from.
RUNNING_LINE_MIN_DOCUMENT = 5
#: Lines inspected at each end of a page (a header and a page number, say).
EDGE_LINES = 2


def clean_ocr_pages(pages: dict[int, str]) -> dict[int, str]:
    """Clean every OCR'd page of one document. Keys are page numbers."""
    running = _running_lines(pages)
    return {number: _clean_page(text, running) for number, text in pages.items()}


def fix_mixed_script_words(text: str) -> str:
    """Bring each mixed Latin/Cyrillic word into its majority script, but only
    when every minority letter has a look-alike to become."""

    def repair(match: regex.Match) -> str:
        word = match.group()
        cyrillic = len(_CYRILLIC.findall(word))
        latin = len(_LATIN.findall(word))
        if not cyrillic or not latin:
            return word
        if cyrillic >= latin:
            converted = word.translate(_TO_CYRILLIC)
            return word if _LATIN.search(converted) else converted
        converted = word.translate(_TO_LATIN)
        return word if _CYRILLIC.search(converted) else converted

    return _WORD.sub(repair, text)


def _clean_page(text: str, running: set[str]) -> str:
    # Scan noise first (specks read as `|`, `~`, `»`), so it cannot hide a
    # page number from the edge checks below.
    lines = [line for line in text.split("\n") if _HAS_CONTENT.search(line) or not line.strip()]

    # Peel page numbers and running headers/footers off the page edges only —
    # stopping at the first real line, since the same number or phrase in the
    # middle of a page is content.
    content = [index for index, line in enumerate(lines) if line.strip()]
    dropped: set[int] = set()
    for edge in (content[:EDGE_LINES], content[::-1][:EDGE_LINES]):
        for index in edge:
            if not _is_edge_furniture(lines[index], running):
                break
            dropped.add(index)

    kept = "\n".join(line for index, line in enumerate(lines) if index not in dropped)
    return normalise_apostrophes(fix_mixed_script_words(kept)).strip()


def normalise_apostrophes(text: str) -> str:
    """`ko'plab` / `koʻplab` → `ko‘plab`; `me'moriy` → `meʼmoriy`."""

    def repair(match: regex.Match) -> str:
        letter = match.group(1)
        return letter + ("‘" if letter in "oOgG" else "ʼ")

    return _LATIN_APOSTROPHE.sub(repair, text)


def _is_edge_furniture(line: str, running: set[str]) -> bool:
    stripped = line.strip()
    return bool(_PAGE_NUMBER.match(stripped)) or _normalise(stripped) in running


def _running_lines(pages: dict[int, str]) -> set[str]:
    if len(pages) < RUNNING_LINE_MIN_DOCUMENT:
        return set()

    counts: Counter[str] = Counter()
    for text in pages.values():
        # The outermost real line at each end, looking past a page number.
        lines = [
            line.strip()
            for line in text.split("\n")
            if _HAS_CONTENT.search(line) and not _PAGE_NUMBER.match(line.strip())
        ]
        if lines:
            counts.update({_normalise(lines[0]), _normalise(lines[-1])})

    threshold = max(RUNNING_LINE_MIN_PAGES, len(pages) * RUNNING_LINE_SHARE)
    return {line for line, count in counts.items() if line and count >= threshold}


def _normalise(line: str) -> str:
    """Headers repeat with a changing page number and pick up scan specks
    ("TURIZM ASOSLARI €"): compare letters and words only, digits as `#`."""
    line = _NOT_WORDLIKE.sub(" ", _DIGITS.sub("#", line.lower()))
    return _SPACES.sub(" ", line).strip()
