"""VSAM migration parity against GnuCOBOL 3.1.2 (not an IBM z/OS verification).

The oracle never sees the migrated images: GnuCOBOL builds its own INDEXED and
RELATIVE files from plain text that this test derives from the raw export with
independent Python code. The Java side reads the *migrated* images through the
real ``CobolFileIo`` runtime class. Both sides must print identical lines.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from enterprise.vsam import migrate_export
from tests.enterprise.vsam_support import (
    fixed_export,
    ksds_records,
    make_manifest,
    rdw_export,
    rrds_export,
    write_export,
)

pytestmark = pytest.mark.docker

ORACLE_IMAGE = "gnucobol-ocesql:latest"
JAVA_IMAGE = "maven-offline-springboot:latest"
KEY_COUNT = 40
PROBE_KEYS = ["0001", "0017", "0040", "0041", "9999"]
RRN_SLOTS = [(1, b"AAAAAAAAAA"), (2, b"BBBBBBBBBB"), (5, b"CCCCCCCCCC"), (9, b"DDDDDDDDDD")]
PROBE_RRNS = [1, 2, 3, 5, 9, 10]


def _docker(image: str, workdir: Path, script: str, entrypoint: str = "sh") -> str:
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{workdir}:/work", "-w", "/work",
         "--entrypoint", entrypoint, image, "-c", script],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


KSDS_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. KSDSORCL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
           SELECT KS ASSIGN TO "ks.dat"
               ORGANIZATION INDEXED ACCESS MODE DYNAMIC
               RECORD KEY IS KS-KEY FILE STATUS IS FS.
       DATA DIVISION.
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
       01 PROBE-LIST.
           05 FILLER PIC X(4) VALUE "0001".
           05 FILLER PIC X(4) VALUE "0017".
           05 FILLER PIC X(4) VALUE "0040".
           05 FILLER PIC X(4) VALUE "0041".
           05 FILLER PIC X(4) VALUE "9999".
       01 PROBES REDEFINES PROBE-LIST.
           05 PROBE PIC X(4) OCCURS 5 TIMES.
       01 I PIC 9 VALUE 0.
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
           OPEN INPUT KS
           MOVE LOW-VALUES TO KS-KEY
           START KS KEY >= KS-KEY
           MOVE "N" TO EOF-FLAG
           PERFORM UNTIL EOF-FLAG = "Y"
               READ KS NEXT AT END MOVE "Y" TO EOF-FLAG
               NOT AT END DISPLAY "SEQ|" KS-KEY "|" KS-DATA
               END-READ
           END-PERFORM
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               MOVE PROBE(I) TO KS-KEY
               READ KS KEY IS KS-KEY
                   INVALID KEY DISPLAY "KEY|" PROBE(I) "|MISS"
                   NOT INVALID KEY DISPLAY "KEY|" KS-KEY "|" KS-DATA
               END-READ
           END-PERFORM
           CLOSE KS
           STOP RUN.
"""

RRDS_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. RRDSORCL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SEQIN ASSIGN TO "seq.txt"
               ORGANIZATION LINE SEQUENTIAL.
           SELECT RS ASSIGN TO "rs.dat"
               ORGANIZATION RELATIVE ACCESS MODE RANDOM
               RELATIVE KEY IS RK FILE STATUS IS FS.
       DATA DIVISION.
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
       01 PROBE-LIST.
           05 FILLER PIC 9(4) VALUE 1.
           05 FILLER PIC 9(4) VALUE 2.
           05 FILLER PIC 9(4) VALUE 3.
           05 FILLER PIC 9(4) VALUE 5.
           05 FILLER PIC 9(4) VALUE 9.
           05 FILLER PIC 9(4) VALUE 10.
       01 PROBES REDEFINES PROBE-LIST.
           05 PROBE PIC 9(4) OCCURS 6 TIMES.
       01 I PIC 9 VALUE 0.
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
           OPEN INPUT RS
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 6
               MOVE PROBE(I) TO RK
               READ RS
                   INVALID KEY DISPLAY "RRN|" PROBE(I) "|MISS"
                   NOT INVALID KEY DISPLAY "RRN|" PROBE(I) "|" RS-REC
               END-READ
           END-PERFORM
           CLOSE RS
           STOP RUN.
