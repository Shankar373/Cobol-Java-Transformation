"""Roadmap unit 12b: lowering EXEC SQL to JDBC calls -- planning, refusals and rendering.

The behaviour (Java output and database state equal to OCESQL on PostgreSQL) is proven in
``tests/integration/test_sql_jdbc_oracle.py``.
"""

from __future__ import annotations

import pytest

from engine.transformation import exec_sql
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.exec_sql_lowering import unsupported_reasons
from engine.transformation.ir import ExecSqlStatement
from engine.transformation.java_generator import JavaGenerator

HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    '       01 DBN PIC X(20) VALUE "testdb".\n       01 USR PIC X(20) VALUE "postgres".\n'
    "       01 PWD PIC X(10) VALUE SPACE.\n       01 WS-ID PIC 9(4).\n"
    "       01 WS-NAME PIC X(10).\n       01 WS-BAL PIC S9(7)V99.\n"
    "       01 WS-PK PIC 9(2) COMP-3.\n       01 WS-IND PIC S9(4) COMP-5.\n"
    "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
    "       PROCEDURE DIVISION.\n       MAIN.\n"
)


def _program(body: str):
    return CobolParser().parse(HEAD + body + "           STOP RUN.\n")


def _statements(program) -> list[ExecSqlStatement]:
    return [s for p in program.paragraphs for s in p.statements if isinstance(s, ExecSqlStatement)]


def _reasons(body: str) -> list[str]:
    program = _program(body)
    return unsupported_reasons(_statements(program)[0], program)


def _java(body: str) -> str:
    return JavaGenerator().generate(_program(body))[0].source_code


class TestShapes:
    def test_select_into_is_split_from_the_select(self):
        text, targets = exec_sql.split_select_into("SELECT A, B INTO :X, :Y:YI FROM T WHERE K = :K")
        assert text == "SELECT A, B FROM T WHERE K = :K"
        assert targets == (("X", ""), ("Y", "YI"))

    def test_connect_cursor_and_transaction_forms(self):
        assert exec_sql.parse_connect("CONNECT :U IDENTIFIED BY :P USING :D") == ("U", "P", "D")
        assert exec_sql.parse_declare_cursor("DECLARE c1 CURSOR FOR SELECT A FROM T") == (
            "C1", "SELECT A FROM T")
        assert exec_sql.parse_cursor_op("FETCH NEXT FROM c1 INTO :A, :B") == (
            "FETCH", "C1", (("A", ""), ("B", "")))
        assert exec_sql.parse_cursor_op("OPEN c1") == ("OPEN", "C1")
        assert exec_sql.parse_tx_end("COMMIT WORK") == "COMMIT"
        assert exec_sql.is_disconnect("DISCONNECT ALL")


