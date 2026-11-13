"""VSAM assessment in the real discovery workflow (ingested workspace -> discovery result -> API response).

The assessment is not a second pipeline: ``discover_application`` (the function behind
``GET /applications/{id}/discovery``) attaches one assessment per FD to each discovered program, using the
programs ApplicationDiscovery already parsed (COPY inside FD expanded).  No data is read or converted here.
"""
from __future__ import annotations

from pathlib import Path

from api.ingestion import discover_application

CUSTOMER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTPGM.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "CUST.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-ID.
           SELECT LEDGER ASSIGN TO "LEDGER.DAT".
       DATA DIVISION.
       FILE SECTION.
       FD CUST-FILE.
           COPY CUSTREC.
       FD LEDGER.
       01 LEDGER-REC.
          05 L-KEY   PIC X(4).
          05 L-COUNT PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
CUSTREC = """\
       01 CUST-REC.
          05 CUST-ID   PIC X(6).
          05 CUST-NAME PIC X(20).
          05 CUST-BAL  PIC S9(7)V99 COMP-3.
"""


def workspace(tmp_path: Path) -> dict:
    (tmp_path / "CUSTPGM.cob").write_text(CUSTOMER, encoding="utf-8")
    (tmp_path / "CUSTREC.cpy").write_text(CUSTREC, encoding="utf-8")
    return discover_application(tmp_path, "vsam-demo").to_dict()


def files_of(result: dict) -> dict:
    (program,) = result["cobol_programs"]
    return {f["file"]: f for f in program["vsam_assessment"]}


def test_discovery_attaches_an_assessment_for_every_fd_of_every_program(tmp_path):
    result = workspace(tmp_path)
    assert result["discovery_errors"] == []
    files = files_of(result)
    assert sorted(files) == ["CUST-FILE", "LEDGER"]


def test_a_copy_inside_the_fd_is_assessed_with_the_copybook_record(tmp_path):
    cust = files_of(workspace(tmp_path))["CUST-FILE"]
    assert cust["organization"] == "INDEXED" and cust["record_key"] == "CUST-ID"
    assert cust["record_layouts"][0]["record_name"] == "CUST-REC"
    assert cust["record_layouts"][0]["record_length"] == 6 + 20 + 5
    assert cust["migration"]["status"] == "MIGRATABLE"


def test_a_binary_file_is_reported_as_requiring_platforms(tmp_path):
    ledger = files_of(workspace(tmp_path))["LEDGER"]
    assert ledger["migration"]["status"] == "REQUIRES_PLATFORMS"
    assert ledger["record_layouts"][0]["has_binary"] is True


def test_the_discovery_result_stays_deterministic_with_the_assessment(tmp_path):
    import json

    first = json.dumps(workspace(tmp_path), sort_keys=True)
    second = json.dumps(discover_application(tmp_path, "vsam-demo").to_dict(), sort_keys=True)
    assert first == second


def test_the_api_discovery_endpoint_returns_the_assessment(tmp_path, monkeypatch):
    """Through the HTTP route the product exposes, not only the function."""
    from fastapi.testclient import TestClient

    import api.app as api_app

    (tmp_path / "CUSTPGM.cob").write_text(CUSTOMER, encoding="utf-8")
    (tmp_path / "CUSTREC.cpy").write_text(CUSTREC, encoding="utf-8")

    class _App:
        cobol_source_path = str(tmp_path)

    class _Svc:
        def get_application(self, app_id):
            return _App()

    monkeypatch.setattr(api_app, "_svc", lambda: _Svc())
    body = TestClient(api_app.app).get("/applications/app-1/discovery")
    assert body.status_code == 200, body.text
    program = body.json()["cobol_programs"][0]
    assert {f["file"] for f in program["vsam_assessment"]} == {"CUST-FILE", "LEDGER"}


def test_an_assessment_failure_in_one_fd_does_not_stop_discovery(tmp_path, monkeypatch):
    import engine.vsam.assess as assess

    def boom(fd):
        raise RuntimeError("layout bug")

    monkeypatch.setattr(assess, "assess_file_definition", boom)
    (tmp_path / "CUSTPGM.cob").write_text(CUSTOMER, encoding="utf-8")
    (tmp_path / "CUSTREC.cpy").write_text(CUSTREC, encoding="utf-8")
    result = discover_application(tmp_path, "vsam-demo").to_dict()
    (program,) = result["cobol_programs"]                              # the program is still discovered
    assert result["discovery_errors"] == []
    assert {f["migration"]["status"] for f in program["vsam_assessment"]} == {"ERROR"}
    assert all("layout bug" in " ".join(f["migration"]["reasons"]) for f in program["vsam_assessment"])
