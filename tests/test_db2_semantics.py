"""Tests for the DB2 lane semantic model and analyzer (engine/sql).

Binding-direction analysis, indicator pairing, table read/write roles,
per-statement possible statuses, transaction boundaries, and program
aggregation over the EXEC SQL blocks.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.transformation.sql_parser import SqlParser

_PARSER = SqlParser()
_ANALYZER = Db2SemanticAnalyzer()


def analyze(sql: str):
    block = _PARSER.parse_embedded_sql(sql)
    return _ANALYZER.analyze_statement(block.statements[0])


def host_var(host_vars, name: str):
    matches = [hv for hv in host_vars if hv.name == name]
    assert len(matches) == 1, f"expected exactly one binding for {name!r}, got {len(matches)}"
    return matches[0]


class TestBindingDirections:
    def test_select_into_outputs_and_where_input(self):
        sem = analyze(
            "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
            "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
        )
        assert host_var(sem.host_variables, "WS-ID").direction.value == "INPUT"
        assert host_var(sem.host_variables, "WS-NAME").direction.value == "OUTPUT"
        assert host_var(sem.host_variables, "WS-BAL").direction.value == "OUTPUT"

    def test_indicator_pair_direction_and_nullable(self):
        sem = analyze(
            "SELECT BALANCE INTO :WS-BAL:WS-BAL-IND FROM ACCOUNT "
            "WHERE ACCOUNT_ID = :WS-ID"
        )
        bal = host_var(sem.host_variables, "WS-BAL")
        assert bal.direction.value == "OUTPUT"
        assert bal.indicator == "WS-BAL-IND"
        assert bal.uses_indicator is True
        assert bal.nullable is True
        assert host_var(sem.host_variables, "WS-BAL-IND").direction.value == "OUTPUT"

    def test_plain_string_literal_is_not_a_host_variable(self):
        sem = analyze(
            "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT WHERE ACCOUNT_ID = 7"
        )
        assert len(sem.host_variables) == 1
        assert sem.host_variables[0].name == "WS-NAME"

    def test_insert_values_are_input_only(self):
        sem = analyze(
            "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) VALUES (:WS-ID, :WS-NAME)"
        )
        assert {hv.direction.value for hv in sem.host_variables} == {"INPUT"}

    def test_update_is_input(self):
        sem = analyze(
            "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"
        )
        assert host_var(sem.host_variables, "WS-ID").direction.value == "INPUT"
        assert host_var(sem.host_variables, "WS-BAL").direction.value == "INPUT"

    def test_delete_where_is_input(self):
        sem = analyze("DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID")
        assert host_var(sem.host_variables, "WS-ID").direction.value == "INPUT"


class TestTableUsage:
    def _model_for(self, sql: str):
        return _ANALYZER.analyze_program(
            "ACCTPROG", (_PARSER.parse_embedded_sql(sql),)
        )

    def test_select_into_reads_account(self):
        account = self._model_for(
            "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
            "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
        ).get_table("ACCOUNT")
        assert account is not None
        assert "SELECT" in account.operations
        assert account.is_read and not account.is_write

    def test_insert_writes_account(self):
        account = self._model_for(
            "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) VALUES (:WS-ID, :WS-NAME)"
        ).get_table("ACCOUNT")
        assert "INSERT" in account.operations and account.is_write

    def test_update_reads_and_writes(self):
        account = self._model_for(
            "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"
        ).get_table("ACCOUNT")
        assert "UPDATE" in account.operations and account.is_write

    def test_delete_writes_account(self):
        account = self._model_for(
            "DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
        ).get_table("ACCOUNT")
        assert "DELETE" in account.operations and account.is_write

    def test_fetch_is_cursor_operation_without_table_ref(self):
        sem = analyze("FETCH C-ACCTS INTO :WS-ID, :WS-NAME")
        assert sem.table_refs == ()
        assert sem.is_cursor_operation


class TestPossibleStatuses:
    def test_select_into_statuses(self):
        sem = analyze(
            "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
        )
        assert sorted(s.sqlcode for s in sem.possible_statuses) == [-811, 0, 100]

    def test_insert_offers_duplicate_key(self):
        sem = analyze(
            "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) VALUES (:WS-ID, :WS-NAME)"
        )
        assert any(s.sqlcode == -803 for s in sem.possible_statuses)

    def test_delete_has_only_success(self):
        sem = analyze("DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID")
        assert [s.sqlcode for s in sem.possible_statuses] == [0]


class TestTransactionBoundaries:
    def test_commit_and_rollback(self):
        for sql, expected in (("COMMIT", "COMMIT"), ("ROLLBACK", "ROLLBACK")):
            sem = _ANALYZER.analyze_statement(_PARSER.parse_embedded_sql(sql).statements[0])
            assert sem.is_transaction_boundary
            assert sem.statement_type == expected


class TestProgramAggregation:
    def test_statements_and_tables_aggregated(self):
        model = _ANALYZER.analyze_program(
            "ACCTPROG",
            (
                _PARSER.parse_embedded_sql(
                    "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) "
                    "VALUES (:WS-ID, :WS-NAME)"
                ),
                _PARSER.parse_embedded_sql(
                    "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                    "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
                ),
                _PARSER.parse_embedded_sql("COMMIT"),
            ),
        )
        assert model.program_id == "ACCTPROG"
        assert [s.statement_type for s in model.statements] == [
            "INSERT", "SELECT", "COMMIT"
        ]
        account = model.get_table("ACCOUNT")
        assert account is not None
        assert account.is_read and account.is_write

    def test_program_host_variable_directions_merge(self):
        model = _ANALYZER.analyze_program(
            "ACCTPROG",
            (
                _PARSER.parse_embedded_sql(
                    "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) "
                    "VALUES (:WS-ID, :WS-NAME)"
                ),
                _PARSER.parse_embedded_sql(
                    "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT "
                    "WHERE ACCOUNT_ID = :WS-ID"
                ),
            ),
        )
        ws_name = host_var(model.host_variables, "WS-NAME")
        assert ws_name.direction.value == "IN_OUT"

    def test_validation_empty_for_clean_program(self):
        model = _ANALYZER.analyze_program(
            "ACCTPROG",
            (
                _PARSER.parse_embedded_sql(
                    "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"
                ),
            ),
        )
        assert model.validation == ()