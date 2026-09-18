"""Tests for DB2 / Embedded SQL semantic foundation.

Covers 37 acceptance criteria for:
- SQL IR types (SqlStatementType, SqlSelect, SqlInsert, SqlUpdate, SqlDelete, etc.)
- SQL parser (embedded SQL extraction)
- Host variable extraction
- Table/column references
- Cursors
- Transactions
- DB2 dependency model
- Db2Application aggregation
"""


from engine.transformation.ir import (
    Db2Application,
    Db2TableDependency,
    EmbeddedSqlBlock,
    SqlColumnReference,
    SqlCursor,
    SqlDelete,
    SqlExpression,
    SqlHostVariable,
    SqlInsert,
    SqlJoinType,
    SqlOperator,
    SqlOrderBy,
    SqlPredicate,
    SqlSelect,
    SqlStatement,
    SqlStatementType,
    SqlTableReference,
    SqlTransactionOperation,
    SqlUpdate,
)
from engine.transformation.sql_parser import SqlParser


# ============================================================================
# TEST GROUP 1: IR Type Existence and Attributes
# ============================================================================

class TestSqlStatementTypeEnum:
    """T1: SqlStatementType enum values."""

    def test_select(self):
        assert SqlStatementType.SELECT.value == "SELECT"

    def test_insert(self):
        assert SqlStatementType.INSERT.value == "INSERT"

    def test_update(self):
        assert SqlStatementType.UPDATE.value == "UPDATE"

    def test_delete(self):
        assert SqlStatementType.DELETE.value == "DELETE"

    def test_declare_cursor(self):
        assert SqlStatementType.DECLARE_CURSOR.value == "DECLARE_CURSOR"

    def test_open_cursor(self):
        assert SqlStatementType.OPEN_CURSOR.value == "OPEN_CURSOR"

    def test_fetch_cursor(self):
        assert SqlStatementType.FETCH_CURSOR.value == "FETCH_CURSOR"

    def test_close_cursor(self):
        assert SqlStatementType.CLOSE_CURSOR.value == "CLOSE_CURSOR"

    def test_commit(self):
        assert SqlStatementType.COMMIT.value == "COMMIT"

    def test_rollback(self):
        assert SqlStatementType.ROLLBACK.value == "ROLLBACK"


class TestSqlSelectAttributes:
    """T2: SqlSelect has all required attributes."""

    def test_columns(self):
        sel = SqlSelect(columns=(SqlColumnReference(column_name="COL1"),))
        assert len(sel.columns) == 1
        assert sel.columns[0].column_name == "COL1"

    def test_into_variables(self):
        sel = SqlSelect(into_variables=(SqlHostVariable(name="WS-VAR"),))
        assert len(sel.into_variables) == 1
        assert sel.into_variables[0].name == "WS-VAR"

    def test_from_tables(self):
        sel = SqlSelect(from_tables=(SqlTableReference(table_name="T1"),))
        assert len(sel.from_tables) == 1
        assert sel.from_tables[0].table_name == "T1"

    def test_where_predicate(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="ID")),
            operator=SqlOperator.EQUALS,
            right=SqlExpression(literal="1"),
        )
        sel = SqlSelect(where_predicate=pred)
        assert sel.where_predicate is not None
        assert sel.where_predicate.operator == SqlOperator.EQUALS

    def test_order_by(self):
        sel = SqlSelect(order_by=(SqlOrderBy(column=SqlColumnReference(column_name="COL1"), ascending=True),))
        assert len(sel.order_by) == 1
        assert sel.order_by[0].ascending is True

    def test_group_by(self):
        from engine.transformation.ir import SqlGroupBy
        sel = SqlSelect(group_by=(SqlGroupBy(column=SqlColumnReference(column_name="COL1")),))
        assert len(sel.group_by) == 1

    def test_distinct(self):
        sel = SqlSelect(distinct=True)
        assert sel.distinct is True

    def test_fetch_first(self):
        sel = SqlSelect(fetch_first=10)
        assert sel.fetch_first == 10


