"""Phase 6 P1 fidelity gates: WHERE-predicate truth (BL-078/BL-079/BL-080).

BL-078: predicate string literals must survive verbatim (DB2 compares
case-sensitively); the old parser uppercased the whole operand text.
BL-079: compound AND/OR, IN and BETWEEN predicates must parse into the IR
fields built for them — never into invented fake column names.
BL-080: unsupported EXEC SQL statements must be preserved and diagnosed,
never silently dropped; EXECUTE IMMEDIATE must set its IR flag.
"""

import pytest

from engine.transformation.ir import SqlOperator
from engine.transformation.sql_parser import SqlParser

_PARSER = SqlParser()


def _where_predicate(sql: str):
    block = _PARSER.parse_embedded_sql(sql)
    assert block.statements, f"no statement parsed from {sql!r}"
    stmt = block.statements[0]
    assert stmt.select is not None, f"not a SELECT: {sql!r}"
    assert stmt.select.where_predicate is not None, f"no WHERE parsed: {sql!r}"
    return stmt.select.where_predicate


class TestStringLiteralPredicates:
    """BL-078: literal data values are case-sensitive DB2 semantics."""

    def test_lowercase_string_literal_predicate_survives_verbatim(self):
        pred = _where_predicate("SELECT ACCT FROM ACCOUNT WHERE NAME = 'abc'")
        assert pred.right is not None
        assert pred.right.literal == "abc"

    def test_mixed_case_string_literal_predicate_survives_verbatim(self):
        pred = _where_predicate(
            "SELECT ACCT FROM ACCOUNT WHERE NAME = 'AbCd'"
        )
        assert pred.right is not None
        assert pred.right.literal == "AbCd"

    def test_host_variable_predicate_keeps_source_case_name(self):
        pred = _where_predicate(
            "SELECT ACCT FROM ACCOUNT WHERE NAME = :ws-name"
        )
        assert pred.right is not None
        assert pred.right.host_variable is not None
        assert pred.right.host_variable.name == "ws-name"

    def test_unquoted_column_identifier_folds_to_uppercase(self):
        pred = _where_predicate("SELECT ACCT FROM ACCOUNT WHERE name = 'x'")
        assert pred.left.column is not None
        assert pred.left.column.column_name == "NAME"

    def test_underscore_identifier_predicate_parses(self):
        pred = _where_predicate(
            "SELECT ACCT FROM ACCOUNT WHERE CUSTOMER_ID = :WS-CUSTOMER-ID"
        )
        assert pred.left.column is not None
        assert pred.left.column.column_name == "CUSTOMER_ID"
        assert pred.right is not None
        assert pred.right.host_variable is not None
        assert pred.right.host_variable.name == "WS-CUSTOMER-ID"


class TestCompoundAndOrPredicates:
    """BL-079: every conjunct parsed on its own; never a fabricated column."""

    def test_compound_and_predicate_parses_each_conjunct_separately(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE ACCT = 1 AND BAL = 2"
        )
        select = block.statements[0].select
        assert len(select.where_predicates) == 2
        first, second = select.where_predicates
        assert first.left.column.column_name == "ACCT"
        assert first.right.literal == "1"
        assert second.left.column.column_name == "BAL"
        assert second.right.literal == "2"
        # where_predicate stays the first conjunct for compatibility.
        assert select.where_predicate == first

    def test_compound_or_predicate_preserves_both_branches(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE ACCT = 1 OR ACCT = 2"
        )
        select = block.statements[0].select
        assert len(select.where_predicates) == 2
        assert {p.right.literal for p in select.where_predicates} == {"1", "2"}

    def test_and_conjunct_columns_reach_the_analyzer_read_columns(self):
        from engine.sql.analyzer import Db2SemanticAnalyzer

        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE ACCT = 1 AND BAL = 2"
        )
        sem = Db2SemanticAnalyzer().analyze_statement(block.statements[0])
        assert list(sem.read_columns) == ["ACCT", "BAL"]

    def test_unparseable_conjunct_is_skipped_not_fabricated(self):
        from engine.sql.analyzer import Db2SemanticAnalyzer

        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE ACCT = 1 AND NOT (BAL = 2)"
        )
        select = block.statements[0].select
        assert len(select.where_predicates) == 1
        sem = Db2SemanticAnalyzer().analyze_statement(block.statements[0])
        assert list(sem.read_columns) == ["ACCT"]

    def test_update_compound_where_exposes_every_conjunct_to_the_analyzer(self):
        from engine.sql.analyzer import Db2SemanticAnalyzer

        block = _PARSER.parse_embedded_sql(
            "UPDATE ACCOUNT SET BAL = 0 WHERE ACCT = 1 AND BAL > 2"
        )
        update = block.statements[0].update
        assert len(update.where_predicates) == 2
        sem = Db2SemanticAnalyzer().analyze_statement(block.statements[0])
        assert "ACCT" in sem.read_columns
        assert "BAL" in sem.read_columns


class TestInListAndBetweenPredicates:
    """BL-079: IR fields built for IN/BETWEEN get populated, honestly."""

    def test_in_list_predicate_populates_right_list_expressions(self):
        pred = _where_predicate("SELECT ACCT FROM ACCOUNT WHERE ACCT IN (1, 2, 3)")
        assert pred.operator == SqlOperator.IN
        assert pred.right is None
        assert [expr.literal for expr in pred.right_list] == ["1", "2", "3"]

    def test_between_predicate_populates_operand_fields(self):
        pred = _where_predicate(
            "SELECT ACCT FROM ACCOUNT WHERE BAL BETWEEN 100 AND 500"
        )
        assert pred.operator == SqlOperator.BETWEEN
        assert pred.right is None
        assert pred.left_operand is not None
        assert pred.left_operand.literal == "100"
        assert pred.right_operand is not None
        assert pred.right_operand.literal == "500"

    def test_between_bounds_are_not_split_into_extra_conjuncts(self):
        block = _PARSER.parse_embedded_sql(
            "SELECT ACCT FROM ACCOUNT WHERE BAL BETWEEN 100 AND 500"
        )
        select = block.statements[0].select
        assert len(select.where_predicates) == 1

    def test_like_predicate_keeps_literal_verbatim(self):
        pred = _where_predicate("SELECT ACCT FROM ACCOUNT WHERE NAME LIKE 'a%'")
        assert pred.operator == SqlOperator.LIKE
        assert pred.right is not None
        assert pred.right.literal == "a%"
