"""Stage 1 end to end: HTTP migration API -> generated Java -> GnuCOBOL parity.

For each organization the flow is:

1. a logical export is uploaded through the control-plane API and migrated by
   the worker; the artifact is downloaded over HTTP;
2. a COBOL reader program is transformed to Java by the production
   ``TransformationProducer`` and run against the *downloaded* artifact;
3. GnuCOBOL 3.1.2 builds its own file from plain text derived independently of
   the migrator (a COBOL loader program), runs the same reader and prints.

The Java and GnuCOBOL stdout must be identical. For ESDS the migrated file
must also be byte-identical to the file GnuCOBOL writes. This is GnuCOBOL
parity, not an IBM z/OS verification.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.vsam_routes as vsam_routes
from api.app import app
from enterprise.vsam.jobs import VsamJobService
from tests.enterprise.vsam_support import (
    fixed_export,
    ksds_records,
    make_manifest,
    rrds_export,
)
from tests.oracle_java_helpers import ORACLE_IMAGE, run_generated_java

pytestmark = pytest.mark.docker
client = TestClient(app)

HEADER = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. {pid}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
"""

KSDS_FILES = """           SELECT KS ASSIGN TO "ks.dat"
               ORGANIZATION INDEXED ACCESS MODE DYNAMIC
               RECORD KEY IS KS-KEY FILE STATUS IS FS.
"""
KSDS_DATA = """       DATA DIVISION.
       FILE SECTION.
       FD KS.
       01 KS-REC.
           05 KS-KEY  PIC X(4).
           05 KS-DATA PIC X(6).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 EOF-FLAG PIC X VALUE "N".
"""
KSDS_READER = HEADER.format(pid="KSDSRD") + KSDS_FILES + KSDS_DATA + """       PROCEDURE DIVISION.
           OPEN INPUT KS
           IF FS NOT = "00" DISPLAY "OPEN|" FS STOP RUN END-IF
           MOVE "0010" TO KS-KEY
           START KS KEY >= KS-KEY
           PERFORM UNTIL EOF-FLAG = "Y"
               READ KS NEXT AT END MOVE "Y" TO EOF-FLAG
               NOT AT END DISPLAY "SEQ|" KS-KEY "|" KS-DATA
               END-READ
           END-PERFORM
           MOVE "0017" TO KS-KEY
           READ KS KEY IS KS-KEY
               INVALID KEY DISPLAY "KEY|0017|MISS"
               NOT INVALID KEY DISPLAY "KEY|" KS-KEY "|" KS-DATA
           END-READ
           MOVE "9999" TO KS-KEY
           READ KS KEY IS KS-KEY
               INVALID KEY DISPLAY "KEY|9999|MISS"
               NOT INVALID KEY DISPLAY "KEY|" KS-KEY "|" KS-DATA
           END-READ
           CLOSE KS
           STOP RUN.
"""
KSDS_LOADER = HEADER.format(pid="KSDSLD") + """           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
""" + KSDS_FILES + """       DATA DIVISION.
       FILE SECTION.
       FD SEQIN.
       01 SEQ-REC PIC X(10).
       FD KS.
       01 KS-REC.
           05 KS-KEY  PIC X(4).
           05 KS-DATA PIC X(6).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT SEQIN OUTPUT KS
           PERFORM UNTIL EOF-FLAG = "Y"
               READ SEQIN AT END MOVE "Y" TO EOF-FLAG
               NOT AT END
                   MOVE SEQ-REC TO KS-REC
                   WRITE KS-REC
               END-READ
           END-PERFORM
           CLOSE SEQIN KS
           STOP RUN.
"""