class TestSqlInsertAttributes:
    """T3: SqlInsert has all required attributes."""

    def test_table(self):
        ins = SqlInsert(table=SqlTableReference(table_name="T1"))
        assert ins.table.table_name == "T1"

    def test_columns(self):
        ins = SqlInsert(columns=(SqlColumnReference(column_name="COL1"),))
        assert len(ins.columns) == 1

    def test_values(self):
        ins = SqlInsert(values=(SqlExpression(literal="1"),))
        assert len(ins.values) == 1


class TestSqlUpdateAttributes:
    """T4: SqlUpdate has all required attributes."""

    def test_table(self):
        upd = SqlUpdate(table=SqlTableReference(table_name="T1"))
        assert upd.table.table_name == "T1"

    def test_assignments(self):
        upd = SqlUpdate(assignments=(
            (SqlColumnReference(column_name="COL1"), SqlExpression(literal="1")),
        ))
        assert len(upd.assignments) == 1
        assert upd.assignments[0][0].column_name == "COL1"
        assert upd.assignments[0][1].literal == "1"

    def test_where_predicate(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="ID")),
            operator=SqlOperator.EQUALS,
            right=SqlExpression(literal="1"),
        )
        upd = SqlUpdate(where_predicate=pred)
        assert upd.where_predicate is not None


class TestSqlDeleteAttributes:
    """T5: SqlDelete has all required attributes."""

    def test_table(self):
        delete = SqlDelete(table=SqlTableReference(table_name="T1"))
        assert delete.table.table_name == "T1"

    def test_where_predicate(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="ID")),
            operator=SqlOperator.EQUALS,
            right=SqlExpression(literal="1"),
        )
        delete = SqlDelete(where_predicate=pred)
        assert delete.where_predicate is not None


class TestSqlHostVariable:
    """T6: SqlHostVariable attributes."""

    def test_name(self):
        hv = SqlHostVariable(name="WS-CUSTOMER-ID")
        assert hv.name == "WS-CUSTOMER-ID"

    def test_indicator(self):
        hv = SqlHostVariable(name="WS-VAR", indicator="WS-IND", has_indicator=True)
        assert hv.indicator == "WS-IND"
        assert hv.has_indicator is True


class TestSqlCursor:
    """T7: SqlCursor attributes."""

    def test_name(self):
        cursor = SqlCursor(name="C1")
        assert cursor.name == "C1"

    def test_query(self):
        sel = SqlSelect(columns=(SqlColumnReference(column_name="COL1"),))
        cursor = SqlCursor(name="C1", query=sel)
        assert cursor.query is not None

    def test_is_hold(self):
        cursor = SqlCursor(name="C1", is_hold=True)
        assert cursor.is_hold is True


class TestSqlTransactionOperation:
    """T8: SqlTransactionOperation attributes."""

    def test_commit(self):
        txn = SqlTransactionOperation(operation="COMMIT")
        assert txn.operation == "COMMIT"

    def test_rollback(self):
        txn = SqlTransactionOperation(operation="ROLLBACK")
        assert txn.operation == "ROLLBACK"


