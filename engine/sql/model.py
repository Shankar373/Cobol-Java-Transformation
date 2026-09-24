"""DB2 SQL semantic model.

Builds on the frozen SQL IR (``engine.transformation.ir``) with the semantics
that an embedded-SQL host program depends on:

- host variable binding directions (INPUT / OUTPUT / IN_OUT / UNKNOWN)
- nullable host variables (indicator variables)
- table access classification (read vs write operations and column sets)
- DB2 status expectations (SQLCODE/SQLSTATE) per statement

This module is lane-owned.  It imports the SQL IR read-only and never
modifies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.sql.status import Db2SqlStatus
from engine.transformation.ir import (
    SqlColumnReference,
    SqlExpression,
    SqlPredicate,
    SqlTableReference,
)


class Db2BindingDirection(Enum):
    """Binding direction of a host variable within a SQL statement.

    Derived from source SQL position, never invented:

    - ``INTO`` targets of SELECT/FETCH are OUTPUT
    - every other ``:VAR`` occurrence is INPUT
    - a variable in both roles within one statement is IN_OUT
    - CALL arguments cannot be classified from SQL text alone → UNKNOWN
    """

    INPUT = "INPUT"        # value is provided to the database
    OUTPUT = "OUTPUT"      # value is received from the database
    IN_OUT = "IN_OUT"      # used as both input and output
    UNKNOWN = "UNKNOWN"    # cannot be determined from the SQL text alone


class Db2ColumnRole(Enum):
    """Role of a column reference within a statement."""

    READ = "READ"      # column value is read (SELECT list, WHERE, SET rhs, …)
    WRITE = "WRITE"    # column value is written (INSERT/UPDATE target)


@dataclass(frozen=True)
class HostVariableOccurrence:
    """One occurrence of a host variable inside a SQL statement."""

    name: str
    direction: Db2BindingDirection
    indicator: str = ""
    uses_indicator: bool = False

    @property
    def nullable(self) -> bool:
        return self.uses_indicator


@dataclass(frozen=True)
class SqlHostVariableSemantic:
    """Aggregated semantic of one host variable within a single statement.

    ``direction`` is the per-statement role.  Table usage and indicator
    presence are folded in by the analyzer.
    """

    name: str
    direction: Db2BindingDirection
    indicator: str = ""
    uses_indicator: bool = False

    @property
    def nullable(self) -> bool:
        return self.uses_indicator


@dataclass(frozen=True)
class Db2TableUsage:
    """Aggregated read/write access to one DB2 table by a program."""

    table_name: str
    schema: str = ""
    operations: tuple[str, ...] = ()          # SELECT, INSERT, UPDATE, DELETE
    read_columns: tuple[str, ...] = ()        # columns whose values are read
    write_columns: tuple[str, ...] = ()       # columns whose values are written

    @property
    def is_read(self) -> bool:
        return "SELECT" in self.operations

    @property
    def is_write(self) -> bool:
        return bool({"INSERT", "UPDATE", "DELETE"} & set(self.operations))


@dataclass(frozen=True)
class Db2StmtSemantic:
    """Semantic analysis of a single embedded SQL statement."""

    raw_sql: str = ""
    statement_type: str = ""                  # SqlStatementType.value
    host_variables: tuple[SqlHostVariableSemantic, ...] = ()
    table_refs: tuple[SqlTableReference, ...] = ()
    read_columns: tuple[str, ...] = ()
    write_columns: tuple[str, ...] = ()
    possible_statuses: tuple[Db2SqlStatus, ...] = ()
    cursor_name: str = ""                     # for cursor operations
    procedure_name: str = ""                  # for CALL
    is_transaction_boundary: bool = False
    is_cursor_operation: bool = False

    @property
    def input_host_variables(self) -> tuple[str, ...]:
        return tuple(
            hv.name for hv in self.host_variables
            if hv.direction in (Db2BindingDirection.INPUT, Db2BindingDirection.IN_OUT)
        )

    @property
    def output_host_variables(self) -> tuple[str, ...]:
        return tuple(
            hv.name for hv in self.host_variables
            if hv.direction in (Db2BindingDirection.OUTPUT, Db2BindingDirection.IN_OUT)
        )


@dataclass(frozen=True)
class Db2SqlModel:
    """The complete DB2 semantic model of one embedded-SQL program.

    ``host_variables`` is the program-level registry with aggregate
    binding directions computed across statements:
    a variable used as OUTPUT anywhere and INPUT anywhere is IN_OUT.
    """

    program_id: str
    statements: tuple[Db2StmtSemantic, ...] = ()
    host_variables: tuple[SqlHostVariableSemantic, ...] = ()
    tables: tuple[Db2TableUsage, ...] = ()
    sqlcode_field: str = ""                   # COBOL SQLCODE field (program-level)
    sqlstate_field: str = ""                  # COBOL SQLSTATE field (program-level)
    validation: tuple[str, ...] = ()          # deterministic analyzer diagnostics

    def table_names(self) -> list[str]:
        ordered: list[str] = []
        for t in self.tables:
            if t.table_name not in ordered:
                ordered.append(t.table_name)
        return ordered

    def get_table(self, table_name: str) -> Db2TableUsage | None:
        for t in self.tables:
            if t.table_name == table_name:
                return t
        return None


def merge_table_usages(
    usages: list[Db2TableUsage],
) -> tuple[Db2TableUsage, ...]:
    """Merge per-statement table usages into a stable program-level view."""
    merged: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    for usage in usages:
        key = (usage.table_name, usage.schema)
        if key not in merged:
            merged[key] = {
                "operations": set(),
                "read_columns": [],
                "write_columns": [],
            }
            order.append(key)
        entry = merged[key]
        entry["operations"].update(usage.operations)
        for col in usage.read_columns:
            if col and col not in entry["read_columns"]:
                entry["read_columns"].append(col)
        for col in usage.write_columns:
            if col and col not in entry["write_columns"]:
                entry["write_columns"].append(col)

    result: list[Db2TableUsage] = []
    for table_name, schema in order:
        entry = merged[(table_name, schema)]
        result.append(
            Db2TableUsage(
                table_name=table_name,
                schema=schema,
                operations=tuple(sorted(entry["operations"])),
                read_columns=tuple(entry["read_columns"]),
                write_columns=tuple(entry["write_columns"]),
            )
        )
    return tuple(result)


def collect_expression_columns(expr: SqlExpression | None) -> list[SqlColumnReference]:
    """Collect all column references inside a SQL expression (deterministic)."""
    if expr is None:
        return []
    columns: list[SqlColumnReference] = []
    if expr.column is not None:
        columns.append(expr.column)
    columns.extend(collect_expression_columns(expr.operand_left))
    columns.extend(collect_expression_columns(expr.operand_right))
    return columns


def collect_predicate_columns(pred: SqlPredicate | None) -> list[SqlColumnReference]:
    """Collect all column references inside a predicate tree"""
    if pred is None:
        return []
    columns: list[SqlColumnReference] = []
    columns.extend(collect_expression_columns(pred.left))
    columns.extend(collect_expression_columns(pred.right))
    columns.extend(collect_expression_columns(pred.right_operand))
    columns.extend(collect_expression_columns(pred.left_operand))
    for item in pred.right_list:
        columns.extend(collect_expression_columns(item))
    return columns


def column_full_names(columns: list[SqlColumnReference]) -> list[str]:
    """Canonical column names (deterministic order, de-duplicated)."""
    seen: list[str] = []
    for col in columns:
        name = col.column_name
        if col.table_name:
            name = f"{col.table_name}.{name}"
        if name and name not in seen:
            seen.append(name)
    return seen