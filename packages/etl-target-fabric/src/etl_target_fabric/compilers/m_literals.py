"""Power Query M text literals shared by Microsoft Fabric compilers.

ASCII identifiers stay byte-identical with a JSON string. Characters that JSON
encodes differently — quotes, hashes, and line breaks — use M rules instead.
"""

from __future__ import annotations


def m_string(value: str) -> str:
    """Return one Power Query text literal. ``#`` is escaped before other replacements."""
    escaped = (
        value.replace("#", "#(#)")
        .replace('"', '""')
        .replace("\r", "#(cr)")
        .replace("\n", "#(lf)")
    )
    return f'"{escaped}"'


def m_text_is_well_formed(code: str) -> bool:
    """Return whether M text literals and comments are closed.

    ``#table`` and other ``#`` keywords outside a string are valid and are not
    treated as errors. A raw control character or an unclosed quote is not.
    """
    index = 0
    length = len(code)
    while index < length:
        character = code[index]
        if character == "/" and index + 1 < length and code[index + 1] == "/":
            newline = code.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if character == "/" and index + 1 < length and code[index + 1] == "*":
            end = code.find("*/", index + 2)
            if end < 0:
                return False
            index = end + 2
            continue
        if character != '"':
            index += 1
            continue
        closed = _close_m_string(code, index + 1)
        if closed is None:
            return False
        index = closed
    return True


def _close_m_string(code: str, index: int) -> int | None:
    length = len(code)
    while index < length:
        character = code[index]
        if character < " " or character in "\r\n":
            return None
        if character == '"':
            if index + 1 < length and code[index + 1] == '"':
                index += 2
                continue
            return index + 1
        if character == "#" and index + 1 < length and code[index + 1] == "(":
            end = code.find(")", index + 2)
            if end < 0 or any(code[cursor] < " " for cursor in range(index + 2, end)):
                return None
            index = end + 1
            continue
        index += 1
    return None