class TestSqlStatement:
    """T9: SqlStatement attributes."""

    def test_select(self):
        sel = SqlSelect(columns=(SqlColumnReference(column_name="COL1"),))
        stmt = SqlStatement(
            statement_type=SqlStatementType.SELECT,
            raw_sql="SELECT COL1 FROM T1",
            select=sel,
        )
        assert stmt.statement_type == SqlStatementType.SELECT
        assert stmt.select is not None

    def test_insert(self):
        ins = SqlInsert(table=SqlTableReference(table_name="T1"))
        stmt = SqlStatement(
            statement_type=SqlStatementType.INSERT,
            raw_sql="INSERT INTO T1 VALUES (1)",
            insert=ins,
        )
        assert stmt.insert is not None

    def test_update(self):
        upd = SqlUpdate(table=SqlTableReference(table_name="T1"))
        stmt = SqlStatement(
            statement_type=SqlStatementType.UPDATE,
            raw_sql="UPDATE T1 SET COL1=1",
            update=upd,
        )
        assert stmt.update is not None

    def test_delete(self):
        delete = SqlDelete(table=SqlTableReference(table_name="T1"))
        stmt = SqlStatement(
            statement_type=SqlStatementType.DELETE,
            raw_sql="DELETE FROM T1 WHERE ID=1",
            delete=delete,
        )
        assert stmt.delete is not None

    def test_cursor(self):
        cursor = SqlCursor(name="C1")
        stmt = SqlStatement(
            statement_type=SqlStatementType.DECLARE_CURSOR,
            raw_sql="DECLARE C1 CURSOR FOR SELECT 1",
            cursor=cursor,
        )
        assert stmt.cursor is not None

    def test_transaction(self):
        txn = SqlTransactionOperation(operation="COMMIT")
        stmt = SqlStatement(
            statement_type=SqlStatementType.COMMIT,
            raw_sql="COMMIT",
            transaction=txn,
        )
        assert stmt.transaction is not None


class TestEmbeddedSqlBlock:
    """T10: EmbeddedSqlBlock attributes."""

    def test_statements(self):
        stmts = (
            SqlStatement(
                statement_type=SqlStatementType.SELECT,
                raw_sql="SELECT 1",
                select=SqlSelect(),
            ),
        )
        block = EmbeddedSqlBlock(statements=stmts, raw_text="SELECT 1")
        assert len(block.statements) == 1

    def test_raw_text(self):
        block = EmbeddedSqlBlock(statements=(), raw_text="SELECT 1 FROM T1")
        assert block.raw_text == "SELECT 1 FROM T1"


class TestDb2TableDependency:
    """T11: Db2TableDependency attributes."""

    def test_program_id(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="T1",
            operation="READ",
        )
        assert dep.program_id == "PROG1"

    def test_table_name(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="CUSTOMER",
            operation="READ",
        )
        assert dep.table_name == "CUSTOMER"

    def test_schema(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="T1",
            schema="DB2INST1",
            operation="READ",
        )
        assert dep.schema == "DB2INST1"

    def test_operation(self):
        dep = Db2TableDependency(program_id="PROG1", table_name="T1", operation="UPDATE")
        assert dep.operation == "UPDATE"

    def test_columns(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="T1",
            operation="READ",
            columns=("COL1", "COL2"),
        )
        assert dep.columns == ("COL1", "COL2")


class TestDb2Application:
    """T12: Db2Application attributes and methods."""

    def test_program_id(self):
        app = Db2Application(program_id="PROG1")
        assert app.program_id == "PROG1"

    def test_all_statements(self):
        stmt1 = SqlStatement(
            statement_type=SqlStatementType.SELECT,
            raw_sql="SELECT 1",
            select=SqlSelect(),
        )
        stmt2 = SqlStatement(
            statement_type=SqlStatementType.INSERT,
            raw_sql="INSERT INTO T1 VALUES (1)",
            insert=SqlInsert(table=SqlTableReference(table_name="T1")),
        )
        block = EmbeddedSqlBlock(statements=(stmt1, stmt2), raw_text="SELECT 1; INSERT INTO T1 VALUES (1)")
        app = Db2Application(
            program_id="PROG1",
            sql_blocks=(block,),
        )
        assert len(app._all_statements()) == 2

    def test_get_tables(self):
        dep1 = Db2TableDependency(
            program_id="PROG1",
            table_name="CUSTOMER",
            operation="READ",
        )
        dep2 = Db2TableDependency(
            program_id="PROG1",
            table_name="ORDERS",
            operation="READ",
        )
        app = Db2Application(
            program_id="PROG1",
            table_dependencies=(dep1, dep2),
        )
        tables = app.get_tables()
        assert "CUSTOMER" in tables
        assert "ORDERS" in tables

    def test_get_table_columns(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="CUSTOMER",
            operation="READ",
            columns=("ID", "NAME"),
        )
        app = Db2Application(
            program_id="PROG1",
            table_dependencies=(dep,),
        )
        cols = app.get_table_columns("CUSTOMER")
        assert "ID" in cols
        assert "NAME" in cols

    def test_get_dependencies(self):
        dep = Db2TableDependency(
            program_id="PROG1",
            table_name="CUSTOMER",
            operation="READ",
        )
        app = Db2Application(
            program_id="PROG1",
            table_dependencies=(dep,),
        )
        deps = app.get_dependencies("CUSTOMER")
        assert len(deps) == 1

    def test_validate(self):
        app = Db2Application(
            program_id="PROG1",
            table_dependencies=(
                Db2TableDependency(
                    program_id="PROG1",
                    table_name="T1",
                    operation="READ",
                ),
            ),
        )
        issues = app.validate()
        assert isinstance(issues, list)


