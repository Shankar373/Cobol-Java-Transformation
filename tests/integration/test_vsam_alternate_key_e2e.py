"""KSDS with ALTERNATE RECORD KEYs: HTTP migration API -> generated Java -> GnuCOBOL parity.

The file has a primary key and two alternate keys (one WITH DUPLICATES, one unique), the shape in which alternate-key
browsing is certified (``engine/transformation/alternate_key.py``). The reader reads by each alternate key and browses
with START and READ NEXT along both. GnuCOBOL builds its own file (and its own alternate indexes) from plain text derived
independently of the migrator; the generated Java reads the migrated, downloaded artifact. Output must be identical.
This is GnuCOBOL parity, not an IBM z/OS verification.
"""

from __future__ import annotations

import pytest

from tests.enterprise.vsam_support import fixed_export, make_manifest
from tests.integration.test_vsam_api_to_java_e2e import (  # noqa: F401  (service is a fixture)
    HEADER,
    _generated_java,
    _gnucobol,
    _migrate_over_http,
    client,
    service,
)

pytestmark = pytest.mark.docker

FILES = """           SELECT KF ASSIGN TO "ks.dat"
               ORGANIZATION INDEXED ACCESS MODE DYNAMIC
               RECORD KEY IS KEYF
               ALTERNATE RECORD KEY IS AKD WITH DUPLICATES
               ALTERNATE RECORD KEY IS AKU
               FILE STATUS IS FS.
"""
DATA = """       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KEYF PIC X(2).
           05 AKD  PIC X(2).
           05 AKU  PIC X(2).
           05 DAT  PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
"""
READER = HEADER.format(pid="ALTRD") + FILES + DATA + """       PROCEDURE DIVISION.
           OPEN I-O KF
           DISPLAY "open " FS
           MOVE "BB" TO AKD
           READ KF KEY IS AKD
           DISPLAY "ra1 " FS " " KEYF " " AKD " " AKU " " DAT
           MOVE "U7" TO AKU
           READ KF KEY IS AKU
           DISPLAY "ra2 " FS " " KEYF " " AKD " " AKU " " DAT
           MOVE "ZZ" TO AKD
           READ KF KEY IS AKD
           DISPLAY "ra3 " FS
           MOVE "BB" TO AKD
           START KF KEY >= AKD
           DISPLAY "s1 " FS
           PERFORM 4 TIMES
               READ KF NEXT
               DISPLAY "n " FS " " KEYF " " AKD " " AKU " " DAT
           END-PERFORM
           MOVE "U4" TO AKU
           START KF KEY > AKU
           DISPLAY "s2 " FS
           PERFORM 3 TIMES
               READ KF NEXT
               DISPLAY "n " FS " " KEYF " " AKD " " AKU " " DAT
           END-PERFORM
           MOVE "U99" TO AKU
           START KF KEY = AKU
           DISPLAY "s3 " FS
           READ KF NEXT
           DISPLAY "n " FS
           MOVE "A5" TO KEYF
           READ KF
           DISPLAY "rk " FS " " KEYF " " AKD " " AKU " " DAT
           CLOSE KF
           STOP RUN.
"""
LOADER = HEADER.format(pid="ALTLD") + """           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
""" + FILES + """       DATA DIVISION.
       FILE SECTION.
       FD SEQIN.
       01 SEQ-REC PIC X(8).
       FD KF.
       01 KF-REC.
           05 KEYF PIC X(2).
           05 AKD  PIC X(2).
           05 AKU  PIC X(2).
           05 DAT  PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 EOF-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT SEQIN OUTPUT KF
           PERFORM UNTIL EOF-FLAG = "Y"
               READ SEQIN AT END MOVE "Y" TO EOF-FLAG
               NOT AT END
                   MOVE SEQ-REC TO KF-REC
                   WRITE KF-REC
               END-READ
           END-PERFORM
           CLOSE SEQIN KF
           STOP RUN.
"""


