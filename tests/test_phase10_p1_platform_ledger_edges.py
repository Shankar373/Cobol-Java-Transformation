"""Phase 10 P1-a/P1-b: DB2 and CICS dependency edges reach the platform ledger.

BL-083: ``DependencyKind.DB2`` was produced by no product code — the SQL
lane's own chain (``extract_embedded_sql_blocks`` →
``SqlParser.parse_embedded_sql`` → ``SqlParser.extract_table_dependencies``)
had zero product callers, so declared DB2 tables never entered the integrated
proof's dependency inventory.  ``DependencyKind.CICS`` had the same defect
(reserved by ``integrated_proof``, instantiated only by a hand-built test
entry that proves the gate *would* block while no product ever made one).

Red-first evidence: the producer functions do not exist on unmodified code
(AttributeError), and ``run_db2_workload`` drops its ``sqlcode_field`` /
``sqlstate_field`` parameters (model fields stay empty).

Engine-only (no fastapi/pydantic): safe for the dependency-free
capability-truth gate in .github/workflows/ci.yml.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityLevel,
    CapabilityReport,
)
from engine.modernization.external_dependency_edges import (
    extract_cics_dependency_entries,
    extract_db2_dependency_entries,
)
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    ProofState,
    RuntimeLaneEvidence,
    build_dependency_ledger,
    evaluate_central_status,
)

PERFECT_RUNTIME = RuntimeLaneEvidence(
    verdict_state="VERIFIED",
    executed_check_count=4,
    evidence_complete=True,
    evidence_integrity_valid=True,
    oracle_exit_code=0,
    candidate_exit_code=0,
)

SQL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCT PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL
             SELECT ACCT_BAL INTO :WS-ACCT
               FROM ACCOUNT
           END-EXEC.
           EXEC SQL
             SELECT ACCT_BAL INTO :WS-ACCT
               FROM ACCOUNT
           END-EXEC.
           EXEC SQL
             INSERT INTO TXN_LOG (ACCT_ID) VALUES (:WS-ACCT)
           END-EXEC.
*>      EXEC SQL DELETE FROM SECRET_TABLE END-EXEC.
           EXEC SQL
             MERGE INTO MYSTERY M USING D ON (M.ID = D.ID)
           END-EXEC.
           STOP RUN.
"""

CICS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSPRG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WORK-AREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS
             LINK PROGRAM('SUBPROG') COMMAREA(WORK-AREA)
           END-EXEC.
           EXEC CICS
             WRITEQ QUEUE('ORDQ') FROM(WORK-AREA)
           END-EXEC.
           EXEC CICS
             READ DATASET('CUSTFILE') INTO(WORK-AREA)
           END-EXEC.
           EXEC CICS
             SEND TRANSID('TSK1') FROM(WORK-AREA)
           END-EXEC.
*>      EXEC CICS DELETEQ QUEUE('HIDDENQ') END-EXEC.
           STOP RUN.
