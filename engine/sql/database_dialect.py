"""Pluggable database dialects: DB2 (the source), PostgreSQL (the first target).

A ``DatabaseDialect`` answers four questions about a target database, deterministically and
without a database connection:

* **types** -- which column type holds a DB2 / COBOL-declared value exactly
  (``DECIMAL(p,s)`` stays ``NUMERIC(p,s)`` and ``java.math.BigDecimal``, never a double);
* **rewriting** -- how DB2-specific SQL text is spelled for the target, with host variables
  turned into positional JDBC markers and their bind order returned;
* **status** -- how the target's SQLSTATE maps to the SQLCODE a COBOL program tests;
* **refusals** -- every construct without a faithful translation is reported as a blocking
  ``issue`` so the caller fails closed instead of running different SQL.

Evidence level: the rewrite rules and the SQLSTATE -> SQLCODE table follow the vendors'
documented behaviour and are unit-tested table-driven.  They are *not* proven against a running
DB2 or PostgreSQL here: the PostgreSQL differential (OCESQL oracle, same seeded database,
DB-state hash) is roadmap unit 12, and no real DB2 is available.  A dialect therefore never
reports a ``verified`` property.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.sql.status import Db2SqlStatus

# --------------------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SqlType:
    """A DB2-side column type: ``name`` plus the size arguments that matter for exactness."""

    name: str  # SMALLINT INTEGER BIGINT DECIMAL CHAR VARCHAR DATE TIME TIMESTAMP DOUBLE REAL CLOB BLOB
    length: int | None = None
    precision: int | None = None
    scale: int | None = None

    def __str__(self) -> str:
        if self.precision is not None:
            return f"{self.name}({self.precision},{self.scale or 0})"
        if self.length is not None:
            return f"{self.name}({self.length})"
        return self.name


_TYPE_RE = re.compile(r"^\s*([A-Za-z ]+?)\s*(?:\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?\s*$")
_ALIASES = {
    "INT": "INTEGER", "DEC": "DECIMAL", "NUMERIC": "DECIMAL", "NUM": "DECIMAL",
    "CHARACTER": "CHAR", "CHARACTER VARYING": "VARCHAR", "CHAR VARYING": "VARCHAR",
    "DOUBLE PRECISION": "DOUBLE", "FLOAT": "DOUBLE",
}
_KNOWN = {"SMALLINT", "INTEGER", "BIGINT", "DECIMAL", "CHAR", "VARCHAR", "DATE", "TIME",
          "TIMESTAMP", "DOUBLE", "REAL", "CLOB", "BLOB"}


def parse_db2_type(text: str) -> SqlType:
    """Parse a DB2 type spelling; raises ``ValueError`` for a type outside the mapped set."""
    match = _TYPE_RE.match(text or "")
    if not match:
        raise ValueError(f"unparseable SQL type {text!r}")
    name = " ".join(match.group(1).upper().split())
    name = _ALIASES.get(name, name)
    if name not in _KNOWN:
        raise ValueError(f"SQL type {name} has no certified mapping")
    first = int(match.group(2)) if match.group(2) else None
    second = int(match.group(3)) if match.group(3) else None
    if name == "DECIMAL":
        if first is None:
            first, second = 5, 0  # DB2 default DECIMAL(5,0)
        second = second or 0
        if not 1 <= first <= 31 or second > first:
            raise ValueError(f"DECIMAL({first},{second}) is outside DB2's 1..31 digits")
        return SqlType(name, precision=first, scale=second)
    if name in ("CHAR", "VARCHAR", "CLOB", "BLOB"):
        if name == "VARCHAR" and first is None:
            raise ValueError("VARCHAR needs a length")
        return SqlType(name, length=first if first is not None else (1 if name == "CHAR" else None))
    if first is not None and name != "TIMESTAMP":
        raise ValueError(f"{name} takes no size arguments")
    return SqlType(name, length=first)


def cobol_to_sql_type(
    *, digits: int = 0, scale: int = 0, signed: bool = True, usage: str = "DISPLAY",
    alphanumeric_length: int = 0, varying: bool = False,
) -> SqlType:
    """The column type DCLGEN gives a COBOL host-variable declaration.

    ``PIC X(n)`` -> ``CHAR(n)``; binary ``COMP`` integers -> SMALLINT (<= 4 digits), INTEGER
    (<= 9), BIGINT (<= 18); packed/DISPLAY decimals -> ``DECIMAL(digits, scale)``.
    """
    if alphanumeric_length:
        return SqlType("VARCHAR" if varying else "CHAR", length=alphanumeric_length)
    if digits <= 0:
        raise ValueError("a numeric host variable needs a digit count")
    if usage.upper() in ("COMP", "BINARY", "COMP-4", "COMP-5") and scale == 0:
        if digits <= 4:
            return SqlType("SMALLINT")
        if digits <= 9:
            return SqlType("INTEGER")
        if digits <= 18:
            return SqlType("BIGINT")
        raise ValueError("binary host variables hold at most 18 digits")
    if digits > 31:
        raise ValueError("DECIMAL holds at most 31 digits")
    return SqlType("DECIMAL", precision=digits, scale=scale)


# --------------------------------------------------------------------------------------
# Rewriting
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BindVariable:
    """One positional marker: the COBOL host variable and its optional indicator."""

    name: str
    indicator: str = ""


@dataclass(frozen=True)
class RewriteResult:
    sql: str
    binds: tuple[BindVariable, ...] = ()
    #: Blocking: a construct with no faithful translation.  A caller must refuse the statement.
    issues: tuple[str, ...] = ()
    #: Non-blocking behavioural differences the caller should record in the evidence.
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_HOST = re.compile(r":([A-Za-z][A-Za-z0-9_-]*)(?:\s+INDICATOR)?(?:\s*:\s*([A-Za-z][A-Za-z0-9_-]*))?",
                   re.IGNORECASE)


def _outside_literals(sql: str, transform) -> str:
    """Apply ``transform`` to the text between quoted literals only."""
    out: list[str] = []
    last = 0
    for match in _LITERAL.finditer(sql):
        out.append(transform(sql[last:match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(transform(sql[last:]))
    return "".join(out)


class DatabaseDialect(ABC):
    """Target-database behaviour; subclass and ``register_dialect`` to add a database."""

    name: str = ""
    #: Marker placed for each host variable ("?" for JDBC).
    marker: str = "?"

    @abstractmethod
    def column_type(self, sql_type: SqlType) -> str:
        """DDL spelling of the column type."""

    @abstractmethod
    def java_type(self, sql_type: SqlType) -> str:
        """Exact Java type that carries the column (BigDecimal for DECIMAL)."""

    @abstractmethod
    def _translate(self, sql: str, issues: list[str], notes: list[str]) -> str:
        """Dialect-specific rewrite of the SQL text outside literals."""

    @abstractmethod
    def map_status(self, sqlstate: str, message: str = "") -> Db2SqlStatus:
        """The DB2-style status a COBOL program sees for the target's SQLSTATE."""

    def rewrite(self, sql: str) -> RewriteResult:
        """Rewrite one statement: translate dialect constructs, bind host variables to markers."""
        issues: list[str] = []
        notes: list[str] = []
        binds: list[BindVariable] = []

        def bind(text: str) -> str:
            def repl(match: re.Match[str]) -> str:
                binds.append(BindVariable(match.group(1).upper(), (match.group(2) or "").upper()))
                return self.marker
            return _HOST.sub(repl, text)

        # Bind first (so ``:HV`` is never mistaken for dialect syntax), in source order.
        marked = _outside_literals(" ".join(sql.split()), bind)
        translated = self._translate(marked, issues, notes)
        return RewriteResult(translated.strip().rstrip(";"), tuple(binds),
                             tuple(dict.fromkeys(issues)), tuple(dict.fromkeys(notes)))


