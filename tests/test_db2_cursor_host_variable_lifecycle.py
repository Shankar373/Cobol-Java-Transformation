"""BL-061: host-variable cursor bindings at OPEN, and fail-closed misuse.

The old harness called ``db.execute(stmt)`` at OPEN without the workload's
per-statement bindings, so a cursor whose query references host variables
could never be bound through the workload (KeyError out of the harness,
`_bind_values` → "missing host variable binding"). DB2 binds query host
variables when the cursor is OPENed, so the OPEN statement's
``statement_bindings`` entry is the binding site.

The controlled database's ``execute`` contract is also pinned: it accepts
analyzed ``Db2StmtSemantic`` values (string ``statement_type`` from the
analyzer) and fails closed with a named diagnostic for misuse — an un-
analyzed IR ``SqlStatement`` (enum statement type) previously slipped
into the DML path and returned a bogus SUCCESS.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.execution import Db2ControlledDatabase
from engine.sql.harness import run_db2_workload
from engine.transformation.sql_parser import SqlParser

_ANALYZER = Db2SemanticAnalyzer()
_PARSER = SqlParser()

_DDL = (
    "CREATE TABLE ACCOUNT ("
    "ACCOUNT_ID INTEGER NOT NULL, "
    "CUSTOMER_NAME VARCHAR(30), "
    "BALANCE DECIMAL(10, 2))"
)
_SEEDS = [
    {"ACCOUNT_ID": 1, "CUSTOMER_NAME": "Alice", "BALANCE": 10.50},
    {"ACCOUNT_ID": 2, "CUSTOMER_NAME": "Bob", "BALANCE": 20.00},
]

_COBOL = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCT  PIC S9(9) COMP-5.
       01  WS-ID    PIC S9(9) COMP-5.
       01  WS-NAME  PIC X(30).
       PROCEDURE DIVISION.
           EXEC SQL
               DECLARE C-ACCTS CURSOR FOR
                   SELECT ACCOUNT_ID, CUSTOMER_NAME
                     FROM ACCOUNT
                    WHERE ACCOUNT_ID = :WS-ACCT
           END-EXEC
           EXEC SQL
               OPEN C-ACCTS
           END-EXEC
           EXEC SQL
               FETCH C-ACCTS INTO :WS-ID, :WS-NAME
           END-EXEC
           EXEC SQL
               CLOSE C-ACCTS
           END-EXEC
           STOP RUN.
"""


class TestHarnessBindsCursorQueryHostVariablesAtOpen:
    def test_open_uses_the_workload_binding_entry_for_query_host_variables(self):
        model, trace, db = run_db2_workload(
            _COBOL,
            "PROG1",
            _DDL,
            _SEEDS,
            # statement_bindings order follows model.statements:
            # [0]=DECLARE, [1]=OPEN (query host variables bind here)
            statement_bindings=[{}, {"WS-ACCT": 1}],
        )
        try:
            lines = trace.splitlines()
            assert len(model.statements) == 4
            open_line = next(line for line in lines if line.startswith("OPEN"))
            assert open_line == "OPEN 0/00000 name=C-ACCTS"
            fetch_line = next(line for line in lines if line.startswith("FETCH"))
            assert fetch_line.startswith("FETCH 0/00000")
            # Row for WS-ACCT=1 bound at OPEN must be the one fetched.
            assert "WS-NAME" in fetch_line
            assert "Alice" in fetch_line
        finally:
            db.close()

    def test_missing_open_binding_fails_loud_with_the_host_variable_named(self):
        with pytest.raises(KeyError, match="WS-ACCT"):
            run_db2_workload(
                _COBOL,
                "PROG1",
                _DDL,
                _SEEDS,
                statement_bindings=[{}, {}],
            )


class TestControlledDatabaseExecuteFailsClosedOnMisuse:
    def test_unanalyzed_ir_statement_is_rejected_with_an_analyzer_hint(self):
        db = Db2ControlledDatabase(_DDL)
        try:
            ir_stmt = _PARSER.parse_embedded_sql(
                "SELECT ACCOUNT_ID FROM ACCOUNT"
            ).statements[0]
            with pytest.raises(TypeError, match="Db2SemanticAnalyzer"):
                db.execute(ir_stmt)
        finally:
            db.close()

    def test_unknown_statement_type_string_is_rejected_with_the_value_named(self):
        db = Db2ControlledDatabase(_DDL)
        try:
            sem = _ANALYZER.analyze_statement(
                _PARSER.parse_embedded_sql(
                    "SELECT ACCOUNT_ID FROM ACCOUNT"
                ).statements[0]
            )
            bogus = replace(sem, statement_type="NOT_A_STATEMENT")
            with pytest.raises(ValueError, match="NOT_A_STATEMENT"):
                db.execute(bogus)
        finally:
            db.close()
