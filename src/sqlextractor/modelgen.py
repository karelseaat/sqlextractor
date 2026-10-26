from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import threading
import time

DEFAULT_GEMMA_REPO = "bartowski/google_gemma-4-E4B-it-GGUF"
DEFAULT_GEMMA_FILENAME = "google_gemma-4-E4B-it-Q4_K_M.gguf"

SYSTEM_PROMPT = """You convert SQL schema files into SQLAlchemy 2.0 declarative models.
Return only valid Python source code.
Generate table classes, mapped columns, primary keys, foreign keys, unique constraints when explicit, and relationships when the SQL schema makes them clear.
Prefer SQLAlchemy 2.0 style with DeclarativeBase, Mapped, mapped_column, relationship, and ForeignKey.
Do not add markdown, explanations, or comments unless a short clarification is required in code.
If the schema is incomplete, keep the generated models conservative and avoid inventing columns or constraints that are not supported by the input.
When the input is an inferred schema summary derived from queries instead of raw DDL, treat it as evidence and only model fields and relationships that are strongly supported by the summary."""

USER_PROMPT_TEMPLATE = """Generate SQLAlchemy 2.0 declarative models from the schema evidence below.

Requirements:
- Output Python source only.
- Define a shared Base class using DeclarativeBase.
- Use snake_case __tablename__ values matching the SQL table names.
- Map SQL column types to reasonable SQLAlchemy column types.
- Preserve nullable, primary key, foreign key, default, and unique information when explicit.
- Add relationship() fields for clear foreign-key relations.
- Use deterministic, readable class names derived from table names.
- Do not include sample usage.
- {input_guidance}

Schema evidence input:
{schema_input}
"""

PYTHON_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
DDL_RE = re.compile(r"^\s*(?:create|alter|drop)\s+(?:table|view|index|schema)\b", re.IGNORECASE | re.MULTILINE)
TABLE_REF_RE = re.compile(
    r"\b(?:from|join|update|into|delete\s+from)\s+([A-Za-z_][\w$]*)(?:\s+(?:as\s+)?([A-Za-z_][\w$]*))?",
    re.IGNORECASE,
)
QUALIFIED_COLUMN_RE = re.compile(r"\b([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)\b")
JOIN_EQ_RE = re.compile(
    r"\b([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)\s*=\s*([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)\b",
    re.IGNORECASE,
)
INSERT_COLUMNS_RE = re.compile(
    r"^\s*insert\s+into\s+([A-Za-z_][\w$]*)\s*\((.*?)\)\s*(?:values|select)\b",
    re.IGNORECASE | re.DOTALL,
)
UPDATE_SET_RE = re.compile(r"^\s*update\s+([A-Za-z_][\w$]*)\s+set\s+(.*?)(?:\bwhere\b|$)", re.IGNORECASE | re.DOTALL)
SELECT_CLAUSE_RE = re.compile(r"\bselect\b(.*?)\bfrom\b", re.IGNORECASE | re.DOTALL)
LEADING_VERB_RE = re.compile(r"^\s*([A-Za-z]+)")
RESERVED_ALIASES = {
    "where",
    "on",
    "set",
    "values",
    "group",
    "order",
    "left",
    "right",
    "inner",
    "outer",
    "full",
    "cross",
    "union",
    "limit",
    "offset",
}
SQL_KEYWORDS = {
    "and",
    "as",
    "asc",
    "by",
    "case",
    "count",
    "desc",
    "distinct",
    "from",
    "group",
    "in",
    "is",
    "join",
    "like",
    "max",
    "min",
    "not",
    "null",
    "on",
    "or",
    "order",
    "select",
    "sum",
    "then",
    "when",
    "where",
}
MAX_COLUMNS_PER_TABLE = 40
MAX_RELATIONS_PER_TABLE = 8
PREFILL_HEARTBEAT_SECONDS = 1.0


@dataclass
class TableEvidence:
    operations: set[str]
    columns: set[str]
    relations: set[str]


@dataclass(frozen=True)
class PreparedSchemaInput:
    content: str
    guidance: str
    inferred: bool


@dataclass
class GenerationProgress:
    chunks: int = 0
    characters: int = 0
    started_at: float = 0.0
    last_render_at: float = 0.0
    prompt_tokens: int = 0


@dataclass(frozen=True)
class GemmaRuntimeConfig:
    model_path: str | None = None
    hf_repo: str = DEFAULT_GEMMA_REPO
    hf_filename: str = DEFAULT_GEMMA_FILENAME
    cache_dir: str | None = None
    n_ctx: int = 131072
    threads: int = max(1, os.cpu_count() or 1)
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9
    gpu_layers: int = 0


