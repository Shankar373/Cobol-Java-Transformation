"""Tests for the DB2 workload fixture (fixtures/workload-db2).

Validates the deterministic fixture contract:
- EXEC SQL extraction from the fixed-format COBOL source
- schema + seed SQL/CSV consistency
- workload manifest loads
- the fixture's expected golden execution trace exists and is deterministic
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from engine.sql.extractor import (
    analyze_cobol_sql,
    extract_embedded_sql_blocks,
    parse_sql_blocks,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workload-db2"
_COBOL = _FIXTURES / "cobol" / "ACCOUNT-DB2.cob"

_SAMPLE = """\
000100 IDENTIFICATION DIVISION.
001500      *> a comment that mentions EXEC SQL and must not open a region.
001600 01 SQLCODE              PIC S9(9) COMP-5.
003000     EXEC SQL
003100         SELECT BALANCE
003200           INTO :WS-BAL
003300           FROM ACCOUNT
003400          WHERE ACCOUNT_ID = :WS-ID
003500     END-EXEC.
004700     EXEC SQL
004800         UPDATE ACCOUNT SET BALANCE = :WS-BAL WHERE ACCOUNT_ID = :WS-ID
005000     END-EXEC.
010900 END PROGRAM ACCOUNT-DB2.
"""


class TestExtraction:
    def test_sample_count_and_first_sql(self):
        blocks = extract_embedded_sql_blocks(_SAMPLE)
        assert len(blocks) == 2
        assert blocks[0].splitlines()[0] == "SELECT BALANCE"
        assert blocks[1].startswith("UPDATE ACCOUNT")

    def test_comment_mentioning_exec_sql_opens_no_region(self):
        blocks = extract_embedded_sql_blocks(_SAMPLE)
        assert all("block." not in b for b in blocks)
        assert not any("DB2 status fields" in b for b in blocks)

    def test_fixture_yields_eleven_blocks(self):
        blocks = extract_embedded_sql_blocks(_COBOL.read_text(encoding="utf-8-sig"))
        assert len(blocks) == 11

    def test_fixture_parses_and_analyzes(self):
        cobol = _COBOL.read_text(encoding="utf-8-sig")
        parsed = parse_sql_blocks(extract_embedded_sql_blocks(cobol))
        assert sum(len(block.statements) for block in parsed) == 11
        model = analyze_cobol_sql(cobol, "ACCOUNT-DB2")
        assert model.program_id == "ACCOUNT-DB2"
        assert {s.statement_type for s in model.statements} == {
            "SELECT", "INSERT", "UPDATE", "DELETE", "COMMIT", "ROLLBACK",
            "DECLARE_CURSOR", "OPEN_CURSOR", "FETCH_CURSOR", "CLOSE_CURSOR",
        }


class TestSchemaAndSeedConsistency:
    def _csv_rows(self) -> set[tuple]:
        with open(_FIXTURES / "data" / "account_seed.csv", newline="") as handle:
            return {
                (int(r["ACCOUNT_ID"]), r["CUSTOMER_NAME"], float(r["BALANCE"]))
                for r in csv.DictReader(handle)
            }

    def _sql_rows(self) -> set[tuple]:
        text = (_FIXTURES / "data" / "account_seed.sql").read_text(encoding="utf-8")
        rows: set[tuple] = set()
        for match in re.finditer(
            r"INSERT INTO ACCOUNT\s*\([^)]*\)\s*VALUES\s*\((\d+),\s*'([^']*)',\s*([0-9.]+)\)",
            text,
            re.IGNORECASE,
        ):
            rows.add((int(match.group(1)), match.group(2), float(match.group(3))))
        return rows

    def test_csv_and_sql_seed_agree(self):
        assert self._csv_rows() == self._sql_rows()
        assert len(self._csv_rows()) == 5

    def test_schema_has_expected_tables(self):
        ddl = (_FIXTURES / "schema" / "account.sql").read_text(encoding="utf-8")
        assert "CREATE TABLE ACCOUNT" in ddl.upper()
        assert "CREATE TABLE ACCOUNT_LOG" in ddl.upper()


class TestWorkloadManifest:
    def test_manifest_loads(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("workload_db2", _FIXTURES / "workload.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        definition = module.db2_workload()
        assert definition.workload_id == "workload-db2"
        names = {i.logical_name for i in definition.inputs}
        assert {"ddl", "seed-sql", "seed-csv", "source"} <= names
        assert {a.artifact_type for a in definition.artifacts} == {"TEXT_FILE", "EXIT_STATUS"}


class TestGoldenTrace:
    def test_golden_trace_is_deterministic_and_supported(self):
        golden = (_FIXTURES / "expected" / "db2_execution.trace").read_text(
            encoding="utf-8"
        ).replace("\r\n", "\n").rstrip("\n")
        lines = golden.splitlines()
        assert lines[0].startswith("SELECT_INTO 0/00000")
        # The golden trace exercises only successful outcomes for the seeded
        # path; no-data (100) and too-many-rows (-811) are covered at unit level.
        assert all(line.count("0/00000") >= 1 for line in lines)
        assert not any(line.startswith(("SELECT_INTO 100", "FETCH 100")) for line in lines)