from apps.common.filename import (
    build_stored_filename,
    decode_multipart_filename,
    sanitize_path_segment,
)


class TestDecodeMultipartFilename:
    def test_recovers_a_utf8_name_that_arrived_decoded_as_latin1(self):
        utf8_name = "Ўзбекистон Конституцияси.pdf"
        as_latin1 = utf8_name.encode("utf-8").decode("latin-1")

        assert as_latin1 != utf8_name
        assert decode_multipart_filename(as_latin1) == utf8_name

    def test_leaves_plain_ascii_names_untouched(self):
        assert decode_multipart_filename("Constitution.pdf") == "Constitution.pdf"

    def test_leaves_an_already_correctly_decoded_name_untouched(self):
        assert decode_multipart_filename("Меҳнат кодекси.docx") == "Меҳнат кодекси.docx"

    def test_leaves_a_genuine_latin1_name_untouched(self):
        # 0xE9 on its own is not valid UTF-8, so no reinterpretation happens.
        assert decode_multipart_filename("café.pdf") == "café.pdf"

    def test_handles_an_empty_name(self):
        assert decode_multipart_filename("") == ""


class TestSanitizePathSegment:
    def test_replaces_unsafe_characters(self):
        assert sanitize_path_segment("my report (v2).txt") == "my_report_v2_.txt"

    def test_strips_leading_dots_and_dashes_so_no_segment_can_traverse(self):
        assert sanitize_path_segment("../../etc") == "etc"
        assert sanitize_path_segment("..") == "unnamed"

    def test_falls_back_when_nothing_safe_remains(self):
        assert sanitize_path_segment("Ўзбекистон") == "unnamed"


class TestBuildStoredFilename:
    HASH = "fdc303ce1833de296eebe3acfd00da59be5ba96a2684e72e11da3334a7cfa6fa"

    def test_keeps_the_extension_so_the_parser_can_still_be_selected(self):
        assert (
            build_stored_filename("Ўзбекистон Конституцияси.txt", ".txt", self.HASH)
            == "fdc303ce1833__unnamed.txt"
        )

    def test_keeps_an_ascii_base_name_readable(self):
        assert (
            build_stored_filename("Constitution.pdf", ".pdf", self.HASH)
            == "fdc303ce1833__Constitution.pdf"
        )

    def test_gives_different_content_under_the_same_name_different_paths(self):
        other = "aaaa" * 16
        assert build_stored_filename("same.pdf", ".pdf", self.HASH) != build_stored_filename(
            "same.pdf", ".pdf", other
        )
