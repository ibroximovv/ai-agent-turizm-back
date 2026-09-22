from apps.pipeline.services.translit import detect_script, repair_uzbek_cyrillic, to_latin


class TestDetectScript:
    def test_detects_uzbek_cyrillic_by_its_distinctive_letters(self):
        assert detect_script("Ўзбекистон Республикаси туризм тўғрисида қонун") == "uz-cyrl"

    def test_detects_russian_when_uzbek_only_letters_are_absent(self):
        assert detect_script("Российская Федерация общие вещи и защита прав") == "ru"

    def test_detects_uzbek_latin(self):
        assert detect_script("Turizm asoslari va qonunchilik masalalari") == "uz-latn"

    def test_returns_other_for_text_with_too_few_letters(self):
        assert detect_script("123 — 456") == "other"


class TestRepairUzbekCyrillic:
    def test_rewrites_a_word_final_ii_as_iy(self):
        assert repair_uzbek_cyrillic("ташкилотларии.") == "ташкилотларий."

    def test_leaves_ii_alone_mid_word(self):
        assert repair_uzbek_cyrillic("ииланган") == "ииланган"


class TestToLatin:
    def test_transliterates_the_uzbek_specific_letters(self):
        assert to_latin("ўқғҳ") == "o‘qg‘h"

    def test_uses_ye_at_word_start_and_e_after_a_consonant(self):
        assert to_latin("ер") == "yer"
        assert to_latin("бет") == "bet"

    def test_uses_ye_after_a_vowel(self):
        assert to_latin("оеч") == "oyech"

    def test_keeps_all_caps_words_in_caps(self):
        assert to_latin("ШАҲАР") == "SHAHAR"

    def test_title_cases_multi_letter_replacements(self):
        assert to_latin("Чегара") == "Chegara"

    def test_repairs_the_corrupted_final_ii_font_artefact(self):
        assert to_latin("ташкилотларии") == "tashkilotlariy"

    def test_leaves_latin_and_punctuation_untouched(self):
        assert to_latin("PDF файл, 2024-йил") == "PDF fayl, 2024-yil"

    def test_transliterates_cyrillic_letters_outside_the_uzbek_subset(self):
        assert to_latin("объект") == "obʼyekt"
