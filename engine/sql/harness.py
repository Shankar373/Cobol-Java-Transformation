"""Deterministic controlled-execution harness for the DB2 lane.

Drives an analyzed ``Db2SqlModel`` against a controlled SQLite database
(``Db2ControlledDatabase``) replicating the DB2 semantics of the supported
subset, and produces a deterministic execution trace:

    <operation> <status> [OUT <outputs>] [n=<rows>] [<bind-key:value>...]

This trace is the lane fixture's executable artifact.  It is NOT DB2
runtime output; it verifies the translated subset under controlled
conditions only.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.execution import Db2ControlledDatabase
from engine.sql.extractor import extract_embedded_sql_blocks
from engine.sql.model import Db2SqlModel
from engine.sql.status import Db2SqlStatus
from engine.transformation.sql_parser import SqlParser


class WorkloadExecutionError(RuntimeError):
    """Raised when a workload statement cannot be executed."""


def _execute_workload_sql(db: Db2ControlledDatabase, stmt) -> Db2SqlStatus | None:
    """Execute one non-cursor, non-singleton statement, returning status."""
    return db.execute(stmt).status


def run_db2_workload(
    cobol_text: str,
    program_id: str,
    ddl_text: str,
    seed_rows: list[tuple | dict],
    controlled_class: type[Db2ControlledDatabase] = Db2ControlledDatabase,
    sqlcode_field: str = "SQLCODE",
    sqlstate_field: str = "SQLSTATE",
    statement_bindings: list[dict[str, object]] | None = None,
) -> tuple[Db2SqlModel, str, Db2ControlledDatabase]:
    """Analyze the COBOL program and execute its SQL on a controlled database.

    Returns ``(model, trace, database)``.  The database is kept open so the
    caller can assert on final table state; callers must close it.

    ``statement_bindings`` supplies input host-variable values in the order
    of ``model.statements``; an empty dict is used for any missing entry.
    """
    model = Db2SemanticAnalyzer().analyze_program(
        program_id,
        (
            SqlParser().parse_embedded_sql(sql)
            for sql in extract_embedded_sql_blocks(cobol_text)
        ),
    )
    db = controlled_class()
    db.create_schema(ddl_text)
    for row in seed_rows:
        db.seed_table("ACCOUNT", [row])

    trace_lines: list[str] = []

    def trace(operation: str, status: Db2SqlStatus | None, **extra) -> None:
        parts = [operation, f"{status.sqlcode}/{status.sqlstate}" if status else "NOOP"]
        for key, value in extra.items():
            parts.append(f"{key}={value}")
        trace_lines.append(" ".join(str(p) for p in parts))

    holders: set[str] = set()
    bindings = statement_bindings or []
    for stmt_index, stmt in enumerate(model.statements):
        stmt_bindings = dict(bindings[stmt_index]) if stmt_index < len(bindings) else {}
        if stmt.statement_type == "DECLARE_CURSOR":
            cursor_name = _cursor_name(stmt)
            holders.add(cursor_name)
            trace("DECLARE", db.execute(stmt).status, name=cursor_name)
            continue
        if stmt.statement_type in ("OPEN_CURSOR", "CLOSE_CURSOR"):
            cursor_name = _cursor_name(stmt)
            if stmt.statement_type == "OPEN_CURSOR" and cursor_name not in holders:
                raise WorkloadExecutionError(f"OPEN before DECLARE: {cursor_name}")
            operation = "OPEN" if stmt.statement_type == "OPEN_CURSOR" else "CLOSE"
            trace(operation, db.execute(stmt).status, name=cursor_name)
            continue
        if stmt.statement_type == "FETCH_CURSOR":
            cursor_name = _cursor_name(stmt)
            result = db.execute(stmt)
            extra: dict = {"name": cursor_name}
            if result.status.is_success:
                extra["out"] = result.outputs
            trace("FETCH", result.status, **extra)
            continue
        if stmt.statement_type == "SELECT" and stmt.output_host_variables:
            result = db.execute(stmt, bindings=stmt_bindings)
            extra = {}
            if result.status.is_success:
                extra["out"] = result.outputs
            trace("SELECT_INTO", result.status, **extra)
            continue
        result = db.execute(stmt, bindings=stmt_bindings)
        extra = {}
        if result.outputs:
            extra["out"] = result.outputs
        if result.rows_affected:
            extra["rows_affected"] = result.rows_affected
        trace(stmt.statement_type, result.status, **extra)

    return model, "\n".join(trace_lines), db


def _cursor_name(stmt) -> str:
    """Return the cursor identifier for DECLARE/OPEN/FETCH/CLOSE statements."""
    name = f"{getattr(stmt, 'cursor_name', '')}".strip()
    if name:
        return name
    cursor = getattr(stmt, "cursor", None)
    name = f"{getattr(cursor, 'name', '').strip() if cursor is not None else ''}"
    if name:
        return name
    raw = stmt.raw_sql.split()
    for index, token in enumerate(raw):
        if token in ("CURSOR", "FETCH", "CLOSE", "OPEN") and index + 1 < len(raw):
            return raw[index + 1].rstrip(",")
    raise WorkloadExecutionError(f"cannot determine cursor name for: {stmt.raw_sql}")