"""Script detection and Uzbek Cyrillic → Latin transliteration.

Latin-script queries do not match Cyrillic documents in a vector store, so
Uzbek Cyrillic material is transliterated before it is indexed. Russian text is
left untouched — transliterating it would only corrupt it.
"""

from __future__ import annotations

import re
from typing import Literal

Script = Literal["uz-latn", "uz-cyrl", "ru", "other"]

#: Letters that exist in Uzbek Cyrillic but not in Russian.
UZ_ONLY = frozenset("ўқғҳЎҚҒҲ")
#: Letters that exist in Russian but not in Uzbek Cyrillic.
RU_ONLY = frozenset("ыщЫЩ")

MAP: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ё": "yo", "ў": "o‘", "қ": "q",
    "ғ": "g‘", "ҳ": "h", "ы": "i",
}

UPPER_MAP: dict[str, str] = {key.upper(): value for key, value in MAP.items()}

#: Every Cyrillic letter the transliterator recognises, as a character class.
CYR_RUN = re.compile("[Ѐ-ӿ]+")

# `е` becomes `ye` at the start of a word and after a vowel or a hard/soft
# sign; elsewhere it is a plain `e`.
VOWEL_BEFORE_YE = frozenset("аеёиоуўэюяъьАЕЁИОУЎЭЮЯЪЬ")

_CYR_LETTER = "а-яёўқғҳА-ЯЁЎҚҒҲ"
#: Corrupted PDF font encodings turn a word-final `ий` into `ии`.
FIX_FINAL_II = re.compile(rf"ии(?![{_CYR_LETTER}])")

_CYRILLIC_E_LOWER = "е"  # е
_CYRILLIC_E_UPPER = "Е"  # Е


def is_uzbek_cyrillic(text: str, sample: int = 4000) -> bool:
    chunk = text[:sample]
    uz = sum(1 for ch in chunk if ch in UZ_ONLY)
    ru = sum(1 for ch in chunk if ch in RU_ONLY)
    return uz > 0 and uz >= ru


def detect_script(text: str, sample: int = 4000) -> Script:
    chunk = text[:sample]
    cyr = 0
    lat = 0
    for ch in chunk:
        if "Ѐ" <= ch <= "ӿ":
            cyr += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            lat += 1

    if cyr + lat < 10:
        return "other"

    if cyr / (cyr + lat) > 0.3:
        return "uz-cyrl" if is_uzbek_cyrillic(text, sample) else "ru"
    return "uz-latn" if lat else "other"


def repair_uzbek_cyrillic(text: str) -> str:
    return FIX_FINAL_II.sub("ий", text)


def _convert_e(word: str) -> str:
    """Expand `е`/`Е` into `ye`/`Ye` or `e`/`E` depending on the preceding letter."""
    out: list[str] = []
    for index, ch in enumerate(word):
        if ch not in (_CYRILLIC_E_LOWER, _CYRILLIC_E_UPPER):
            out.append(ch)
            continue
        prev = word[index - 1] if index > 0 else ""
        if not prev or prev in VOWEL_BEFORE_YE:
            out.append("Ye" if ch == _CYRILLIC_E_UPPER else "ye")
        else:
            out.append("E" if ch == _CYRILLIC_E_UPPER else "e")
    return "".join(out)


def _translit_word(word: str) -> str:
    is_upper = word == word.upper() and word != word.lower()
    out: list[str] = []

    for ch in _convert_e(word):
        if ch in MAP:
            out.append(MAP[ch])
        elif ch in UPPER_MAP:
            replacement = UPPER_MAP[ch]
            # A multi-letter replacement keeps only its first letter capitalised
            # (`Ч` → `Ch`); the all-caps pass below fixes genuine headings.
            out.append(
                replacement[0].upper() + replacement[1:].lower()
                if len(replacement) > 1
                else replacement.upper()
            )
        else:
            out.append(ch)

    result = "".join(out)
    return result.upper() if is_upper else result


def to_latin(text: str) -> str:
    """Transliterate every Cyrillic run in `text` to the Uzbek Latin alphabet."""
    repaired = repair_uzbek_cyrillic(text)
    # Match the whole Cyrillic block so that letters outside the Uzbek subset
    # (ё, ъ, ь, э and Russian loanword letters) are transliterated too, instead
    # of being left behind as stray Cyrillic inside Latin words.
    return CYR_RUN.sub(lambda match: _translit_word(match.group(0)), repaired)