class TestCertifiedStatementsLower:
    @pytest.mark.parametrize("body", [
        "           EXEC SQL CONNECT :USR IDENTIFIED BY :PWD USING :DBN END-EXEC.\n",
        "           EXEC SQL SELECT NAME INTO :WS-NAME FROM T\n"
        "                WHERE ID = :WS-ID END-EXEC.\n",
        "           EXEC SQL INSERT INTO T VALUES (:WS-ID, :WS-NAME) END-EXEC.\n",
        "           EXEC SQL UPDATE T SET BAL = :WS-BAL\n"
        "                WHERE ID = :WS-ID END-EXEC.\n",
        "           EXEC SQL DELETE FROM T WHERE ID = :WS-ID END-EXEC.\n",
        "           EXEC SQL COMMIT END-EXEC.\n",
        "           EXEC SQL ROLLBACK WORK END-EXEC.\n",
        "           EXEC SQL DISCONNECT ALL END-EXEC.\n",
    ])
    def test_no_refusal(self, body):
        assert _reasons(body) == []

    def test_select_into_renders_the_call_and_typed_reads(self):
        source = _java(
            "           EXEC SQL SELECT NAME, BAL INTO :WS-NAME, :WS-BAL\n"
            "                FROM T WHERE ID = :WS-ID END-EXEC.\n")
        assert 'CobolSql.selectInto("SELECT NAME, BAL FROM T WHERE ID = ?", WS_ID)' in source
        assert "WS_NAME = CobolSql.str(0, 10, WS_NAME)" in source
        assert "WS_BAL = CobolSql.dec(1, 7, 2, WS_BAL)" in source
        assert "SQLCODE = CobolSql.code" in source and "SQLSTATE = CobolSql.state" in source
        assert "final class CobolSql" in source and "gnucobol" not in source.lower()

    def test_a_cursor_binds_at_open_and_reads_at_fetch(self):
        source = _java(
            "           EXEC SQL DECLARE C1 CURSOR FOR\n"
            "                SELECT NAME FROM T WHERE ID > :WS-ID END-EXEC.\n"
            "           EXEC SQL OPEN C1 END-EXEC.\n"
            "           EXEC SQL FETCH C1 INTO :WS-NAME END-EXEC.\n"
            "           EXEC SQL CLOSE C1 END-EXEC.\n")
        assert 'CobolSql.declare("C1", "SELECT NAME FROM T WHERE ID > ?")' in source
        assert 'CobolSql.open("C1", WS_ID)' in source
        assert 'CobolSql.fetch("C1")' in source and 'CobolSql.close("C1")' in source

    def test_db2_syntax_is_translated_for_postgresql(self):
        source = _java(
            "           EXEC SQL SELECT NAME INTO :WS-NAME FROM T\n"
            "                FETCH FIRST 1 ROW ONLY END-EXEC.\n")
        assert "LIMIT 1" in source

    def test_no_support_class_when_there_is_no_sql(self):
        assert "CobolSql" not in _java("           MOVE 1 TO WS-ID.\n")


class TestRefusals:
    @pytest.mark.parametrize("body,reason", [
        ("           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.\n", "FORM"),
        ("           EXEC SQL SELECT NAME INTO :WS-NAME:WS-IND FROM T END-EXEC.\n", "INDICATOR"),
        ("           EXEC SQL SELECT NAME INTO :WS-PK FROM T END-EXEC.\n", "HOST_VARIABLE"),
        ("           EXEC SQL SELECT NAME INTO :NOPE FROM T END-EXEC.\n", "HOST_VARIABLE"),
        ("           EXEC SQL OPEN C9 END-EXEC.\n", "CURSOR_NOT_DECLARED"),
        ("           EXEC SQL PREPARE S1 FROM :WS-NAME END-EXEC.\n", "FORM"),
        ("           EXEC SQL CALL P(:WS-ID) END-EXEC.\n", "FORM"),
        ("           EXEC SQL SELECT DAYS(D) INTO :WS-ID FROM T END-EXEC.\n", "DIALECT_"),
        ("           EXEC SQL SELECT A FROM T END-EXEC.\n", "FORM"),
    ])
    def test_outside_the_subset(self, body, reason):
        assert any(r.startswith(reason) for r in _reasons(body)), _reasons(body)

    def test_a_cursor_with_hold_is_refused(self):
        assert "FORM" in _reasons(
            "           EXEC SQL DECLARE C1 CURSOR WITH HOLD\n"
            "                FOR SELECT A FROM T END-EXEC.\n")

    def test_without_sqlca_the_program_cannot_be_lowered(self):
        source = HEAD.replace("           EXEC SQL INCLUDE SQLCA END-EXEC.\n", "")
        program = CobolParser().parse(
            source + "           EXEC SQL COMMIT END-EXEC.\n           STOP RUN.\n")
        assert "SQLCA" in unsupported_reasons(_statements(program)[0], program)

    def test_a_refused_statement_does_not_compile(self):
        source = _java("           EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC.\n")
        assert "UNSUPPORTED_EXEC_SQL$FORM" in source

    def test_sqlca_fields_are_synthesised_once(self):
        program = _program("")
        names = [i.name for i in program.working_storage]
        assert names.count("SQLCODE") == 1 and names.count("SQLSTATE") == 1