def build_sqlalchemy_prompt(schema_sql: str) -> str:
    prepared = prepare_schema_input(schema_sql)
    return USER_PROMPT_TEMPLATE.format(
        input_guidance=prepared.guidance,
        schema_input=prepared.content,
    )


def prepare_schema_input(schema_sql: str) -> PreparedSchemaInput:
    normalized = schema_sql.strip()
    if DDL_RE.search(normalized):
        return PreparedSchemaInput(
            content=normalized,
            guidance="The input contains direct schema DDL. Use it as the primary source of truth.",
            inferred=False,
        )
    return PreparedSchemaInput(
        content=infer_schema_summary(normalized),
        guidance=(
            "The input was inferred from non-DDL application queries. "
            "Treat listed tables, columns, and joins as evidence, and avoid inventing unsupported constraints or fields."
        ),
        inferred=True,
    )


def extract_python_source(response_text: str) -> str:
    stripped = response_text.strip()
    fenced_match = PYTHON_FENCE_RE.search(stripped)
    if fenced_match:
        stripped = fenced_match.group(1).strip()
    if stripped.lower().startswith("python\n"):
        stripped = stripped.split("\n", 1)[1]
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    return stripped


def generate_sqlalchemy_models(schema_sql: str, config: GemmaRuntimeConfig) -> str:
    if not schema_sql.strip():
        raise ValueError("No SQL schema content provided")

    _print_progress("[1/3] Resolving model path...")
    model_path = _resolve_model_path(config)
    _print_progress(f"[1/3] Using model: {model_path}")
    prompt = _format_gemma_prompt(SYSTEM_PROMPT, build_sqlalchemy_prompt(schema_sql))

    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise RuntimeError(
            "Model generation requires the optional 'modelgen' dependencies. "
            "Install them with: pip install -e '.[modelgen]'"
        ) from exc

    _print_progress(
        f"[2/3] Loading model with context {config.n_ctx} on CPU using {config.threads} thread(s)..."
    )
    llm = Llama(
        model_path=str(model_path),
        n_ctx=config.n_ctx,
        n_threads=config.threads,
        n_gpu_layers=config.gpu_layers,
        verbose=False,
    )
    prompt_tokens = _estimate_prompt_tokens(llm, prompt)
    _print_progress(
        f"[3/3a] Prompt prepared: {prompt_tokens} token(s) in, max {config.max_tokens} token(s) out."
    )
    _print_progress("[3/3b] Prefilling prompt and waiting for first output chunk...")
    try:
        response = llm.create_completion(
            prompt=prompt,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            top_p=config.top_p,
            stop=["<turn|>", "<|turn>user", "<|turn>system"],
            stream=True,
        )
    except ValueError as exc:
        if "exceed context window" not in str(exc):
            raise
        raise ValueError(
            "The SQL schema is still larger than the configured model context window. "
            "Increase --context-size or split the input schema into smaller files."
        ) from exc
    output = extract_python_source(_consume_streamed_response(response, prompt_tokens=prompt_tokens))
    if not output.strip():
        raise RuntimeError("The model returned an empty response")
    _print_progress(f"[done] Generated {len(output)} characters of Python output.")
    return output


