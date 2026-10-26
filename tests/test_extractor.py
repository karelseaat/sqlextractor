from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.extractor import _is_floor_division, extract_string_tokens


class ExtractorTests(unittest.TestCase):
    def test_block_comment_is_skipped(self) -> None:
        text = '/* SELECT bad FROM nowhere */ query = "SELECT good FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT good FROM users"])

    def test_slash_slash_line_comment_is_skipped(self) -> None:
        text = '// SELECT bad FROM nowhere\nquery = "SELECT good FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT good FROM users"])

    def test_slash_slash_comment_at_file_start_without_space_is_skipped(self) -> None:
        text = '//SELECT bad FROM nowhere\nquery = "SELECT good FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT good FROM users"])

    def test_floor_division_is_not_treated_as_comment(self) -> None:
        text = 'x = 10//2; s = "SELECT a FROM b"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT a FROM b"])
        self.assertTrue(_is_floor_division("10//2", 2))
        self.assertFalse(_is_floor_division("//", 0))

    def test_hash_line_comment_is_skipped(self) -> None:
        text = '# SELECT bad FROM nowhere\nq = "SELECT good FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT good FROM users"])

    def test_stray_apostrophe_does_not_swallow_following_text(self) -> None:
        text = "x = don't\ny = \"SELECT a FROM b\""
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT a FROM b"])

    def test_unterminated_string_is_discarded(self) -> None:
        text = 'query = "SELECT a FROM b\nother = "SELECT c FROM d"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT c FROM d"])

    def test_verbatim_string_unescapes_doubled_quotes(self) -> None:
        text = 'q = @"SELECT ""quoted"" FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ['SELECT "quoted" FROM users'])

    def test_escaped_quote_stays_inside_string(self) -> None:
        text = 'q = "SELECT \\"quoted\\" FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ['SELECT "quoted" FROM users'])

    def test_triple_quoted_string_records_line_range(self) -> None:
        text = 'q = """\nSELECT id\nFROM users\nWHERE active = 1\n"""\nnext = 1'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual(len(tokens), 1)
        token = tokens[0]
        self.assertEqual(token.value, "\nSELECT id\nFROM users\nWHERE active = 1\n")
        self.assertEqual(token.start_line, 1)
        self.assertEqual(token.end_line, 5)
        self.assertEqual(token.file_path, "sample.py")

    def test_backtick_string_is_extracted(self) -> None:
        text = "q = `SELECT id FROM users`"
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT id FROM users"])

    def test_concatenated_strings_merge(self) -> None:
        text = 'q = "INSERT INTO t (a) " + "VALUES (?)";'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].value, "INSERT INTO t (a) VALUES (?)")
        self.assertEqual(tokens[0].start_index, 4)
        self.assertEqual(tokens[0].end_index, 39)

    def test_multiline_concatenation_merges_and_spans_lines(self) -> None:
        text = 'q = "SELECT id "\n    + "FROM users"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].value, "SELECT id FROM users")
        self.assertEqual(tokens[0].start_line, 1)
        self.assertEqual(tokens[0].end_line, 2)

    def test_unrelated_strings_are_not_merged(self) -> None:
        text = 'a = "SELECT 1"; b = "SELECT 2"'
        tokens = extract_string_tokens(text, "sample.py")
        self.assertEqual([token.value for token in tokens], ["SELECT 1", "SELECT 2"])


if __name__ == "__main__":
    unittest.main()
