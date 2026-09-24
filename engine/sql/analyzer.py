"""DB2 semantic analyzer.

Consumes ``EmbeddedSqlBlock`` (produced by the existing ``SqlParser`` in
``engine.transformation.sql_parser``) and produces the lane-owned
``Db2SqlModel`` with:

- per-statement host variable binding directions
- per-statement table read/write classification
- per-statement possible DB2 statuses (SQLCODE/SQLSTATE)
- program-level aggregated host variable registry and table usage
- deterministic validation diagnostics

All analysis is derived from SQL source positions.  Nothing is invented.
"""

from __future__ import annotations

import re

from engine.sql.model import (
    Db2BindingDirection,
    Db2SqlModel,
    Db2StmtSemantic,
    Db2TableUsage,
    SqlHostVariableSemantic,
    collect_expression_columns,
    collect_predicate_columns,
    column_full_names,
    merge_table_usages,
)
from engine.sql.status import (
    DELETE_STATUSES,
    DML_STATUSES,
    SINGLETON_SELECT_STATUSES,
)
from engine.transformation.ir import (
    EmbeddedSqlBlock,
    SqlColumnReference,
    SqlSelect,
    SqlStatementType,
)

_HOST_VAR_RE = re.compile(r":([A-Z][A-Z0-9-]*)", re.IGNORECASE)
_INDICATOR_PAIR_RE = re.compile(r":([A-Z][A-Z0-9-]*):([A-Z][A-Z0-9-]*)", re.IGNORECASE)


