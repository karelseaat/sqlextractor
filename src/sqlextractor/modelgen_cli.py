from __future__ import annotations

import argparse
from pathlib import Path

from .discovery import iter_source_files, read_text_file
from .modelgen import GemmaRuntimeConfig, generate_sqlalchemy_models, prepare_schema_input


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqlamodelgen",
        description="Generate SQLAlchemy models from SQL schema files using a local Gemma 4 model.",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan.")
    parser.add_argument(
        "-o",
        "--output",
        default="models.py",
        help="Output Python file for generated SQLAlchemy models.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob pattern to include. Defaults to *.sql when omitted.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude. Can be passed multiple times.",
    )
    parser.add_argument(
        "--model-path",
        help="Path to a local Gemma 4 GGUF file. If omitted, the CLI downloads a default CPU-friendly model from Hugging Face.",
    )
    parser.add_argument(
        "--hf-repo",
        default=GemmaRuntimeConfig.hf_repo,
        help="Hugging Face repository to download a GGUF model from when --model-path is omitted.",
    )
    parser.add_argument(
        "--hf-filename",
        default=GemmaRuntimeConfig.hf_filename,
        help="Filename to download from the Hugging Face model repository.",
    )
    parser.add_argument(
        "--cache-dir",
        help="Optional Hugging Face cache directory for downloaded GGUF files.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=GemmaRuntimeConfig.threads,
        help="CPU thread count passed to llama.cpp.",
    )
    parser.add_argument(
        "--context-size",
        type=int,
        default=GemmaRuntimeConfig.n_ctx,
        help="Context size passed to llama.cpp.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=GemmaRuntimeConfig.max_tokens,
        help="Maximum number of generated tokens.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=GemmaRuntimeConfig.temperature,
        help="Sampling temperature for generation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    targets = [Path(path) for path in args.paths]
    files = iter_source_files(
        targets=targets,
        include_patterns=args.include or ["*.sql"],
        exclude_patterns=args.exclude,
        skip_paths={output_path.resolve()},
    )
    if not files:
        parser.exit(1, "No SQL files matched the requested paths and filters.\n")

    schema_sql = _load_schema_sql(files)
    if not schema_sql.strip():
        parser.exit(1, "The matched SQL files did not contain any readable text.\n")
    prepared = prepare_schema_input(schema_sql)
    if prepared.inferred:
        print("Detected query-only SQL input; using inferred schema summary before model generation.")

    config = GemmaRuntimeConfig(
        model_path=args.model_path,
        hf_repo=args.hf_repo,
        hf_filename=args.hf_filename,
        cache_dir=args.cache_dir,
        threads=max(1, args.threads),
        n_ctx=max(1024, args.context_size),
        max_tokens=max(256, args.max_tokens),
        temperature=max(0.0, args.temperature),
    )
    generated = generate_sqlalchemy_models(schema_sql, config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generated, encoding="utf-8")
    print(
        f"Scanned {len(files)} SQL file(s) and wrote SQLAlchemy models to {output_path}."
    )
    return 0


def _load_schema_sql(files: list[Path]) -> str:
    parts: list[str] = []
    for path in files:
        content = read_text_file(path).strip()
        if not content:
            continue
        parts.append(f"-- FILE: {_display_path(path)}\n{content}")
    return "\n\n".join(parts)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
