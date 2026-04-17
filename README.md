# sqlextractor

Small Python CLI that scans source files, extracts likely SQL strings, deduplicates them, and writes the unique queries to a text file.

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
