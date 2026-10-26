from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.cli import main


class CliTests(unittest.TestCase):
    def test_root_script_is_executable_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "example.py").write_text(
                'query = "SELECT count(*) FROM users";\n',
                encoding="utf-8",
            )
            output_path = root / "queries.sql"
            script_path = Path(__file__).resolve().parents[1] / "sqlextractor"

            result = subprocess.run(
                [str(script_path), str(root), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SELECT count(*) FROM users", output_path.read_text(encoding="utf-8"))

    def test_deduplicates_queries_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "example.py").write_text(
                'QUERY = """\nSELECT id, name\nFROM users\nWHERE active = 1\n"""\n',
                encoding="utf-8",
            )
            (root / "example.js").write_text(
                'const query = "SELECT id, name FROM users WHERE active = 1";\n',
                encoding="utf-8",
            )
            output_path = root / "queries.sql"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([str(root), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8").strip(),
                "SELECT id, name\nFROM users\nWHERE active = 1",
            )
            summary = stdout.getvalue()
            self.assertIn("found 2 SQL matches", summary)
            self.assertIn("wrote 1 unique queries", summary)

    def test_merges_common_string_concatenation_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Example.java").write_text(
                'String query = "INSERT INTO audit_log (id, message) " +\n'
                '               "VALUES (?, ?)";\n',
                encoding="utf-8",
            )
            (root / "example.ts").write_text(
                "const report = `WITH recent AS (\n"
                "  SELECT id FROM audit_log\n"
                ")\n"
                "SELECT id FROM recent`;\n",
                encoding="utf-8",
            )
            output_path = root / "queries.sql"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([str(root), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("INSERT INTO audit_log (id, message) VALUES (?, ?)", content)
            self.assertIn("WITH recent AS (\n  SELECT id FROM audit_log\n)\nSELECT id FROM recent", content)
            summary = stdout.getvalue()
            self.assertIn("wrote 2 unique queries", summary)

    def test_excludes_non_sql_text_that_only_contains_sql_later(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Example.java").write_text(
                'String bad = "notes for receipts.\\n"\n'
                '    + "public static Date findLatestChangeTimestampForReceipts(...)\\n"\n'
                '    + "{\\n"\n'
                '    + "String query = \\"SELECT MAX(r.updated_at) AS last_updated \\";";\n'
                'String good = "SELECT MAX(r.updated_at) AS last_updated FROM receipts r";\n',
                encoding="utf-8",
            )
            output_path = root / "queries.sql"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main([str(root), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            content = output_path.read_text(encoding="utf-8")
            self.assertNotIn("public static", content)
            self.assertEqual(
                content.strip(),
                "SELECT MAX(r.updated_at) AS last_updated FROM receipts r",
            )


if __name__ == "__main__":
    unittest.main()
