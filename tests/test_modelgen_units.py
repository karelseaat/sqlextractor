from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.modelgen import _split_sql_statements, extract_python_source


class SplitSqlStatementsTests(unittest.TestCase):
    def test_split_on_semicolons(self) -> None:
        self.assertEqual(_split_sql_statements("SELECT 1; SELECT 2"), ["SELECT 1", "SELECT 2"])

    def test_split_on_blank_lines(self) -> None:
        self.assertEqual(
            _split_sql_statements("SELECT a\n\nSELECT b"),
            ["SELECT a", "SELECT b"],
        )

    def test_merges_unbalanced_parenthesis(self) -> None:
        self.assertEqual(
            _split_sql_statements("SELECT id FROM t WHERE id IN (1,\n\n2)"),
            ["SELECT id FROM t WHERE id IN (1,\n2)"],
        )

    def test_merges_trailing_comma(self) -> None:
        self.assertEqual(
            _split_sql_statements("SELECT a,\n\nb FROM t"),
            ["SELECT a,\nb FROM t"],
        )

    def test_merges_trailing_keyword(self) -> None:
        self.assertEqual(
            _split_sql_statements("FROM users WHERE\n\nid = 1"),
            ["FROM users WHERE\nid = 1"],
        )

    def test_merges_trailing_operator(self) -> None:
        self.assertEqual(
            _split_sql_statements("SELECT a =\n\nb"),
            ["SELECT a =\nb"],
        )

    def test_does_not_merge_complete_statements(self) -> None:
        self.assertEqual(
            _split_sql_statements("SELECT a\n\nb FROM t"),
            ["SELECT a", "b FROM t"],
        )

    def test_empty_input_returns_no_statements(self) -> None:
        self.assertEqual(_split_sql_statements(""), [])
        self.assertEqual(_split_sql_statements("\n\n"), [])


class ExtractPythonSourceTests(unittest.TestCase):
    def test_extracts_fenced_python(self) -> None:
        self.assertEqual(extract_python_source("```python\nx = 1\n```"), "x = 1\n")

    def test_strips_python_language_prefix(self) -> None:
        self.assertEqual(extract_python_source("python\nx = 1"), "x = 1\n")

    def test_returns_bare_source_with_trailing_newline(self) -> None:
        self.assertEqual(extract_python_source("x = 1"), "x = 1\n")
        self.assertEqual(extract_python_source("x = 1\n"), "x = 1\n")


if __name__ == "__main__":
    unittest.main()
