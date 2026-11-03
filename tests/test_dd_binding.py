"""Roadmap unit 4: JCL DD statements bind to COBOL ddnames; datasets are catalogued.

A mainframe program names a file by DD name (``SELECT IN-FILE ASSIGN TO CUSTIN``);
the JCL step binds ``//CUSTIN DD DSN=...``. Before this unit discovery matched a DSN against
the COBOL *SELECT* name, which is not how the binding works. Binding and catalogue are
analysis only: no JCL is executed and the proof state of a JCL application stays PARTIAL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.ingestion import discover_application
from engine.jcl.dd_binding import bind_dd_names, build_dataset_catalog

PAYROLL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO EMPIN
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT PAY-FILE ASSIGN TO PAYOUT
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT LOG-FILE ASSIGN TO "audit.log"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD EMP-FILE.
       01 EMP-REC PIC X(20).
       FD PAY-FILE.
       01 PAY-REC PIC X(20).
       FD LOG-FILE.
       01 LOG-REC PIC X(20).
       PROCEDURE DIVISION.
           STOP RUN.
"""

REPORT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPORTER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PAY-IN ASSIGN TO PAYIN
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT MISSING-F ASSIGN TO NOSUCHDD
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD PAY-IN.
       01 PAY-REC PIC X(20).
       FD MISSING-F.
       01 MISS-REC PIC X(20).
       PROCEDURE DIVISION.
           STOP RUN.
"""

JCL = """\
//PAYJOB   JOB CLASS=A
//STEP01   EXEC PGM=PAYROLL
//EMPIN    DD DSN=HR.EMPLOYEES,DISP=SHR
//PAYOUT   DD DSN=HR.PAYMENTS.G0001V00,DISP=(NEW,CATLG,DELETE)
//SYSPRINT DD SYSOUT=*
//EXTRA    DD DSN=HR.UNUSED,DISP=SHR
//STEP02   EXEC PGM=REPORTER
//PAYIN    DD DSN=HR.PAYMENTS.G0001V00,DISP=SHR
//TMPWORK  DD DSN=&&WORK,DISP=(NEW,PASS),SPACE=(TRK,(1,1))
//STEP03   EXEC PGM=GHOST
//SYSIN    DD *
"""


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "PAYROLL.cob").write_text(PAYROLL, encoding="utf-8")
    (tmp_path / "REPORTER.cob").write_text(REPORT, encoding="utf-8")
    (tmp_path / "PAYJOB.jcl").write_text(JCL, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def discovery(workspace):
    return discover_application(workspace, "dd-binding").to_dict()


def _by_key(rows, *keys):
    return {tuple(r[k] for k in keys): r for r in rows}


class TestBindings:
    def test_ddnames_bind_to_the_steps_dd_statements(self, discovery):
        rows = _by_key(discovery["dd_bindings"], "step", "ddname")
        emp = rows[("STEP01", "EMPIN")]
        assert (emp["status"], emp["dataset"], emp["file_name"], emp["program"]) == (
            "BOUND", "HR.EMPLOYEES", "EMP-FILE", "PAYROLL")
        assert rows[("STEP01", "PAYOUT")]["status"] == "BOUND"
        assert rows[("STEP02", "PAYIN")]["dataset"] == "HR.PAYMENTS.G0001V00"

    def test_a_ddname_without_a_dd_statement_is_unbound(self, discovery):
        row = _by_key(discovery["dd_bindings"], "step", "ddname")[("STEP02", "NOSUCHDD")]
        assert row["status"] == "UNBOUND"
        assert "no DD statement" in row["detail"]

    def test_a_literal_file_name_is_not_jcl_bound(self, discovery):
        rows = [r for r in discovery["dd_bindings"] if r["file_name"] == "LOG-FILE"]
        assert rows and rows[0]["status"] == "LITERAL_PATH"

    def test_unused_dd_is_reported_but_standard_dds_are_not(self, discovery):
        unused = {r["ddname"] for r in discovery["dd_bindings"] if r["status"] == "UNUSED_DD"}
        assert "EXTRA" in unused
        assert "SYSPRINT" not in unused and "SYSIN" not in unused

    def test_a_step_whose_program_is_not_in_the_application_has_no_bindings(self, discovery):
        assert not [r for r in discovery["dd_bindings"] if r["step"] == "STEP03"]

    def test_deterministic_and_sorted(self, workspace):
        first = discover_application(workspace, "a").to_dict()["dd_bindings"]
        second = discover_application(workspace, "a").to_dict()["dd_bindings"]
        assert first == second
        keys = [(r["job"], r["step"], r["ddname"]) for r in first]
        assert keys == sorted(keys)


class TestDatasetCatalog:
    def test_producers_and_consumers(self, discovery):
        catalog = {e["dsn"]: e for e in discovery["dataset_catalog"]}
        payments = catalog["HR.PAYMENTS.G0001V00"]
        roles = {(u["step"], u["role"]) for u in payments["uses"]}
        assert roles == {("STEP01", "PRODUCER"), ("STEP02", "CONSUMER")}
        assert catalog["HR.EMPLOYEES"]["uses"][0]["role"] == "CONSUMER"

    def test_temporary_and_inline_and_sysout_are_classified(self, discovery):
        catalog = {e["dsn"]: e for e in discovery["dataset_catalog"]}
        assert catalog["&&WORK"]["kind"] == "TEMPORARY"
        assert catalog["&&WORK"]["uses"][0]["role"] == "PRODUCER"
        assert catalog["HR.EMPLOYEES"]["kind"] == "PERMANENT"

    def test_cross_step_flow_edges(self, discovery):
        flows = {(f["from"], f["to"], f["dsn"]) for f in discovery["dataset_flows"]}
        assert ("PAYJOB.STEP01", "PAYJOB.STEP02", "HR.PAYMENTS.G0001V00") in flows


class TestUnits:
    def test_gdg_relative_forms_are_flagged_not_resolved(self):
        from engine.transformation.jcl_discovery import JclDiscovery

        jcl = (
            "//GDGJOB JOB CLASS=A\n"
            "//S1 EXEC PGM=PAYROLL\n"
            "//EMPIN DD DSN=HR.MASTER(+1),DISP=(NEW,CATLG)\n"
            "//PAYOUT DD DSN=HR.MASTER(0),DISP=SHR\n"
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "G.jcl").write_text(jcl, encoding="utf-8")
            app = JclDiscovery().discover(tmp)
        catalog = {e["dsn"]: e for e in build_dataset_catalog(app)}
        assert catalog["HR.MASTER(+1)"]["kind"] == "GDG_RELATIVE"
        assert "not resolved" in catalog["HR.MASTER(+1)"]["flags"][0]

    def test_bind_with_no_programs_is_empty(self):
        from engine.transformation.ir import JclApplication

        assert bind_dd_names(JclApplication(), {}) == []