# ============================================================================
# TEST GROUP 2: SQL Parser
# ============================================================================

class TestSqlParserSelect:
    """T13: SQL parser SELECT statements."""

    def test_simple_select(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("SELECT COL1 FROM T1")
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.SELECT
        assert stmt.select is not None
        assert len(stmt.select.columns) == 1
        assert stmt.select.columns[0].column_name == "COL1"
        assert len(stmt.select.from_tables) == 1
        assert stmt.select.from_tables[0].table_name == "T1"

    def test_select_multiple_columns(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("SELECT COL1, COL2, COL3 FROM T1")
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert len(stmt.select.columns) == 3

    def test_select_into(self):
        parser = SqlParser()
        sql = "SELECT COL1 INTO :WS-VAR FROM T1"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert len(stmt.select.into_variables) == 1
        assert stmt.select.into_variables[0].name == "WS-VAR"

    def test_select_where(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 WHERE COL2 = 'VALUE'"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.select.where_predicate is not None
        assert stmt.select.where_predicate.operator == SqlOperator.EQUALS

    def test_select_distinct(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("SELECT DISTINCT COL1 FROM T1")
        stmt = block.statements[0]
        assert stmt.select.distinct is True

    def test_select_order_by(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 ORDER BY COL1 ASC"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert len(stmt.select.order_by) == 1
        assert stmt.select.order_by[0].ascending is True

    def test_select_order_by_desc(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 ORDER BY COL1 DESC"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.select.order_by[0].ascending is False

    def test_select_group_by(self):
        parser = SqlParser()
        sql = "SELECT COL1, COUNT(*) FROM T1 GROUP BY COL1"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert len(stmt.select.group_by) == 1

    def test_select_fetch_first(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 FETCH FIRST 10 ROWS ONLY"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.select.fetch_first == 10

    def test_select_with_table_alias(self):
        parser = SqlParser()
        sql = "SELECT A.COL1 FROM T1 AS A WHERE A.COL1 = 1"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.select.from_tables[0].alias == "A"

    def test_select_star(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("SELECT * FROM T1")
        stmt = block.statements[0]
        assert len(stmt.select.columns) == 0


class TestSqlParserInsert:
    """T14: SQL parser INSERT statements."""

    def test_simple_insert(self):
        parser = SqlParser()
        sql = "INSERT INTO T1 (COL1, COL2) VALUES (:WS-VAR1, :WS-VAR2)"
        block = parser.parse_embedded_sql(sql)
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.INSERT
        assert stmt.insert.table.table_name == "T1"
        assert len(stmt.insert.columns) == 2
        assert len(stmt.insert.values) == 2

    def test_insert_into_table(self):
        parser = SqlParser()
        sql = "INSERT INTO SCHEMA1.T1 (COL1) VALUES ('TEST')"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.insert.table.schema == "SCHEMA1"
        assert stmt.insert.table.table_name == "T1"


class TestSqlParserUpdate:
    """T15: SQL parser UPDATE statements."""

    def test_simple_update(self):
        parser = SqlParser()
        sql = "UPDATE T1 SET COL1 = :WS-VAR WHERE COL2 = 1"
        block = parser.parse_embedded_sql(sql)
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.UPDATE
        assert stmt.update.table.table_name == "T1"
        assert len(stmt.update.assignments) == 1
        assert stmt.update.where_predicate is not None


class TestSqlParserDelete:
    """T16: SQL parser DELETE statements."""

    def test_simple_delete(self):
        parser = SqlParser()
        sql = "DELETE FROM T1 WHERE COL1 = :WS-VAR"
        block = parser.parse_embedded_sql(sql)
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.DELETE
        assert stmt.delete.table.table_name == "T1"
        assert stmt.delete.where_predicate is not None


class TestSqlParserCursor:
    """T17: SQL parser cursor operations."""

    def test_declare_cursor(self):
        parser = SqlParser()
        sql = "DECLARE C1 CURSOR FOR SELECT COL1 FROM T1"
        block = parser.parse_embedded_sql(sql)
        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.DECLARE_CURSOR
        assert stmt.cursor.name == "C1"
        assert stmt.cursor.query is not None

    def test_declare_cursor_with_hold(self):
        parser = SqlParser()
        sql = "DECLARE C1 CURSOR WITH HOLD FOR SELECT COL1 FROM T1"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.cursor.is_hold is True

    def test_open_cursor(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("OPEN C1")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.OPEN_CURSOR
        assert stmt.cursor_name == "C1"

    def test_fetch_cursor(self):
        parser = SqlParser()
        sql = "FETCH C1 INTO :WS-VAR"
        block = parser.parse_embedded_sql(sql)
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.FETCH_CURSOR
        assert stmt.cursor_name == "C1"

    def test_close_cursor(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("CLOSE C1")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.CLOSE_CURSOR
        assert stmt.cursor_name == "C1"


class TestSqlParserTransaction:
    """T18: SQL parser transaction operations."""

    def test_commit(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("COMMIT")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.COMMIT
        assert stmt.transaction.operation == "COMMIT"

    def test_rollback(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("ROLLBACK")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.ROLLBACK
        assert stmt.transaction.operation == "ROLLBACK"


class TestSqlParserHostVariables:
    """T19: SQL parser host variable extraction."""

    def test_extract_from_select_into(self):
        parser = SqlParser()
        sql = "SELECT COL1 INTO :WS-VAR FROM T1"
        block = parser.parse_embedded_sql(sql)
        host_vars = parser.extract_host_variables(block)
        assert len(host_vars) == 1
        assert host_vars[0].name == "WS-VAR"

    def test_extract_from_where(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 WHERE COL1 = :WS-VAR"
        block = parser.parse_embedded_sql(sql)
        host_vars = parser.extract_host_variables(block)
        assert len(host_vars) == 1
        assert host_vars[0].name == "WS-VAR"

    def test_extract_multiple(self):
        parser = SqlParser()
        sql = "SELECT COL1 INTO :WS-OUT FROM T1 WHERE COL2 = :WS-IN"
        block = parser.parse_embedded_sql(sql)
        host_vars = parser.extract_host_variables(block)
        assert len(host_vars) == 2
        names = {hv.name for hv in host_vars}
        assert "WS-OUT" in names
        assert "WS-IN" in names

    def test_extract_no_duplicates(self):
        parser = SqlParser()
        sql = "SELECT COL1 INTO :WS-VAR FROM T1 WHERE COL2 = :WS-VAR"
        block = parser.parse_embedded_sql(sql)
        host_vars = parser.extract_host_variables(block)
        assert len(host_vars) == 1


class TestSqlParserTableDependencies:
    """T20: SQL parser table dependency extraction."""

    def test_select_dependency(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM T1 WHERE COL2 = 1"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert len(deps) == 1
        assert deps[0].program_id == "PROG1"
        assert deps[0].table_name == "T1"
        assert deps[0].operation == "READ"

    def test_insert_dependency(self):
        parser = SqlParser()
        sql = "INSERT INTO T1 (COL1) VALUES ('TEST')"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert len(deps) == 1
        assert deps[0].operation == "INSERT"

    def test_update_dependency(self):
        parser = SqlParser()
        sql = "UPDATE T1 SET COL1 = 'TEST' WHERE COL2 = 1"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert len(deps) == 1
        assert deps[0].operation == "UPDATE"

    def test_delete_dependency(self):
        parser = SqlParser()
        sql = "DELETE FROM T1 WHERE COL1 = 1"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert len(deps) == 1
        assert deps[0].operation == "DELETE"

    def test_multiple_tables(self):
        parser = SqlParser()
        sql = "SELECT T1.COL1, T2.COL2 FROM T1, T2 WHERE T1.ID = T2.ID"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert len(deps) == 2
        table_names = {dep.table_name for dep in deps}
        assert "T1" in table_names
        assert "T2" in table_names

    def test_schema_qualified(self):
        parser = SqlParser()
        sql = "SELECT COL1 FROM DB2INST1.T1"
        block = parser.parse_embedded_sql(sql)
        deps = parser.extract_table_dependencies(block, "PROG1")
        assert deps[0].schema == "DB2INST1"


class TestSqlParserCall:
    """T21: SQL parser CALL statement."""

    def test_call(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("CALL MYPROC")
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.CALL
        assert stmt.procedure_name == "MYPROC"


class TestSqlParserMultipleStatements:
    """T22: SQL parser multiple statements in one block."""

    def test_multiple_statements(self):
        parser = SqlParser()
        sql = """
        SELECT COL1 INTO :WS-VAR FROM T1;
        UPDATE T1 SET COL1 = 'DONE' WHERE COL1 = :WS-VAR;
        COMMIT
        """
        block = parser.parse_embedded_sql(sql)
        assert len(block.statements) == 3
        types = [s.statement_type for s in block.statements]
        assert SqlStatementType.SELECT in types
        assert SqlStatementType.UPDATE in types
        assert SqlStatementType.COMMIT in types


class TestSqlParserEdgeCases:
    """T23: SQL parser edge cases."""

    def test_empty_sql(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("")
        assert len(block.statements) == 0

    def test_whitespace_only(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("   \n  \t  ")
        assert len(block.statements) == 0

    def test_comments_only(self):
        parser = SqlParser()
        block = parser.parse_embedded_sql("-- this is a comment")
        assert len(block.statements) == 0


class TestSqlOperatorEnum:
    """T24: SqlOperator enum values."""

    def test_equals(self):
        assert SqlOperator.EQUALS.value == "="

    def test_not_equals(self):
        assert SqlOperator.NOT_EQUALS.value == "<>"

    def test_greater(self):
        assert SqlOperator.GREATER.value == ">"

    def test_less(self):
        assert SqlOperator.LESS.value == "<"

    def test_like(self):
        assert SqlOperator.LIKE.value == "LIKE"

    def test_in(self):
        assert SqlOperator.IN.value == "IN"

    def test_between(self):
        assert SqlOperator.BETWEEN.value == "BETWEEN"

    def test_is_null(self):
        assert SqlOperator.IS_NULL.value == "IS NULL"

    def test_is_not_null(self):
        assert SqlOperator.IS_NOT_NULL.value == "IS NOT NULL"


class TestSqlJoinType:
    """T25: SqlJoinType enum values."""

    def test_inner(self):
        assert SqlJoinType.INNER.value == "INNER"

    def test_left(self):
        assert SqlJoinType.LEFT.value == "LEFT"

    def test_right(self):
        assert SqlJoinType.RIGHT.value == "RIGHT"

    def test_full(self):
        assert SqlJoinType.FULL.value == "FULL"

    def test_cross(self):
        assert SqlJoinType.CROSS.value == "CROSS"


class TestSqlTableReference:
    """T26: SqlTableReference attributes."""

    def test_table_name(self):
        ref = SqlTableReference(table_name="T1")
        assert ref.table_name == "T1"

    def test_schema(self):
        ref = SqlTableReference(table_name="T1", schema="DB2INST1")
        assert ref.schema == "DB2INST1"

    def test_alias(self):
        ref = SqlTableReference(table_name="T1", alias="A")
        assert ref.alias == "A"


class TestSqlColumnReference:
    """T27: SqlColumnReference attributes."""

    def test_column_name(self):
        ref = SqlColumnReference(column_name="COL1")
        assert ref.column_name == "COL1"

    def test_table_name(self):
        ref = SqlColumnReference(column_name="COL1", table_name="T1")
        assert ref.table_name == "T1"

    def test_alias(self):
        ref = SqlColumnReference(column_name="COL1", alias="C1")
        assert ref.alias == "C1"


class TestSqlExpression:
    """T28: SqlExpression attributes."""

    def test_literal(self):
        expr = SqlExpression(literal="TEST")
        assert expr.literal == "TEST"

    def test_column(self):
        expr = SqlExpression(column=SqlColumnReference(column_name="COL1"))
        assert expr.column.column_name == "COL1"

    def test_host_variable(self):
        expr = SqlExpression(host_variable=SqlHostVariable(name="WS-VAR"))
        assert expr.host_variable.name == "WS-VAR"


class TestSqlPredicate:
    """T29: SqlPredicate attributes."""

    def test_left(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="COL1")),
            operator=SqlOperator.EQUALS,
            right=SqlExpression(literal="1"),
        )
        assert pred.left.column.column_name == "COL1"

    def test_operator(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="COL1")),
            operator=SqlOperator.NOT_EQUALS,
            right=SqlExpression(literal="1"),
        )
        assert pred.operator == SqlOperator.NOT_EQUALS

    def test_right(self):
        pred = SqlPredicate(
            left=SqlExpression(column=SqlColumnReference(column_name="COL1")),
            operator=SqlOperator.EQUALS,
            right=SqlExpression(literal="1"),
        )
        assert pred.right.literal == "1"


class TestSqlOrderBy:
    """T30: SqlOrderBy attributes."""

    def test_column(self):
        order = SqlOrderBy(column=SqlColumnReference(column_name="COL1"))
        assert order.column.column_name == "COL1"

    def test_ascending(self):
        order = SqlOrderBy(column=SqlColumnReference(column_name="COL1"), ascending=True)
        assert order.ascending is True

    def test_descending(self):
        order = SqlOrderBy(column=SqlColumnReference(column_name="COL1"), ascending=False)
        assert order.ascending is False


class TestSqlGroupBy:
    """T31: SqlGroupBy attributes."""

    def test_column(self):
        from engine.transformation.ir import SqlGroupBy
        group = SqlGroupBy(column=SqlColumnReference(column_name="COL1"))
        assert group.column.column_name == "COL1"


class TestDb2ApplicationValidation:
    """T32: Db2Application validation."""

    def test_validate_empty(self):
        app = Db2Application(program_id="PROG1")
        issues = app.validate()
        assert isinstance(issues, list)

    def test_validate_with_dependencies(self):
        app = Db2Application(
            program_id="PROG1",
            table_dependencies=(
                Db2TableDependency(
                    program_id="PROG1",
                    table_name="T1",
                    operation="READ",
                ),
            ),
        )
        issues = app.validate()
        assert isinstance(issues, list)


class TestDb2ApplicationGetTables:
    """T33: Db2Application get_tables()."""

    def test_empty(self):
        app = Db2Application(program_id="PROG1")
        assert app.get_tables() == []

    def test_with_deps(self):
        deps = (
            Db2TableDependency(program_id="PROG1", table_name="T1", operation="READ"),
            Db2TableDependency(program_id="PROG1", table_name="T2", operation="READ"),
            Db2TableDependency(program_id="PROG1", table_name="T1", operation="UPDATE"),
        )
        app = Db2Application(program_id="PROG1", table_dependencies=deps)
        tables = app.get_tables()
        assert "T1" in tables
        assert "T2" in tables


class TestDb2ApplicationGetTableColumns:
    """T34: Db2Application get_table_columns()."""

    def test_empty(self):
        app = Db2Application(program_id="PROG1")
        assert app.get_table_columns("T1") == []

    def test_with_columns(self):
        deps = (
            Db2TableDependency(
                program_id="PROG1",
                table_name="T1",
                operation="READ",
                columns=("COL1", "COL2"),
            ),
        )
        app = Db2Application(program_id="PROG1", table_dependencies=deps)
        cols = app.get_table_columns("T1")
        assert "COL1" in cols
        assert "COL2" in cols


class TestDb2ApplicationGetDependencies:
    """T35: Db2Application get_dependencies()."""

    def test_empty(self):
        app = Db2Application(program_id="PROG1")
        assert app.get_dependencies("T1") == []

    def test_with_deps(self):
        deps = (
            Db2TableDependency(
                program_id="PROG1",
                table_name="T1",
                operation="READ",
            ),
            Db2TableDependency(
                program_id="PROG2",
                table_name="T2",
                operation="READ",
            ),
        )
        app = Db2Application(program_id="PROG1", table_dependencies=deps)
        t1_deps = app.get_dependencies("T1")
        assert len(t1_deps) == 1
        assert t1_deps[0].program_id == "PROG1"


class TestEmbeddedSqlBlockIntegration:
    """T36: EmbeddedSqlBlock integration test."""

    def test_full_block(self):
        parser = SqlParser()
        sql = """
        EXEC SQL
            SELECT CUSTOMER_NAME
              INTO :WS-CUSTOMER-NAME
              FROM CUSTOMER
             WHERE CUSTOMER_ID = :WS-CUSTOMER-ID
        END-EXEC
        """
        # Remove EXEC SQL / END-EXEC markers
        sql_text = sql.replace("EXEC SQL", "").replace("END-EXEC", "").strip()
        block = parser.parse_embedded_sql(sql_text)

        assert len(block.statements) == 1
        stmt = block.statements[0]
        assert stmt.statement_type == SqlStatementType.SELECT
        assert stmt.select.columns[0].column_name == "CUSTOMER_NAME"
        assert stmt.select.from_tables[0].table_name == "CUSTOMER"
        assert stmt.select.into_variables[0].name == "WS-CUSTOMER-NAME"
        assert stmt.select.where_predicate.left.column.column_name == "CUSTOMER_ID"
        assert stmt.select.where_predicate.right.host_variable.name == "WS-CUSTOMER-ID"


class TestDb2ApplicationIntegration:
    """T37: Db2Application full integration test."""

    def test_build_application(self):
        parser = SqlParser()

        sql1 = "SELECT COL1 INTO :WS-VAR FROM T1 WHERE COL2 = :WS-IN"
        sql2 = "INSERT INTO T2 (COL1) VALUES (:WS-VAR)"
        sql3 = "UPDATE T1 SET COL1 = 'DONE' WHERE COL2 = :WS-IN"

        block1 = parser.parse_embedded_sql(sql1)
        block2 = parser.parse_embedded_sql(sql2)
        block3 = parser.parse_embedded_sql(sql3)

        deps1 = parser.extract_table_dependencies(block1, "PROG1")
        deps2 = parser.extract_table_dependencies(block2, "PROG1")
        deps3 = parser.extract_table_dependencies(block3, "PROG1")

        all_deps = tuple(deps1 + deps2 + deps3)

        app = Db2Application(
            program_id="PROG1",
            sql_blocks=(block1, block2, block3),
            table_dependencies=all_deps,
        )

        assert app.program_id == "PROG1"
        assert len(app._all_statements()) == 3
        assert len(app.get_tables()) == 2
        assert "T1" in app.get_tables()
        assert "T2" in app.get_tables()
        assert len(app.get_dependencies("T1")) == 2