def infer_schema_summary(schema_sql: str) -> str:
    statements = [statement for statement in _split_sql_statements(schema_sql) if statement]
    tables: dict[str, TableEvidence] = defaultdict(
        lambda: TableEvidence(operations=set(), columns=set(), relations=set())
    )

    for statement in statements:
        verb = _leading_verb(statement)
        alias_map = _extract_table_aliases(statement)
        table_names = sorted(set(alias_map.values()))
        for table in table_names:
            tables[table].operations.add(verb)

        for alias, column in QUALIFIED_COLUMN_RE.findall(statement):
            table = alias_map.get(alias)
            if table:
                tables[table].columns.add(column)

        insert_match = INSERT_COLUMNS_RE.search(statement)
        if insert_match:
            table = insert_match.group(1)
            tables[table].operations.add("insert")
            tables[table].columns.update(_split_identifier_list(insert_match.group(2)))

        update_match = UPDATE_SET_RE.search(statement)
        if update_match:
            table = update_match.group(1)
            tables[table].operations.add("update")
            tables[table].columns.update(_extract_assignment_columns(update_match.group(2)))

        select_match = SELECT_CLAUSE_RE.search(statement)
        if select_match and len(table_names) == 1:
            tables[table_names[0]].columns.update(_extract_unqualified_select_columns(select_match.group(1)))

        for alias_left, column_left, alias_right, column_right in JOIN_EQ_RE.findall(statement):
            left_table = alias_map.get(alias_left)
            right_table = alias_map.get(alias_right)
            if not left_table or not right_table or left_table == right_table:
                continue
            relation = f"{left_table}.{column_left} = {right_table}.{column_right}"
            tables[left_table].relations.add(relation)
            tables[right_table].relations.add(relation)

    if not tables:
        return "No table or column evidence could be inferred from the SQL input."

    lines = [
        "Input type: inferred schema summary from application SQL queries.",
        f"Statements analyzed: {len(statements)}",
        f"Tables inferred: {len(tables)}",
    ]
    for table_name in sorted(tables):
        evidence = tables[table_name]
        operations = ", ".join(sorted(evidence.operations)) or "unknown"
        columns = sorted(evidence.columns)
        relations = sorted(evidence.relations)
        lines.append("")
        lines.append(f"TABLE {table_name}")
        lines.append(f"- operations observed: {operations}")
        if columns:
            visible_columns = columns[:MAX_COLUMNS_PER_TABLE]
            suffix = ""
            if len(columns) > MAX_COLUMNS_PER_TABLE:
                suffix = f", ... (+{len(columns) - MAX_COLUMNS_PER_TABLE} more)"
            lines.append(f"- columns observed ({len(columns)}): {', '.join(visible_columns)}{suffix}")
        else:
            lines.append("- columns observed: none")
        if relations:
            visible_relations = relations[:MAX_RELATIONS_PER_TABLE]
            suffix = ""
            if len(relations) > MAX_RELATIONS_PER_TABLE:
                suffix = f", ... (+{len(relations) - MAX_RELATIONS_PER_TABLE} more)"
            lines.append(f"- relation evidence ({len(relations)}): {'; '.join(visible_relations)}{suffix}")

    return "\n".join(lines)


def _resolve_model_path(config: GemmaRuntimeConfig) -> Path:
    if config.model_path:
        path = Path(config.model_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")
        return path

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            "Automatic model download requires the optional 'modelgen' dependencies. "
            "Install them with: pip install -e '.[modelgen]'"
        ) from exc

    downloaded = hf_hub_download(
        repo_id=config.hf_repo,
        filename=config.hf_filename,
        cache_dir=config.cache_dir,
    )
    return Path(downloaded)


def _format_gemma_prompt(system_prompt: str, user_prompt: str) -> str:
    return (
        "<|turn>system\n"
        f"{system_prompt.strip()}<turn|>\n"
        "<|turn>user\n"
        f"{user_prompt.strip()}<turn|>\n"
        "<|turn>model\n"
    )


def _consume_streamed_response(chunks: object, *, prompt_tokens: int = 0) -> str:
    progress = GenerationProgress(started_at=time.monotonic(), prompt_tokens=prompt_tokens)
    first_chunk_seen = threading.Event()
    finished = threading.Event()
    heartbeat = threading.Thread(
        target=_prefill_heartbeat,
        args=(progress, first_chunk_seen, finished),
        daemon=True,
    )
    heartbeat.start()
    parts: list[str] = []
    try:
        for chunk in chunks:
            text = chunk["choices"][0].get("text", "")
            if not text:
                continue
            first_chunk_seen.set()
            parts.append(text)
            progress.chunks += 1
            progress.characters += len(text)
            _render_generation_progress(progress)
    finally:
        finished.set()
        first_chunk_seen.set()
        heartbeat.join(timeout=0.2)
    _finish_generation_progress(progress)
    return "".join(parts)


_CONTINUATION_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "in", "on", "join", "inner",
    "left", "right", "full", "outer", "cross", "using", "set", "values",
    "group", "order", "by", "having", "union", "intersect", "except", "as",
}

_CONTINUATION_TAIL_CHARS = {",", "(", ".", "+", "-", "*", "/", "%", "=", "<", ">"}


def _split_sql_statements(schema_sql: str) -> list[str]:
    statements: list[str] = []
    for segment in schema_sql.split(";"):
        statements.extend(_split_segment_on_blank_lines(segment))
    return statements


