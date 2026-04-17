from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceLocation:
    file_path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class StringToken:
    file_path: str
    start_line: int
    end_line: int
    value: str
    start_index: int
    end_index: int


@dataclass
class QueryResult:
    query_text: str
    canonical_text: str
    occurrences: list[SourceLocation] = field(default_factory=list)
    max_confidence: int = 0

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)
