"""Roadmap unit 13: load fixed-width COBOL records into PostgreSQL 14 and reconcile the read-back.

Runs in the ``ocesql-pg`` image (no network).  The source rows are decoded from the text records; the
target rows are read back from the database with ``dump_query``.  A clean load must reconcile; every
kind of tampering after the load (changed value, deleted row, extra row, changed padding) must be
reported, never reconciled.
"""

from __future__ import annotations

import os
import subprocess
from decimal import Decimal

import pytest

from engine.sql.migration import (
    columns_from_record,
    create_table_sql,
    decode_records,
    dump_query,
    load_sql,
    parse_dump,
    reconcile,
)
from engine.sql.oracle_pg import ORACLE_PG_IMAGE, run_sql
from engine.transformation.cobol_parser import CobolParser

SOURCE = (
    "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. T.\n       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n       01 ACCT-REC.\n"
    "          05 ACCT-ID   PIC 9(4).\n          05 ACCT-NAME PIC X(8).\n"
    "          05 ACCT-BAL  PIC 9(7)V99.\n          05 ACCT-BIG  PIC 9(15).\n"
    "       PROCEDURE DIVISION.\n       MAIN.\n           STOP RUN.\n"
)
COLUMNS = columns_from_record(CobolParser().parse(SOURCE).working_storage[0])
KEY = ("acct_id",)
TEXT = (
    "0001ALICE   000012345000000000000001\n"
    "0002BOB     000000100000000000000002\n"
    "0003O'NEIL  000000005999999999999999\n"
    "0004  PAD   099999999000000000000000\n"
)


def _ready() -> bool:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        return False
    try:
        done = subprocess.run(["docker", "image", "inspect", ORACLE_PG_IMAGE],
                              capture_output=True, timeout=60)
        return done.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_oracle = pytest.mark.skipif(not _ready(), reason="set RUN_DOCKER_TESTS=1 with the ocesql-pg image built")


def _round_trip(tamper: str = ""):
    source = decode_records(TEXT, COLUMNS)
    seed = create_table_sql("acct", COLUMNS, KEY) + "\n" + load_sql("acct", source, COLUMNS) + "\n" + tamper
    lines = run_sql(seed, dump_query("acct", COLUMNS, KEY))
    return source, parse_dump(list(lines), COLUMNS)


@needs_oracle
def test_a_clean_load_reconciles_exactly():
    source, target = _round_trip()
    report = reconcile(source, target, COLUMNS, KEY)
    assert report.ok, report
    assert report.source_count == report.target_count == 4
    # the largest value fits NUMERIC(15,0) without rounding, and the totals are exact decimals
    assert report.target_totals["acct_big"] == Decimal("1000000000000002")
    assert report.target_totals["acct_bal"] == Decimal("1000124.49")


@needs_oracle
@pytest.mark.parametrize("tamper,expect", [
    ("UPDATE acct SET acct_bal = acct_bal + 0.01 WHERE acct_id = 2;", "mismatch"),
    ("DELETE FROM acct WHERE acct_id = 3;", "missing"),
    ("INSERT INTO acct VALUES (9, 'EXTRA', 1.00, 1);", "extra"),
    ("UPDATE acct SET acct_name = 'BOB' WHERE acct_id = 2;", "padding"),
])
def test_every_tampering_is_reported(tamper, expect):
    source, target = _round_trip(tamper)
    report = reconcile(source, target, COLUMNS, KEY)
    if expect == "padding":
        # CHAR(n) ignores trailing spaces, so the database cannot hold a different padding: the
        # read-back restores the declared width and the load still reconciles.
        assert report.ok
        return
    assert not report.ok
    if expect == "mismatch":
        assert [(m.column, m.source, m.target) for m in report.mismatches] == [
            ("acct_bal", "1.00", "1.01")]
    elif expect == "missing":
        assert report.missing_in_target == ((Decimal("3"),),)
    else:
        assert report.extra_in_target == ((Decimal("9"),),)
    assert report.source_digest != report.target_digest


@needs_oracle
def test_quotes_and_leading_spaces_survive_the_round_trip():
    source, target = _round_trip()
    by_id = {int(r[0]): r for r in target}
    assert by_id[3][1] == "O'NEIL  " and by_id[4][1] == "  PAD   "
