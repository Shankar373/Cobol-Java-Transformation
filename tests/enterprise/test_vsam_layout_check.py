import pytest
from fastapi.testclient import TestClient

import api.vsam_routes as vsam_routes
from api.app import app
from enterprise.quotas import VsamQuotas
from enterprise.vsam import VsamRefusal
from enterprise.vsam.jobs import VsamJobService
from enterprise.vsam.layout_check import check_manifest_against_cobol
from tests.enterprise.vsam_support import fixed_export, ksds_records, make_manifest

client = TestClient(app)


def program(select: str, fd_body: str, extra_ws: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CHK.\n"
        "       ENVIRONMENT DIVISION.\n       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
        f"{select}"
        "       DATA DIVISION.\n       FILE SECTION.\n"
        f"{fd_body}"
        "       WORKING-STORAGE SECTION.\n       01 FS PIC XX.\n"
        f"{extra_ws}"
        "       PROCEDURE DIVISION.\n           STOP RUN.\n"
    )


KSDS_SELECT = (
    '           SELECT KS ASSIGN TO "ks.dat"\n'
    "               ORGANIZATION INDEXED ACCESS MODE DYNAMIC\n"
    "               RECORD KEY IS KS-KEY FILE STATUS IS FS.\n"
)
KSDS_FD = (
    "       FD KS.\n       01 KS-REC.\n"
    "           05 KS-KEY  PIC X(4).\n           05 KS-DATA PIC X(6).\n"
)
BLOB = fixed_export(ksds_records(3))


def ksds_manifest(**kw):
    return make_manifest(BLOB, 3, **kw)


def refusal_code(source, manifest, runtime_path="ks.dat", file_name=None):
    with pytest.raises(VsamRefusal) as exc:
        check_manifest_against_cobol(source, manifest, runtime_path, file_name)
    return exc.value.code


def test_matching_ksds_layout_is_accepted():
    layout = check_manifest_against_cobol(program(KSDS_SELECT, KSDS_FD), ksds_manifest(), "ks.dat")
    assert (layout.record_length, layout.key_offset, layout.key_length) == (10, 0, 4)
    assert layout.file_name == "KS"


def test_select_can_be_chosen_by_file_name():
    layout = check_manifest_against_cobol(program(KSDS_SELECT, KSDS_FD), ksds_manifest(), "other", "ks")
    assert layout.file_name == "KS"


def test_key_length_mismatch_is_refused():
    assert refusal_code(program(KSDS_SELECT, KSDS_FD), ksds_manifest(key_length=3)) == "KEY_MISMATCH"


def test_key_not_at_offset_zero_is_refused():
    fd = (
        "       FD KS.\n       01 KS-REC.\n"
        "           05 KS-DATA PIC X(6).\n           05 KS-KEY  PIC X(4).\n"
    )
    assert refusal_code(program(KSDS_SELECT, fd), ksds_manifest()) == "KEY_MISMATCH"


def test_record_length_mismatch_is_refused():
    manifest = make_manifest(BLOB, 3, min_len=10, max_len=10).model_copy()
    longer = KSDS_FD.replace("PIC X(6)", "PIC X(8)")
    assert refusal_code(program(KSDS_SELECT, longer), manifest) == "RECORD_LENGTH_MISMATCH"


def test_organization_mismatch_is_refused():
    manifest = make_manifest(BLOB, 3, organization="ESDS")
    assert refusal_code(program(KSDS_SELECT, KSDS_FD), manifest) == "ORGANIZATION_MISMATCH"


def test_cobol_alternate_key_is_refused():
    select = KSDS_SELECT.replace(
        "RECORD KEY IS KS-KEY", "RECORD KEY IS KS-KEY\n               ALTERNATE RECORD KEY IS KS-DATA")
    assert refusal_code(program(select, KSDS_FD), ksds_manifest()) == "ALTERNATE_KEY_UNSUPPORTED"


@pytest.mark.parametrize(
    "extra_field",
    ["           05 KS-N PIC S9(4) COMP.\n", "           05 KS-R REDEFINES KS-DATA PIC X(6).\n"],
)
def test_layouts_that_need_guessing_are_refused(extra_field):
    fd = KSDS_FD + extra_field
    assert refusal_code(program(KSDS_SELECT, fd), ksds_manifest()) == "LAYOUT_UNVERIFIABLE"


def test_missing_select_is_refused():
    assert refusal_code(program(KSDS_SELECT, KSDS_FD), ksds_manifest(), runtime_path="nope.dat") == "FD_NOT_FOUND"


def test_unparseable_source_is_refused():
    # The parser is lenient: garbage yields no SELECT, which is still a refusal.
    assert refusal_code("THIS IS NOT COBOL", ksds_manifest()) in {"COBOL_PARSE_ERROR", "FD_NOT_FOUND"}


@pytest.fixture()
def service(tmp_path):
    svc = VsamJobService(":memory:", tmp_path / "vsam", VsamQuotas(stream_buffer_bytes=4096))
    previous = vsam_routes._service
    vsam_routes.configure(service=svc)
    yield svc
    svc.shutdown()
    vsam_routes._service = previous


def _create(app_id, source, key="k", **manifest_kw):
    return client.post(
        f"/applications/{app_id}/vsam/migrations",
        json={"idempotency_key": key, "runtime_path": "ks.dat", "cobol_source": source,
              "manifest": ksds_manifest(**manifest_kw).model_dump(mode="json")},
    )


def test_api_validates_manifest_against_cobol(service):
    app_id = client.post("/applications", json={"name": "lc", "workload_id": "wl"}).json()["id"]
    good = _create(app_id, program(KSDS_SELECT, KSDS_FD), key="good").json()
    assert good["state"] == "CREATED"
    bad = _create(app_id, program(KSDS_SELECT, KSDS_FD), key="bad", key_length=3).json()
    assert bad["state"] == "REFUSED" and bad["error_code"] == "KEY_MISMATCH"


def test_idempotency_key_covers_the_cobol_source(service):
    app_id = client.post("/applications", json={"name": "lc2", "workload_id": "wl"}).json()["id"]
    source = program(KSDS_SELECT, KSDS_FD)
    first = _create(app_id, source).json()
    assert _create(app_id, source).json()["job_id"] == first["job_id"]
    assert _create(app_id, source + "      * changed\n").status_code == 409
