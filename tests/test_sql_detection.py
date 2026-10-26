from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.sql_detection import (
    canonicalize_query,
    looks_like_sql_statement,
    normalize_query_text,
    score_sql_candidate,
)


class SqlDetectionTests(unittest.TestCase):
    def test_multiline_select_matches_pattern(self) -> None:
        self.assertTrue(looks_like_sql_statement("prefix\nselect id from users"))

    def test_case_insensitive_match(self) -> None:
        self.assertTrue(looks_like_sql_statement("sElEcT id fRoM users"))

    def test_delete_from_matches_pattern(self) -> None:
        self.assertTrue(looks_like_sql_statement("DELETE FROM users WHERE id = 1"))

    def test_with_select_matches_pattern(self) -> None:
        self.assertTrue(looks_like_sql_statement("WITH x AS (SELECT 1) SELECT * FROM x"))

    def test_create_table_matches_pattern(self) -> None:
        self.assertTrue(looks_like_sql_statement("CREATE TABLE users (id INTEGER)"))

    def test_non_sql_does_not_match(self) -> None:
        self.assertFalse(looks_like_sql_statement("hello world this is not sql at all"))

    def test_score_simple_select(self) -> None:
        self.assertEqual(score_sql_candidate("SELECT id FROM users"), 85)

    def test_score_select_with_where(self) -> None:
        self.assertEqual(score_sql_candidate("SELECT id, name FROM users WHERE active = 1"), 95)

    def test_score_insert_values(self) -> None:
        self.assertEqual(score_sql_candidate("INSERT INTO users (id, name) VALUES (1, 'a')"), 95)

    def test_non_sql_scores_zero(self) -> None:
        self.assertEqual(score_sql_candidate("hello world this is not sql at all"), 0)

    def test_short_text_scores_zero(self) -> None:
        self.assertEqual(score_sql_candidate("SELECT"), 0)

    def test_canonicalize_query_collapses_whitespace(self) -> None:
        self.assertEqual(canonicalize_query("  SELECT   id\nFROM\tusers  "), "select id from users")

    def test_normalize_query_text_normalizes_crlf(self) -> None:
        self.assertEqual(normalize_query_text("SELECT 1\r\nFROM t\r"), "SELECT 1\nFROM t")


if __name__ == "__main__":
    unittest.main()
