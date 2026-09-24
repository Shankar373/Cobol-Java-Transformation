"""Tests for the Java repository/service mapping (engine/sql/repository_model).

The mapping is a deterministic representation consumed by the (off-limits)
Spring generation lane via the documented hook in
``engine.transformation.sql_repository_mapping``.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.transformation.sql_parser import SqlParser

_ANALYZER = Db2SemanticAnalyzer()
_PARSER = SqlParser()


def map_program(program_id: str, sqls: list[str]):
    blocks = tuple(_PARSER.parse_embedded_sql(s) for s in sqls)
    model = _ANALYZER.analyze_program(program_id, blocks)
    from engine.sql.repository_model import map_db2_model_to_repository

    return map_db2_model_to_repository(model)


class TestRepositoryStructure:
    def test_one_repository_per_table(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
                "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) "
                "VALUES (:WS-ID, :WS-NAME)",
            ],
        )
        assert [r.class_name for r in mapping.repositories] == ["AccountRepository"]
        assert mapping.repositories[0].table_name == "ACCOUNT"

    def test_method_naming_and_parameter_by_statement(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
                "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) "
                "VALUES (:WS-ID, :WS-NAME)",
            ],
        )
        repo = mapping.repositories[0]
        by_name = {m.name: m for m in repo.methods}
        assert set(by_name) == {"findAccount", "insertAccount"}

        find = by_name["findAccount"]
        assert find.operation == "SELECT_INTO"
        assert find.return_type == "Row"
        assert [p.name for p in find.parameters] == ["WS-ID"]
        assert find.parameters[0].direction.value == "INPUT"

        insert = by_name["insertAccount"]
        assert insert.operation == "INSERT"
        assert [p.name for p in insert.parameters] == ["WS-ID", "WS-NAME"]
        assert {p.direction.value for p in insert.parameters} == {"INPUT"}

    def test_status_outcomes_follow_db2_semantics(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
                "DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
            ],
        )
        repo = mapping.repositories[0]
        by_name = {m.name: m for m in repo.methods}

        find = by_name["findAccount"]
        assert find.status_outcomes == ("SUCCESS", "NO_DATA", "TOO_MANY_ROWS")

        delete = by_name["deleteAccount"]
        assert delete.status_outcomes == ("SUCCESS",)

    def test_repeated_operations_get_suffix_tokens(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT "
                "WHERE ACCOUNT_ID = :WS-ID",
                "SELECT BALANCE INTO :WS-BAL FROM ACCOUNT "
                "WHERE ACCOUNT_ID = :WS-ID",
            ],
        )
        names = sorted(m.name for m in mapping.repositories[0].methods)
        assert names == ["findAccount", "findAccount2"]


class TestTransactionBoundaries:
    def test_commit_and_rollback_become_service_methods(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID",
                "COMMIT",
                "ROLLBACK",
            ],
        )
        service_names = [m.name for m in mapping.service.methods]
        assert "commit" in service_names
        assert "rollback" in service_names
        commits = [m for m in mapping.service.methods if m.transaction_boundary == "COMMIT"]
        assert commits and commits[0].return_type == "void"

    def test_service_class_name_from_program_id(self):
        mapping = map_program(
            "ACCTPROG",
            ["UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"],
        )
        assert mapping.service.class_name == "AcctprogService"


class TestDefaultsAndNotes:
    def test_host_variable_type_note_present(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT "
                "WHERE ACCOUNT_ID = :WS-ID"
            ],
        )
        assert any("String" in note for note in mapping.notes)

    def test_host_variables_aggregated(self):
        mapping = map_program(
            "ACCTPROG",
            [
                "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
                "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID",
            ],
        )
        names = set(mapping.host_variables)
        assert names == {"WS-NAME", "WS-BAL", "WS-ID"}


class TestFacade:
    def test_facade_reroutes_to_engine_mapping(self):
        mapping = map_program(
            "ACCTPROG",
            ["INSERT INTO ACCOUNT (ACCOUNT_ID) VALUES (:WS-ID)"],
        )
        from engine.transformation.sql_repository_mapping import (
            map_sql_model_to_repository,
        )

        model = _ANALYZER.analyze_program(
            "ACCTPROG",
            (
                _PARSER.parse_embedded_sql(
                    "INSERT INTO ACCOUNT (ACCOUNT_ID) VALUES (:WS-ID)"
                ),
            ),
        )
        facade = map_sql_model_to_repository(model)
        assert facade.repositories[0].class_name == mapping.repositories[0].class_name


class TestDeterminism:
    def test_identical_input_yields_identical_mapping(self):
        sqls = [
            "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID",
            "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME) VALUES (:WS-ID, :WS-NAME)",
            "COMMIT",
        ]
        first = map_program("ACCTPROG", sqls)
        second = map_program("ACCTPROG", sqls)

        def signature(mapping):
            return (
                tuple(r.class_name for r in mapping.repositories),
                tuple(
                    (m.name, m.operation, tuple(p.name for p in m.parameters), m.status_outcomes)
                    for r in mapping.repositories
                    for m in r.methods
                ),
                tuple(m.name for m in mapping.service.methods),
            )

        assert signature(first) == signature(second)