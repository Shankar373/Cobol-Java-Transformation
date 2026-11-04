"""Roadmap unit 10: EXEC SQL regions are faithful IR, and stay refused.

Before this unit the statement parser dropped ``SELECT`` / ``INSERT`` regions and parsed the
``DELETE`` / ``OPEN`` / ``CLOSE`` inside them as COBOL file verbs.  Every region is now one
``ExecSqlStatement``; the mapper and the capability analysis still refuse it (no Java lowering
exists until unit 12), so no program with embedded SQL can be reported as transformed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_statement
from engine.transformation.exec_sql import classify, find_includes
from engine.transformation.ir import ExecSqlStatement
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY, IR_TYPE_TO_CONSTRUCT

ROOT = Path(__file__).resolve().parent.parent
HEAD = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
    "           EXEC SQL INCLUDE EMPREC END-EXEC.\n       01 WS-ID PIC 9(4).\n"
    "       01 WS-NAME PIC X(10).\n       01 WS-IND PIC S9(4) COMP.\n"
    "       PROCEDURE DIVISION.\n       MAIN.\n"
)


def _parse(body: str):
    return CobolParser().parse(HEAD + body + "           STOP RUN.\n")


def _sql(program) -> list[ExecSqlStatement]:
    found: list[ExecSqlStatement] = []

    def walk(items):
        for s in items:
            if isinstance(s, ExecSqlStatement):
                found.append(s)
            for attr in ("then_body", "else_body", "body"):
                walk(getattr(s, attr, ()) or ())

    for paragraph in program.paragraphs:
        walk(paragraph.statements)
    return found


class TestClassification:
    def test_select_into_directions_and_indicator(self):
        facts = classify("SELECT NAME INTO :WS-NAME:WS-IND FROM T WHERE ID = :WS-ID")
        assert facts["kind"] == "SELECT"
        assert facts["outputs"] == ("WS-NAME",)
        assert facts["inputs"] == ("WS-ID",)
        assert facts["indicators"] == ("WS-IND",)

    def test_indicator_keyword_form(self):
        assert classify("SELECT A INTO :X INDICATOR :XI FROM T")["indicators"] == ("XI",)

    def test_a_host_name_inside_a_string_literal_is_not_a_host_variable(self):
        assert classify("SELECT A INTO :X FROM T WHERE N = ':NOT-A-HOST'")["inputs"] == ()

    @pytest.mark.parametrize("text,kind", [
        ("INSERT INTO T VALUES (:A, :B)", "INSERT"),
        ("UPDATE T SET A = :A WHERE K = :K", "UPDATE"),
        ("DELETE FROM T WHERE K = :K", "DELETE"),
        ("DECLARE C1 CURSOR FOR SELECT A FROM T", "DECLARE_CURSOR"),
        ("OPEN C1", "OPEN"), ("FETCH C1 INTO :A", "FETCH"), ("CLOSE C1", "CLOSE"),
        ("COMMIT", "COMMIT"), ("ROLLBACK", "ROLLBACK"), ("CALL P(:A)", "CALL"),
        ("MYSTERY STATEMENT", "OTHER"),
    ])
    def test_kinds(self, text, kind):
        assert classify(text)["kind"] == kind

    def test_fetch_into_is_output_and_insert_values_are_inputs(self):
        assert classify("FETCH C1 INTO :A, :B")["outputs"] == ("A", "B")
        assert classify("INSERT INTO T VALUES (:A, :B)")["inputs"] == ("A", "B")

    @pytest.mark.parametrize("text,expected", [
        ("WHENEVER SQLERROR GO TO ERR-PARA", ("SQLERROR", "GOTO", "ERR-PARA")),
        ("WHENEVER NOT FOUND GOTO DONE", ("NOT FOUND", "GOTO", "DONE")),
        ("WHENEVER SQLWARNING CONTINUE", ("SQLWARNING", "CONTINUE", "")),
    ])
    def test_whenever(self, text, expected):
        assert classify(text)["whenever"] == expected

    def test_include_members(self):
        assert classify("INCLUDE SQLCA")["include"] == "SQLCA"
        assert find_includes(["EXEC SQL INCLUDE SQLCA END-EXEC.", "EXEC SQL",
                              "  INCLUDE   DCLEMP", "END-EXEC."]) == ("SQLCA", "DCLEMP")


class TestParserKeepsTheRegionWhole:
    def test_includes_are_recorded_on_the_program(self):
        program = _parse("")
        assert program.sql_includes == ("SQLCA", "EMPREC")
        assert [d.name for d in program.working_storage] == ["WS-ID", "WS-NAME", "WS-IND"]

    def test_statements_in_order_with_their_kinds(self):
        program = _parse(
            "           EXEC SQL WHENEVER SQLERROR GO TO ERR END-EXEC.\n"
            "           EXEC SQL\n"
            "               SELECT NAME INTO :WS-NAME:WS-IND\n"
            "                 FROM T WHERE ID = :WS-ID\n"
            "           END-EXEC.\n"
            "           EXEC SQL COMMIT END-EXEC.\n"
        )
        assert [(s.kind, s.outputs, s.inputs) for s in _sql(program)] == [
            ("WHENEVER", (), ()), ("SELECT", ("WS-NAME",), ("WS-ID",)), ("COMMIT", (), ())]
        assert _sql(program)[0].whenever == ("SQLERROR", "GOTO", "ERR")

    def test_a_region_inside_an_if_keeps_the_following_statements(self):
        program = _parse(
            "           IF WS-ID > 1\n"
            "               EXEC SQL DELETE FROM T WHERE K = :WS-ID END-EXEC\n"
            "           END-IF.\n"
            "           MOVE 1 TO WS-ID.\n"
        )
        kinds = [type(s).__name__ for s in program.paragraphs[0].statements]
        assert kinds == ["IfStatement", "MoveStatement", "StopRunStatement"]
        assert [s.kind for s in _sql(program)] == ["DELETE"]

    def test_sql_verbs_are_no_longer_parsed_as_cobol_file_verbs(self):
        program = _parse(
            "           EXEC SQL OPEN C1 END-EXEC.\n"
            "           EXEC SQL CLOSE C1 END-EXEC.\n"
            "           EXEC SQL DELETE FROM T END-EXEC.\n"
        )
        names = {type(s).__name__ for s in program.paragraphs[0].statements}
        assert not names & {"OpenStatement", "CloseStatement", "DeleteStatement"}
        assert program.open_statements == ()

    def test_unterminated_region_is_diagnosed(self):
        parser = CobolParser()
        program = parser.parse(HEAD + "           EXEC SQL SELECT 1 INTO :WS-ID FROM T\n")
        assert [s.terminated for s in _sql(program)] == [False]

    def test_the_db2_fixture_now_keeps_every_statement(self):
        source = (ROOT / "fixtures" / "workload-db2" / "cobol" / "ACCOUNT-DB2.cob").read_text(
            encoding="utf-8")
        program = CobolParser().parse(source)
        kinds = [s.kind for s in _sql(program)]
        assert kinds == ["SELECT", "INSERT", "UPDATE", "DELETE", "COMMIT", "DECLARE_CURSOR",
                         "OPEN", "FETCH", "CLOSE", "COMMIT", "ROLLBACK"]
        assert "SQLCA" not in program.sql_includes  # the fixture declares SQLCODE directly


class TestStillRefused:
    def test_the_mapper_refuses_the_statement(self):
        stmt = _sql(_parse("           EXEC SQL COMMIT END-EXEC.\n"))[0]
        with pytest.raises(NotImplementedError, match="no Java mapping"):
            map_cobol_statement(stmt)

    def test_the_registry_keeps_exec_sql_unsupported(self):
        assert IR_TYPE_TO_CONSTRUCT["ExecSqlStatement"] == "EXEC SQL"
        assert CONSTRUCT_REGISTRY["EXEC SQL"].level.name == "UNSUPPORTED"