class Db2Dialect(DatabaseDialect):
    """DB2 for z/OS as the source dialect: SQL text is kept, host variables become markers."""

    name = "db2"
    _JAVA = {"SMALLINT": "short", "INTEGER": "int", "BIGINT": "long", "DECIMAL": "java.math.BigDecimal",
             "CHAR": "String", "VARCHAR": "String", "DATE": "java.time.LocalDate",
             "TIME": "java.time.LocalTime", "TIMESTAMP": "java.time.LocalDateTime",
             "DOUBLE": "double", "REAL": "float", "CLOB": "String", "BLOB": "byte[]"}

    def column_type(self, sql_type: SqlType) -> str:
        return str(sql_type)

    def java_type(self, sql_type: SqlType) -> str:
        return self._JAVA[sql_type.name]

    def _translate(self, sql: str, issues: list[str], notes: list[str]) -> str:
        return sql

    def map_status(self, sqlstate: str, message: str = "") -> Db2SqlStatus:
        return _status_from_sqlstate(sqlstate, message)


# Documented SQLSTATE -> DB2 SQLCODE correspondences (DB2 for z/OS messages DSNT408I-style codes).
# ``None`` entries are deliberately absent: an unknown SQLSTATE stays an explicit unmapped error.
_SQLSTATE_TO_SQLCODE: dict[str, tuple[int, str, str]] = {
    # target SQLSTATE: (DB2 SQLCODE, DB2 SQLSTATE, meaning)
    "00000": (0, "00000", "successful completion"),
    "02000": (100, "02000", "no row found"),
    "21000": (-811, "21000", "singleton SELECT returned more than one row"),
    "23505": (-803, "23505", "duplicate key value in a unique index"),
    "23503": (-530, "23503", "foreign key violation on INSERT/UPDATE"),
    "23502": (-407, "23502", "null value in a NOT NULL column"),
    "22001": (-302, "22001", "value too long for the host variable or column"),
    "22003": (-413, "22003", "numeric value out of range"),
    "22012": (-802, "22012", "division by zero"),
    "22007": (-181, "22007", "invalid datetime value"),
    "42P01": (-204, "42704", "undefined table"),
    "42703": (-206, "42703", "undefined column"),
    "42601": (-104, "42601", "SQL syntax error"),
    "40001": (-911, "40001", "serialization failure: rolled back"),
    "40P01": (-911, "40001", "deadlock detected: rolled back"),
    "55P03": (-913, "57033", "lock not available: statement rolled back"),
    "57014": (-905, "57014", "statement cancelled: resource limit"),
}


