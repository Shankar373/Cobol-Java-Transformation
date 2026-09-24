"""Tests for DB2 compatibility classification (engine/sql/dialect).

Core discipline under test: a passing controlled-database run may only
ever claim PORTABLE_EXECUTABLE (or lower).  DB2_RUNTIME_VERIFIED must
remain empty on this lane; that claim requires evidence from a real DB2
subsystem, which this lane does not have.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.dialect import (
    Db2CompatibilityLevel,
    classify_statement,
    compatibility_report,
    runtime_verified_features,
)
from engine.transformation.sql_parser import SqlParser

_ANALYZER = Db2SemanticAnalyzer()
_PARSER = SqlParser()


def analyze_one(sql: str):
    block = _PARSER.parse_embedded_sql(sql)
    return _ANALYZER.analyze_statement(block.statements[0])


def _workload_model():
    blocks = (
        _PARSER.parse_embedded_sql(
            "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
            "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
        ),
        _PARSER.parse_embedded_sql(
            "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME, BALANCE) "
            "VALUES (:WS-ID, :WS-NAME, 0.00)"
        ),
        _PARSER.parse_embedded_sql(
            "UPDATE ACCOUNT SET BALANCE = BALANCE + :WS-BAL "
            "WHERE ACCOUNT_ID = :WS-ID"
        ),
        _PARSER.parse_embedded_sql("DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"),
        _PARSER.parse_embedded_sql(
            "DECLARE C-ACCTS CURSOR FOR SELECT ACCOUNT_ID, CUSTOMER_NAME "
            "FROM ACCOUNT ORDER BY ACCOUNT_ID"
        ),
        _PARSER.parse_embedded_sql("OPEN C-ACCTS"),
        _PARSER.parse_embedded_sql("FETCH C-ACCTS INTO :WS-ID, :WS-NAME"),
        _PARSER.parse_embedded_sql("CLOSE C-ACCTS"),
        _PARSER.parse_embedded_sql("COMMIT"),
        _PARSER.parse_embedded_sql("ROLLBACK"),
    )
    return _ANALYZER.analyze_program("ACCOUNT-DB2", blocks)


class TestLevels:
    def test_strict_ordering(self):
        levels = [
            Db2CompatibilityLevel.DB2_SYNTAX,
            Db2CompatibilityLevel.DB2_SEMANTIC,
            Db2CompatibilityLevel.PORTABLE_EXECUTABLE,
            Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED,
        ]
        ranks = [level.rank for level in levels]
        assert ranks == sorted(ranks) and len(set(ranks)) == 4

    def test_at_least(self):
        portable = Db2CompatibilityLevel.PORTABLE_EXECUTABLE
        assert portable.at_least(Db2CompatibilityLevel.DB2_SEMANTIC)
        assert not Db2CompatibilityLevel.DB2_SEMANTIC.at_least(portable)

    def test_runtime_verified_is_top_level(self):
        assert (
            Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED
            == Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED
        )
        assert not Db2CompatibilityLevel.PORTABLE_EXECUTABLE.at_least(
            Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED
        )


class TestClassification:
    def test_select_is_portable(self):
        c = classify_statement(analyze_one("SELECT CUSTOMER_NAME FROM ACCOUNT"))
        assert c.syntax_known and c.semantically_modeled and c.portable

    def test_dml_is_portable(self):
        c = classify_statement(
            analyze_one(
                "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"
            )
        )
        assert c.portable

    def test_cursor_operations_are_portable(self):
        c = classify_statement(analyze_one("OPEN C-ACCTS"))
        assert c.portable and "cursor" in c.note

    def test_prepare_is_semantic_only(self):
        c = classify_statement(analyze_one("PREPARE S1 FROM :STMT"))
        assert c.syntax_known and c.semantically_modeled and not c.portable
        assert "dynamic SQL" in c.note


class TestReportNoRuntimeClaims:
    def test_runtime_verified_empty_for_supported_workload(self):
        report = compatibility_report(_workload_model())
        assert report
        assert runtime_verified_features(report) == []

    def test_no_runtime_claim_anywhere(self):
        for item in compatibility_report(_workload_model()):
            assert not item.runtime_verified
            assert item.claim != Db2CompatibilityLevel.DB2_RUNTIME_VERIFIED

    def test_insert_claims_portable_executable(self):
        items = [
            item
            for item in compatibility_report(_workload_model())
            if item.feature == "INSERT"
        ]
        assert items
        assert items[0].claim == Db2CompatibilityLevel.PORTABLE_EXECUTABLE

    def test_fetch_first_is_db2_specific_syntax_claim(self):
        model = _ANALYZER.analyze_program(
            "ACCTPROG",
            (
                _PARSER.parse_embedded_sql(
                    "SELECT ACCOUNT_ID FROM ACCOUNT FETCH FIRST 10 ROWS ONLY"
                ),
            ),
        )
        fetch_items = [
            item for item in compatibility_report(model) if item.feature.startswith("FETCH FIRST")
        ]
        assert fetch_items
        assert fetch_items[0].claim == Db2CompatibilityLevel.DB2_SYNTAX