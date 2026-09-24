"""Tests for controlled DB2 test-database execution (engine/sql).

Claims are scoped: these tests prove deterministic behavior of the
translated subset on the SQLite-backed controlled database — at most
PORTABLE_EXECUTABLE.  They are not DB2 runtime verification.
"""

from __future__ import annotations

import csv
from pathlib import Path

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.execution import Db2ControlledDatabase
from engine.sql.harness import run_db2_workload
from engine.transformation.sql_parser import SqlParser

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO_ROOT / "fixtures" / "workload-db2"

_ANALYZER = Db2SemanticAnalyzer()
_PARSER = SqlParser()


def semantic(sql: str):
    block = _PARSER.parse_embedded_sql(sql)
    return _ANALYZER.analyze_statement(block.statements[0])


def build_db() -> Db2ControlledDatabase:
    ddl = (_FIXTURES / "schema" / "account.sql").read_text(encoding="utf-8-sig")
    db = Db2ControlledDatabase()
    db.create_schema(ddl)
    return db


def seed_full(db: Db2ControlledDatabase) -> None:
    with open(_FIXTURES / "data" / "account_seed.csv", newline="") as handle:
        records = [
            {
                "ACCOUNT_ID": int(r["ACCOUNT_ID"]),
                "CUSTOMER_NAME": r["CUSTOMER_NAME"],
                "BALANCE": float(r["BALANCE"]),
            }
            for r in csv.DictReader(handle)
        ]
    db.seed_table("ACCOUNT", records)


class TestSchema:
    def test_schema_and_seed(self):
        db = build_db()
        seed_full(db)
        assert db.table_row_count("ACCOUNT") == 5
        rows = db.fetch_table("ACCOUNT")
        by_id = {r["ACCOUNT_ID"]: r for r in rows}
        assert by_id[1]["CUSTOMER_NAME"] == "Alice"
        db.close()


class TestSingletonSelect:
    def test_success_returns_outputs(self):
        db = build_db()
        seed_full(db)
        result = db.execute(
            semantic(
                "SELECT CUSTOMER_NAME, BALANCE INTO :WS-NAME, :WS-BAL "
                "FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"
            ),
            bindings={"WS-ID": 1},
        )
        assert result.status.sqlcode == 0
        assert result.status.sqlstate == "00000"
        assert result.outputs == {"WS-NAME": "Alice", "WS-BAL": 100.0}
        db.close()

    def test_no_data_maps_to_sqlcode_100(self):
        db = build_db()
        seed_full(db)
        result = db.execute(
            semantic(
                "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT "
                "WHERE ACCOUNT_ID = :WS-ID"
            ),
            bindings={"WS-ID": 404},
        )
        assert result.status.sqlcode == 100
        assert result.status.sqlstate == "02000"
        assert result.outputs == {}
        db.close()

    def test_too_many_rows_maps_to_minus_811(self):
        db = build_db()
        seed_full(db)
        result = db.execute(
            semantic(
                "SELECT CUSTOMER_NAME INTO :WS-NAME FROM ACCOUNT"
            ),
            bindings={},
        )
        assert result.status.sqlcode == -811
        assert result.status.sqlstate == "21000"
        db.close()


class TestDml:
    def test_insert_success_and_duplicate_key(self):
        db = build_db()
        seed_full(db)
        ok = db.execute(
            semantic(
                "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME, BALANCE) "
                "VALUES (:WS-ID, :WS-NAME, 0.00)"
            ),
            bindings={"WS-ID": 6, "WS-NAME": "Frank"},
        )
        assert ok.status.sqlcode == 0
        assert ok.rows_affected == 1

        dup = db.execute(
            semantic(
                "INSERT INTO ACCOUNT (ACCOUNT_ID, CUSTOMER_NAME, BALANCE) "
                "VALUES (:WS-ID, :WS-NAME, 0.00)"
            ),
            bindings={"WS-ID": 1, "WS-NAME": "Alice"},
        )
        assert dup.status.sqlcode == -803
        assert dup.status.sqlstate == "23505"
        assert db.table_row_count("ACCOUNT") == 6
        db.close()

    def test_update_rowcount_is_captured(self):
        db = build_db()
        seed_full(db)
        result = db.execute(
            semantic(
                "UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID"
            ),
            bindings={"WS-ID": 2, "WS-BAL": 300.0},
        )
        assert result.status.sqlcode == 0
        assert result.rows_affected == 1
        rows = db.fetch_table("ACCOUNT")
        bob = [r for r in rows if r["ACCOUNT_ID"] == 2][0]
        assert bob["BALANCE"] == 300.0
        db.close()

    def test_delete_success(self):
        db = build_db()
        seed_full(db)
        result = db.execute(
            semantic("DELETE FROM ACCOUNT WHERE ACCOUNT_ID = :WS-ID"),
            bindings={"WS-ID": 4},
        )
        assert result.status.sqlcode == 0
        assert result.rows_affected == 1
        assert db.table_row_count("ACCOUNT") == 4
        db.close()


