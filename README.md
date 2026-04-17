# sqlextractor

Small Python CLI that scans source files, extracts likely SQL strings, deduplicates them, and writes the unique queries to a text file.

It also includes a separate CPU-oriented tool that can feed SQL schema files into a local Gemma 4 model and generate SQLAlchemy models.

## Usage

```bash
./sqlextractor path/to/source --output extracted_queries.sql
```

If you prefer, the root script can also be run explicitly with Python:

```bash
python3 ./sqlextractor path/to/source --output extracted_queries.sql
```

## What it does

- scans directories recursively
- skips common generated and dependency directories
- extracts single-line and multi-line string literals
- merges common string concatenation patterns such as `+`, `.` and `..`
- scores candidate strings as likely SQL
- writes each unique query once to the output file

## SQLAlchemy model generation with Gemma 4

Install the optional runtime dependencies:

```bash
pip install -e '.[modelgen]'
```

The separate `sqlamodelgen` tool reads `.sql` files, sends the schema to a local Gemma 4 CPU model, and writes SQLAlchemy 2.0 declarative models:

```bash
./sqlamodelgen path/to/sql --output models.py
```

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
