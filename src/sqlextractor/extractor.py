from __future__ import annotations

from bisect import bisect_right
import re

from .models import StringToken

CONCATENATION_GAP_RE = re.compile(r"^\s*(?:\+|\.{1,2})\s*$", re.DOTALL)


def extract_string_tokens(text: str, file_path: str) -> list[StringToken]:
    line_starts = _line_starts(text)
    tokens: list[StringToken] = []
    index = 0
    length = len(text)

    while index < length:
        if text.startswith('@"', index):
            token, index = _parse_verbatim_string(text, file_path, line_starts, index)
            tokens.append(token)
            continue

        if text[index] in {"'", '"', "`"}:
            token, index = _parse_quoted_string(text, file_path, line_starts, index)
            tokens.append(token)
            continue

        index += 1

    return merge_concatenated_tokens(text, tokens)


def merge_concatenated_tokens(text: str, tokens: list[StringToken]) -> list[StringToken]:
    if not tokens:
        return []

    merged: list[StringToken] = []
    current = tokens[0]

    for token in tokens[1:]:
        gap = text[current.end_index:token.start_index]
        if CONCATENATION_GAP_RE.fullmatch(gap or ""):
            current = StringToken(
                file_path=current.file_path,
                start_line=current.start_line,
                end_line=token.end_line,
                value=current.value + token.value,
                start_index=current.start_index,
                end_index=token.end_index,
            )
            continue

        merged.append(current)
        current = token

    merged.append(current)
    return merged


def _parse_verbatim_string(
    text: str,
    file_path: str,
    line_starts: list[int],
    start_index: int,
) -> tuple[StringToken, int]:
    index = start_index + 2
    parts: list[str] = []
    length = len(text)

    while index < length:
        if text.startswith('""', index):
            parts.append('"')
            index += 2
            continue
        if text[index] == '"':
            end_index = index + 1
            return _build_token(
                file_path=file_path,
                line_starts=line_starts,
                start_index=start_index,
                end_index=end_index,
                value="".join(parts),
            ), end_index
        parts.append(text[index])
        index += 1

    return _build_token(
        file_path=file_path,
        line_starts=line_starts,
        start_index=start_index,
        end_index=length,
        value="".join(parts),
    ), length


def _parse_quoted_string(
    text: str,
    file_path: str,
    line_starts: list[int],
    start_index: int,
) -> tuple[StringToken, int]:
    quote = text[start_index]
    triple = quote in {"'", '"'} and text.startswith(quote * 3, start_index)
    delimiter_length = 3 if triple else 1
    index = start_index + delimiter_length
    parts: list[str] = []
    length = len(text)

    while index < length:
        if not triple and text[index] == "\\" and index + 1 < length:
            parts.append(_decode_escape(text[index + 1]))
            index += 2
            continue
        if triple and text[index] == "\\" and index + 1 < length:
            parts.append(_decode_escape(text[index + 1]))
            index += 2
            continue
        if triple and text.startswith(quote * 3, index):
            end_index = index + 3
            return _build_token(
                file_path=file_path,
                line_starts=line_starts,
                start_index=start_index,
                end_index=end_index,
                value="".join(parts),
            ), end_index
        if not triple and text[index] == quote:
            end_index = index + 1
            return _build_token(
                file_path=file_path,
                line_starts=line_starts,
                start_index=start_index,
                end_index=end_index,
                value="".join(parts),
            ), end_index
        parts.append(text[index])
        index += 1

    return _build_token(
        file_path=file_path,
        line_starts=line_starts,
        start_index=start_index,
        end_index=length,
        value="".join(parts),
    ), length


def _build_token(
    file_path: str,
    line_starts: list[int],
    start_index: int,
    end_index: int,
    value: str,
) -> StringToken:
    return StringToken(
        file_path=file_path,
        start_line=_line_number(line_starts, start_index),
        end_line=_line_number(line_starts, max(start_index, end_index - 1)),
        value=value,
        start_index=start_index,
        end_index=end_index,
    )


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer(r"\n", text))
    return starts


def _line_number(line_starts: list[int], index: int) -> int:
    return bisect_right(line_starts, index)


def _decode_escape(character: str) -> str:
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "0": "\0",
        "`": "`",
    }
    return escapes.get(character, character)
