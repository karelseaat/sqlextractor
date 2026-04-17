from __future__ import annotations

from pathlib import Path
import io
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlextractor.modelgen import (
    PREFILL_HEARTBEAT_SECONDS,
    GemmaRuntimeConfig,
    _consume_streamed_response,
    _estimate_prompt_tokens,
    extract_python_source,
    infer_schema_summary,
    prepare_schema_input,
)
from sqlextractor.modelgen_cli import main


class ModelGenCliTests(unittest.TestCase):
    def test_gemma_prompt_defaults_use_full_context_window(self) -> None:
        self.assertEqual(GemmaRuntimeConfig().n_ctx, 131072)

    def test_extract_python_source_prefers_fenced_python(self) -> None:
        response = """
Here you go:

```python
from sqlalchemy.orm import DeclarativeBase
```
"""
        self.assertEqual(
            extract_python_source(response),
            "from sqlalchemy.orm import DeclarativeBase\n",
        )

    def test_prepare_schema_input_infers_query_only_sql(self) -> None:
        prepared = prepare_schema_input(
            """
SELECT u.id, u.email, o.id, o.user_id
FROM users u
JOIN orders o ON o.user_id = u.id

INSERT INTO orders (id, user_id, total_amount) VALUES (?, ?, ?)

UPDATE users SET email = ?
"""
        )
        self.assertTrue(prepared.inferred)
        self.assertIn("TABLE users", prepared.content)
        self.assertIn("TABLE orders", prepared.content)
        self.assertIn("orders.user_id = users.id", prepared.content)
        self.assertIn("email", prepared.content)
        self.assertIn("total_amount", prepared.content)

    def test_infer_schema_summary_is_compact(self) -> None:
        summary = infer_schema_summary(
            """
SELECT b.id, b.code, b.asset_id, t.code_ref
FROM batches b
LEFT JOIN assets t ON t.asset_id = b.asset_id

UPDATE batches SET Status = ?, asset_id = ?

INSERT INTO assets (asset_id, code_ref) VALUES (?, ?)
"""
        )
        self.assertIn("Input type: inferred schema summary", summary)
        self.assertIn("TABLE batches", summary)
        self.assertIn("TABLE assets", summary)
        self.assertNotIn("LEFT JOIN assets", summary)

    def test_streamed_response_reports_progress(self) -> None:
        stderr = io.StringIO()
        chunks = [
            {"choices": [{"text": "class User"}]},
            {"choices": [{"text": "(Base):\n    pass\n"}]},
        ]
        with redirect_stderr(stderr):
            output = _consume_streamed_response(chunks)

        self.assertEqual(output, "class User(Base):\n    pass\n")
        self.assertIn("Decoding output...", stderr.getvalue())

    def test_prefill_heartbeat_reports_waiting_status(self) -> None:
        stderr = io.StringIO()

        def delayed_chunks() -> object:
            time.sleep(0.06)
            yield {"choices": [{"text": "class User"}]}

        with patch("sqlextractor.modelgen.PREFILL_HEARTBEAT_SECONDS", 0.02):
            with redirect_stderr(stderr):
                output = _consume_streamed_response(delayed_chunks(), prompt_tokens=123)

        self.assertEqual(output, "class User")
        self.assertIn("Prefilling prompt...", stderr.getvalue())
        self.assertIn("123 prompt token(s)", stderr.getvalue())

    def test_estimate_prompt_tokens_uses_tokenizer_when_available(self) -> None:
        llm = MagicMock()
        llm.tokenize.return_value = [1, 2, 3]
        self.assertEqual(_estimate_prompt_tokens(llm, "hello"), 3)

    def test_generates_models_from_sql_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "schema.sql").write_text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE);\n",
                encoding="utf-8",
            )
            (root / "notes.txt").write_text("ignore me\n", encoding="utf-8")
            output_path = root / "models.py"

            captured: dict[str, object] = {}

            def fake_generate(schema_sql: str, config: object) -> str:
                captured["schema_sql"] = schema_sql
                captured["config"] = config
                return "class Base: ...\n"

            with patch("sqlextractor.modelgen_cli.generate_sqlalchemy_models", side_effect=fake_generate):
                exit_code = main([str(root), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "class Base: ...\n")
            self.assertIn("CREATE TABLE users", str(captured["schema_sql"]))
            self.assertNotIn("ignore me", str(captured["schema_sql"]))

    def test_cli_reports_query_inference_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "queries.sql").write_text(
                "SELECT u.id, u.email FROM users u\n\nUPDATE users SET email = ?\n",
                encoding="utf-8",
            )
            output_path = root / "models.py"

            stdout = io.StringIO()
            with patch("sqlextractor.modelgen_cli.generate_sqlalchemy_models", return_value="class Base: ...\n"):
                with redirect_stdout(stdout):
                    exit_code = main([str(root), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertIn("Detected query-only SQL input", stdout.getvalue())

    def test_errors_when_no_sql_files_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("ignore me\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                main([str(root)])

            self.assertEqual(context.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