def _records() -> list[bytes]:
    # primary key A1..A9; AKD cycles AA, BB, CC (duplicates); AKU is unique and not in primary order
    unique = ["U3", "U1", "U9", "U4", "U7", "U2", "U8", "U5", "U6"]
    return [f"A{i}{'ABC'[(i - 1) % 3] * 2}{unique[i - 1]}d{i}".encode() for i in range(1, 10)]


def test_alternate_key_ksds_api_to_generated_java_matches_gnucobol(service, tmp_path):  # noqa: F811
    recs = _records()
    blob = fixed_export(recs)
    manifest = make_manifest(
        blob, len(recs), key_length=2, min_len=8, max_len=8, alternate_keys=((2, 2, True), (4, 2, False)))
    artifact = _migrate_over_http(blob, manifest, "ks.dat", cobol_source=READER, cobol_file="KF")
    (tmp_path / "seq.txt").write_text("".join(r.decode() + "\n" for r in recs), encoding="ascii")

    java = _generated_java(tmp_path, READER, "ALTRD", {"ks.dat.idx": artifact})
    oracle = _gnucobol(tmp_path, ("ALTLD", LOADER), ("ALTRD", READER))
    assert oracle[0] == "open 00"
    assert any(line.startswith("ra3 23") for line in oracle)  # a miss is exercised
    assert len([line for line in oracle if line.startswith("n 00")]) >= 4  # browsing is exercised
    assert java == oracle


WIDE = 40  # data after the key is longer than the 32 hex digits of write-sequence prefix the image carries
WIDE_DATA = DATA.replace("05 DAT  PIC X(2).", f"05 DAT  PIC X({WIDE}).")
WIDE_READER = HEADER.format(pid="ALTWR") + FILES + WIDE_DATA + """       PROCEDURE DIVISION.
           OPEN I-O KF
           DISPLAY "open " FS
           MOVE "BB" TO AKD
           READ KF KEY IS AKD
           DISPLAY "ra1 " FS " " KEYF " " AKD " " AKU " " DAT
           MOVE "U7" TO AKU
           READ KF KEY IS AKU
           DISPLAY "ra2 " FS " " KEYF " " AKD " " AKU " " DAT
           MOVE "ZZ" TO AKU
           READ KF KEY IS AKU
           DISPLAY "ra3 " FS
           MOVE "A9" TO KEYF
           READ KF
           DISPLAY "rk " FS " " KEYF " " AKD " " AKU " " DAT
           CLOSE KF
           STOP RUN.
"""
WIDE_LOADER = LOADER.replace("PIC X(8)", f"PIC X({6 + WIDE})").replace(
    "05 DAT  PIC X(2).", f"05 DAT  PIC X({WIDE}).").replace("ALTLD", "ALTWL")


def test_wide_alternate_key_ksds_api_to_generated_java_matches_gnucobol(service, tmp_path):  # noqa: F811
    recs = [r[:6] + f"d{r[7:8].decode()}".encode() + (r[7:8] * (WIDE - 2)) for r in _records()]
    assert all(len(r) == 6 + WIDE for r in recs)
    blob = fixed_export(recs)
    manifest = make_manifest(
        blob, len(recs), key_length=2, min_len=6 + WIDE, max_len=6 + WIDE,
        alternate_keys=((2, 2, True), (4, 2, False)))
    artifact = _migrate_over_http(blob, manifest, "ks.dat", cobol_source=WIDE_READER, cobol_file="KF")
    (tmp_path / "seq.txt").write_text("".join(r.decode() + "\n" for r in recs), encoding="ascii")

    java = _generated_java(tmp_path, WIDE_READER, "ALTWR", {"ks.dat.idx": artifact})
    oracle = _gnucobol(tmp_path, ("ALTWL", WIDE_LOADER), ("ALTWR", WIDE_READER))
    assert oracle[0] == "open 00" and any(line.startswith("ra3 23") for line in oracle)
    assert java == oracle