"""


def _java_harness(body: str) -> str:
    return "public class Check {\n  public static void main(String[] a) throws Exception {\n" + body + "\n  }\n}\n"


KSDS_JAVA = _java_harness(
    '    String p = "ks.dat";\n'
    '    CobolFileIo.open(p, "INPUT", 4);\n'
    '    CobolFileIo.start(p, ">=", "");\n'
    '    String r;\n'
    '    while ((r = CobolFileIo.readNext(p)) != null) {\n'
    '      System.out.println("SEQ|" + r.substring(0, 4) + "|" + r.substring(4));\n'
    '    }\n'
    '    for (String k : new String[]{"0001", "0017", "0040", "0041", "9999"}) {\n'
    '      String v = CobolFileIo.readKey(p, k);\n'
    '      System.out.println("KEY|" + k + "|" + (v == null ? "MISS" : v.substring(4)));\n'
    '    }'
)
RRDS_JAVA = _java_harness(
    '    String p = "rs.dat";\n'
    '    if (!CobolFileIo.open(p, "INPUT", -1).equals("00")) { System.out.println("OPEN-FAIL"); return; }\n'
    '    for (int n : new int[]{1, 2, 3, 5, 9, 10}) {\n'
    '      String v = CobolFileIo.readRelative(p, n);\n'
    '      System.out.println("RRN|" + String.format("%04d", n) + "|" + (v == null ? "MISS" : v));\n'
    '    }'
)


def _run_oracle(workdir: Path, name: str, source: str) -> list[str]:
    (workdir / f"{name}.cob").write_text(source, encoding="ascii")
    out = _docker(ORACLE_IMAGE, workdir, f"cobc -x -o {name} {name}.cob && ./{name}")
    return [line.rstrip() for line in out.splitlines() if "|" in line]


def _run_java(workdir: Path, body: str, disk_backed: bool = False) -> list[str]:
    (workdir / "CobolFileIo.java").write_text(COBOL_FILE_IO_JAVA, encoding="utf-8")
    (workdir / "Check.java").write_text(body, encoding="utf-8")
    out = _docker(JAVA_IMAGE, workdir,
                  "javac -encoding UTF-8 CobolFileIo.java Check.java && java -Dfile.encoding=UTF-8 "
                  # Threshold 1 byte forces the disk-backed read-only index on these small images.
                  + ("-Dcobolio.diskIndexBytes=1 " if disk_backed else "") + "Check")
    return [line.rstrip() for line in out.splitlines() if "|" in line]


@pytest.mark.parametrize("disk_backed", [False, True], ids=["in-memory", "disk-backed"])
@pytest.mark.parametrize("framing", ["FIXED", "VARIABLE_RDW"])
def test_ksds_migrated_index_matches_gnucobol(tmp_path, framing, disk_backed):
    recs = ksds_records(KEY_COUNT)
    if framing == "FIXED":
        blob = fixed_export(recs)
        manifest = make_manifest(blob, KEY_COUNT)
    else:
        blob = rdw_export(recs)
        manifest = make_manifest(blob, KEY_COUNT, record_format="VARIABLE_RDW", min_len=10, max_len=10)
    migrate_export(write_export(tmp_path, blob), manifest, tmp_path / "ks.dat.idx")
    # Independent oracle input: derived from the raw records without the migrator.
    (tmp_path / "seq.txt").write_text("".join(r.decode("ascii") + "\n" for r in recs), encoding="ascii")

    oracle = _run_oracle(tmp_path, "ksdsorcl", KSDS_COBOL)
    java = _run_java(tmp_path, KSDS_JAVA, disk_backed)
    assert len(oracle) == KEY_COUNT + len(PROBE_KEYS)
    assert any(line.endswith("|MISS") for line in oracle)
    assert java == oracle


@pytest.mark.parametrize("disk_backed", [False, True], ids=["in-memory", "disk-backed"])
def test_rrds_migrated_relative_image_matches_gnucobol(tmp_path, disk_backed):
    blob = rrds_export(RRN_SLOTS)
    manifest = make_manifest(blob, len(RRN_SLOTS), organization="RRDS")
    migrate_export(write_export(tmp_path, blob), manifest, tmp_path / "rs.dat.rel")
    (tmp_path / "seq.txt").write_text(
        "".join(f"{n:04d}{r.decode('ascii')}\n" for n, r in RRN_SLOTS), encoding="ascii")

    oracle = _run_oracle(tmp_path, "rrdsorcl", RRDS_COBOL)
    java = _run_java(tmp_path, RRDS_JAVA, disk_backed)
    assert len(oracle) == len(PROBE_RRNS)
    assert any(line.endswith("|MISS") for line in oracle)
    assert java == oracle
