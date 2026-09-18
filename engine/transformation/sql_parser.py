"""SQL parser for embedded SQL / DB2 semantic extraction.

Parses embedded SQL statements within COBOL EXEC SQL ... END-EXEC blocks.
Extracts semantic SQL IR for:
- SELECT, INSERT, UPDATE, DELETE
- Host variables
- Table/column references
- Cursors
- Transactions (COMMIT, ROLLBACK)
- DB2 dependencies

This is NOT a complete SQL parser. It handles only the supported subset
for semantic extraction.
"""

from __future__ import annotations

import re

from engine.transformation.ir import (
    Db2TableDependency,
    EmbeddedSqlBlock,
    SqlColumnReference,
    SqlCursor,
    SqlDelete,
    SqlExpression,
    SqlHostVariable,
    SqlInsert,
    SqlOrderBy,
    SqlOperator,
    SqlSelect,
    SqlStatement,
    SqlStatementType,
    SqlTableReference,
    SqlTransactionOperation,
    SqlUpdate,
    SqlPredicate,
)


class SqlParser:
    """Parse embedded SQL statements into SQL IR.

    Usage:
        parser = SqlParser()
        block = parser.parse_embedded_sql(sql_text)
    """

    def parse_embedded_sql(self, sql_text: str) -> EmbeddedSqlBlock:
        """Parse an embedded SQL block (between EXEC SQL and END-EXEC).

        Args:
            sql_text: the SQL text (without EXEC SQL/END-EXEC markers)

        Returns:
            EmbeddedSqlBlock with parsed statements
        """
        statements: list[SqlStatement] = []
        cursor_declarations: list[SqlCursor] = []

        # Split into individual statements
        stmts = self._split_statements(sql_text)

        for stmt_text in stmts:
            stmt_text = stmt_text.strip()
            if not stmt_text:
                continue

            upper = stmt_text.upper()

            # SELECT
            if upper.startswith("SELECT"):
                select = self._parse_select(stmt_text)
                if select:
                    stmt_type = SqlStatementType.SELECT
                    if select.into_variables:
                        stmt_type = SqlStatementType.SELECT
                    statements.append(SqlStatement(
                        statement_type=stmt_type,
                        raw_sql=stmt_text,
                        select=select,
                    ))

            # INSERT
            elif upper.startswith("INSERT"):
                insert = self._parse_insert(stmt_text)
                if insert:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.INSERT,
                        raw_sql=stmt_text,
                        insert=insert,
                    ))

            # UPDATE
            elif upper.startswith("UPDATE"):
                update = self._parse_update(stmt_text)
                if update:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.UPDATE,
                        raw_sql=stmt_text,
                        update=update,
                    ))

            # DELETE
            elif upper.startswith("DELETE"):
                delete = self._parse_delete(stmt_text)
                if delete:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.DELETE,
                        raw_sql=stmt_text,
                        delete=delete,
                    ))

            # DECLARE CURSOR
            elif "DECLARE" in upper and "CURSOR" in upper:
                cursor = self._parse_declare_cursor(stmt_text)
                if cursor:
                    cursor_declarations.append(cursor)
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.DECLARE_CURSOR,
                        raw_sql=stmt_text,
                        cursor=cursor,
                    ))

            # OPEN cursor
            elif upper.startswith("OPEN"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.OPEN_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))

            # FETCH cursor
            elif upper.startswith("FETCH"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.FETCH_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))

            # CLOSE cursor
            elif upper.startswith("CLOSE"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.CLOSE_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))

            # COMMIT
            elif upper.startswith("COMMIT"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.COMMIT,
                    raw_sql=stmt_text,
                    transaction=SqlTransactionOperation(operation="COMMIT"),
                ))

            # ROLLBACK
            elif upper.startswith("ROLLBACK"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.ROLLBACK,
                    raw_sql=stmt_text,
                    transaction=SqlTransactionOperation(operation="ROLLBACK"),
                ))

            # CALL
            elif upper.startswith("CALL"):
                proc_name = self._extract_procedure_name(stmt_text)
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.CALL,
                    raw_sql=stmt_text,
                    procedure_name=proc_name,
                ))

            # PREPARE
            elif upper.startswith("PREPARE"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.PREPARE,
                    raw_sql=stmt_text,
                    prepare_statement=stmt_text,
                ))

            # EXECUTE
            elif upper.startswith("EXECUTE"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.EXECUTE,
                    raw_sql=stmt_text,
                ))

        return EmbeddedSqlBlock(
            statements=tuple(statements),
            raw_text=sql_text,
        )

    def extract_host_variables(self, block: EmbeddedSqlBlock) -> list[SqlHostVariable]:
        """Extract all host variables from an embedded SQL block."""
        host_vars: list[SqlHostVariable] = []
        seen: set[str] = set()

        for stmt in block.statements:
            # Extract from SELECT INTO
            if stmt.select and stmt.select.into_variables:
                for hv in stmt.select.into_variables:
                    if hv.name not in seen:
                        host_vars.append(hv)
                        seen.add(hv.name)

            # Extract from raw SQL using regex
            pattern = re.compile(r":([A-Z][A-Z0-9-]*)", re.IGNORECASE)
            for match in pattern.finditer(stmt.raw_sql):
                var_name = match.group(1)
                if var_name not in seen:
                    host_vars.append(SqlHostVariable(name=var_name))
                    seen.add(var_name)

        return host_vars

    def extract_table_dependencies(
        self,
        block: EmbeddedSqlBlock,
        program_id: str,
    ) -> list[Db2TableDependency]:
        """Extract DB2 table dependencies from an embedded SQL block."""
        deps: list[Db2TableDependency] = []

        for stmt in block.statements:
            if stmt.select:
                for table in stmt.select.from_tables:
                    columns = [col.column_name for col in stmt.select.columns]
                    deps.append(Db2TableDependency(
                        program_id=program_id,
                        table_name=table.table_name,
                        schema=table.schema,
                        operation="READ",
                        columns=tuple(columns),
                    ))

            elif stmt.insert and stmt.insert.table:
                columns = [col.column_name for col in stmt.insert.columns]
                deps.append(Db2TableDependency(
                    program_id=program_id,
                    table_name=stmt.insert.table.table_name,
                    schema=stmt.insert.table.schema,
                    operation="INSERT",
                    columns=tuple(columns),
                ))

            elif stmt.update and stmt.update.table:
                columns = [col.column_name for col, _ in stmt.update.assignments]
                deps.append(Db2TableDependency(
                    program_id=program_id,
                    table_name=stmt.update.table.table_name,
                    schema=stmt.update.table.schema,
                    operation="UPDATE",
                    columns=tuple(columns),
                ))

            elif stmt.delete and stmt.delete.table:
                deps.append(Db2TableDependency(
                    program_id=program_id,
                    table_name=stmt.delete.table.table_name,
                    schema=stmt.delete.table.schema,
                    operation="DELETE",
                ))

        return deps

    def _split_statements(self, sql_text: str) -> list[str]:
        """Split SQL text into individual statements."""
        # Simple split by semicolon, respecting quoted strings
        stmts: list[str] = []
        current: list[str] = []
        in_quote = False
        quote_char = ""

        for ch in sql_text:
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
                stmts.append("".join(current))
                current = []
            else:
                current.append(ch)

        if current:
            stmts.append("".join(current))

        return stmts

    def _parse_select(self, sql_text: str) -> SqlSelect | None:
        """Parse a SELECT statement."""
        upper = sql_text.upper()

        # Find SELECT keyword
        select_match = re.search(r"SELECT\s+(DISTINCT\s+)?", upper)
        if not select_match:
            return None

        distinct = select_match.group(1) is not None
        start_pos = select_match.end()

        # Find FROM keyword
        from_match = re.search(r"\bFROM\b", upper[start_pos:])
        if not from_match:
            return None

        # Extract columns
        cols_text = sql_text[start_pos:start_pos + from_match.start()].strip()

        # Find INTO clause (for SELECT INTO) - between SELECT and FROM
        into_variables: tuple[SqlHostVariable, ...] = ()
        into_match = re.search(r"\bINTO\b", upper[start_pos:start_pos + from_match.start()])
        if into_match:
            into_pos = start_pos + into_match.start()
            # Extract host variables after INTO (until FROM)
            into_text = sql_text[into_pos + 5:start_pos + from_match.start()].strip()
            into_variables = tuple(self._parse_host_variable_list(into_text))
            # Remove INTO clause from columns text
            cols_text = cols_text[:into_match.start()].strip()

        columns = self._parse_column_list(cols_text)

        # Extract tables from FROM clause
        from_start = start_pos + from_match.start() + 4
        where_match = re.search(r"\bWHERE\b", upper[from_start:])
        join_match = re.search(r"\b(?:INNER\s+)?JOIN\b", upper[from_start:])

        if where_match:
            tables_text = sql_text[from_start:from_start + where_match.start()].strip()
        elif join_match:
            tables_text = sql_text[from_start:from_start + join_match.start()].strip()
        else:
            tables_text = sql_text[from_start:].strip()

        from_tables = self._parse_table_list(tables_text)

        # Extract WHERE clause
        where_predicate = None
        if where_match:
            where_start = from_start + where_match.start() + 5
            # Find end of WHERE (GROUP BY, ORDER BY, FETCH FIRST, or end)
            end_match = re.search(
                r"\b(?:GROUP\s+BY|ORDER\s+BY|FETCH\s+FIRST|HAVING)\b",
                upper[where_start:],
            )
            if end_match:
                where_text = sql_text[where_start:where_start + end_match.start()].strip()
            else:
                where_text = sql_text[where_start:].strip()
            where_predicate = self._parse_predicate(where_text)

        # Extract ORDER BY
        order_by: tuple[SqlOrderBy, ...] = ()
        order_match = re.search(r"\bORDER\s+BY\b", upper)
        if order_match:
            order_start = order_match.end()
            order_text = sql_text[order_start:].strip()
            order_by = self._parse_order_by(order_text)

        # Extract GROUP BY
        group_by: tuple[SqlGroupBy, ...] = ()
        group_match = re.search(r"\bGROUP\s+BY\b", upper)
        if group_match:
            group_start = group_match.end()
            group_text = sql_text[group_start:].strip()
            # Find end of GROUP BY
            having_match = re.search(r"\bHAVING\b", upper[group_start:])
            if having_match:
                group_text = sql_text[group_start:group_start + having_match.start()].strip()
            group_by = self._parse_group_by(group_text)

        # Extract FETCH FIRST
        fetch_first = None
        fetch_match = re.search(r"FETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY", upper)
        if fetch_match:
            fetch_first = int(fetch_match.group(1))

        return SqlSelect(
            columns=tuple(columns),
            into_variables=into_variables,
            from_tables=tuple(from_tables),
            where_predicate=where_predicate,
            order_by=order_by,
            group_by=group_by,
            distinct=distinct,
            fetch_first=fetch_first,
        )

    def _parse_insert(self, sql_text: str) -> SqlInsert | None:
        """Parse an INSERT statement."""
        upper = sql_text.upper()

        # Find INTO keyword
        into_match = re.search(r"INSERT\s+INTO\s+(\S+)", upper)
        if not into_match:
            return None

        table_name = into_match.group(1).rstrip(".")
        schema = ""
        if "." in table_name:
            parts = table_name.split(".")
            schema = parts[0]
            table_name = parts[1]

        table = SqlTableReference(table_name=table_name, schema=schema)

        # Find columns
        columns: tuple[SqlColumnReference, ...] = ()
        col_match = re.search(r"\(([^)]+)\)", sql_text[into_match.end():])
        if col_match:
            col_text = col_match.group(1)
            columns = tuple(self._parse_column_list(col_text))

        # Find VALUES
        values: tuple[SqlExpression, ...] = ()
        values_match = re.search(r"\bVALUES\s*\(([^)]+)\)", upper)
        if values_match:
            values_text = values_match.group(1)
            values = tuple(self._parse_expression_list(values_text))

        return SqlInsert(
            table=table,
            columns=columns,
            values=values,
        )

    def _parse_update(self, sql_text: str) -> SqlUpdate | None:
        """Parse an UPDATE statement."""
        upper = sql_text.upper()

        # Find table name
        update_match = re.search(r"UPDATE\s+(\S+)", upper)
        if not update_match:
            return None

        table_name = update_match.group(1)
        schema = ""
        if "." in table_name:
            parts = table_name.split(".")
            schema = parts[0]
            table_name = parts[1]

        table = SqlTableReference(table_name=table_name, schema=schema)

        # Find SET clause
        set_match = re.search(r"\bSET\b", upper)
        if not set_match:
            return None

        set_start = set_match.end()

        # Find WHERE clause
        where_match = re.search(r"\bWHERE\b", upper[set_start:])

        if where_match:
            set_text = sql_text[set_start:set_start + where_match.start()].strip()
        else:
            set_text = sql_text[set_start:].strip()

        # Parse assignments
        assignments = self._parse_assignments(set_text)

        # Parse WHERE
        where_predicate = None
        if where_match:
            where_start = set_start + where_match.start() + 5
            where_text = sql_text[where_start:].strip()
            where_predicate = self._parse_predicate(where_text)

        return SqlUpdate(
            table=table,
            assignments=tuple(assignments),
            where_predicate=where_predicate,
        )

    def _parse_delete(self, sql_text: str) -> SqlDelete | None:
        """Parse a DELETE statement."""
        upper = sql_text.upper()

        # Find FROM keyword
        from_match = re.search(r"DELETE\s+FROM\s+(\S+)", upper)
        if not from_match:
            return None

        table_name = from_match.group(1)
        schema = ""
        if "." in table_name:
            parts = table_name.split(".")
            schema = parts[0]
            table_name = parts[1]

        table = SqlTableReference(table_name=table_name, schema=schema)

        # Find WHERE clause
        where_predicate = None
        where_match = re.search(r"\bWHERE\b", upper[from_match.end():])
        if where_match:
            where_start = from_match.end() + where_match.start() + 5
            where_text = sql_text[where_start:].strip()
            where_predicate = self._parse_predicate(where_text)

        return SqlDelete(
            table=table,
            where_predicate=where_predicate,
        )

    def _parse_declare_cursor(self, sql_text: str) -> SqlCursor | None:
        """Parse a DECLARE CURSOR statement."""
        upper = sql_text.upper()

        # Find cursor name
        match = re.search(r"DECLARE\s+(\S+)\s+CURSOR(?:\s+WITH\s+HOLD)?\s+FOR", upper)
        if not match:
            return None

        cursor_name = match.group(1)

        # Check for WITH HOLD
        is_hold = "WITH HOLD" in upper

        # Parse the query (everything after FOR)
        query_start = match.end()
        query_text = sql_text[query_start:].strip()

        # Parse the SELECT query
        select = self._parse_select(query_text) if query_text.upper().startswith("SELECT") else None

        return SqlCursor(
            name=cursor_name,
            query=select,
            is_hold=is_hold,
        )

    def _extract_cursor_name(self, sql_text: str) -> str:
        """Extract cursor name from OPEN/FETCH/CLOSE statement."""
        upper = sql_text.upper()
        match = re.search(r"(?:OPEN|FETCH|CLOSE)\s+(\S+)", upper)
        if match:
            return match.group(1)
        return ""

    def _extract_procedure_name(self, sql_text: str) -> str:
        """Extract procedure name from CALL statement."""
        upper = sql_text.upper()
        match = re.search(r"CALL\s+(\S+)", upper)
        if match:
            return match.group(1)
        return ""

    def _parse_column_list(self, text: str) -> list[SqlColumnReference]:
        """Parse a comma-separated column list."""
        columns: list[SqlColumnReference] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if not part or part == "*":
                continue

            # Check for alias (AS or space)
            as_match = re.search(r"\bAS\s+(\S+)", part, re.IGNORECASE)
            if as_match:
                col_name = part[:as_match.start()].strip()
                alias = as_match.group(1)
            else:
                parts2 = part.split()
                if len(parts2) >= 2:
                    col_name = parts2[0]
                    alias = parts2[1]
                else:
                    col_name = part
                    alias = ""

            # Check for table qualifier
            table_name = ""
            if "." in col_name:
                tparts = col_name.split(".")
                table_name = tparts[0]
                col_name = tparts[1]

            columns.append(SqlColumnReference(
                column_name=col_name,
                table_name=table_name,
                alias=alias,
            ))

        return columns

    def _parse_table_list(self, text: str) -> list[SqlTableReference]:
        """Parse a comma-separated table list."""
        tables: list[SqlTableReference] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check for alias
            as_match = re.search(r"\bAS\s+(\S+)", part, re.IGNORECASE)
            if as_match:
                table_name = part[:as_match.start()].strip()
                alias = as_match.group(1)
            else:
                parts2 = part.split()
                table_name = parts2[0]
                alias = parts2[1] if len(parts2) >= 2 else ""

            schema = ""
            if "." in table_name:
                sparts = table_name.split(".")
                schema = sparts[0]
                table_name = sparts[1]

            tables.append(SqlTableReference(
                table_name=table_name,
                schema=schema,
                alias=alias,
            ))

        return tables

    def _parse_host_variable_list(self, text: str) -> list[SqlHostVariable]:
        """Parse a comma-separated host variable list."""
        host_vars: list[SqlHostVariable] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Remove leading colon
            if part.startswith(":"):
                part = part[1:]

            # Check for indicator
            indicator = ""
            has_indicator = False
            if " :" in part:
                idx = part.index(" :")
                indicator = part[idx + 2:].strip()
                part = part[:idx].strip()
                has_indicator = True

            host_vars.append(SqlHostVariable(
                name=part,
                indicator=indicator,
                has_indicator=has_indicator,
            ))

        return host_vars

    def _parse_predicate(self, text: str) -> SqlPredicate | None:
        """Parse a WHERE predicate."""
        if not text:
            return None

        # Simple predicate parsing
        # Handle: column = value, column <> value, etc.
        for op_str in ["<>", ">=", "<=", "=", ">", "<", "LIKE", "IN", "BETWEEN"]:
            if f" {op_str} " in text.upper():
                parts = text.upper().split(f" {op_str} ", 1)
                if len(parts) == 2:
                    left_text = parts[0].strip()
                    right_text = parts[1].strip()

                    left_expr = self._parse_expression(left_text)
                    right_expr = self._parse_expression(right_text)

                    op_map = {
                        "=": SqlOperator.EQUALS,
                        "<>": SqlOperator.NOT_EQUALS,
                        ">": SqlOperator.GREATER,
                        "<": SqlOperator.LESS,
                        ">=": SqlOperator.GREATER_EQUALS,
                        "<=": SqlOperator.LESS_EQUALS,
                        "LIKE": SqlOperator.LIKE,
                        "IN": SqlOperator.IN,
                        "BETWEEN": SqlOperator.BETWEEN,
                    }

                    return SqlPredicate(
                        left=left_expr,
                        operator=op_map.get(op_str, SqlOperator.EQUALS),
                        right=right_expr,
                    )

        # Check for NULL
        upper = text.upper()
        if "IS NULL" in upper:
            col_text = upper.replace("IS NULL", "").strip()
            col_expr = self._parse_expression(col_text)
            return SqlPredicate(
                left=col_expr,
                operator=SqlOperator.IS_NULL,
            )
        elif "IS NOT NULL" in upper:
            col_text = upper.replace("IS NOT NULL", "").strip()
            col_expr = self._parse_expression(col_text)
            return SqlPredicate(
                left=col_expr,
                operator=SqlOperator.IS_NOT_NULL,
            )

        return None

    def _parse_expression(self, text: str) -> SqlExpression:
        """Parse a SQL expression (column, literal, or host variable)."""
        text = text.strip()

        # Host variable
        if text.startswith(":"):
            return SqlExpression(
                host_variable=SqlHostVariable(name=text[1:]),
            )

        # Literal
        if text.startswith("'") and text.endswith("'"):
            return SqlExpression(literal=text[1:-1])

        # Numeric literal
        if text.replace(".", "").replace("-", "").isdigit():
            return SqlExpression(literal=text)

        # Column reference
        table_name = ""
        col_name = text
        if "." in text:
            parts = text.split(".")
            table_name = parts[0]
            col_name = parts[1]

        return SqlExpression(
            column=SqlColumnReference(
                column_name=col_name,
                table_name=table_name,
            ),
        )

    def _parse_expression_list(self, text: str) -> list[SqlExpression]:
        """Parse a comma-separated expression list."""
        expressions: list[SqlExpression] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if part:
                expressions.append(self._parse_expression(part))

        return expressions

    def _parse_assignments(self, text: str) -> list[tuple[SqlColumnReference, SqlExpression]]:
        """Parse SET clause assignments."""
        assignments: list[tuple[SqlColumnReference, SqlExpression]] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if "=" in part:
                col_text, val_text = part.split("=", 1)
                col = self._parse_expression(col_text.strip())
                val = self._parse_expression(val_text.strip())
                if col.column:
                    assignments.append((col.column, val))

        return assignments

    def _parse_order_by(self, text: str) -> tuple[SqlOrderBy, ...]:
        """Parse ORDER BY clause."""
        order_items: list[SqlOrderBy] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            ascending = True
            if " DESC" in part.upper():
                ascending = False
                part = part.upper().replace(" DESC", "").strip()
            elif " ASC" in part.upper():
                part = part.upper().replace(" ASC", "").strip()

            col = self._parse_expression(part)
            if col.column:
                order_items.append(SqlOrderBy(
                    column=col.column,
                    ascending=ascending,
                ))

        return tuple(order_items)

    def _parse_group_by(self, text: str) -> tuple[SqlGroupBy, ...]:
        """Parse GROUP BY clause."""
        from engine.transformation.ir import SqlGroupBy

        group_items: list[SqlGroupBy] = []
        parts = text.split(",")

        for part in parts:
            part = part.strip()
            if not part:
                continue

            col = self._parse_expression(part)
            if col.column:
                group_items.append(SqlGroupBy(column=col.column))

        return tuple(group_items)
