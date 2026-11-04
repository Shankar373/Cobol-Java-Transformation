"""Data migration and reconciliation: fixed-width COBOL records into a PostgreSQL table, proven equal.

Scope, stated so no caller over-reads it:

* **Record layout** -- the elementary items of one record (a level-01 group) whose usage is DISPLAY:
  ``PIC X(n)`` becomes ``CHAR(n)`` (the padding is data and is kept) and unsigned ``PIC 9(i)V9(s)``
  becomes ``NUMERIC(i+s, s)``.  Signed DISPLAY numerics (overpunched sign), packed ``COMP-3`` and
  binary items, ``REDEFINES``, ``OCCURS`` and nested groups are *refused by name* (``MigrationError``):
  their byte encoding is not certified, and a migration that guessed would silently change data.
* **Records** -- one text line per record, exactly the layout's width.
* **Reconciliation** -- source rows (decoded) against target rows (read back from the database):
  counts, missing / extra / duplicate keys, every differing column, exact decimal column totals, and a
  SHA-256 over the canonical rows in key order.  ``ok`` is true only when nothing differs; a report never
  rounds, ignores padding, or treats a missing row as a pass.

Evidence level: the logic is unit-tested hermetically and exercised against PostgreSQL 14 in the
``ocesql-pg`` image (``tests/integration/test_migration_postgres.py``).  Nothing here reads DB2, VSAM
or EBCDIC data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from engine.sql.database_dialect import DatabaseDialect, SqlType, dialect_for

FIELD_SEPARATOR = "\x1f"
NULL_TEXT = "<NULL>"

_RESERVED = frozenset({
    "all", "and", "any", "as", "asc", "check", "column", "constraint", "create", "default", "desc",
    "distinct", "end", "from", "group", "having", "in", "index", "into", "is", "key", "limit", "not",
    "null", "offset", "on", "or", "order", "primary", "references", "select", "table", "to", "union",
    "unique", "user", "using", "values", "when", "where", "with",
})


class MigrationError(ValueError):
    """A layout, record or name the migration refuses rather than guesses."""


@dataclass(frozen=True)
class Column:
    name: str  # SQL column name
    cobol_name: str
    kind: str  # CHAR | NUMERIC
    offset: int
    width: int
    scale: int
    sql_type: SqlType


def sql_name(cobol_name: str) -> str:
    name = cobol_name.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise MigrationError(f"{cobol_name!r} is not a plain identifier")
    if name in _RESERVED:
        raise MigrationError(f"{cobol_name!r} is a reserved SQL word; rename the column explicitly")
    return name


def columns_from_record(record) -> tuple[Column, ...]:
    """Columns for the elementary items of a record group (or a tuple of elementary items)."""
    items = tuple(record.children) if hasattr(record, "children") and record.children else tuple(record)
    if not items:
        raise MigrationError("the record has no items")
    columns: list[Column] = []
    offset = 0
    seen: set[str] = set()
    for item in items:
        reasons = []
        if item.children:
            reasons.append("nested group")
        if item.occurs:
            reasons.append("OCCURS")
        if item.redefines:
            reasons.append("REDEFINES")
        if (item.usage or "").upper() not in ("", "DISPLAY"):
            reasons.append(f"USAGE {item.usage}")
        if item.signed:
            reasons.append("signed DISPLAY (overpunched sign)")
        if item.pic_length <= 0:
            reasons.append("no PIC")
        if reasons:
            raise MigrationError(f"{item.name}: {', '.join(reasons)} is not certified for migration")
        name = sql_name(item.name)
        if name in seen:
            raise MigrationError(f"duplicate column {name}")
        seen.add(name)
        if item.is_numeric:
            if item.pic_length > 31:
                raise MigrationError(f"{item.name}: more than 31 digits")
            kind, scale = "NUMERIC", item.decimal_places
            sql_type = SqlType("DECIMAL", precision=item.pic_length, scale=scale)
        else:
            kind, scale = "CHAR", 0
            sql_type = SqlType("CHAR", length=item.pic_length)
        columns.append(Column(name, item.name, kind, offset, item.pic_length, scale, sql_type))
        offset += item.pic_length
    return tuple(columns)


def record_width(columns: tuple[Column, ...]) -> int:
    return sum(c.width for c in columns)


def create_table_sql(
    table: str, columns: tuple[Column, ...], key: tuple[str, ...] = (),
    dialect: DatabaseDialect | None = None,
) -> str:
    dialect = dialect or dialect_for("postgresql")
    names = {c.name for c in columns}
    if any(k not in names for k in key):
        raise MigrationError(f"key {key} names a column that is not in the layout")
    parts = [f"{c.name} {dialect.column_type(c.sql_type)} NOT NULL" for c in columns]
    if key:
        parts.append(f"PRIMARY KEY ({', '.join(key)})")
    return f"CREATE TABLE {sql_name(table)} ({', '.join(parts)});"


def decode_records(text: str, columns: tuple[Column, ...]) -> list[tuple]:
    """Rows from fixed-width text records: ``str`` for CHAR (padding kept), ``Decimal`` for NUMERIC."""
    width = record_width(columns)
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) != width:
            raise MigrationError(f"record {number} is {len(line)} characters, the layout is {width}")
        values: list = []
        for c in columns:
            chunk = line[c.offset:c.offset + c.width]
            if c.kind == "CHAR":
                values.append(chunk)
                continue
            if not chunk.isdigit():
                raise MigrationError(f"record {number} column {c.name}: {chunk!r} is not unsigned digits")
            values.append(Decimal(chunk).scaleb(-c.scale))
        rows.append(tuple(values))
    return rows


def _literal(column: Column, value) -> str:
    if column.kind == "CHAR":
        return "'" + value.replace("'", "''") + "'"
    return format(value.quantize(Decimal(1).scaleb(-column.scale)), "f")


def load_sql(table: str, rows: list[tuple], columns: tuple[Column, ...]) -> str:
    names = ", ".join(c.name for c in columns)
    statements = []
    for row in rows:
        values = ", ".join(_literal(c, v) for c, v in zip(columns, row))
        statements.append(f"INSERT INTO {sql_name(table)} ({names}) VALUES ({values});")
    return "\n".join(statements)


def dump_query(table: str, columns: tuple[Column, ...], key: tuple[str, ...]) -> str:
    """Query returning every column as text, NULLs spelled out, in key order."""
    # CHAR(n) -> text drops trailing spaces in PostgreSQL; rpad restores the width a host variable
    # receives (trailing spaces of a CHAR(n) are not significant to the database).
    selected = ", ".join(
        f"coalesce(rpad({c.name}::text, {c.width}), '{NULL_TEXT}')" if c.kind == "CHAR"
        else f"coalesce({c.name}::text, '{NULL_TEXT}')"
        for c in columns)
    order = ", ".join(key or tuple(c.name for c in columns))
    return f"SELECT {selected} FROM {sql_name(table)} ORDER BY {order};"


def parse_dump(lines: list[str], columns: tuple[Column, ...]) -> list[tuple]:
    """Rows from ``dump_query`` output (fields separated by ``FIELD_SEPARATOR``)."""
    rows = []
    for line in lines:
        parts = line.split(FIELD_SEPARATOR)
        if len(parts) != len(columns):
            raise MigrationError(f"dump row has {len(parts)} fields, the layout has {len(columns)}")
        values: list = []
        for c, text in zip(columns, parts):
            if text == NULL_TEXT:
                values.append(None)
            elif c.kind == "CHAR":
                values.append(text)
            else:
                try:
                    values.append(Decimal(text))
                except InvalidOperation as error:
                    raise MigrationError(f"column {c.name}: {text!r} is not a number") from error
        rows.append(tuple(values))
    return rows


def canonical(columns: tuple[Column, ...], row: tuple) -> str:
    """Deterministic text of a row: scale-exact numbers, padded characters, NULL spelled out."""
    out = []
    for c, value in zip(columns, row):
        if value is None:
            out.append(NULL_TEXT)
        elif c.kind == "CHAR":
            out.append(value)
        else:
            out.append(format(value.quantize(Decimal(1).scaleb(-c.scale)), "f"))
    return FIELD_SEPARATOR.join(out)


@dataclass(frozen=True)
class Mismatch:
    key: tuple
    column: str
    source: str
    target: str


@dataclass(frozen=True)
class ReconciliationReport:
    source_count: int
    target_count: int
    missing_in_target: tuple = ()
    extra_in_target: tuple = ()
    duplicate_source_keys: tuple = ()
    duplicate_target_keys: tuple = ()
    mismatches: tuple[Mismatch, ...] = ()
    source_totals: dict = field(default_factory=dict)
    target_totals: dict = field(default_factory=dict)
    source_digest: str = ""
    target_digest: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.source_count == self.target_count
            and not self.missing_in_target and not self.extra_in_target
            and not self.duplicate_source_keys and not self.duplicate_target_keys
            and not self.mismatches
            and self.source_totals == self.target_totals
            and self.source_digest == self.target_digest
        )


def _index(rows: list[tuple], key_positions: list[int]):
    indexed: dict[tuple, tuple] = {}
    duplicates: list[tuple] = []
    for row in rows:
        key = tuple(row[i] for i in key_positions)
        if key in indexed:
            duplicates.append(key)
        indexed[key] = row
    return indexed, tuple(duplicates)


def _totals(columns: tuple[Column, ...], rows: list[tuple]) -> dict:
    totals: dict[str, Decimal] = {}
    for i, c in enumerate(columns):
        if c.kind == "NUMERIC":
            totals[c.name] = sum((r[i] for r in rows if r[i] is not None), Decimal(0)).quantize(
                Decimal(1).scaleb(-c.scale))
    return totals


def _digest(columns: tuple[Column, ...], rows: list[tuple], key_positions: list[int]) -> str:
    ordered = sorted(rows, key=lambda r: tuple(str(r[i]) for i in key_positions))
    h = hashlib.sha256()
    for row in ordered:
        h.update(canonical(columns, row).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def reconcile(
    source_rows: list[tuple], target_rows: list[tuple], columns: tuple[Column, ...],
    key: tuple[str, ...],
) -> ReconciliationReport:
    """Compare decoded source rows with rows read back from the target; see the module docstring."""
    names = [c.name for c in columns]
    if not key or any(k not in names for k in key):
        raise MigrationError("reconciliation needs a key made of layout columns")
    positions = [names.index(k) for k in key]
    source, source_dups = _index(source_rows, positions)
    target, target_dups = _index(target_rows, positions)
    mismatches: list[Mismatch] = []
    for k in sorted(set(source) & set(target), key=lambda t: tuple(map(str, t))):
        for c, left, right in zip(columns, source[k], target[k]):
            a = canonical((c,), (left,))
            b = canonical((c,), (right,))
            if a != b:
                mismatches.append(Mismatch(k, c.name, a, b))
    return ReconciliationReport(
        source_count=len(source_rows),
        target_count=len(target_rows),
        missing_in_target=tuple(sorted(set(source) - set(target), key=lambda t: tuple(map(str, t)))),
        extra_in_target=tuple(sorted(set(target) - set(source), key=lambda t: tuple(map(str, t)))),
        duplicate_source_keys=source_dups,
        duplicate_target_keys=target_dups,
        mismatches=tuple(mismatches),
        source_totals=_totals(columns, source_rows),
        target_totals=_totals(columns, target_rows),
        source_digest=_digest(columns, source_rows, positions),
        target_digest=_digest(columns, target_rows, positions),
    )
