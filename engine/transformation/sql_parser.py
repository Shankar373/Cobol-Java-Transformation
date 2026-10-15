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

from engine.transformation.sql_split import split_sql_statements


#: Host-variable reference (``:NAME``) in raw embedded SQL text.
_HOST_VARIABLE_RE = re.compile(r":([A-Z][A-Z0-9-]*)", re.IGNORECASE)

#: Predicate operator token -> ``SqlOperator`` for `_parse_predicate`.
_PREDICATE_OP_MAP = {
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
            EmbeddedSqlBlock with parsed statements; statement texts this
            parser cannot model are preserved in ``unsupported_statements``
            (BL-080) instead of being silently dropped.
        """
        statements: list[SqlStatement] = []
        unsupported: list[str] = []

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
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.SELECT,
                        raw_sql=stmt_text,
                        select=select,
                    ))
                else:
                    unsupported.append(stmt_text)

            # INSERT
            elif upper.startswith("INSERT"):
                insert = self._parse_insert(stmt_text)
                if insert:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.INSERT,
                        raw_sql=stmt_text,
                        insert=insert,
                    ))
                else:
                    unsupported.append(stmt_text)

            # UPDATE
            elif upper.startswith("UPDATE"):
                update = self._parse_update(stmt_text)
                if update:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.UPDATE,
                        raw_sql=stmt_text,
                        update=update,
                    ))
                else:
                    unsupported.append(stmt_text)

            # DELETE
            elif upper.startswith("DELETE"):
                delete = self._parse_delete(stmt_text)
                if delete:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.DELETE,
                        raw_sql=stmt_text,
                        delete=delete,
                    ))
                else:
                    unsupported.append(stmt_text)

            # DECLARE CURSOR
            elif "DECLARE" in upper and "CURSOR" in upper:
                cursor = self._parse_declare_cursor(stmt_text)
                if cursor:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.DECLARE_CURSOR,
                        raw_sql=stmt_text,
                        cursor=cursor,
                    ))
                else:
                    unsupported.append(stmt_text)

            # OPEN cursor
            elif upper.startswith("OPEN"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.OPEN_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))
                else:
                    unsupported.append(stmt_text)

            # FETCH cursor
            elif upper.startswith("FETCH"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.FETCH_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))
                else:
                    unsupported.append(stmt_text)

            # CLOSE cursor
            elif upper.startswith("CLOSE"):
                cursor_name = self._extract_cursor_name(stmt_text)
                if cursor_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.CLOSE_CURSOR,
                        raw_sql=stmt_text,
                        cursor_name=cursor_name,
                    ))
                else:
                    unsupported.append(stmt_text)

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
                if proc_name:
                    statements.append(SqlStatement(
                        statement_type=SqlStatementType.CALL,
                        raw_sql=stmt_text,
                        procedure_name=proc_name,
                    ))
                else:
                    unsupported.append(stmt_text)

            # PREPARE
            elif upper.startswith("PREPARE"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.PREPARE,
                    raw_sql=stmt_text,
                    prepare_statement=stmt_text,
                ))

            # EXECUTE (IMMEDIATE carries its IR flag, BL-080)
            elif upper.startswith("EXECUTE"):
                statements.append(SqlStatement(
                    statement_type=SqlStatementType.EXECUTE,
                    raw_sql=stmt_text,
                    execute_immediate=bool(
                        re.match(r"EXECUTE\s+IMMEDIATE\b", upper)
                    ),
                ))

            # Anything else is preserved, never silently dropped (BL-080).
            else:
                unsupported.append(stmt_text)

        return EmbeddedSqlBlock(
            statements=tuple(statements),
            raw_text=sql_text,
            unsupported_statements=tuple(unsupported),
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
            for match in _HOST_VARIABLE_RE.finditer(stmt.raw_sql):
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
        return split_sql_statements(sql_text)

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

        # Extract WHERE clause (all honest conjuncts, BL-079)
        where_predicate = None
        where_predicates: tuple[SqlPredicate, ...] = ()
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
            parsed_preds = self._parse_predicates(where_text)
            if parsed_preds:
                where_predicate = parsed_preds[0]
                where_predicates = tuple(parsed_preds)

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
            where_predicates=where_predicates,
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

        # Parse WHERE (all honest conjuncts, BL-079)
        where_predicate = None
        where_predicates: tuple[SqlPredicate, ...] = ()
        if where_match:
            where_start = set_start + where_match.start() + 5
            where_text = sql_text[where_start:].strip()
            parsed_preds = self._parse_predicates(where_text)
            if parsed_preds:
                where_predicate = parsed_preds[0]
                where_predicates = tuple(parsed_preds)

        return SqlUpdate(
            table=table,
            assignments=tuple(assignments),
            where_predicate=where_predicate,
            where_predicates=where_predicates,
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

        # Find WHERE clause (all honest conjuncts, BL-079)
        where_predicate = None
        where_predicates: tuple[SqlPredicate, ...] = ()
        where_match = re.search(r"\bWHERE\b", upper[from_match.end():])
        if where_match:
            where_start = from_match.end() + where_match.start() + 5
            where_text = sql_text[where_start:].strip()
            parsed_preds = self._parse_predicates(where_text)
            if parsed_preds:
                where_predicate = parsed_preds[0]
                where_predicates = tuple(parsed_preds)

        return SqlDelete(
            table=table,
            where_predicate=where_predicate,
            where_predicates=where_predicates,
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

    def _mask_literals(self, text: str) -> str:
        """Blank out quoted literal spans (same length) so keyword and
        operator searches never match inside data values."""
        out: list[str] = []
        in_quote = False
        quote_char = ""
        for ch in text:
            if in_quote:
                out.append(" ")
                if ch == quote_char:
                    in_quote = False
                continue
            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                out.append(" ")
                continue
            out.append(ch)
        return "".join(out)

    def _split_where_conjuncts(self, text: str) -> list[str]:
        """Split WHERE text on top-level ``AND``/``OR`` tokens.

        Quote- and paren-aware; the ``AND`` belonging to a
        ``BETWEEN low AND high`` range is not a split point (BL-079).
        Returns the non-empty stripped segments.
        """
        depth = 0
        in_quote = False
        quote_char = ""
        between_pending = False
        word_start = -1
        segments: list[str] = []
        last = 0
        i = 0
        n = len(text)

        def handle_word(end: int, start: int) -> bool:
            """True when the word ending at ``end`` is a split point."""
            nonlocal between_pending
            word = text[start:end].upper()
            if word == "BETWEEN":
                between_pending = True
                return False
            if word == "AND" and between_pending:
                between_pending = False
                return False
            return word in ("AND", "OR")

        while i < n:
            ch = text[i]
            if in_quote:
                if ch == quote_char:
                    in_quote = False
                i += 1
                continue
            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                word_start = -1
                i += 1
                continue
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                depth = max(0, depth - 1)
                i += 1
                continue
            if ch.isalnum() or ch in "_-":
                if word_start < 0:
                    word_start = i
                i += 1
                continue
            if depth == 0 and word_start >= 0 and handle_word(i, word_start):
                segments.append(text[last:word_start].strip())
                last = i
            word_start = -1
            i += 1

        if depth == 0 and word_start >= 0 and handle_word(n, word_start):
            segments.append(text[last:word_start].strip())
            last = n
        tail = text[last:].strip()
        if tail:
            segments.append(tail)
        return segments

    def _find_top_level_and(self, text: str) -> int:
        """Character index of the first top-level ``AND`` token (-1 if none).

        Quote- and paren-aware; words inside literals or groups never match.
        """
        depth = 0
        in_quote = False
        quote_char = ""
        word_start = -1
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if in_quote:
                if ch == quote_char:
                    in_quote = False
                i += 1
                continue
            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                word_start = -1
                i += 1
                continue
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                depth = max(0, depth - 1)
                i += 1
                continue
            if ch.isalnum() or ch in "_-":
                if word_start < 0:
                    word_start = i
                i += 1
                continue
            if depth == 0 and word_start >= 0 and text[word_start:i].upper() == "AND":
                return word_start
            word_start = -1
            i += 1
        if depth == 0 and word_start >= 0 and text[word_start:].upper() == "AND":
            return word_start
        return -1

    def _is_simple_operand(self, text: str) -> bool:
        """True for a single column ref, quoted literal, host variable or number.

        Anything else (compound text, parenthesized sub-expressions,
        function calls) is NOT representable by this parser's operand
        fields and must never be fabricated into a column name (BL-079).
        """
        t = text.strip()
        if not t:
            return False
        if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
            return True
        if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
            return True
        return re.fullmatch(
            r":?[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)?", t
        ) is not None

    def _parse_simple_predicate(self, text: str) -> SqlPredicate | None:
        """Parse one conjunct (no AND/OR left at top level) honestly.

        Operator/keyword positions are located on the literal-masked
        uppercase copy; operands are sliced from the ORIGINAL text so
        string literals and host-variable names survive verbatim
        (BL-078). An unparseable conjunct yields ``None`` — never a
        fabricated column name (BL-079).
        """
        if not text or not text.strip():
            return None

        masked = self._mask_literals(text)
        upper = masked.upper()

        # BETWEEN low AND high — one conjunct; its AND is not a split.
        between_match = re.search(r"\bBETWEEN\b", upper)
        if between_match:
            left_text = text[:between_match.start()].strip()
            bounds = text[between_match.end():].strip()
            split = self._find_top_level_and(bounds)
            if split < 0:
                return None
            low = bounds[:split].strip()
            high = bounds[split + 3:].strip()
            if not all(
                self._is_simple_operand(t) for t in (left_text, low, high)
            ):
                return None
            return SqlPredicate(
                left=self._parse_expression(left_text),
                operator=SqlOperator.BETWEEN,
                left_operand=self._parse_expression(low),
                right_operand=self._parse_expression(high),
            )

        # IN (v1, v2, ...) — items go to right_list, never a fake column.
        in_match = re.search(r"\bIN\b", upper)
        if in_match:
            left_text = text[:in_match.start()].strip()
            items_text = text[in_match.end():].strip()
            if not items_text.startswith("(") or not items_text.endswith(")"):
                return None
            items = [p.strip() for p in items_text[1:-1].split(",") if p.strip()]
            if not self._is_simple_operand(left_text) or not items:
                return None
            if not all(self._is_simple_operand(p) for p in items):
                return None
            return SqlPredicate(
                left=self._parse_expression(left_text),
                operator=SqlOperator.IN,
                right_list=tuple(self._parse_expression(p) for p in items),
            )

        # Simple comparison operators (first operator wins; operands must
        # be simple or the conjunct is honestly unparsed).
        for op_str in ["<>", ">=", "<=", "=", ">", "<"]:
            idx = upper.find(op_str)
            if idx < 0:
                continue
            left_text = text[:idx].strip()
            right_text = text[idx + len(op_str):].strip()
            if not self._is_simple_operand(left_text):
                return None
            if not self._is_simple_operand(right_text):
                return None
            return SqlPredicate(
                left=self._parse_expression(left_text),
                operator=_PREDICATE_OP_MAP.get(op_str, SqlOperator.EQUALS),
                right=self._parse_expression(right_text),
            )

        like_match = re.search(r"\bLIKE\b", upper)
        if like_match:
            left_text = text[:like_match.start()].strip()
            right_text = text[like_match.end():].strip()
            if not self._is_simple_operand(left_text):
                return None
            if not self._is_simple_operand(right_text):
                return None
            return SqlPredicate(
                left=self._parse_expression(left_text),
                operator=SqlOperator.LIKE,
                right=self._parse_expression(right_text),
            )

        # NULL checks (operands sliced from the original text, BL-078)
        not_null_match = re.search(r"\bIS\s+NOT\s+NULL\b", upper)
        if not_null_match:
            col_text = text[:not_null_match.start()].strip()
            if self._is_simple_operand(col_text):
                return SqlPredicate(
                    left=self._parse_expression(col_text),
                    operator=SqlOperator.IS_NOT_NULL,
                )
            return None
        null_match = re.search(r"\bIS\s+NULL\b", upper)
        if null_match:
            col_text = text[:null_match.start()].strip()
            if self._is_simple_operand(col_text):
                return SqlPredicate(
                    left=self._parse_expression(col_text),
                    operator=SqlOperator.IS_NULL,
                )
            return None

        return None

    def _parse_predicates(self, text: str) -> list[SqlPredicate]:
        """Parse WHERE text into its honest conjunct list (BL-079).

        Top-level AND/OR segments are parsed individually; conjuncts this
        parser cannot represent are skipped rather than fabricated.
        """
        results: list[SqlPredicate] = []
        for segment in self._split_where_conjuncts(text):
            pred = self._parse_simple_predicate(segment)
            if pred is not None:
                results.append(pred)
        return results

    def _parse_predicate(self, text: str) -> SqlPredicate | None:
        """First honest conjunct of a WHERE text (compatibility view)."""
        preds = self._parse_predicates(text)
        return preds[0] if preds else None

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

        # Column reference (unquoted identifiers fold to uppercase per
        # DB2 rules; literals/host variables keep their source case).
        table_name = ""
        col_name = text
        if "." in text:
            parts = text.split(".")
            table_name = parts[0].upper()
            col_name = parts[1].upper()
        else:
            col_name = text.upper()

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
