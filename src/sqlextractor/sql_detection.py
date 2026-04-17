from __future__ import annotations

import re
import textwrap

SQL_PATTERNS = [
    re.compile(r"^\s*select\b.+\bfrom\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*insert\s+into\b.+\bvalues\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*update\b.+\bset\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*delete\s+from\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*create\s+(table|view|index|schema)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*alter\s+table\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*drop\s+(table|view|index)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*with\b.+\b(select|insert|update|delete)\b", re.IGNORECASE | re.DOTALL),
]

SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "group",
    "order",
    "having",
    "insert",
    "into",
    "values",
    "update",
    "set",
    "delete",
    "create",
    "alter",
    "drop",
    "table",
    "view",
    "index",
    "with",
    "union",
    "limit",
    "offset",
}


def normalize_query_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = textwrap.dedent(normalized).strip()
    return normalized


def canonicalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_query_text(text)).strip().lower()


def score_sql_candidate(text: str) -> int:
    normalized = normalize_query_text(text)
    if len(normalized) < 12:
        return 0

    if not looks_like_sql_statement(normalized):
        return 0

    lowered = normalized.lower()
    score = 0

    for pattern in SQL_PATTERNS:
        if pattern.search(normalized):
            score = max(score, 75)
            break

    keyword_hits = sum(1 for keyword in SQL_KEYWORDS if re.search(rf"\b{keyword}\b", lowered))
    if keyword_hits >= 2:
        score += 10
    if keyword_hits >= 4:
        score += 10
    if keyword_hits >= 6:
        score += 5

    if any(fragment in lowered for fragment in (" join ", " where ", " values ", " group by ", " order by ")):
        score += 10

    if normalized.endswith(";"):
        score += 5

    if re.search(r"https?://|<[a-z][^>]*>|^\{", normalized, re.IGNORECASE):
        score -= 30

    return max(0, min(score, 100))


def looks_like_sql_statement(text: str) -> bool:
    stripped = normalize_query_text(text)
    return any(pattern.search(stripped) for pattern in SQL_PATTERNS)
