"""Controlled test-database execution for the DB2 lane.

Executes the supported SQL subset on an embedded, dependency-free SQLite
database (standard library) with deterministic DB2-compatible status
semantics (SQLCODE/SQLSTATE at the status boundary):

- 0:     successful completion (+ rows affected / row / outputs)
- 100:   no data (singleton SELECT / FETCH at end of cursor)
- -811:  singleton SELECT returned more than one row
- -803:  unique constraint violation on INSERT/UPDATE

Scope discipline: this harness proves behavior of the *translated subset*
on the controlled database.  It does NOT verify DB2 runtime behavior;
``compatibility_report`` keeps that distinction explicit.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from engine.sql.db2_sqlite import (
    UnsupportedTranslationError,
    translate_db2_ddl,
    translate_db2_dml,
)
from engine.sql.status import (
    SQLCODE_DUPLICATE_KEY,
    Db2SqlStatus,
)

_HOST_RE = re.compile(r":[A-Z][A-Z0-9-]*", re.IGNORECASE)
_PAIR_RE = re.compile(r":[A-Z][A-Z0-9-]*:[A-Z][A-Z0-9-]*", re.IGNORECASE)


@dataclass(frozen=True)
class Db2SqlExecutionResult:
    """Deterministic execution outcome on the controlled test database."""

    statement_type: str
    status: Db2SqlStatus = field(default_factory=Db2SqlStatus.success)
    row: tuple | None = None                    # singleton SELECT row
    rows: tuple[tuple, ...] = ()                # multi-row SELECT rows
    outputs: dict[str, Any] = field(default_factory=dict)  # INTO targets
    rows_affected: int = 0                      # INSERT/UPDATE/DELETE rowcount
    translated_sql: str = ""                    # SQL actually executed
    note: str = ""

    @property
    def successful(self) -> bool:
        return self.status.is_success

    @property
    def no_data(self) -> bool:
        return self.status.is_no_data


@dataclass(frozen=True)
class _CursorState:
    masked_sql: str
    rows: tuple[tuple, ...] = ()
    columns: tuple[str, ...] = ()
    fetch_index: int = 0


class Db2ControlledDatabase:
    """In-memory controlled database for reproducible SQL workloads.

    Each instance is isolated: schema + seed data are created fresh from
    the provided DDL seed, so every test run is deterministic.
    """

    def __init__(self, ddl_text: str = "") -> None:
        self._connection = sqlite3.connect(":memory:")
        self._connection.row_factory = sqlite3.Row
        self._cursors: dict[str, _CursorState] = {}
        self._ddl_statements: list[str] = []
        if ddl_text:
            self.create_schema(ddl_text)

    # ------------------------------------------------------------------
    # Schema and seed
    # ------------------------------------------------------------------

    def create_schema(self, ddl_text: str) -> list[str]:
        """Translate and apply DB2 DDL; returns the translated statements."""
        translated = translate_db2_ddl(ddl_text)
        with self._connection:
            for statement in translated:
                self._connection.execute(statement)
        self._ddl_statements.extend(translated)
        return translated

    def seed_table(self, table: str, records: list[dict[str, Any]]) -> None:
        """Insert seed records; column order follows the first record."""
        if not records:
            raise ValueError("seed_table requires at least one record")
        columns = list(records[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        with self._connection:
            for record in records:
                values = [record.get(col) for col in columns]
                self._connection.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})",
                    values,
                )

    def fetch_table(self, table: str) -> list[dict[str, Any]]:
        """Return all rows of a table (ordered by rowid) as dicts."""
        rows = self._connection.execute(
            f"SELECT * FROM {table} ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def table_row_count(self, table: str) -> int:
        return self._connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

    # ------------------------------------------------------------------
    # Execution entry point
    # ------------------------------------------------------------------

    def execute(
        self,
        semantic_stmt,
        bindings: dict[str, Any] | None = None,
        cursor_name: str = "",
    ) -> Db2SqlExecutionResult:
        """Execute one analyzed statement with host-variable bindings.

        ``semantic_stmt`` is a ``Db2StmtSemantic`` produced by the analyzer.
        ``bindings`` supplies input host variable values by COBOL name.
        """
        bindings = dict(bindings or {})
        stype = semantic_stmt.statement_type

        if stype == "OPEN_CURSOR":
            return self._open_cursor(cursor_name or semantic_stmt.cursor_name, bindings)
        if stype == "FETCH_CURSOR":
            return self._fetch_cursor(cursor_name or semantic_stmt.cursor_name, semantic_stmt)
        if stype == "CLOSE_CURSOR":
            return self._close_cursor(cursor_name or semantic_stmt.cursor_name)
        if stype == "COMMIT":
            self.commit()
            return self._ok_result("COMMIT", translated_sql="COMMIT")
        if stype == "ROLLBACK":
            self.rollback()
            return self._ok_result("ROLLBACK", translated_sql="ROLLBACK")
        if stype == "DECLARE_CURSOR":
            return self._declare_cursor(semantic_stmt)

        return self._execute_dml_or_select(semantic_stmt, bindings)

    # ------------------------------------------------------------------
    # Cursor lifecycle (harness-managed; not SQLite cursors)
    # ------------------------------------------------------------------

    def _declare_cursor(self, semantic_stmt) -> Db2SqlExecutionResult:
        raw = semantic_stmt.raw_sql
        upper = raw.upper()
        for_match = re.search(r"\bFOR\b", upper)
        if not for_match:
            raise UnsupportedTranslationError(
                f"DECLARE CURSOR without FOR query: {raw[:64]!r}"
            )
        query_sql = raw[for_match.end():].strip()
        exec_sql = translate_db2_dml(query_sql)
        masked, _binds = self._mask_host_variables(exec_sql)
        name = semantic_stmt.cursor_name
        self._cursors[name] = _CursorState(masked_sql=masked)
        return Db2SqlExecutionResult(
            statement_type="DECLARE_CURSOR",
            status=Db2SqlStatus.success(),
            translated_sql=masked,
        )

    def _open_cursor(
        self, name: str, bindings: dict[str, Any]
    ) -> Db2SqlExecutionResult:
        state = self._cursors.get(name)
        if state is None:
            raise KeyError(f"cursor not declared: {name}")
        masked_sql = state.masked_sql
        _info, values = self._bind_from_sql(masked_sql, bindings)
        try:
            cur = self._connection.execute(masked_sql, values)
        except sqlite3.IntegrityError as exc:
            return self._integrity_result("OPEN_CURSOR", exc)
        except sqlite3.OperationalError as exc:
            return self._operational_result("OPEN_CURSOR", exc, masked_sql)

        rows = [tuple(row) for row in cur.fetchall()]
        columns = tuple(cur.description[i][0] for i in range(len(cur.description)))
        self._cursors[name] = _CursorState(
            masked_sql=masked_sql,
            rows=tuple(rows),
            columns=columns,
            fetch_index=0,
        )
        return Db2SqlExecutionResult(
            statement_type="OPEN_CURSOR",
            status=Db2SqlStatus.success(),
            translated_sql=masked_sql,
            note=f"cursor {name} open with {len(rows)} row(s)",
        )

    def _fetch_cursor(
        self, name: str, semantic_stmt
    ) -> Db2SqlExecutionResult:
        state = self._cursors.get(name)
        if state is None:
            raise KeyError(f"cursor not open/declared: {name}")
        if state.fetch_index >= len(state.rows):
            return Db2SqlExecutionResult(
                statement_type="FETCH_CURSOR",
                status=Db2SqlStatus.no_data(),
                translated_sql=state.masked_sql,
                note=f"cursor {name} exhausted (SQLCODE 100)",
            )
        row = state.rows[state.fetch_index]
        column_names = list(semantic_stmt.output_host_variables)
        outputs: dict[str, Any] = {}
        for idx, col in enumerate(column_names):
            if idx >= len(row):
                break
            outputs[col] = row[idx]
        self._cursors[name] = _CursorState(
            masked_sql=state.masked_sql,
            rows=state.rows,
            columns=state.columns,
            fetch_index=state.fetch_index + 1,
        )
        return Db2SqlExecutionResult(
            statement_type="FETCH_CURSOR",
            status=Db2SqlStatus.success(),
            row=row,
            outputs=outputs,
            translated_sql=state.masked_sql,
        )

    def _close_cursor(self, name: str) -> Db2SqlExecutionResult:
        if name not in self._cursors:
            raise KeyError(f"cursor not declared: {name}")
        del self._cursors[name]
        return Db2SqlExecutionResult(
            statement_type="CLOSE_CURSOR",
            status=Db2SqlStatus.success(),
            note=f"cursor {name} closed",
        )

    # ------------------------------------------------------------------
    # DML / SELECT execution
    # ------------------------------------------------------------------

    def _execute_dml_or_select(
        self, semantic_stmt, bindings: dict[str, Any]
    ) -> Db2SqlExecutionResult:
        stype = semantic_stmt.statement_type
        translated = translate_db2_dml(semantic_stmt.raw_sql)
        masked_sql, bind_info = self._mask_host_variables(translated)
        values = self._bind_values(bind_info, bindings)
        is_singleton_select = stype == "SELECT" and bool(semantic_stmt.output_host_variables)

        try:
            if is_singleton_select:
                return self._run_singleton_select(semantic_stmt, masked_sql, values)
            return self._run_simple(semantic_stmt, masked_sql, values)
        except sqlite3.IntegrityError as exc:
            return self._integrity_result(stype, exc)
        except sqlite3.OperationalError as exc:
            return self._operational_result(stype, exc, masked_sql)

    def _run_singleton_select(
        self, semantic_stmt, masked_sql: str, values: list
    ) -> Db2SqlExecutionResult:
        cur = self._connection.execute(masked_sql, values)
        rows = cur.fetchall()
        row = tuple(rows[0]) if rows else None

        if len(rows) == 0:
            return Db2SqlExecutionResult(
                statement_type="SELECT",
                status=Db2SqlStatus.no_data(),
                translated_sql=masked_sql,
                note="singleton SELECT returned no rows (SQLCODE 100)",
            )
        if len(rows) > 1:
            return Db2SqlExecutionResult(
                statement_type="SELECT",
                status=Db2SqlStatus.too_many_rows(),
                translated_sql=masked_sql,
                rows=tuple(tuple(r) for r in rows),
                note="singleton SELECT returned more than one row (SQLCODE -811)",
            )

        outputs = self._capture_outputs(semantic_stmt, row)
        return Db2SqlExecutionResult(
            statement_type="SELECT",
            status=Db2SqlStatus.success(),
            row=row,
            outputs=outputs,
            translated_sql=masked_sql,
        )

    def _run_simple(
        self, semantic_stmt, masked_sql: str, values: list
    ) -> Db2SqlExecutionResult:
        stype = semantic_stmt.statement_type
        if stype == "SELECT":
            cur = self._connection.execute(masked_sql, values)
            rows = [tuple(r) for r in cur.fetchall()]
            return Db2SqlExecutionResult(
                statement_type="SELECT",
                status=Db2SqlStatus.success(),
                rows=tuple(rows),
                translated_sql=masked_sql,
            )
        cur = self._connection.execute(masked_sql, values)
        return Db2SqlExecutionResult(
            statement_type=stype,
            status=Db2SqlStatus.success(),
            rows_affected=max(cur.rowcount, 0),
            translated_sql=masked_sql,
        )

    def _capture_outputs(self, semantic_stmt, row: tuple) -> dict[str, Any]:
        """Bind result columns to the SELECT INTO host variables.

        Indicator variables (nullable targets) receive 0 when the value is
        non-NULL and -1 when the value is NULL (DB2 indicator convention).
        """
        outputs: dict[str, Any] = {}
        targets = list(semantic_stmt.output_host_variables)
        for idx, name in enumerate(targets):
            if idx >= len(row):
                break
            value = row[idx]
            outputs[name] = value
            indicator = next(
                (hv.indicator for hv in semantic_stmt.host_variables
                 if hv.name == name and hv.uses_indicator),
                "",
            )
            if indicator:
                outputs[indicator] = -1 if value is None else 0
        return outputs

    # ------------------------------------------------------------------
    # Host variable masking and binding
    # ------------------------------------------------------------------

    def _mask_host_variables(
        self, sql: str,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Replace ``:VAR`` / ``:VAR:IND`` tokens with '?' placeholders.

        Returns (masked_sql, bind_info) where bind_info is an ordered list
        of (name, indicator_name) tuples matching placeholder order.
        """
        result: list[str] = []
        bind_info: list[tuple[str, str]] = []
        i = 0
        length = len(sql)
        while i < length:
            pair = _PAIR_RE.match(sql, i)
            if pair:
                primary, ind = pair.group(0)[1:].split(":", 1)
                result.append("?")
                bind_info.append((primary, ind))
                i = pair.end()
                continue
            host = _HOST_RE.match(sql, i)
            if host:
                result.append("?")
                bind_info.append((host.group(0)[1:], ""))
                i = host.end()
                continue
            result.append(sql[i])
            i += 1
        return "".join(result), bind_info

    def _bind_from_sql(
        self, sql: str, bindings: dict[str, Any]
    ) -> tuple[list[tuple[str, str]], list]:
        """Mask host variables and resolve values for the placeholders."""
        _masked, bind_info = self._mask_host_variables(sql)
        return bind_info, self._bind_values(bind_info, bindings)

    def _bind_values(
        self, bind_info: list[tuple[str, str]], bindings: dict[str, Any]
    ) -> list:
        values: list[Any] = []
        for name, _indicator in bind_info:
            if name not in bindings:
                raise KeyError(f"missing host variable binding: {name}")
            values.append(bindings[name])
        return values

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    # ------------------------------------------------------------------
    # Status mapping helpers
    # ------------------------------------------------------------------

    def _integrity_result(
        self, stype: str, exc: sqlite3.IntegrityError
    ) -> Db2SqlExecutionResult:
        message = str(exc)
        if "UNIQUE" in message.upper():
            return Db2SqlExecutionResult(
                statement_type=stype,
                status=Db2SqlStatus.duplicate_key(),
                note=f"unique constraint violation (SQLCODE {SQLCODE_DUPLICATE_KEY}): {message}",
            )
        return Db2SqlExecutionResult(
            statement_type=stype,
            status=Db2SqlStatus(sqlcode=-1, sqlstate="", message=message),
            note=f"integrity violation outside the mapped subset: {message}",
        )

    def _operational_result(
        self, stype: str, exc: sqlite3.OperationalError, sql: str
    ) -> Db2SqlExecutionResult:
        return Db2SqlExecutionResult(
            statement_type=stype,
            status=Db2SqlStatus(sqlcode=-1, sqlstate="", message=str(exc)),
            translated_sql=sql,
            note=f"operational error on the controlled database: {exc}",
        )

    def _ok_result(
        self, stype: str, translated_sql: str
    ) -> Db2SqlExecutionResult:
        return Db2SqlExecutionResult(
            statement_type=stype,
            status=Db2SqlStatus.success(),
            translated_sql=translated_sql,
        )