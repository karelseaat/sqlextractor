# sqlextractor

Small Python CLI that scans source files, extracts likely SQL strings, deduplicates them, and writes the unique queries to a text file.

It also includes a separate CPU-oriented tool that can feed SQL schema files into a local Gemma 4 model and generate SQLAlchemy models.

## Installation

Python 3.10+ is required. The core tool has no dependencies:

```bash
pip install -e .
```

This installs the `sqlextractor` and `sqlamodelgen` commands. Without installing, both root scripts also run directly with Python (`python3 ./sqlextractor ...`).

Model generation needs the optional runtime dependencies:

```bash
pip install -e '.[modelgen]'
```

## sqlextractor usage

```bash
./sqlextractor path/to/source --output extracted_queries.sql
```

Options:

| Flag | Default | Description |
| --- | --- | --- |
| `paths` (positional) | `.` | Files or directories to scan. |
| `-o`, `--output` | `extracted_queries.sql` | Output text file for deduplicated queries. |
| `--include` | all files | Glob pattern to include; repeatable. |
| `--exclude` | none | Glob pattern to exclude; repeatable. |
| `--min-confidence` | `60` | Minimum SQL confidence score (0-100) to include in the output. |

Example:

```bash
./sqlextractor src tests --include '*.py' --exclude '*_test.py' \
  --min-confidence 80 --output queries.sql
```

## What it does

- scans directories recursively
- skips common generated and dependency directories
- extracts single-line and multi-line string literals
- merges common string concatenation patterns such as `+`, `.` and `..`
- scores candidate strings as likely SQL
- writes each unique query once to the output file

## SQLAlchemy model generation with Gemma 4

The separate `sqlamodelgen` tool reads `.sql` files, sends the schema to a local Gemma 4 CPU model, and writes SQLAlchemy 2.0 declarative models:

```bash
./sqlamodelgen path/to/sql --output models.py
```

Options:

| Flag | Default | Description |
| --- | --- | --- |
| `paths` (positional) | `.` | Files or directories to scan. |
| `-o`, `--output` | `models.py` | Output Python file for generated models. |
| `--include` | `*.sql` | Glob pattern to include; repeatable. |
| `--exclude` | none | Glob pattern to exclude; repeatable. |
| `--model-path` | Hugging Face download | Path to a local GGUF file. |
| `--hf-repo` | `bartowski/google_gemma-4-E4B-it-GGUF` | Hugging Face repository for the model download. |
| `--hf-filename` | `google_gemma-4-E4B-it-Q4_K_M.gguf` | Filename within the Hugging Face repository. |
| `--cache-dir` | Hugging Face default | Cache directory for downloaded GGUF files. |
| `--threads` | CPU count | CPU thread count passed to llama.cpp. |
| `--context-size` | `131072` | Context size passed to llama.cpp. |
| `--max-tokens` | `4096` | Maximum number of generated tokens. |
| `--temperature` | `0.1` | Sampling temperature for generation. |

By default it downloads a CPU-friendly GGUF model from Hugging Face:

- repo: `bartowski/google_gemma-4-E4B-it-GGUF`
- file: `google_gemma-4-E4B-it-Q4_K_M.gguf`

You can also point it at an already-downloaded local model file:

```bash
./sqlamodelgen path/to/sql \
  --model-path ~/models/google_gemma-4-E4B-it-Q4_K_M.gguf \
  --output models.py
```

The generator is aimed at schema SQL such as `CREATE TABLE` statements so it can reconstruct tables, types, primary keys, foreign keys, and relationships.

If you only have extracted application queries instead of schema DDL, `sqlamodelgen` now falls back to building a compact inferred schema summary from the observed tables, columns, CRUD operations, and join conditions before sending that reduced input to Gemma. DDL is still the preferred input and will produce more reliable models.

During model generation, the tool prints phase progress and a live output counter to stderr so long CPU runs are easier to track.

## Development

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

Tests use only the standard library and do not require the `modelgen` extras.
