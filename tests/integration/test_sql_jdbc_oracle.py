"""Roadmap unit 12b: generated JDBC Java equals the OCESQL + PostgreSQL reference.

Every program runs twice against the same seeded PostgreSQL 14 in the ``ocesql-pg`` image: once
compiled by OCESQL v1.4 + GnuCOBOL 3.1.2, once as the Java the generator emits (JDK 21, the
PostgreSQL JDBC driver).  Standard output, the return code and the SHA-256 of the final database
state must be identical.

Error paths compare SQLSTATE of the first failing statement, never the SQLCODE number: the
reference reports its own codes (-403, -400) and leaves the transaction aborted, where the lowering
follows DB2 (documented code, statement-level rollback).  See ``engine/sql/oracle_pg.py``.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from engine.sql.oracle_pg import ORACLE_PG_IMAGE, run_cobol, run_java
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator

SEED = (
    "create table acct(id int primary key, name varchar(10), bal numeric(9,2));\n"
    "insert into acct values (1,'ALICE',123.45),(2,'BOB',1.00),(3,'CY',-5.50);\n"
    "create table big(k bigint primary key, note varchar(12));\n"
    "insert into big values (1234567890123,'LARGE');\n"
)
TABLES = ("acct", "big")

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01 DBNAME   PIC X(20) VALUE "testdb".
       01 USERNAME PIC X(20) VALUE "postgres".
       01 PASSWD   PIC X(10) VALUE SPACE.
       01 WS-ID    PIC 9(4).
       01 WS-NAME  PIC X(10).
       01 WS-BAL   PIC S9(7)V99.
       01 WS-BIG   PIC 9(13).
       01 WS-NOTE  PIC X(12).
       EXEC SQL END DECLARE SECTION END-EXEC.
       EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL CONNECT :USERNAME IDENTIFIED BY :PASSWD
                USING :DBNAME END-EXEC.
"""
TAIL = "           EXEC SQL COMMIT END-EXEC.\n           EXEC SQL DISCONNECT ALL END-EXEC.\n           STOP RUN.\n"


def _oracle_ready() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", ORACLE_PG_IMAGE],
                              capture_output=True, timeout=60)
        if done.returncode != 0:
            return False
        probe = subprocess.run(["docker", "run", "--rm", ORACLE_PG_IMAGE, "test", "-s",
                                "/opt/jdbc/postgresql.jar"], capture_output=True, timeout=120)
        return probe.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_oracle = pytest.mark.skipif(
    not _oracle_ready(), reason="set RUN_DOCKER_TESTS=1 with the ocesql-pg image (with JDK + JDBC) built")


def _generate(source: str) -> tuple[str, dict[str, str]]:
    generated = JavaGenerator().generate(CobolParser().parse(source))[0]
    name = re.search(r"public\s+class\s+(\w+)", generated.source_code).group(1)
    return name, {f"{name}.java": generated.source_code}


def _both(body: str):
    source = HEAD + body + TAIL
    reference = run_cobol(source, SEED, TABLES)
    name, files = _generate(source)
    candidate = run_java(files, name, SEED, TABLES)
    assert candidate.stdout == reference.stdout
    assert candidate.returncode == reference.returncode == 0
    assert candidate.state == reference.state
    assert candidate.state_hash == reference.state_hash
    return reference


@needs_oracle
def test_singleton_select_into_character_decimal_and_integer_hosts():
    result = _both(
        "           MOVE 1 TO WS-ID.\n"
        "           EXEC SQL SELECT NAME, BAL INTO :WS-NAME, :WS-BAL\n"
        "                FROM ACCT WHERE ID = :WS-ID END-EXEC.\n"
        '           DISPLAY "A " SQLCODE " [" WS-NAME "] " WS-BAL.\n'
        "           MOVE 3 TO WS-ID.\n"
        "           EXEC SQL SELECT NAME, BAL INTO :WS-NAME, :WS-BAL\n"
        "                FROM ACCT WHERE ID = :WS-ID END-EXEC.\n"
        '           DISPLAY "C " SQLCODE " [" WS-NAME "] " WS-BAL.\n'
        "           EXEC SQL SELECT K, NOTE INTO :WS-BIG, :WS-NOTE\n"
        "                FROM BIG END-EXEC.\n"
        '           DISPLAY "B " SQLCODE " " WS-BIG " " WS-NOTE.\n')
    assert result.stdout[0] == "A +0000000000 [ALICE     ] +0000123.45"


@needs_oracle
def test_no_row_is_sqlcode_100_and_leaves_the_host_variables_alone():
    result = _both(
        '           MOVE "KEEP" TO WS-NAME.\n'
        "           MOVE 9 TO WS-ID.\n"
        "           EXEC SQL SELECT NAME INTO :WS-NAME\n"
        "                FROM ACCT WHERE ID = :WS-ID END-EXEC.\n"
        '           DISPLAY "N " SQLCODE " " SQLSTATE " [" WS-NAME "]".\n')
    assert result.stdout == ("N +0000000100 02000 [KEEP      ]",)


