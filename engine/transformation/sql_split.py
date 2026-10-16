"""Quote-aware SQL statement splitting shared by the SQL parser and DB2 lanes."""

from __future__ import annotations


def split_sql_statements(text: str) -> list[str]:
    """Split SQL by top-level ``;``, respecting quoted string literals."""
    statements: list[str] = []
    current: list[str] = []
    in_quote = False
    quote_char = ""
    for ch in text:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
            continue
        if ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == ";":
            statements.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        statements.append("".join(current))
    return statements
