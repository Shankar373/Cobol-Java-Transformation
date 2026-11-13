"""VSAM migration through the control-plane API: upload a dataset for a file the application declares.

Layout, keys and organization come from the application's own discovered FD (COPY inside FD expanded); the request only
chooses encodings, platforms and the record of a multi-record FD.  A success is stored under a deterministic id, can be
read back and downloaded, and a refusal never produces a downloadable artifact.  Dependency-free apart from FastAPI's
TestClient (pytest only).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app as api_app
from api import vsam_migration

PROGRAM = """\
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


def customer(ident: str, name: str, bal: bytes = bytes([0x00, 0x01, 0x23, 0x45, 0x6C])) -> bytes:
    return ident.encode().ljust(6) + name.encode().ljust(20) + bal


@pytest.fixture()
def client(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "CUSTPGM.cob").write_text(PROGRAM, encoding="utf-8")
    (src / "CUSTREC.cpy").write_text(CUSTREC, encoding="utf-8")

    class _App:
        cobol_source_path = str(src)

    class _Svc:
        def get_application(self, app_id):
            return _App()

    monkeypatch.setattr(api_app, "_svc", lambda: _Svc())
    monkeypatch.setenv("CONTROL_PLANE_WORKSPACE_DIR", str(tmp_path / "work"))
    return TestClient(api_app.app)


def post(client, data: bytes, **options):
    options.setdefault("file", "CUST-FILE")
    options.setdefault("source_encoding", "ASCII")
    options.setdefault("destination_encoding", "EBCDIC_CP037")
    return client.post("/applications/app-1/vsam/migrate",
                       files={"dataset": ("CUST.DAT", data, "application/octet-stream")},
                       data={"options": json.dumps(options)})


def test_a_ksds_dataset_is_migrated_with_layout_and_key_taken_from_the_applications_own_fd(client):
    src = customer("B002", "bravo") + customer("A001", "alpha")
    response = post(client, src)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "RECONCILED" and body["success"] is True
    assert body["file"] == "CUST-FILE" and body["source"]["organization"] == "KSDS"
    assert body["layout"]["record_name"] == "CUST-REC" and body["layout"]["record_length"] == 31
    assert body["converted_record_count"] == 2 and body["rejected_record_count"] == 0
    download = client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download")
    assert download.status_code == 200
    first = download.content[:31]
    assert first[:6] == "A001  ".encode("cp037") and first[26:] == bytes([0x00, 0x01, 0x23, 0x45, 0x6C])   # key order, packed kept


def test_the_stored_report_survives_and_matches(client):
    body = post(client, customer("A001", "alpha")).json()
    again = client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}")
    assert again.status_code == 200 and again.json()["output_sha256"] == body["output_sha256"]


def test_the_same_request_gets_the_same_deterministic_id(client):
    src = customer("A001", "alpha")
    assert post(client, src).json()["migration_id"] == post(client, src).json()["migration_id"]
    assert post(client, src + customer("B002", "b")).json()["migration_id"] != post(client, src).json()["migration_id"]


def test_a_rejected_record_is_reported_and_the_state_is_not_hidden(client):
    src = customer("A001", "alpha") + customer("B002", "bad", bal=bytes([0x1A, 0x00, 0x00, 0x00, 0x0C]))
    body = post(client, src).json()
    assert body["rejected_record_count"] == 1 and body["converted_record_count"] == 1
    assert "non-decimal digit" in body["rejected"][0]["reason"]


def test_a_binary_file_without_platforms_is_refused_by_name_and_has_no_download(client):
    response = post(client, b"ABCD\x00\x01", file="LEDGER")
    body = response.json()
    assert response.status_code == 201 and body["state"] == "REFUSED" and body["success"] is False
    assert any("source_platform" in f for f in body["failures"])
    assert client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download").status_code == 404


def test_a_binary_file_with_explicit_platforms_is_converted(client):
    ibm_to_gnu = {"source_platform": "IBM_ZOS", "target_platform": "GNUCOBOL_X86_DEFAULT",
                  "source_encoding": "EBCDIC_CP037", "destination_encoding": "ASCII"}
    src = "AB12".encode("cp037") + (258).to_bytes(2, "big", signed=True)
    body = post(client, src, file="LEDGER", **ibm_to_gnu).json()
    assert body["state"] == "RECONCILED", body.get("failures")
    out = client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download").content
    assert out == b"AB12" + (258).to_bytes(2, "big", signed=True)


@pytest.mark.parametrize("options,phrase", [
    ({"file": "NOPE"}, "no file named"),
    ({"source_encoding": "LATIN1"}, "source_encoding"),
    ({"organization": "VOLCANO"}, "organization"),
    ({"source_platform": "IBM_ZOS"}, "given together"),
    ({"unexpected": "x"}, "unknown option"),
])
def test_bad_requests_are_400_with_the_reason(client, options, phrase):
    response = post(client, customer("A001", "a"), **options)
    assert response.status_code == 400 and phrase in response.text


def test_the_options_must_be_json_and_the_dataset_is_required(client):
    bad = client.post("/applications/app-1/vsam/migrate", files={"dataset": ("d", b"x")}, data={"options": "not json"})
    assert bad.status_code == 400
    assert client.post("/applications/app-1/vsam/migrate", data={"options": "{}"}).status_code == 422


def test_an_unknown_or_malformed_migration_id_is_404_or_400_and_never_a_path(client):
    assert client.get("/applications/app-1/vsam/migrations/vm-0000000000000000").status_code == 404
    assert client.get("/applications/app-1/vsam/migrations/..%2f..%2fetc").status_code in (400, 404)


def test_a_tampered_stored_output_is_not_served(client):
    body = post(client, customer("A001", "alpha")).json()
    stored = next(Path(vsam_migration._root()).rglob("output.dat"))
    stored.write_bytes(b"tampered")
    assert client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download").status_code == 404


def test_an_oversized_dataset_is_refused(client, monkeypatch):
    monkeypatch.setattr(vsam_migration, "MAX_DATASET_BYTES", 10)
    assert post(client, customer("A001", "alpha")).status_code == 400
