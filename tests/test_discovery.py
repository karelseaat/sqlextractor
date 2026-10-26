from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.discovery import iter_source_files, read_text_file


class DiscoveryTests(unittest.TestCase):
    def test_include_patterns_filter_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "b.txt").write_text("note\n", encoding="utf-8")

            results = iter_source_files([root], include_patterns=["*.py"])

            self.assertEqual([path.name for path in results], ["a.py"])

    def test_exclude_patterns_filter_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "b.txt").write_text("note\n", encoding="utf-8")

            results = iter_source_files([root], exclude_patterns=["*.txt"])

            self.assertEqual([path.name for path in results], ["a.py"])

    def test_default_patterns_include_all_text_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "b.txt").write_text("note\n", encoding="utf-8")

            results = iter_source_files([root])

            self.assertEqual([path.name for path in results], ["a.py", "b.txt"])

    def test_single_file_target_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "a.py"
            target.write_text("x = 1\n", encoding="utf-8")

            results = iter_source_files([target])

            self.assertEqual([path.name for path in results], ["a.py"])

    def test_skip_paths_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "b.py").write_text("y = 2\n", encoding="utf-8")

            results = iter_source_files([root], skip_paths={root / "a.py"})

            self.assertEqual([path.name for path in results], ["b.py"])

    def test_missing_target_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            results = iter_source_files([root / "does-not-exist"])

            self.assertEqual(results, [])

    def test_binary_files_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "bin.dat").write_bytes(b"\x00\x01\x02")

            results = iter_source_files([root])

            self.assertEqual([path.name for path in results], ["a.py"])

    def test_common_ignored_dirs_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            for ignored in ("__pycache__", ".git", "node_modules", "venv"):
                nested = root / ignored
                nested.mkdir()
                (nested / "inner.py").write_text("y = 2\n", encoding="utf-8")

            results = iter_source_files([root])

            self.assertEqual([path.name for path in results], ["a.py"])

    def test_read_text_file_reads_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "u.txt"
            path.write_text("héllo\n", encoding="utf-8")

            self.assertEqual(read_text_file(path), "héllo\n")

    def test_read_text_file_falls_back_to_latin1(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "l.txt"
            path.write_bytes(b"caf\xe9")

            self.assertEqual(read_text_file(path), "café")

    def test_read_text_file_rejects_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "b.dat"
            path.write_bytes(b"\x00abc")

            with self.assertRaises(ValueError) as context:
                read_text_file(path)

            self.assertIn("appears to be binary", str(context.exception))


if __name__ == "__main__":
    unittest.main()