"""


def _db2_report():
    class _R:
        application_id = "app-sqlprog"
        generation_success = True
        overall_capability = "SUPPORTED"
        capability_report = CapabilityReport(
            application_id="app-sqlprog",
            components=(),
            overall_level=CapabilityLevel.SUPPORTED,
        )

    return _R()


class TestDb2LedgerEdges:
    """BL-083: DB2 tables enter the ledger, fail-closed and visible."""

    def test_db2_tables_reach_the_ledger(self):
        entries = extract_db2_dependency_entries(SQL_SOURCE, program_id="SQLPROG")
        by_id = {e.dependency_id: e for e in entries}

        account = by_id["DB2:TABLE=ACCOUNT"]
        assert account.kind is DependencyKind.DB2
        assert account.visible is True
        assert account.required is True
        assert account.capability_level is CapabilityLevel.UNSUPPORTED
        assert account.proof_state is ProofState.BLOCKED
        assert "no DB2 runtime lane" in account.reason
        assert "READ" in account.reason

        txn_log = by_id["DB2:TABLE=TXN_LOG"]
        assert txn_log.kind is DependencyKind.DB2
        assert txn_log.proof_state is ProofState.BLOCKED
        assert "INSERT" in txn_log.reason

    def test_db2_entries_deduplicated_and_deterministic(self):
        first = extract_db2_dependency_entries(SQL_SOURCE, program_id="SQLPROG")
        second = extract_db2_dependency_entries(SQL_SOURCE, program_id="SQLPROG")
        assert first == second
        ids = [e.dependency_id for e in first]
        assert ids.count("DB2:TABLE=ACCOUNT") == 1  # two SELECTs, one entry
        # A comment mentioning EXEC SQL never extracts.
        assert not any("SECRET_TABLE" in i for i in ids)

    def test_db2_unmodelled_sql_stays_visible_fail_closed(self):
        entries = extract_db2_dependency_entries(SQL_SOURCE, program_id="SQLPROG")
        unparseable = [
            e for e in entries if e.dependency_id.startswith("DB2:UNPARSEABLE")
        ]
        assert unparseable, (
            "unmodelled SQL (MERGE) silently disappeared from the inventory"
        )
        entry = unparseable[0]
        assert entry.kind is DependencyKind.DB2
        assert entry.required is True
        assert entry.proof_state is ProofState.BLOCKED
        assert "MERGE" in entry.reason

    def test_db2_producer_empty_without_exec_sql(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PLAIN.\n"
            "       PROCEDURE DIVISION.\n"
            '           DISPLAY "HI".\n'
            "           STOP RUN.\n"
        )
        assert extract_db2_dependency_entries(source, program_id="PLAIN") == ()


class TestCicsLedgerEdges:
    """P1-b: CICS resources enter the ledger, fail-closed and visible."""

    def test_cics_resources_reach_the_ledger(self):
        entries = extract_cics_dependency_entries(CICS_SOURCE)
        by_id = {e.dependency_id: e for e in entries}

        program = by_id["CICS:PROGRAM=SUBPROG"]
        assert program.kind is DependencyKind.CICS
        assert program.visible is True
        assert program.required is True
        assert program.capability_level is CapabilityLevel.UNSUPPORTED
        assert program.proof_state is ProofState.BLOCKED
        assert "no CICS runtime lane" in program.reason

        assert by_id["CICS:QUEUE=ORDQ"].proof_state is ProofState.BLOCKED
        assert by_id["CICS:FILE=CUSTFILE"].proof_state is ProofState.BLOCKED
        assert by_id["CICS:TRANSID=TSK1"].proof_state is ProofState.BLOCKED

    def test_cics_entries_deduplicated_and_comment_safe(self):
        first = extract_cics_dependency_entries(CICS_SOURCE)
        second = extract_cics_dependency_entries(CICS_SOURCE)
        assert first == second
        ids = [e.dependency_id for e in first]
        assert ids.count("CICS:PROGRAM=SUBPROG") == 1
        # A commented-out EXEC CICS block never extracts.
        assert not any("HIDDENQ" in i for i in ids)

    def test_cics_producer_empty_without_exec_cics(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PLAIN.\n"
            "       PROCEDURE DIVISION.\n"
            '           DISPLAY "HI".\n'
            "           STOP RUN.\n"
        )
        assert extract_cics_dependency_entries(source) == ()


class TestPlatformEdgesKeepTheGateFailClosed:
    """§41: the central gate accounts for DB2/CICS dependencies."""

    def test_platform_edges_force_not_verified(self):
        ledger = build_dependency_ledger(
            _db2_report(),
            PERFECT_RUNTIME,
            extra_dependencies=extract_db2_dependency_entries(
                SQL_SOURCE, program_id="SQLPROG"
            )
            + extract_cics_dependency_entries(CICS_SOURCE),
            jcl_status="NOT_PRESENT",
        )
        status, reasons = evaluate_central_status(
            ledger, PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED
        assert any("DB2:TABLE=ACCOUNT" in r for r in reasons), reasons
        assert any("CICS:PROGRAM=SUBPROG" in r for r in reasons), reasons


class TestSqlcaFieldsForwarded:
    """BL-083 sub-defect: run_db2_workload declared sqlcode_field /
    sqlstate_field but never forwarded them to the analyzer."""

    def test_run_db2_workload_forwards_sqlca_field_names(self):
        from engine.sql.harness import run_db2_workload

        base = Path("fixtures") / "workload-db2"
        cobol = (base / "cobol" / "ACCOUNT-DB2.cob").read_text(encoding="utf-8-sig")
        ddl = (base / "schema" / "account.sql").read_text(encoding="utf-8-sig")
        model, _trace, db = run_db2_workload(
            cobol,
            "ACCOUNT-DB2",
            ddl,
            [],
            sqlcode_field="WS-SQLCODE",
            sqlstate_field="WS-SQLSTATE",
            # Same host-variable binding plan the golden execution test uses;
            # seed rows stay empty (bindings are what the harness requires).
            statement_bindings=[
                {"WS-ACCOUNT-ID": 1},
                {"WS-ACCOUNT-ID": 6, "WS-ACCOUNT-NAME": "Frank"},
                {"WS-ACCOUNT-ID": 2, "WS-BALANCE": 50.00},
                {"WS-ACCOUNT-ID": 4},
            ],
        )
        try:
            assert model.sqlcode_field == "WS-SQLCODE"
            assert model.sqlstate_field == "WS-SQLSTATE"
        finally:
            db.close()
