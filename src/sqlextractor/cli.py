from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path

from .discovery import iter_source_files, read_text_file
from .extractor import extract_string_tokens
from .models import QueryResult, SourceLocation
from .sql_detection import canonicalize_query, normalize_query_text, score_sql_candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqlextractor",
        description="Extract likely SQL queries from source code and save unique queries to a text file.",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan.")
    parser.add_argument(
        "-o",
        "--output",
        default="extracted_queries.sql",
        help="Output text file for deduplicated queries.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob pattern to include. Can be passed multiple times.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude. Can be passed multiple times.",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=60,
        help="Minimum SQL confidence score to include in the output file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    targets = [Path(path) for path in args.paths]
    files = iter_source_files(
        targets=targets,
        include_patterns=args.include or ["*"],
        exclude_patterns=args.exclude,
        skip_paths={output_path.resolve()},
    )

    results: "OrderedDict[str, QueryResult]" = OrderedDict()
    total_matches = 0

    for path in files:
        try:
            content = read_text_file(path)
        except (OSError, ValueError):
            continue

        for token in extract_string_tokens(content, _display_path(path)):
            confidence = score_sql_candidate(token.value)
            if confidence < args.min_confidence:
                continue

            query_text = normalize_query_text(token.value)
            canonical = canonicalize_query(query_text)
            if not canonical:
                continue

            total_matches += 1
            result = results.get(canonical)
            location = SourceLocation(
                file_path=token.file_path,
                start_line=token.start_line,
                end_line=token.end_line,
            )

            if result is None:
                results[canonical] = QueryResult(
                    query_text=query_text,
                    canonical_text=canonical,
                    occurrences=[location],
                    max_confidence=confidence,
                )
            else:
                result.occurrences.append(location)
                result.max_confidence = max(result.max_confidence, confidence)
                result.query_text = _prefer_query_text(result.query_text, query_text)

    _write_output(output_path, [result.query_text for result in results.values()])
    _print_summary(files, results, output_path, total_matches)
    return 0


def _write_output(output_path: Path, queries: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(query.strip() for query in queries if query.strip())
    if content:
        content += "\n"
    output_path.write_text(content, encoding="utf-8")


def _print_summary(
    files: list[Path],
    results: OrderedDict[str, QueryResult],
    output_path: Path,
    total_matches: int,
) -> None:
    print(
        f"Scanned {len(files)} files, found {total_matches} SQL matches, "
        f"wrote {len(results)} unique queries to {output_path}."
    )
    for index, result in enumerate(results.values(), start=1):
        locations = ", ".join(
            f"{location.file_path}:{location.start_line}-{location.end_line}"
            for location in result.occurrences[:3]
        )
        extra = ""
        if result.occurrence_count > 3:
            extra = f", +{result.occurrence_count - 3} more"
        print(
            f"[{index}] {result.occurrence_count} occurrence(s), "
            f"confidence {result.max_confidence}: {locations}{extra}"
        )


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _prefer_query_text(current: str, candidate: str) -> str:
    current_newlines = current.count("\n")
    candidate_newlines = candidate.count("\n")
    if candidate_newlines > current_newlines:
        return candidate
    if candidate_newlines == current_newlines and len(candidate) > len(current):
        return candidate
    return current
