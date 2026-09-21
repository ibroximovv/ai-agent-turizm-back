"""Typography, line-unwrapping and font-encoding repair.

Uses the third-party :mod:`regex` module rather than :mod:`re` because the
rules depend on Unicode categories (``\\p{L}``, ``\\p{Lu}``, ``\\p{Ll}``) that
the standard library does not support.
"""

from __future__ import annotations

import unicodedata

import regex

# Digraphs whose second letter is frequently left lowercase by broken PDF/PPTX
# font encodings inside otherwise all-caps headings (`TO‘RTINChI BOB`).
_CAPS_DIGRAPHS = regex.compile(r"(Ch|Sh|Yo|Yu|Ya|Ts|Ng)")

#: A word, including the apostrophe variants used by `o‘` / `g‘`.
_WORD_WITH_APOSTROPHES = regex.compile(r"[\p{L}\p{M}‘’'ʼ`]+")

_ZERO_WIDTH = regex.compile("[\u200b-\u200d\ufeff\u00ad]")
_LINE_ENDINGS = regex.compile("\r\n?")
_IRREGULAR_SPACE = regex.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_HYPHEN_LINEBREAK = regex.compile(r"(\p{L}+)-[ \t]*\n[ \t]*(\p{L}+)")
_SINGLE_LINEBREAK = regex.compile(r"([^\n])\n(?=[^\n])")
_INLINE_WHITESPACE = regex.compile(r"[^\S\n]+")
_EXCESS_NEWLINES = regex.compile(r"\n{3,}")

_HAS_LOWERCASE = regex.compile(r"\p{Ll}")
_HAS_UPPERCASE = regex.compile(r"\p{Lu}")


def clean_text(text: str) -> str:
    """Normalise text layout, unicode anomalies and capital digraphs."""
    if not text:
        return ""

    # 1. Unicode NFC normalisation
    cleaned = unicodedata.normalize("NFC", text)

    # 2. Drop zero-width characters that break word matching and RAG lookups
    cleaned = _ZERO_WIDTH.sub("", cleaned)

    # 3. Normalise line endings so the unwrap steps below see plain \n
    cleaned = _LINE_ENDINGS.sub("\n", cleaned)

    # 4. Replace non-breaking spaces and irregular whitespace
    cleaned = _IRREGULAR_SPACE.sub(" ", cleaned)

    # 5. Fix hyphenated line breaks ("konver- \ntatsiya" -> "konvertatsiya")
    cleaned = _HYPHEN_LINEBREAK.sub(r"\1\2", cleaned)

    # 6. Unwrap single linebreaks within paragraphs while preserving double
    #    linebreaks. A lookahead is used so that adjacent single newlines are
    #    all unwrapped — a consuming match would skip every other one.
    cleaned = _SINGLE_LINEBREAK.sub(r"\1 ", cleaned)

    # 7. Clean excessive spaces per line
    cleaned = "\n".join(
        _INLINE_WHITESPACE.sub(" ", line).strip() for line in cleaned.split("\n")
    )

    # 8. Repair all-caps words whose digraph tail was decoded as lowercase
    #    (TO‘RTINChI -> TO‘RTINCHI, ShAHARShUNOSLIK -> SHAHARSHUNOSLIK)
    cleaned = _fix_all_caps_digraphs(cleaned)

    # 9. Collapse more than 2 consecutive newlines into 2
    cleaned = _EXCESS_NEWLINES.sub("\n\n", cleaned)

    return cleaned.strip()


def _fix_all_caps_digraphs(text: str) -> str:
    """Uppercase digraph tails only when that leaves the whole word in caps.

    Ordinary capitalised words (`Shahar`, `Chegara`) are left untouched.
    """

    def repair(match: regex.Match) -> str:
        word = match.group(0)
        if not _CAPS_DIGRAPHS.search(word):
            return word

        repaired = _CAPS_DIGRAPHS.sub(lambda d: d.group(0).upper(), word)

        # Any remaining lowercase letter means this was a mixed-case word.
        if _HAS_LOWERCASE.search(repaired):
            return word
        if not _HAS_UPPERCASE.search(word):
            return word
        return repaired

    return _WORD_WITH_APOSTROPHES.sub(repair, text)
