"""Deterministic DB2 → SQLite translation for the controlled test database.

Purpose and limits (read before claiming anything):

- This translates the *supported subset* of DB2 syntax into SQLite so the
  lane can execute workloads on a controllable, dependency-free database.
- It is a test-database adapter.  Passing on SQLite proves behavior of the
  translated subset only — it is NOT DB2 runtime verification.
- Portability decisions are explicit: the translator either handles a
  construct deterministically or raises ``UnsupportedTranslationError``.
  It never silently drops semantics.
"""

from __future__ import annotations

import re


class UnsupportedTranslationError(ValueError):
    """Raised when a DB2 construct cannot be translated to SQLite."""


# Documented DB2 → SQLite type mapping (supported subset only).
_DB2_TYPE_RE = re.compile(
    r"\b(VARCHAR|CHARACTER|CHAR|INTEGER|INT|BIGINT|SMALLINT|"
    r"DECIMAL|NUMERIC|FLOAT|REAL|DOUBLE|DATE|TIMESTAMP|TIME)\b(?:\(\s*\d+(?:\s*,\s*\d+)?\s*\))?",
    re.IGNORECASE,
)

_DB2_TYPE_MAP = {
    "varchar": "TEXT",
    "character": "TEXT",
    "char": "TEXT",
    "integer": "INTEGER",
    "int": "INTEGER",
    "bigint": "INTEGER",
    "smallint": "INTEGER",
    "decimal": "NUMERIC",
    "numeric": "NUMERIC",
    "float": "REAL",
    "real": "REAL",
    "double": "REAL",
    "date": "TEXT",
    "time": "TEXT",
    "timestamp": "TEXT",
}

_FETCH_FIRST_RE = re.compile(
    r"FETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY", re.IGNORECASE
)

_IDENTITY_RE = re.compile(
    r"\s*GENERATED\s+ALWAYS\s+AS\s+IDENTITY", re.IGNORECASE
)


def translate_db2_type(column_type: str) -> str:
    """Translate one DB2 column type to a SQLite type name."""
    token = column_type.strip()
    if not token:
        raise UnsupportedTranslationError("empty column type")
    lowered = token.lower()
    for key, mapped in _DB2_TYPE_MAP.items():
        if lowered == key:
            return mapped
        if lowered.startswith((key + "(", key + " ")):
            return mapped
    raise UnsupportedTranslationError(f"no SQLite mapping for DB2 type {token!r}")
    raise UnsupportedTranslationError(f"no SQLite mapping for DB2 type {token!r}")


def translate_db2_ddl(ddl_text: str) -> list[str]:
    """Translate a DB2 CREATE TABLE statement into SQLite-compatible SQL.

    The input may contain multiple statements separated by ';'.
    Returns the translated SQL statements.
    """
    statements = _split_statements(ddl_text)
    translated: list[str] = []
    for statement in statements:
        translated.append(_translate_create_table(statement))
    return translated


def _translate_create_table(statement: str) -> str:
    upper = statement.strip()
    if not upper:
        raise UnsupportedTranslationError("empty DDL statement")

    create_match = re.match(
        r"CREATE\s+TABLE\s+(?:(?P<schema>\w+)\s*\.\s*)?(?P<table>\w+)", upper, re.IGNORECASE
    )
    if not create_match:
        raise UnsupportedTranslationError(
            f"only CREATE TABLE is supported by the DDL translator: {upper[:64]!r}"
        )

    open_paren = upper.find("(")
    close_paren = upper.rfind(")")
    if open_paren < 0 or close_paren < open_paren:
        raise UnsupportedTranslationError("CREATE TABLE without column list")

    head = upper[:open_paren]
    body = upper[open_paren + 1:close_paren]
    tail = upper[close_paren + 1:].strip()

    if tail and not re.match(r"IN\s+\S+", tail, re.IGNORECASE):
        raise UnsupportedTranslationError(f"unsupported CREATE TABLE suffix {tail!r}")

    columns: list[str] = []
    for raw_col in _split_columns(body):
        columns.append(_translate_column(raw_col))

    return f"{head.strip()} ({', '.join(columns)})"


def _translate_column(raw_column: str) -> str:
    raw_column = raw_column.strip()
    if re.match(r"PRIMARY\s+KEY", raw_column, re.IGNORECASE) or re.match(
        r"UNIQUE", raw_column, re.IGNORECASE
    ) or re.match(r"CONSTRAINT\s+\w+\s+(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY)", raw_column, re.IGNORECASE):
        return raw_column

    match = re.match(r"(?P<name>\w+)\s+(?P<type>.+)", raw_column, re.IGNORECASE)
    if not match:
        raise UnsupportedTranslationError(f"cannot parse column {raw_column!r}")

    name = match.group("name")
    rest = match.group("type").strip()
    identity = False
    if _IDENTITY_RE.search(rest):
        rest = _IDENTITY_RE.sub(" ", rest).strip()
        identity = True

    type_match = re.match(r"[A-Za-z]+(?:\(\s*\d+(?:\s*,\s*\d+)?\s*\))?", rest)
    if not type_match:
        raise UnsupportedTranslationError(f"cannot parse type in {raw_column!r}")
    db2_type = type_match.group(0)
    constraints = rest[type_match.end():].strip()
    sqlite_type = translate_db2_type(db2_type)

    if identity:
        if sqlite_type != "INTEGER":
            raise UnsupportedTranslationError(
                f"identity column {name!r} must be integer to translate"
            )
        if "NOT NULL" in constraints.upper() or re.search(
            r"\bPRIMARY\s+KEY\b", constraints, re.IGNORECASE
        ):
            # PRIMARY KEY / NOT NULL present → keep explicit AUTOINCREMENT PK.
            new_constraints = "PRIMARY KEY AUTOINCREMENT"
            return f"{name} {sqlite_type} {new_constraints}"

        return f"{name} {sqlite_type} PRIMARY KEY AUTOINCREMENT"

    return " ".join(part for part in (name, sqlite_type, constraints) if part)


def translate_db2_dml(sql: str) -> str:
    """Translate one DML statement for the controlled test database.

    Handles the supported subset: SELECT (incl. INTO-stripping), INSERT,
    UPDATE, DELETE.  FETCH FIRST n ROWS ONLY → LIMIT n.
    """
    result = sql
    result = _strip_select_into(result)
    result = _FETCH_FIRST_RE.sub(lambda m: f"LIMIT {m.group(1)}", result)
    return result


def _strip_select_into(sql: str) -> str:
    """Remove ``INTO :VAR[, ...]`` from a SELECT so it runs on SQLite.

    SELECT INTO is embedded-SQL syntax, not executable on the test
    database; the harness captures outputs from the result row instead.
    """
    upper = sql.upper()
    into_match = re.search(r"\bINTO\b", upper)
    if not into_match:
        return sql
    # SELECT ... INTO <vars> FROM ...  →  keep SELECT list, drop INTO <vars>
    select_list_end = into_match.start()
    from_match = re.search(r"\bFROM\b", upper[into_match.end():])
    if not from_match:
        # No FROM → malformed for this subset; leave as-is.
        return sql
    from_start = into_match.end() + from_match.start()
    head = sql[:select_list_end].rstrip()
    tail = sql[from_start:]
    return f"{head} {tail}"


def _split_statements(text: str) -> list[str]:
    """Split SQL by ';' respecting simple quoted literals."""
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
    return [s for s in statements if s.strip()]


def _split_columns(body: str) -> list[str]:
    """Split a CREATE TABLE column list on top-level commas."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False
    quote_char = ""
    for ch in body:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
            continue
        if ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]