class TestCursorLifecycle:
    def test_declare_open_fetch_close(self):
        db = build_db()
        seed_full(db)
        declare = semantic(
            "DECLARE C-ACCTS CURSOR FOR "
            "SELECT ACCOUNT_ID, CUSTOMER_NAME FROM ACCOUNT ORDER BY ACCOUNT_ID"
        )
        open_result = db.execute(declare)
        assert open_result.status.sqlcode == 0

        first = db.execute(semantic("OPEN C-ACCTS"))
        assert first.status.sqlcode == 0

        fetch = db.execute(semantic("FETCH C-ACCTS INTO :WS-ID, :WS-NAME"))
        assert fetch.status.sqlcode == 0
        assert fetch.outputs == {"WS-ID": 1, "WS-NAME": "Alice"}

        second = db.execute(semantic("FETCH C-ACCTS INTO :WS-ID, :WS-NAME"))
        assert second.outputs == {"WS-ID": 2, "WS-NAME": "Bob"}

        close = db.execute(semantic("CLOSE C-ACCTS"))
        assert close.status.sqlcode == 0
        db.close()

    def test_fetch_cursor_exhaustion_maps_to_100(self):
        db = build_db()
        seed_full(db)
        db.execute(semantic(
            "DECLARE C-ACCTS CURSOR FOR "
            "SELECT ACCOUNT_ID, CUSTOMER_NAME FROM ACCOUNT ORDER BY ACCOUNT_ID"
        ))
        db.execute(semantic("OPEN C-ACCTS"))
        for _ in range(5):
            db.execute(semantic("FETCH C-ACCTS INTO :WS-ID, :WS-NAME"))
        exhausted = db.execute(semantic("FETCH C-ACCTS INTO :WS-ID, :WS-NAME"))
        assert exhausted.status.sqlcode == 100
        assert exhausted.status.sqlstate == "02000"
        db.close()


class TestTransactions:
    def test_commit_and_rollback_have_success_status(self):
        db = build_db()
        seed_full(db)
        assert db.execute(semantic("COMMIT")).status.sqlcode == 0
        assert db.execute(semantic("ROLLBACK")).status.sqlcode == 0
        db.close()


class TestEndToEndWorkload:
    def test_full_workload_matches_golden_trace(self):
        cobol = (_FIXTURES / "cobol" / "ACCOUNT-DB2.cob").read_text(encoding="utf-8-sig")
        ddl = (_FIXTURES / "schema" / "account.sql").read_text(encoding="utf-8-sig")
        with open(_FIXTURES / "data" / "account_seed.csv", newline="") as handle:
            seed_rows = [
                {
                    "ACCOUNT_ID": int(r["ACCOUNT_ID"]),
                    "CUSTOMER_NAME": r["CUSTOMER_NAME"],
                    "BALANCE": float(r["BALANCE"]),
                }
                for r in csv.DictReader(handle)
            ]
        binding_plan = [
            {"WS-ACCOUNT-ID": 1},
            {"WS-ACCOUNT-ID": 6, "WS-ACCOUNT-NAME": "Frank"},
            {"WS-ACCOUNT-ID": 2, "WS-BALANCE": 50.00},
            {"WS-ACCOUNT-ID": 4},
        ]
        model, trace, db = run_db2_workload(
            cobol,
            "ACCOUNT-DB2",
            ddl,
            seed_rows,
            statement_bindings=binding_plan,
        )
        try:
            golden = (_FIXTURES / "expected" / "db2_execution.trace").read_text(
                encoding="utf-8"
            ).replace("\r\n", "\n").rstrip("\n")
            assert trace.replace("\r\n", "\n").rstrip("\n") == golden
            assert db.table_row_count("ACCOUNT") == 5
            assert model.program_id == "ACCOUNT-DB2"
        finally:
            db.close()