def _status_from_sqlstate(sqlstate: str, message: str) -> Db2SqlStatus:
    entry = _SQLSTATE_TO_SQLCODE.get((sqlstate or "").upper())
    if entry is None:
        return Db2SqlStatus.unmapped_error(message or f"SQLSTATE {sqlstate}")
    sqlcode, db2_state, text = entry
    return Db2SqlStatus(sqlcode=sqlcode, sqlstate=db2_state, message=message or text)


class PostgresDialect(DatabaseDialect):
    """PostgreSQL as the first migration target."""

    name = "postgresql"
    _DDL = {"DOUBLE": "DOUBLE PRECISION", "CLOB": "TEXT", "BLOB": "BYTEA"}
    _JAVA = Db2Dialect._JAVA

    def column_type(self, sql_type: SqlType) -> str:
        if sql_type.name == "DECIMAL":
            return f"NUMERIC({sql_type.precision},{sql_type.scale or 0})"
        if sql_type.name == "TIMESTAMP":
            return f"TIMESTAMP({sql_type.length if sql_type.length is not None else 6})"
        if sql_type.name in self._DDL:
            return self._DDL[sql_type.name]
        return str(sql_type)

    def java_type(self, sql_type: SqlType) -> str:
        return self._JAVA[sql_type.name]

    # (pattern, replacement, note)
    _SIMPLE = (
        (re.compile(r"\bCURRENT\s+DATE\b", re.IGNORECASE), "CURRENT_DATE"),
        (re.compile(r"\bCURRENT\s+TIMESTAMP\b", re.IGNORECASE), "CURRENT_TIMESTAMP"),
        (re.compile(r"\bCURRENT\s+TIME\b", re.IGNORECASE), "CURRENT_TIME"),
        (re.compile(r"\bNVL\s*\(", re.IGNORECASE), "COALESCE("),
        (re.compile(r"\bVALUE\s*\(", re.IGNORECASE), "COALESCE("),
        (re.compile(r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY\b", re.IGNORECASE), r"LIMIT \1"),
        (re.compile(r"\bFETCH\s+FIRST\s+ROW\s+ONLY\b", re.IGNORECASE), "LIMIT 1"),
    )
    _ISOLATION = re.compile(r"\bWITH\s+(UR|CS|RS|RR)\b(?!\s+AS\b)", re.IGNORECASE)
    _READ_ONLY = re.compile(r"\bFOR\s+(?:READ|FETCH)\s+ONLY\b", re.IGNORECASE)
    _UNSUPPORTED = (
        (re.compile(r"\bFETCH\s+FIRST\b[^;]*\bWITH\s+TIES\b", re.IGNORECASE), "FETCH FIRST ... WITH TIES"),
        (re.compile(r"\b(?:DAYS|MIDNIGHT_SECONDS|DIGITS|HEX|RAISE_ERROR)\s*\(", re.IGNORECASE),
         "DB2 scalar function without a PostgreSQL equivalent"),
        (re.compile(r"\bFOR\s+UPDATE\s+OF\b", re.IGNORECASE), "FOR UPDATE OF column list"),
        (re.compile(r"\bUSING\s+CCSID\b", re.IGNORECASE), "CCSID clause"),
        (re.compile(r"\bGENERATED\s+ALWAYS\s+AS\s+IDENTITY\b", re.IGNORECASE),
         "identity column DDL (DDL is not rewritten)"),
        (re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE), "nested EXEC SQL"),
    )

    def _translate(self, sql: str, issues: list[str], notes: list[str]) -> str:
        def apply(chunk: str) -> str:
            for pattern, label in self._UNSUPPORTED:
                if pattern.search(chunk):
                    issues.append(label)
            for pattern, repl in self._SIMPLE:
                chunk = pattern.sub(repl, chunk)
            iso = self._ISOLATION.search(chunk)
            if iso:
                level = iso.group(1).upper()
                notes.append(
                    f"isolation WITH {level} dropped from the statement text; PostgreSQL runs "
                    + ("READ COMMITTED at the least (UR is strengthened)" if level == "UR"
                       else "at the transaction's isolation level")
                )
                chunk = self._ISOLATION.sub("", chunk)
            if self._READ_ONLY.search(chunk):
                notes.append("FOR READ ONLY / FOR FETCH ONLY dropped (PostgreSQL cursors are read-only by default)")
                chunk = self._READ_ONLY.sub("", chunk)
            return chunk

        text = _outside_literals(sql, apply)
        # LIMIT must follow ORDER BY and precede any trailing text: a FETCH FIRST that was not last
        # keeps its position, which is valid for SELECT ... [ORDER BY ...] FETCH FIRST n ROWS ONLY.
        return re.sub(r"\s+", " ", text)

    def map_status(self, sqlstate: str, message: str = "") -> Db2SqlStatus:
        return _status_from_sqlstate(sqlstate, message)


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

_REGISTRY: dict[str, DatabaseDialect] = {}


def register_dialect(dialect: DatabaseDialect) -> None:
    """Add a dialect; a name can be registered once (no silent replacement)."""
    key = dialect.name.lower()
    if not key:
        raise ValueError("a dialect needs a name")
    if key in _REGISTRY:
        raise ValueError(f"dialect {key!r} is already registered")
    _REGISTRY[key] = dialect


def dialect_for(name: str) -> DatabaseDialect:
    """The registered dialect, or ``ValueError`` listing the available ones (fail closed)."""
    try:
        return _REGISTRY[(name or "").lower()]
    except KeyError:
        raise ValueError(
            f"no database dialect {name!r}; available: {', '.join(sorted(_REGISTRY))}"
        ) from None


def available_dialects() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


register_dialect(Db2Dialect())
register_dialect(PostgresDialect())
