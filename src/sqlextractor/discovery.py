from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

COMMON_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


def iter_source_files(
    targets: list[Path],
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    skip_paths: set[Path] | None = None,
) -> list[Path]:
    include_patterns = include_patterns or ["*"]
    exclude_patterns = exclude_patterns or []
    skip_paths = {path.resolve() for path in (skip_paths or set())}
    results: list[Path] = []

    for target in targets:
        resolved = target.resolve()
        if resolved in skip_paths or not target.exists():
            continue
        if target.is_file():
            if _should_process(target, include_patterns, exclude_patterns):
                results.append(target)
            continue

        for path in target.rglob("*"):
            if path.resolve() in skip_paths:
                continue
            if path.is_dir():
                if path.name in COMMON_IGNORED_DIRS:
                    continue
                continue
            if _is_ignored_dir(path):
                continue
            if _should_process(path, include_patterns, exclude_patterns):
                results.append(path)

    return sorted({path.resolve(): path for path in results}.values())


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(f"{path} appears to be binary")

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _should_process(path: Path, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    if not path.is_file():
        return False

    relative = path.as_posix()
    if any(fnmatch(relative, pattern) for pattern in exclude_patterns):
        return False
    if not any(fnmatch(relative, pattern) for pattern in include_patterns):
        return False

    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError:
        return False

    return b"\x00" not in sample


def _is_ignored_dir(path: Path) -> bool:
    return any(part in COMMON_IGNORED_DIRS for part in path.parts[:-1])
