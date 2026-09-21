from apps.pipeline.services.cleaner import clean_text


def test_returns_an_empty_string_for_empty_input():
    assert clean_text("") == ""


def test_unwraps_every_single_newline_inside_a_paragraph():
    assert clean_text("bir\nikki\nuch") == "bir ikki uch"


def test_unwraps_adjacent_newlines_even_around_one_character_lines():
    # A consuming regex would skip every other newline and leave "a\nikki".
    assert clean_text("bir\na\nikki") == "bir a ikki"


def test_keeps_paragraph_breaks():
    assert clean_text("birinchi band\n\nikkinchi band") == "birinchi band\n\nikkinchi band"


def test_collapses_runs_of_more_than_two_newlines():
    assert clean_text("a\n\n\n\nb") == "a\n\nb"


def test_normalises_crlf_line_endings():
    assert clean_text("bir\r\nikki") == "bir ikki"


def test_rejoins_words_broken_by_a_hyphenated_line_break():
    assert clean_text("konver-\ntatsiya") == "konvertatsiya"


def test_replaces_non_breaking_spaces_with_regular_spaces():
    assert clean_text("turizm asoslari") == "turizm asoslari"


def test_drops_zero_width_characters():
    assert clean_text("tur​izm") == "turizm"


class TestAllCapsDigraphRepair:
    def test_repairs_a_trailing_lowercase_digraph_tail(self):
        assert clean_text("TO‘RTINChI BOB") == "TO‘RTINCHI BOB"
        assert clean_text("TUZILIShI") == "TUZILISHI"

    def test_repairs_several_digraphs_in_the_same_word(self):
        assert clean_text("ShAHARShUNOSLIK") == "SHAHARSHUNOSLIK"

    def test_repairs_a_word_initial_digraph(self):
        assert clean_text("ChIQISh") == "CHIQISH"

    def test_repairs_digraphs_around_o_g_apostrophe(self):
        assert clean_text("MAShG‘ULOT") == "MASHG‘ULOT"

    def test_leaves_ordinary_capitalised_words_untouched(self):
        assert clean_text("Shahar va Chegara") == "Shahar va Chegara"

    def test_leaves_lowercase_words_untouched(self):
        assert clean_text("shahar chegara") == "shahar chegara"