@needs_oracle
def test_insert_update_delete_and_zero_row_dml():
    result = _both(
        '           MOVE 4 TO WS-ID.\n           MOVE "DAVE" TO WS-NAME.\n'
        "           MOVE -12.34 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        '           DISPLAY "INS " SQLCODE.\n'
        "           EXEC SQL UPDATE ACCT SET BAL = BAL + 10 WHERE ID < 3 END-EXEC.\n"
        '           DISPLAY "UPD " SQLCODE.\n'
        "           EXEC SQL DELETE FROM ACCT WHERE ID = 2 END-EXEC.\n"
        '           DISPLAY "DEL " SQLCODE.\n'
        "           EXEC SQL UPDATE ACCT SET BAL = 0 WHERE ID = 77 END-EXEC.\n"
        '           DISPLAY "ZERO " SQLCODE.\n')
    assert result.stdout == (
        "INS +0000000000", "UPD +0000000000", "DEL +0000000000", "ZERO +0000000000")


@needs_oracle
def test_commit_keeps_and_rollback_discards():
    _both(
        '           MOVE 5 TO WS-ID.\n           MOVE "EVE" TO WS-NAME.\n'
        "           MOVE 1 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        "           EXEC SQL COMMIT END-EXEC.\n"
        '           MOVE 6 TO WS-ID.\n           MOVE "FAY" TO WS-NAME.\n'
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        "           EXEC SQL ROLLBACK END-EXEC.\n"
        "           EXEC SQL SELECT COUNT(*) INTO :WS-ID FROM ACCT END-EXEC.\n"
        '           DISPLAY "COUNT " WS-ID.\n')


@needs_oracle
def test_cursor_lifecycle_with_a_host_variable_in_the_where_clause():
    result = _both(
        "           MOVE 1 TO WS-ID.\n"
        "           EXEC SQL DECLARE C1 CURSOR FOR\n"
        "                SELECT ID, NAME, BAL FROM ACCT WHERE ID > :WS-ID\n"
        "                ORDER BY ID END-EXEC.\n"
        "           EXEC SQL OPEN C1 END-EXEC.\n"
        '           DISPLAY "OPEN " SQLCODE.\n'
        "           PERFORM 3 TIMES\n"
        "               EXEC SQL FETCH C1 INTO :WS-ID, :WS-NAME, :WS-BAL\n"
        "               END-EXEC\n"
        '               DISPLAY "FETCH " SQLCODE " " WS-ID " " WS-NAME " " WS-BAL\n'
        "           END-PERFORM.\n"
        "           EXEC SQL CLOSE C1 END-EXEC.\n"
        '           DISPLAY "CLOSE " SQLCODE.\n')
    assert result.stdout[0] == "OPEN +0000000000"
    assert any(line.startswith("FETCH +0000000100") for line in result.stdout)


@needs_oracle
def test_host_variables_are_bound_padded_to_their_picture():
    # 'AL' is stored as 'AL        ' by MOVE; comparing it with the trimmed name finds nothing,
    # exactly as in the reference.
    result = _both(
        '           MOVE "AL" TO WS-NAME.\n'
        "           EXEC SQL SELECT ID INTO :WS-ID FROM ACCT\n"
        "                WHERE NAME = :WS-NAME END-EXEC.\n"
        '           DISPLAY "P " SQLCODE.\n'
        '           MOVE "ALICE" TO WS-NAME.\n'
        "           EXEC SQL SELECT ID INTO :WS-ID FROM ACCT\n"
        "                WHERE NAME = :WS-NAME END-EXEC.\n"
        '           DISPLAY "Q " SQLCODE " " WS-ID.\n')
    assert result.stdout[0] == "P +0000000100"


@needs_oracle
def test_first_failure_has_the_same_sqlstate():
    source = HEAD + (
        "           MOVE 1 TO WS-ID.\n           MOVE \"DUP\" TO WS-NAME.\n"
        "           MOVE 5 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        '           IF SQLCODE < 0 DISPLAY "ERR " SQLSTATE.\n'
        "           EXEC SQL ROLLBACK END-EXEC.\n"
    ) + TAIL
    reference = run_cobol(source, SEED, TABLES)
    name, files = _generate(source)
    candidate = run_java(files, name, SEED, TABLES)
    assert candidate.stdout == reference.stdout == ("ERR 23505",)
    assert candidate.state_hash == reference.state_hash


@needs_oracle
def test_the_lowering_keeps_the_transaction_usable_after_a_failure():
    # DB2 behaviour (statement-level rollback): the next statement succeeds.  The reference
    # leaves PostgreSQL's transaction aborted (25P02), so only the lowering is checked here.
    source = HEAD + (
        "           MOVE 1 TO WS-ID.\n           MOVE \"DUP\" TO WS-NAME.\n"
        "           MOVE 5 TO WS-BAL.\n"
        "           EXEC SQL INSERT INTO ACCT VALUES (:WS-ID, :WS-NAME, :WS-BAL)\n"
        "                END-EXEC.\n"
        '           DISPLAY "E " SQLCODE " " SQLSTATE.\n'
        "           EXEC SQL SELECT NAME INTO :WS-NAME FROM ACCT\n"
        "                WHERE ID = 1 END-EXEC.\n"
        '           DISPLAY "N " SQLCODE " [" WS-NAME "]".\n'
    ) + TAIL
    name, files = _generate(source)
    candidate = run_java(files, name, SEED, TABLES)
    assert candidate.stdout == ("E -0000000803 23505", "N +0000000000 [ALICE     ]")