class Db2SemanticAnalyzer:
    """Deterministic semantic analysis of embedded SQL blocks.

    Usage::

        analyzer = Db2SemanticAnalyzer()
        model = analyzer.analyze_program("PROG1", (block1, block2))
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_program(
        self,
        program_id: str,
        blocks: tuple[EmbeddedSqlBlock, ...],
        sqlcode_field: str = "",
        sqlstate_field: str = "",
    ) -> Db2SqlModel:
        """Analyze all SQL blocks of a program into a DB2 semantic model."""
        stmt_semantics: list[Db2StmtSemantic] = []
        table_usages: list[Db2TableUsage] = []

        for block in blocks:
            for stmt in block.statements:
                sem = self.analyze_statement(stmt)
                stmt_semantics.append(sem)
                table_usages.extend(self.statement_table_usages(stmt, sem))

        return Db2SqlModel(
            program_id=program_id,
            statements=tuple(stmt_semantics),
            host_variables=self.aggregate_host_variables(stmt_semantics),
            tables=merge_table_usages(table_usages),
            sqlcode_field=sqlcode_field,
            sqlstate_field=sqlstate_field,
            validation=tuple(self.program_diagnostics(stmt_semantics)),
        )

    def analyze_statement(self, stmt) -> Db2StmtSemantic:
        """Analyze a single ``SqlStatement`` into statement semantics."""
        stype = stmt.statement_type
        raw = stmt.raw_sql

        if stype == SqlStatementType.SELECT and stmt.select is not None:
            return self._analyze_select(stmt.select, raw)

        if stype == SqlStatementType.INSERT and stmt.insert is not None:
            return self._analyze_insert(stmt, raw)

        if stype == SqlStatementType.UPDATE and stmt.update is not None:
            return self._analyze_update(stmt, raw)

        if stype == SqlStatementType.DELETE and stmt.delete is not None:
            return self._analyze_delete(stmt, raw)

        if stype == SqlStatementType.DECLARE_CURSOR and stmt.cursor is not None:
            return self._analyze_declare_cursor(stmt, raw)

        if stype == SqlStatementType.FETCH_CURSOR:
            return self._analyze_fetch(stmt, raw)

        if stype in (SqlStatementType.OPEN_CURSOR, SqlStatementType.CLOSE_CURSOR):
            return Db2StmtSemantic(
                raw_sql=raw,
                statement_type=stype.value,
                cursor_name=stmt.cursor_name,
                is_cursor_operation=True,
            )

        if stype in (SqlStatementType.COMMIT, SqlStatementType.ROLLBACK):
            return Db2StmtSemantic(
                raw_sql=raw,
                statement_type=stype.value,
                is_transaction_boundary=True,
            )

        if stype == SqlStatementType.CALL:
            return Db2StmtSemantic(
                raw_sql=raw,
                statement_type=stype.value,
                host_variables=self._host_variables(raw, into_span=False, unknown=True),
                procedure_name=stmt.procedure_name,
            )

        if stype in (SqlStatementType.PREPARE, SqlStatementType.EXECUTE):
            return Db2StmtSemantic(
                raw_sql=raw,
                statement_type=stype.value,
                host_variables=self._host_variables(raw, into_span=False),
            )

        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=stype.value,
            host_variables=self._host_variables(raw, into_span=False),
        )

    # ------------------------------------------------------------------
    # Per-statement analyzers
    # ------------------------------------------------------------------

    def _analyze_select(self, select: SqlSelect, raw: str) -> Db2StmtSemantic:
        read_cols: list[SqlColumnReference] = []
        read_cols.extend(select.columns)
        read_cols.extend(collect_predicate_columns(select.where_predicate))
        read_cols.extend(collect_predicate_columns(select.having))
        for group in select.group_by:
            if group.column is not None:
                read_cols.append(group.column)
        for order in select.order_by:
            if order.column is not None:
                read_cols.append(order.column)

        is_singleton = bool(select.into_variables)
        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.SELECT.value,
            host_variables=self._host_variables(raw, into_span=is_singleton),
            table_refs=tuple(select.from_tables),
            read_columns=tuple(column_full_names(read_cols)),
            possible_statuses=SINGLETON_SELECT_STATUSES if is_singleton else (),
        )

    def _analyze_insert(self, stmt, raw: str) -> Db2StmtSemantic:
        insert = stmt.insert
        read_cols: list[SqlColumnReference] = []
        for value in insert.values:
            read_cols.extend(collect_expression_columns(value))
        write_cols = list(insert.columns)
        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.INSERT.value,
            host_variables=self._host_variables(raw, into_span=False),
            table_refs=(insert.table,) if insert.table is not None else (),
            read_columns=tuple(column_full_names(read_cols)),
            write_columns=tuple(column_full_names(write_cols)),
            possible_statuses=DML_STATUSES,
        )

    def _analyze_update(self, stmt, raw: str) -> Db2StmtSemantic:
        update = stmt.update
        read_cols: list[SqlColumnReference] = []
        write_cols: list[SqlColumnReference] = []
        for column, value in update.assignments:
            write_cols.append(column)
            read_cols.extend(collect_expression_columns(value))
        read_cols.extend(collect_predicate_columns(update.where_predicate))

        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.UPDATE.value,
            host_variables=self._host_variables(raw, into_span=False),
            table_refs=(update.table,) if update.table is not None else (),
            read_columns=tuple(column_full_names(read_cols)),
            write_columns=tuple(column_full_names(write_cols)),
            possible_statuses=DML_STATUSES,
        )

    def _analyze_delete(self, stmt, raw: str) -> Db2StmtSemantic:
        delete = stmt.delete
        read_cols = collect_predicate_columns(delete.where_predicate)
        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.DELETE.value,
            host_variables=self._host_variables(raw, into_span=False),
            table_refs=(delete.table,) if delete.table is not None else (),
            read_columns=tuple(column_full_names(read_cols)),
            possible_statuses=DELETE_STATUSES,
        )

    def _analyze_declare_cursor(self, stmt, raw: str) -> Db2StmtSemantic:
        cursor = stmt.cursor
        query = cursor.query
        read_cols: list[SqlColumnReference] = []
        tables: tuple = ()
        if query is not None:
            read_cols.extend(query.columns)
            read_cols.extend(collect_predicate_columns(query.where_predicate))
            read_cols.extend(collect_predicate_columns(query.having))
            for group in query.group_by:
                if group.column is not None:
                    read_cols.append(group.column)
            for order in query.order_by:
                if order.column is not None:
                    read_cols.append(order.column)
            tables = tuple(query.from_tables)

        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.DECLARE_CURSOR.value,
            host_variables=self._host_variables(raw, into_span=False),
            table_refs=tables,
            read_columns=tuple(column_full_names(read_cols)),
            cursor_name=cursor.name,
            is_cursor_operation=True,
        )

    def _analyze_fetch(self, stmt, raw: str) -> Db2StmtSemantic:
        return Db2StmtSemantic(
            raw_sql=raw,
            statement_type=SqlStatementType.FETCH_CURSOR.value,
            host_variables=self._host_variables(raw, into_span=True),
            possible_statuses=SINGLETON_SELECT_STATUSES,
            cursor_name=stmt.cursor_name,
            is_cursor_operation=True,
        )

    # ------------------------------------------------------------------
    # Host variable discovery
    # ------------------------------------------------------------------

    def _into_span(self, raw: str) -> tuple[int, int] | None:
        """Index span of the INTO clause (``[start, end)``), if present."""
        upper = raw.upper()
        into_match = re.search(r"\bINTO\b", upper)
        if not into_match:
            return None
        start = into_match.start()
        from_match = re.search(r"\bFROM\b", upper[start + 4:])
        if from_match:
            end = start + 4 + from_match.start()
        else:
            end = len(raw)
        return start, end

    def _host_variables(
        self,
        raw: str,
        into_span: bool,
        unknown: bool = False,
    ) -> tuple[SqlHostVariableSemantic, ...]:
        """Derive host variable semantics from raw SQL text.

        A host variable inside the INTO clause is OUTPUT; any occurrence
        outside the INTO clause is INPUT; both roles ⇒ IN_OUT.
        ``:A:B`` indicator pairs are merged into a single nullable variable.
        """
        matches = list(_HOST_VAR_RE.finditer(raw))
        positions: dict[str, int] = {}
        for m in matches:
            positions.setdefault(m.group(1), m.start())

        span = self._into_span(raw) if into_span else None
        direction: dict[str, Db2BindingDirection] = {}
        indicators: dict[str, str] = {}

        for m in matches:
            name = m.group(1)
            in_into = span is not None and span[0] <= m.start() < span[1]
            role = Db2BindingDirection.OUTPUT if in_into else Db2BindingDirection.INPUT
            current = direction.get(name)
            if current is None:
                direction[name] = role
            elif current != role:
                direction[name] = Db2BindingDirection.IN_OUT

        for m in _INDICATOR_PAIR_RE.finditer(raw):
            primary, ind = m.group(1), m.group(2)
            if primary in direction:
                indicators.setdefault(primary, ind)

        if unknown:
            direction = {  # CALL arguments: role unknowable from SQL text
                name: Db2BindingDirection.UNKNOWN for name in direction
            }

        ordered = sorted(direction, key=lambda n: positions.get(n, len(raw)))
        result: list[SqlHostVariableSemantic] = []
        for name in ordered:
            indicator = indicators.get(name, "")
            result.append(
                SqlHostVariableSemantic(
                    name=name,
                    direction=direction[name],
                    indicator=indicator,
                    uses_indicator=bool(indicator),
                )
            )
        return tuple(result)

    # ------------------------------------------------------------------
    # Table usage per statement
    # ------------------------------------------------------------------

    def statement_table_usages(
        self,
        stmt,
        sem: Db2StmtSemantic,
    ) -> list[Db2TableUsage]:
        """Produce per-statement table usage records."""
        stype = stmt.statement_type
        usages: list[Db2TableUsage] = []
        targets = []

        if stype == SqlStatementType.SELECT:
            targets = list(stmt.select.from_tables) if stmt.select is not None else []
            for t in targets:
                usages.append(Db2TableUsage(
                    table_name=t.table_name, schema=t.schema,
                    operations=("SELECT",), read_columns=sem.read_columns,
                ))
            return usages

        if stype == SqlStatementType.INSERT and stmt.insert is not None:
            table = stmt.insert.table
            if table is not None:
                usages.append(Db2TableUsage(
                    table_name=table.table_name, schema=table.schema,
                    operations=("INSERT",), write_columns=sem.write_columns,
                ))
            return usages

        if stype == SqlStatementType.UPDATE and stmt.update is not None:
            table = stmt.update.table
            if table is not None:
                usages.append(Db2TableUsage(
                    table_name=table.table_name, schema=table.schema,
                    operations=("UPDATE",),
                    read_columns=sem.read_columns,
                    write_columns=sem.write_columns,
                ))
            return usages

        if stype == SqlStatementType.DELETE and stmt.delete is not None:
            table = stmt.delete.table
            if table is not None:
                usages.append(Db2TableUsage(
                    table_name=table.table_name, schema=table.schema,
                    operations=("DELETE",), read_columns=sem.read_columns,
                ))
            return usages

        if stype == SqlStatementType.DECLARE_CURSOR and stmt.cursor is not None:
            query = stmt.cursor.query
            if query is not None:
                for t in query.from_tables:
                    usages.append(Db2TableUsage(
                        table_name=t.table_name, schema=t.schema,
                        operations=("SELECT",), read_columns=sem.read_columns,
                    ))
            return usages

        return usages

    # ------------------------------------------------------------------
    # Program-level aggregation
    # ------------------------------------------------------------------

    def aggregate_host_variables(
        self,
        stmt_semantics: list[Db2StmtSemantic],
    ) -> tuple[SqlHostVariableSemantic, ...]:
        """Aggregate per-statement host variables into a program registry."""
        directions: dict[str, set[str]] = {}
        indicators: dict[str, str] = {}
        positions: dict[str, int] = {}
        order = 0

        for sem in stmt_semantics:
            for hv in sem.host_variables:
                directions.setdefault(hv.name, set()).add(hv.direction.value)
                if hv.indicator:
                    indicators.setdefault(hv.name, hv.indicator)
                positions.setdefault(hv.name, order)
                order += 1

        def merged(roles: set[str]) -> Db2BindingDirection:
            if {Db2BindingDirection.INPUT.value, Db2BindingDirection.OUTPUT.value} <= roles:
                return Db2BindingDirection.IN_OUT
            if Db2BindingDirection.OUTPUT.value in roles:
                return Db2BindingDirection.OUTPUT
            if Db2BindingDirection.INPUT.value in roles:
                return Db2BindingDirection.INPUT
            if Db2BindingDirection.UNKNOWN.value in roles:
                return Db2BindingDirection.UNKNOWN
            return Db2BindingDirection.INPUT

        result: list[SqlHostVariableSemantic] = []
        for name in sorted(directions, key=lambda n: positions[n]):
            indicator = indicators.get(name, "")
            result.append(
                SqlHostVariableSemantic(
                    name=name,
                    direction=merged(directions[name]),
                    indicator=indicator,
                    uses_indicator=bool(indicator),
                )
            )
        return tuple(result)

    def program_diagnostics(self, stmt_semantics: list[Db2StmtSemantic]) -> list[str]:
        """Deterministic semantic diagnostics."""
        diagnostics: list[str] = []
        for idx, sem in enumerate(stmt_semantics):
            if sem.is_cursor_operation and not sem.cursor_name:
                diagnostics.append(
                    f"statement[{idx}] cursor operation missing cursor name"
                )
        return diagnostics