def _split_segment_on_blank_lines(segment: str) -> list[str]:
    fragments = [part.strip() for part in re.split(r"\n\s*\n+", segment) if part.strip()]
    merged: list[str] = []
    for fragment in fragments:
        if merged and _continues_previous_statement(merged[-1]):
            merged[-1] = f"{merged[-1]}\n{fragment}"
            continue
        merged.append(fragment)
    return merged


def _continues_previous_statement(statement: str) -> bool:
    stripped = statement.rstrip()
    if not stripped:
        return False
    if stripped.count("(") > stripped.count(")"):
        return True
    if stripped[-1] in _CONTINUATION_TAIL_CHARS:
        return True
    words = re.findall(r"[a-z_][a-z0-9_]*", stripped.lower())
    return bool(words) and words[-1] in _CONTINUATION_KEYWORDS


def _leading_verb(statement: str) -> str:
    match = LEADING_VERB_RE.match(statement)
    return match.group(1).lower() if match else "unknown"


def _extract_table_aliases(statement: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for table, alias in TABLE_REF_RE.findall(statement):
        normalized_table = _normalize_identifier(table)
        alias_map[normalized_table] = normalized_table
        normalized_alias = _normalize_identifier(alias)
        if normalized_alias and normalized_alias.lower() not in RESERVED_ALIASES:
            alias_map[normalized_alias] = normalized_table
    return alias_map


def _extract_assignment_columns(set_clause: str) -> set[str]:
    columns: set[str] = set()
    for part in _split_csv(set_clause):
        if "=" not in part:
            continue
        left_side = part.split("=", 1)[0].strip()
        if "." in left_side:
            left_side = left_side.split(".", 1)[1]
        identifier = _normalize_identifier(left_side)
        if identifier:
            columns.add(identifier)
    return columns


def _extract_unqualified_select_columns(select_clause: str) -> set[str]:
    columns: set[str] = set()
    for part in _split_csv(select_clause):
        candidate = part.strip()
        if not candidate or "." in candidate or "(" in candidate or ")" in candidate or candidate == "*":
            continue
        candidate = re.split(r"\s+as\s+|\s+", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
        identifier = _normalize_identifier(candidate)
        if not identifier or identifier.lower() in SQL_KEYWORDS:
            continue
        columns.add(identifier)
    return columns


def _split_identifier_list(text: str) -> set[str]:
    return {identifier for identifier in (_normalize_identifier(part) for part in _split_csv(text)) if identifier}


def _split_csv(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")" and depth > 0:
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _normalize_identifier(identifier: str) -> str:
    cleaned = identifier.strip().strip(",;")
    if not cleaned:
        return ""
    if cleaned[0] in "\"'`[":
        cleaned = cleaned[1:]
    if cleaned and cleaned[-1] in "\"'`]":
        cleaned = cleaned[:-1]
    return cleaned


def _render_generation_progress(progress: GenerationProgress) -> None:
    now = time.monotonic()
    if progress.last_render_at and now - progress.last_render_at < 0.5:
        return
    elapsed = max(now - progress.started_at, 0.001)
    chars_per_second = progress.characters / elapsed
    _print_progress(
        "\r"
        f"[3/3c] Decoding output... {progress.chunks} chunk(s), "
        f"{progress.characters} chars, {chars_per_second:.0f} chars/s",
        end="",
    )
    progress.last_render_at = now


def _finish_generation_progress(progress: GenerationProgress) -> None:
    if progress.chunks:
        _render_generation_progress(progress)
    _print_progress("")


def _print_progress(message: str, *, end: str = "\n") -> None:
    print(message, file=sys.stderr, end=end, flush=True)


def _prefill_heartbeat(
    progress: GenerationProgress,
    first_chunk_seen: threading.Event,
    finished: threading.Event,
) -> None:
    while not first_chunk_seen.wait(timeout=PREFILL_HEARTBEAT_SECONDS):
        if finished.is_set():
            return
        elapsed = max(time.monotonic() - progress.started_at, 0.0)
        _print_progress(
            f"[3/3b] Prefilling prompt... {elapsed:.1f}s elapsed, {progress.prompt_tokens} prompt token(s)."
        )


def _estimate_prompt_tokens(llm: object, prompt: str) -> int:
    encoded = prompt.encode("utf-8")
    tokenize = getattr(llm, "tokenize", None)
    if tokenize is None:
        return 0
    for kwargs in ({"add_bos": False, "special": True}, {"add_bos": False}, {}):
        try:
            return len(tokenize(encoded, **kwargs))
        except TypeError:
            continue
    return 0
