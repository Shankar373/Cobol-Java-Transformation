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


# --- security review findings ---------------------------------------------------------------------------------------------

def test_two_programs_declaring_the_file_with_different_keys_are_refused(client, tmp_path):
    workspace = next((tmp_path / "src").parent.glob("src"))
    other = PROGRAM.replace("PROGRAM-ID. CUSTPGM.", "PROGRAM-ID. OTHERPGM.").replace(
        "RECORD KEY IS CUST-ID.", "RECORD KEY IS CUST-NAME.")
    (workspace / "OTHERPGM.cob").write_text(other, encoding="utf-8")
    response = post(client, customer("A001", "alpha"))
    assert response.status_code == 400 and "declared differently" in response.text


def test_discovery_errors_refuse_the_migration_instead_of_trusting_a_partial_picture(client, tmp_path):
    workspace = next((tmp_path / "src").parent.glob("src"))
    (workspace / "BROKEN.cob").write_bytes(b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. BAD.\n\xff\xfe\x80\n")
    response = post(client, customer("A001", "alpha"))
    assert response.status_code == 400 and "discovery" in response.text.lower()


def test_the_rejected_list_in_the_report_is_capped_but_the_count_is_exact(client, monkeypatch):
    monkeypatch.setattr(vsam_migration, "MAX_REPORTED_REJECTIONS", 3)
    bad = bytes([0x1A, 0x00, 0x00, 0x00, 0x0C])
    src = b"".join(customer(f"K{i:03d}", "x", bal=bad) for i in range(8))
    body = post(client, src).json()
    assert body["rejected_record_count"] == 8 and len(body["rejected"]) == 3
    assert body["rejected_truncated"] is True


def test_ids_with_a_trailing_newline_or_dot_names_are_rejected(client):
    assert client.get("/applications/app-1/vsam/migrations/vm-0123456789abcdef%0A").status_code in (400, 404)
    with pytest.raises(vsam_migration.VsamRequestError):
        vsam_migration._dir("..", "vm-0123456789abcdef")


def test_an_existing_id_is_not_overwritten_with_a_different_result(client):
    body = post(client, customer("A001", "alpha")).json()
    forged = dict(body, output_sha256="0" * 64)
    with pytest.raises(vsam_migration.VsamRequestError, match="different result"):
        vsam_migration.store("app-1", forged, b"other")


def test_a_concurrent_migration_over_the_limit_is_refused_as_busy(client, monkeypatch):
    acquired = [vsam_migration._SLOTS.acquire(blocking=False) for _ in range(vsam_migration.MAX_CONCURRENT)]
    try:
        response = post(client, customer("A001", "alpha"))
        assert response.status_code in (429, 503) and "busy" in response.text.lower()
    finally:
        for ok in acquired:
            if ok:
                vsam_migration._SLOTS.release()


def test_store_writes_are_atomic_no_partial_files_are_left(client):
    post(client, customer("A001", "alpha"))
    names = {p.name for p in Path(vsam_migration._root()).rglob("*") if p.is_file()}
    assert names == {"output.dat", "report.json"}


# --- architecture review findings ----------------------------------------------------------------------------------------

def test_a_refused_migration_can_be_rerun_after_the_cobol_source_is_fixed(client, tmp_path):
    """The id is tied to the application's layout, so a fixed source gets its own id instead of colliding forever."""
    workspace = tmp_path / "src"
    broken = PROGRAM.replace("COPY CUSTREC.", "COPY MISSING.")
    (workspace / "CUSTPGM.cob").write_text(broken, encoding="utf-8")
    refused = post(client, customer("A001", "alpha"))
    assert refused.status_code == 400                                   # unresolvable FD: refused before any id exists
    (workspace / "CUSTPGM.cob").write_text(PROGRAM, encoding="utf-8")
    ok = post(client, customer("A001", "alpha"))
    assert ok.status_code == 201 and ok.json()["success"] is True


def test_the_same_dataset_gets_a_different_id_when_the_layout_changes(client, tmp_path):
    first = post(client, customer("A001", "alpha")).json()["migration_id"]
    (tmp_path / "src" / "CUSTREC.cpy").write_text(CUSTREC.replace("PIC X(20)", "PIC X(20) "), encoding="utf-8")
    assert post(client, customer("A001", "alpha")).json()["migration_id"] == first      # identical layout: same id
    (tmp_path / "src" / "CUSTREC.cpy").write_text(CUSTREC.replace("CUST-NAME PIC X(20)", "CUST-NAME PIC X(19)\n          05 PAD PIC X"),
                                                  encoding="utf-8")
    assert post(client, customer("A001", "alpha")).json()["migration_id"] != first      # different layout identity


def test_the_organization_option_cannot_downgrade_an_indexed_file(client):
    response = post(client, customer("A001", "alpha"), organization="SEQUENTIAL")
    assert response.status_code == 400 and "organization" in response.text


def test_a_relative_file_is_refused_over_the_api(client, tmp_path):
    (tmp_path / "src" / "CUSTPGM.cob").write_text(PROGRAM.replace(
        "ORGANIZATION IS INDEXED\n               ACCESS MODE IS DYNAMIC\n               RECORD KEY IS CUST-ID.",
        "ORGANIZATION IS RELATIVE\n               ACCESS MODE IS DYNAMIC\n               RELATIVE KEY IS WS-REL."), encoding="utf-8")
    response = post(client, customer("A001", "alpha"))
    assert response.status_code in (201, 400) and "RRDS" in response.text


def test_the_report_states_the_layout_and_engine_it_came_from(client):
    body = post(client, customer("A001", "alpha")).json()
    assert body["engine_version"] and body["layout"]["identity"] and body["source_layout_sha256"]
    assert body["complete"] is True                                      # no rejected records


def test_a_migration_with_rejected_records_is_not_complete(client):
    body = post(client, customer("A001", "alpha") + customer("B002", "b", bal=bytes([0x1A, 0, 0, 0, 0x0C]))).json()
    assert body["success"] is True and body["complete"] is False and body["rejected_record_count"] == 1


def test_downloading_converted_data_needs_the_operator_role_not_viewer():
    from api import rbac

    assert rbac.required_role("GET", "/applications/app-1/vsam/migrations/vm-0123456789abcdef/download") == "operator"
    assert rbac.required_role("GET", "/applications/app-1/vsam/migrations/vm-0123456789abcdef") == "viewer"
    assert rbac.required_role("POST", "/applications/app-1/vsam/migrate") == "operator"


# ---- product-workflow acceptance: authorization over HTTP, unknown application, restart ----

VIEWER, OPERATOR = "viewer-token-0123456789abcdef", "operator-token-0123456789abcdef"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_over_http_a_viewer_cannot_upload_or_download_and_an_operator_can(client, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", json.dumps({VIEWER: "viewer", OPERATOR: "operator"}))
    upload = {"files": {"dataset": ("CUST.DAT", customer("A001", "alpha"), "application/octet-stream")},
              "data": {"options": json.dumps({"file": "CUST-FILE", "source_encoding": "ASCII",
                                              "destination_encoding": "EBCDIC_CP037"})}}
    assert client.post("/applications/app-1/vsam/migrate", **upload).status_code == 401           # no token
    assert client.post("/applications/app-1/vsam/migrate", headers=_auth(VIEWER), **upload).status_code == 403
    created = client.post("/applications/app-1/vsam/migrate", headers=_auth(OPERATOR), **upload)
    assert created.status_code == 201, created.text
    base = f"/applications/app-1/vsam/migrations/{created.json()['migration_id']}"
    assert client.get(base, headers=_auth(VIEWER)).status_code == 200                              # status is readable
    assert client.get(base + "/download").status_code == 401
    assert client.get(base + "/download", headers=_auth(VIEWER)).status_code == 403                # data is not
    assert client.get(base + "/download", headers=_auth(OPERATOR)).status_code == 200


def test_an_unknown_application_is_404_for_every_vsam_route(tmp_path, monkeypatch):
    from api.errors import NotFoundError

    class _Svc:
        def get_application(self, app_id):
            raise NotFoundError(f"Application {app_id!r} not found")

    monkeypatch.setattr(api_app, "_svc", lambda: _Svc())
    monkeypatch.setenv("CONTROL_PLANE_WORKSPACE_DIR", str(tmp_path / "work"))
    ghost = TestClient(api_app.app)
    assert post(ghost, customer("A001", "alpha")).status_code == 404
    assert ghost.get("/applications/app-1/vsam/migrations/vm-0123456789abcdef").status_code == 404
    assert ghost.get("/applications/app-1/vsam/migrations/vm-0123456789abcdef/download").status_code == 404


def test_a_stored_migration_is_readable_after_a_process_restart(client, tmp_path, monkeypatch):
    body = post(client, customer("A001", "alpha") + customer("B002", "bravo")).json()
    first = client.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download").content
    src = tmp_path / "src"

    class _App:
        cobol_source_path = str(src)

    class _Svc:
        def get_application(self, app_id):
            return _App()

    # a new client and service object: the result must come from the files under the workspace alone
    monkeypatch.setattr(api_app, "_svc", lambda: _Svc())
    restarted = TestClient(api_app.app)
    report = restarted.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}")
    assert report.status_code == 200 and report.json()["output_sha256"] == body["output_sha256"]
    assert restarted.get(f"/applications/app-1/vsam/migrations/{body['migration_id']}/download").content == first
    assert post(restarted, customer("A001", "alpha") + customer("B002", "bravo")).json()["migration_id"] == body["migration_id"]
