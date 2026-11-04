"""Roadmap unit 12: what OCESQL on PostgreSQL does, pinned as the reference for JDBC generation.

Runs real embedded-SQL COBOL through OCESQL v1.4 against PostgreSQL 14 (image ``ocesql-pg``,
``Dockerfile.ocesql-pg``).  Two kinds of fact are pinned:

* behaviour a faithful migration must reproduce: SQLCODE 0 / 100 on the success and no-data
  paths, row counts, host-variable values and the final database state (hash);
* behaviour where this reference is **not DB2**: OCESQL's own error SQLCODEs (-403, -400) and a
  PostgreSQL transaction left aborted after an error.  A JDBC lowering must follow DB2 semantics
  there, so those cases compare SQLSTATE and state, never the SQLCODE number.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from engine.sql.oracle_pg import ORACLE_PG_IMAGE, run_cobol

SEED = (
    "create table acct(id int primary key, name varchar(10), bal numeric(9,2));\n"
    "insert into acct values (1,'ALICE',123.45),(2,'BOB',1.00);\n"
)

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01 DBNAME   PIC X(20) VALUE "testdb".
       01 USERNAME PIC X(20) VALUE "postgres".
       01 PASSWD   PIC X(10) VALUE SPACE.
       01 WS-ID    PIC 9(4).
       01 WS-NAME  PIC X(10).
       01 WS-BAL   PIC S9(7)V99.
       EXEC SQL END DECLARE SECTION END-EXEC.
       EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL CONNECT :USERNAME IDENTIFIED BY :PASSWD
                USING :DBNAME END-EXEC.
"""
TAIL = "           EXEC SQL COMMIT END-EXEC.\n           STOP RUN.\n"


def _image_present() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", ORACLE_PG_IMAGE],
                              capture_output=True, timeout=60)
        return done.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_oracle = pytest.mark.skipif(
    not _image_present(), reason="set RUN_DOCKER_TESTS=1 with the ocesql-pg image built")


def _run(body: str):
    return run_cobol(HEAD + body + TAIL, SEED, ("acct",))


@needs_oracle
def test_singleton_select_found_and_not_found():
    result = _run(
        "           MOVE 1 TO WS-ID.\n"
        "           EXEC SQL SELECT NAME, BAL INTO :WS-NAME, :WS-BAL\n"
        "                FROM ACCT WHERE ID = :WS-ID END-EXEC.\n"
        '           DISPLAY "FOUND " SQLCODE " [" WS-NAME "] " WS-BAL.\n'
        "           MOVE 9 TO WS-ID.\n"
        "           EXEC SQL SELECT NAME, BAL INTO :WS-NAME, :WS-BAL\n"
        "                FROM ACCT WHERE ID = :WS-ID END-EXEC.\n"
        '           DISPLAY "NONE " SQLCODE.\n')
    assert result.stdout == (
        "FOUND +0000000000 [ALICE     ] +0000123.45", "NONE +0000000100")
    assert result.returncode == 0


@needs_oracle
def test_dml_row_counts_and_final_state():
    result = _run(
        '           MOVE 3 TO WS-ID.\n           MOVE "CAROL" TO WS-NAME.\n'
        "           MOVE 7.5 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        '           DISPLAY "INS " SQLCODE " " SQLERRD(3).\n'
        "           EXEC SQL UPDATE ACCT SET BAL = BAL + 10 WHERE ID < 3 END-EXEC.\n"
        '           DISPLAY "UPD " SQLCODE " " SQLERRD(3).\n'
        "           EXEC SQL DELETE FROM ACCT WHERE ID = 2 END-EXEC.\n"
        '           DISPLAY "DEL " SQLCODE " " SQLERRD(3).\n'
        "           EXEC SQL UPDATE ACCT SET BAL = 0 WHERE ID = 77 END-EXEC.\n"
        '           DISPLAY "UPD0 " SQLCODE " " SQLERRD(3).\n')
    assert result.stdout == (
        "INS +0000000000 +0000000001", "UPD +0000000000 +0000000002",
        "DEL +0000000000 +0000000001", "UPD0 +0000000000 +0000000000")
    assert result.state == ("--acct", "(1,ALICE,133.45)", '(3,"CAROL     ",7.50)')  # the host variable is passed padded to its PIC width


@needs_oracle
def test_the_same_program_and_seed_give_the_same_state_hash():
    body = "           EXEC SQL UPDATE ACCT SET BAL = BAL * 2 END-EXEC.\n"
    assert _run(body).state_hash == _run(body).state_hash


@needs_oracle
def test_cursor_lifecycle_fetches_rows_in_order_then_no_data():
    result = _run(
        "           EXEC SQL DECLARE C1 CURSOR FOR\n"
        "                SELECT ID, NAME FROM ACCT ORDER BY ID END-EXEC.\n"
        "           EXEC SQL OPEN C1 END-EXEC.\n"
        '           DISPLAY "OPEN " SQLCODE.\n'
        "           PERFORM 3 TIMES\n"
        "               EXEC SQL FETCH C1 INTO :WS-ID, :WS-NAME END-EXEC\n"
        '               DISPLAY "FETCH " SQLCODE " " WS-ID " " WS-NAME\n'
        "           END-PERFORM.\n"
        "           EXEC SQL CLOSE C1 END-EXEC.\n"
        '           DISPLAY "CLOSE " SQLCODE.\n')
    assert result.stdout == (
        "OPEN +0000000000", "FETCH +0000000000 0001 ALICE     ",
        "FETCH +0000000000 0002 BOB       ", "FETCH +0000000100 0002 BOB       ",
        "CLOSE +0000000000")


@needs_oracle
def test_reference_is_not_db2_error_codes_and_aborted_transaction():
    result = _run(
        '           MOVE 1 TO WS-ID.\n           MOVE "DUP" TO WS-NAME.\n'
        "           MOVE 5 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        '           DISPLAY "DUP " SQLCODE " " SQLSTATE.\n'
        "           EXEC SQL SELECT NAME INTO :WS-NAME FROM ACCT\n"
        "                WHERE ID = 1 END-EXEC.\n"
        '           DISPLAY "AFTER " SQLCODE " " SQLSTATE.\n'
        "           EXEC SQL ROLLBACK END-EXEC.\n"
        "           EXEC SQL SELECT NAME INTO :WS-NAME FROM ACCT\n"
        "                WHERE ID = 1 END-EXEC.\n"
        '           DISPLAY "RECOVERED " SQLCODE.\n')
    # DB2 would report -803 for the duplicate key and let the next statement run; this reference
    # reports -403 and fails every statement with 25P02 until the transaction is rolled back.
    assert result.stdout == (
        "DUP -0000000403 23505", "AFTER -0000000400 25P02", "RECOVERED +0000000000")
    assert result.state == ("--acct", "(1,ALICE,123.45)", "(2,BOB,1.00)")