RRDS_FILES = """           SELECT RS ASSIGN TO "rs.dat"
               ORGANIZATION RELATIVE ACCESS MODE RANDOM
               RELATIVE KEY IS RK FILE STATUS IS FS.
"""
RRDS_READER = HEADER.format(pid="RRDSRD") + RRDS_FILES + """       DATA DIVISION.
       FILE SECTION.
       FD RS.
       01 RS-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 RK PIC 9(4).
       PROCEDURE DIVISION.
           OPEN INPUT RS
           MOVE 1 TO RK
           READ RS INVALID KEY DISPLAY "RRN|0001|MISS"
               NOT INVALID KEY DISPLAY "RRN|0001|" RS-REC
           END-READ
           MOVE 3 TO RK
           READ RS INVALID KEY DISPLAY "RRN|0003|MISS"
               NOT INVALID KEY DISPLAY "RRN|0003|" RS-REC
           END-READ
           MOVE 5 TO RK
           READ RS INVALID KEY DISPLAY "RRN|0005|MISS"
               NOT INVALID KEY DISPLAY "RRN|0005|" RS-REC
           END-READ
           MOVE 9 TO RK
           READ RS INVALID KEY DISPLAY "RRN|0009|MISS"
               NOT INVALID KEY DISPLAY "RRN|0009|" RS-REC
           END-READ
           CLOSE RS
           STOP RUN.
"""
RRDS_LOADER = HEADER.format(pid="RRDSLD") + """           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
""" + RRDS_FILES + """       DATA DIVISION.
       FILE SECTION.
       FD SEQIN.
       01 SEQ-REC.
           05 SEQ-RRN PIC 9(4).
           05 SEQ-DATA PIC X(10).
       FD RS.
       01 RS-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 RK PIC 9(4).
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT SEQIN OUTPUT RS
           PERFORM UNTIL EOF-FLAG = "Y"
               READ SEQIN AT END MOVE "Y" TO EOF-FLAG
               NOT AT END
                   MOVE SEQ-RRN TO RK
                   MOVE SEQ-DATA TO RS-REC
                   WRITE RS-REC
               END-READ
           END-PERFORM
           CLOSE SEQIN RS
           STOP RUN.
"""

ESDS_FILES = """           SELECT ES ASSIGN TO "es.dat"
               ORGANIZATION SEQUENTIAL FILE STATUS IS FS.
"""
ESDS_READER = HEADER.format(pid="ESDSRD") + ESDS_FILES + """       DATA DIVISION.
       FILE SECTION.
       FD ES.
       01 ES-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT ES
           PERFORM UNTIL EOF-FLAG = "Y"
               READ ES AT END MOVE "Y" TO EOF-FLAG
               NOT AT END DISPLAY "ES|" ES-REC
               END-READ
           END-PERFORM
           CLOSE ES
           STOP RUN.
"""
ESDS_LOADER = HEADER.format(pid="ESDSLD") + """           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
""" + ESDS_FILES + """       DATA DIVISION.
       FILE SECTION.
       FD SEQIN.
       01 SEQ-REC PIC X(10).
       FD ES.
       01 ES-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT SEQIN OUTPUT ES
           PERFORM UNTIL EOF-FLAG = "Y"
               READ SEQIN AT END MOVE "Y" TO EOF-FLAG
               NOT AT END
                   MOVE SEQ-REC TO ES-REC
                   WRITE ES-REC
               END-READ
           END-PERFORM
           CLOSE SEQIN ES
           STOP RUN.
"""


@pytest.fixture()
def service(tmp_path):
    svc = VsamJobService(":memory:", tmp_path / "vsam-data")
    previous = vsam_routes._service
    vsam_routes.configure(service=svc)
    yield svc
    svc.shutdown()
    vsam_routes._service = previous


def _migrate_over_http(blob: bytes, manifest, runtime_path: str) -> bytes:
    app_id = client.post("/applications", json={"name": "e2e", "workload_id": "wl"}).json()["id"]
    job = client.post(
        f"/applications/{app_id}/vsam/migrations",
        json={"idempotency_key": "e2e", "runtime_path": runtime_path,
              "manifest": manifest.model_dump(mode="json")},
    ).json()
    assert client.put(job["upload_path"], content=blob).status_code == 202
    deadline = time.time() + 30
    while time.time() < deadline:
        state = client.get(f"/vsam/migrations/{job['job_id']}").json()
        if state["state"] in ("SUCCEEDED", "REFUSED", "FAILED"):
            break
        time.sleep(0.05)
    assert state["state"] == "SUCCEEDED", state
    download = client.get(f"/vsam/migrations/{job['job_id']}/download")
    assert download.status_code == 200
    return download.content


