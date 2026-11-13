"""G-22: an ``EXEC CICS ... END-EXEC`` block is one refused construct, not COBOL file verbs.

The parser had no EXEC CICS awareness, so the inner ``READ DATASET(...)`` /
``WRITE DATASET(...)`` of a block was parsed as an ordinary COBOL READ/WRITE and
then failed FILE SECTION ownership with a misleading "no FD declares ..." error.
CICS stays UNSUPPORTED in the product gate (``scan_constructs`` finds it); this
file pins that the *parser* names the real reason and leaves genuine COBOL file
verbs untouched.  Dependency-free (pytest only).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import ReadStatement, WriteStatement
from engine.transformation.semantic_capability import scan_constructs

HEADER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER ASSIGN TO "MASTER.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD MASTER.
       01 MASTER-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 WS-BUF PIC X(10).
       01 WS-RESP PIC S9(8) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""
FOOTER = "           STOP RUN.\n"


def parse(body: str) -> tuple[CobolParser, list]:
    parser = CobolParser()
    program = parser.parse(HEADER + body + FOOTER)
    return parser, [s for para in program.paragraphs for s in para.statements]


def messages(parser: CobolParser, level: str) -> list[str]:
    pool = parser.diagnostics.errors if level == "error" else parser.diagnostics.warnings
    return [d.message for d in pool]


def cics_warnings(parser: CobolParser) -> list[str]:
    return [m for m in messages(parser, "warning") if "EXEC CICS" in m]


def file_verbs(statements: list) -> list:
    return [s for s in statements if isinstance(s, (ReadStatement, WriteStatement))]


def test_cics_read_dataset_is_not_a_cobol_read():
    parser, statements = parse(
        "           EXEC CICS READ DATASET('CUSTFILE') INTO(WS-BUF)\n"
        "                RIDFLD(WS-BUF) RESP(WS-RESP)\n"
        "           END-EXEC.\n"
    )
    assert file_verbs(statements) == []
    assert not any("FD" in m or "owning file" in m for m in messages(parser, "error"))
    assert any("EXEC CICS READ" in m for m in cics_warnings(parser))


def test_cics_write_dataset_is_not_a_cobol_write():
    parser, statements = parse(
        "           EXEC CICS WRITE DATASET('AUDITFILE') FROM(WS-BUF)\n"
        "                RIDFLD(WS-BUF) RESP(WS-RESP)\n"
        "           END-EXEC.\n"
    )
    assert file_verbs(statements) == []
    assert messages(parser, "error") == []
    assert any("EXEC CICS WRITE" in m for m in cics_warnings(parser))


@pytest.mark.parametrize("command", ["REWRITE DATASET('F') FROM(WS-BUF)", "DELETE DATASET('F')",
                                     "READ UPDATE DATASET('F') INTO(WS-BUF)", "SEND TEXT FROM(WS-BUF)"])
def test_other_cics_commands_are_named_and_never_become_file_verbs(command):
    parser, statements = parse(f"           EXEC CICS {command} END-EXEC.\n")
    assert file_verbs(statements) == []
    assert messages(parser, "error") == []
    assert any("EXEC CICS" in m and command.split()[0] in m for m in cics_warnings(parser))


def test_genuine_cobol_file_verbs_around_a_cics_block_are_unaffected():
    parser, statements = parse(
        "           READ MASTER.\n"
        "           EXEC CICS READ DATASET('X') INTO(WS-BUF) END-EXEC.\n"
        "           MOVE MASTER-REC TO WS-BUF.\n"
        "           WRITE MASTER-REC FROM WS-BUF.\n"
    )
    verbs = file_verbs(statements)
    assert [type(v).__name__ for v in verbs] == ["ReadStatement", "WriteStatement"]
    assert verbs[0].file_name == "MASTER" and verbs[0].record_name == "MASTER-REC"
    assert verbs[1].file_name == "MASTER"
    assert messages(parser, "error") == []
    assert len(cics_warnings(parser)) == 1


def test_a_genuine_cobol_write_of_an_undeclared_record_is_still_refused_next_to_a_cics_block():
    parser, _ = parse(
        "           EXEC CICS READ DATASET('X') INTO(WS-BUF) END-EXEC.\n"
        "           WRITE GHOST-REC FROM WS-BUF.\n"
    )
    assert any("GHOST-REC" in m for m in messages(parser, "error"))


def test_string_literals_that_mention_exec_cics_or_read_are_ordinary_data():
    parser, statements = parse(
        "           DISPLAY 'EXEC CICS READ DATASET(X) END-EXEC'.\n"
        "           DISPLAY 'READ MASTER'.\n"
    )
    assert file_verbs(statements) == []
    assert cics_warnings(parser) == [] and messages(parser, "error") == []
    assert "EXEC CICS" not in scan_constructs(HEADER + "           DISPLAY 'EXEC CICS READ'.\n" + FOOTER)


def test_end_exec_inside_a_literal_does_not_close_the_block():
    parser, statements = parse(
        "           EXEC CICS SEND TEXT FROM('see END-EXEC here')\n"
        "                RESP(WS-RESP)\n"
        "           END-EXEC.\n"
        "           READ MASTER.\n"
    )
    assert messages(parser, "error") == []
    assert len(file_verbs(statements)) == 1  # only the genuine READ after the block


def test_comment_lines_inside_a_block_are_not_part_of_it():
    parser, statements = parse(
        "           EXEC CICS READ DATASET('X') INTO(WS-BUF)\n"
        "      * WRITE MASTER-REC is only a comment\n"
        "                RESP(WS-RESP)\n"
        "           END-EXEC.\n"
    )
    assert file_verbs(statements) == [] and messages(parser, "error") == []


def test_a_block_closed_on_its_own_line_and_on_the_same_line_are_both_recognised():
    parser, statements = parse(
        "           EXEC CICS RETURN END-EXEC.\n"
        "           EXEC CICS\n"
        "               READ DATASET('X') INTO(WS-BUF)\n"
        "           END-EXEC.\n"
        "           EXEC CICS WRITE DATASET('Y') FROM(WS-BUF) END-EXEC.\n"
    )
    assert file_verbs(statements) == [] and messages(parser, "error") == []
    named = cics_warnings(parser)
    assert len(named) == 3
    assert any("RETURN" in m for m in named) and any("READ" in m for m in named) and any("WRITE" in m for m in named)


def test_an_unterminated_block_fails_closed_with_an_error():
    parser, statements = parse(
        "           EXEC CICS READ DATASET('X') INTO(WS-BUF)\n"
        "           MOVE WS-BUF TO MASTER-REC.\n"
    )
    assert any("EXEC CICS" in m and "END-EXEC" in m for m in messages(parser, "error"))
    assert file_verbs(statements) == []


def test_exec_cics_without_a_command_is_malformed():
    parser, _ = parse("           EXEC CICS END-EXEC.\n")
    assert any("EXEC CICS" in m and "no command" in m for m in messages(parser, "error"))


def test_cics_programs_remain_unsupported_in_the_product_gate():
    source = HEADER + "           EXEC CICS READ DATASET('X') INTO(WS-BUF) END-EXEC.\n" + FOOTER
    assert "EXEC CICS" in scan_constructs(source)


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "workload-cics" / "cobol"


@pytest.mark.parametrize("program", ["CUSTINQ.cob", "ORDPROC.cob"])
def test_the_cics_fixture_programs_no_longer_report_a_fabricated_file_problem(program):
    parser = CobolParser()
    parser.parse((FIXTURE / program).read_text(encoding="utf-8"))
    errors = messages(parser, "error")
    assert not any("FILE SECTION" in m or "owning file" in m for m in errors), errors
    assert any("EXEC CICS" in m for m in cics_warnings(parser))
    assert "EXEC CICS" in scan_constructs((FIXTURE / program).read_text(encoding="utf-8"))
