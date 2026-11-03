"""Phase 6 P2 clause fidelity: INSERT column lists, ORDER BY bounds, JOINs.

BL-062: ``INSERT INTO T VALUES (:A, :B)`` must not store the VALUES list
as the column list (the old parser matched the VALUES parens as columns,
polluting write-columns and INSERT dependency records — audit probe E).

BL-082: ORDER BY column names must end at ``FETCH FIRST`` (the old
parser swallowed the trailing clause into the column name — audit
probe J).

BL-081: JOIN tables and ON conditions must be preserved in
``SqlSelect.joins`` (which exists to hold them) and reach the analyzer's
table usage / read columns (audit probe I: ``T2`` vanished from the
dependency truth while the SELECT list referenced ``B.NAME``).
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.transformation.ir import SqlJoinType, SqlOperator
from engine.transformation.sql_parser import SqlParser

_PARSER = SqlParser()
_ANALYZER = Db2SemanticAnalyzer()


class TestInsertColumnListTruth:
    """BL-062."""

    def test_insert_without_column_list_parses_no_invented_columns(self):
        block = _PARSER.parse_embedded_sql(
            "INSERT INTO ACCOUNT VALUES (:HV1, :HV2)"
        )
        insert = block.statements[0].insert
        assert insert.columns == ()
        names = [
            v.host_variable.name if v.host_variable else v.literal
            for v in insert.values
        ]
        assert names == ["HV1", "HV2"]

    def test_insert_with_explicit_column_list_parses_both_sides(self):
        block = _PARSER.parse_embedded_sql(
            "INSERT INTO ACCOUNT (ACCT, BAL) VALUES (:HV1, :HV2)"
        )
        insert = block.statements[0].insert
        assert [c.column_name for c in insert.columns] == ["ACCT", "BAL"]
        assert [v.host_variable.name for v in insert.values] == ["HV1", "HV2"]

    def test_column_less_insert_reports_no_written_columns_in_the_analyzer(self):
        block = _PARSER.parse_embedded_sql(
            "INSERT INTO ACCOUNT VALUES (:HV1, :HV2)"
        )
        sem = _ANALYZER.analyze_statement(block.statements[0])
        assert sem.write_columns == ()


class TestOrderByClauseBounds:
    """BL-082."""

    def test_order_by_text_ends_at_fetch_first(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT ORDER BY ACCT DESC FETCH FIRST 5 ROWS ONLY"
        )
        select = block.statements[0].select
        assert select.fetch_first == 5
        assert len(select.order_by) == 1
        assert select.order_by[0].column is not None
        assert select.order_by[0].column.column_name == "ACCT"
        assert select.order_by[0].ascending is False

    def test_order_by_without_fetch_first_parses_every_item(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT ORDER BY ACCT DESC, BAL ASC"
        )
        select = block.statements[0].select
        assert [(o.column.column_name, o.ascending) for o in select.order_by] == [
            ("ACCT", False),
            ("BAL", True),
        ]

    def test_fetch_first_without_order_by_still_parses(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT FETCH FIRST 1 ROW ONLY"
        )
        select = block.statements[0].select
        assert select.fetch_first == 1
        assert select.order_by == ()


class TestJoinClausesArePreserved:
    """BL-081."""

    JOIN_SQL = (
        "SELECT A.ID, B.NAME FROM T1 A INNER JOIN T2 B ON A.ID = B.ID "
        "WHERE A.ID = 1"
    )

    def test_inner_join_table_and_on_condition_are_preserved(self):
        select = _PARSER.parse_embedded_sql(self.JOIN_SQL).statements[0].select
        assert [t.table_name for t in select.from_tables] == ["T1"]
        assert len(select.joins) == 1
        join = select.joins[0]
        assert join.join_type == SqlJoinType.INNER
        assert join.table is not None
        assert join.table.table_name == "T2"
        assert join.table.alias == "B"
        assert join.on_condition is not None
        assert join.on_condition.operator == SqlOperator.EQUALS
        assert join.on_condition.left.column.column_name == "ID"
        assert join.on_condition.left.column.table_name == "A"
        assert join.on_condition.right.column.column_name == "ID"
        assert join.on_condition.right.column.table_name == "B"

    def test_left_outer_join_type_is_preserved(self):
        select = _PARSER.parse_embedded_sql(
            "SELECT A.ID FROM T1 A LEFT OUTER JOIN T2 B ON A.ID = B.ID"
        ).statements[0].select
        assert len(select.joins) == 1
        assert select.joins[0].join_type == SqlJoinType.LEFT

    def test_joined_table_reaches_analyzer_table_usage(self):
        block = _PARSER.parse_embedded_sql(self.JOIN_SQL)
        model = _ANALYZER.analyze_program("PROG1", (block,))
        assert {t.table_name for t in model.tables} == {"T1", "T2"}

    def test_joined_table_reaches_extract_table_dependencies(self):
        block = _PARSER.parse_embedded_sql(self.JOIN_SQL)
        deps = _PARSER.extract_table_dependencies(block, "PROG1")
        assert {d.table_name for d in deps} == {"T1", "T2"}

    def test_on_condition_columns_reach_analyzer_read_columns(self):
        block = _PARSER.parse_embedded_sql(self.JOIN_SQL)
        sem = _ANALYZER.analyze_statement(block.statements[0])
        # A.ID/B.NAME come from the SELECT list; B.ID exists only in the
        # ON condition, so it proves the ON side is analyzed.
        assert "B.ID" in sem.read_columns

    def test_select_without_join_has_no_joins_control(self):
        select = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE ACCT = 1"
        ).statements[0].select
        assert select.joins == ()