def _gnucobol(workdir: Path, loader: tuple[str, str], reader: tuple[str, str]) -> list[str]:
    for pid, source in (loader, reader):
        (workdir / f"{pid}.cob").write_text(source, encoding="ascii")
    os.chmod(workdir, 0o777)
    script = (
        f"cd /work && cobc -x -o load {loader[0]}.cob && ./load && "
        f"cobc -x -o rd {reader[0]}.cob && ./rd"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{workdir}:/work",
         ORACLE_IMAGE, "sh", "-c", script],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.splitlines()


def _generated_java(tmp_path: Path, source: str, pid: str, staged: dict[str, bytes]) -> list[str]:
    run_dir = tmp_path / "java"
    run_dir.mkdir()
    for name, data in staged.items():
        (run_dir / name).write_bytes(data)
    return run_generated_java(source, pid, run_dir).splitlines()


def test_ksds_api_to_generated_java_matches_gnucobol(service, tmp_path):
    recs = ksds_records(30)
    blob = fixed_export(recs)
    artifact = _migrate_over_http(blob, make_manifest(blob, 30), "ks.dat")
    (tmp_path / "seq.txt").write_text("".join(r.decode() + "\n" for r in recs), encoding="ascii")

    java = _generated_java(tmp_path, KSDS_READER, "KSDSRD", {"ks.dat.idx": artifact})
    oracle = _gnucobol(tmp_path, ("KSDSLD", KSDS_LOADER), ("KSDSRD", KSDS_READER))
    assert len(oracle) == 21 + 2  # keys 0010..0030, two random probes
    assert oracle[-1] == "KEY|9999|MISS"
    assert java == oracle


def test_rrds_api_to_generated_java_matches_gnucobol(service, tmp_path):
    slots = [(1, b"AAAAAAAAAA"), (2, b"BBBBBBBBBB"), (5, b"CCCCCCCCCC"), (9, b"DDDDDDDDDD")]
    blob = rrds_export(slots)
    artifact = _migrate_over_http(blob, make_manifest(blob, 4, organization="RRDS"), "rs.dat")
    (tmp_path / "seq.txt").write_text(
        "".join(f"{n:04d}{r.decode()}\n" for n, r in slots), encoding="ascii")

    java = _generated_java(tmp_path, RRDS_READER, "RRDSRD", {"rs.dat.rel": artifact})
    oracle = _gnucobol(tmp_path, ("RRDSLD", RRDS_LOADER), ("RRDSRD", RRDS_READER))
    assert oracle == ["RRN|0001|AAAAAAAAAA", "RRN|0003|MISS", "RRN|0005|CCCCCCCCCC", "RRN|0009|DDDDDDDDDD"]
    assert java == oracle


def test_esds_api_to_generated_java_matches_gnucobol_bytes(service, tmp_path):
    recs = [f"ROW{i:03d}XYZ!".encode() for i in range(12)]
    blob = fixed_export(recs)
    artifact = _migrate_over_http(blob, make_manifest(blob, 12, organization="ESDS"), "es.dat")
    (tmp_path / "seq.txt").write_text("".join(r.decode() + "\n" for r in recs), encoding="ascii")

    java = _generated_java(tmp_path, ESDS_READER, "ESDSRD", {"es.dat": artifact})
    oracle = _gnucobol(tmp_path, ("ESDSLD", ESDS_LOADER), ("ESDSRD", ESDS_READER))
    assert len(oracle) == 12
    assert java == oracle
    assert (tmp_path / "es.dat").read_bytes() == artifact  # GnuCOBOL's own file image
