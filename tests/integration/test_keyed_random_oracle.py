"""Roadmap unit 7: ``ACCESS MODE IS RANDOM`` on indexed and relative files.

For a program GnuCOBOL accepts, RANDOM access is a strict subset of DYNAMIC: keyed READ,
WRITE (in any key order), REWRITE and DELETE, and no START / READ NEXT. The generated Java
therefore runs the same keyed runtime; this test proves it by running one program on
GnuCOBOL 3.1.2 and on the generated Java and comparing every FILE STATUS it prints.

``ACCESS MODE IS SEQUENTIAL`` was refused here because it changes what a plain READ means, makes an
out-of-order WRITE status 21 and REWRITE/DELETE without a prior READ status 43; roadmap unit 27 added
the ``*Seq`` runtime entry points and proved them in ``test_keyed_sequential_oracle.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import ORACLE_IMAGE

JAVA_IMAGE = "eclipse-temurin:21-jdk"

INDEXED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. KEYRND.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KEYRND.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS RANDOM
               RECORD KEY IS KF-KEY
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-KEY PIC X(4).
           05 KF-DATA PIC X(8).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           DISPLAY "open out " FS
           MOVE "K002" TO KF-KEY
           MOVE "TWO" TO KF-DATA
           WRITE KF-REC
           DISPLAY "write K002 " FS
           MOVE "K001" TO KF-KEY
           MOVE "ONE" TO KF-DATA
           WRITE KF-REC
           DISPLAY "write K001 (out of order) " FS
           MOVE "K001" TO KF-KEY
           MOVE "DUP" TO KF-DATA
           WRITE KF-REC
           DISPLAY "write K001 again " FS
           CLOSE KF
           OPEN I-O KF
           DISPLAY "open i-o " FS
           MOVE "K001" TO KF-KEY
           READ KF
           DISPLAY "read K001 " FS " [" KF-DATA "]"
           MOVE "K009" TO KF-KEY
           READ KF
           DISPLAY "read K009 " FS
           MOVE "K002" TO KF-KEY
           MOVE "TWO-NEW" TO KF-DATA
           REWRITE KF-REC
           DISPLAY "rewrite K002 " FS
           MOVE "K777" TO KF-KEY
           REWRITE KF-REC
           DISPLAY "rewrite K777 " FS
           MOVE "K001" TO KF-KEY
           DELETE KF RECORD
           DISPLAY "delete K001 " FS
           DELETE KF RECORD
           DISPLAY "delete K001 again " FS
           MOVE "K001" TO KF-KEY
           READ KF
           DISPLAY "read K001 after delete " FS
           CLOSE KF
           OPEN INPUT KF
           MOVE "K002" TO KF-KEY
           READ KF
           DISPLAY "read K002 " FS " [" KF-DATA "]"
           CLOSE KF
           STOP RUN.
"""

RELATIVE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RELRND.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RLF ASSIGN TO "RELRND.DAT"
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS RANDOM
               RELATIVE KEY IS RRN
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD RLF.
       01 RLF-REC PIC X(8).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 RRN PIC 9(3).
       PROCEDURE DIVISION.
           OPEN OUTPUT RLF
           MOVE 3 TO RRN
           MOVE "THREE" TO RLF-REC
           WRITE RLF-REC
           DISPLAY "write 3 " FS
           MOVE 1 TO RRN
           MOVE "ONE" TO RLF-REC
           WRITE RLF-REC
           DISPLAY "write 1 " FS
           MOVE 3 TO RRN
           WRITE RLF-REC
           DISPLAY "write 3 again " FS
           CLOSE RLF
           OPEN I-O RLF
           MOVE 1 TO RRN
           READ RLF
           DISPLAY "read 1 " FS " [" RLF-REC "]"
           MOVE 2 TO RRN
           READ RLF
           DISPLAY "read 2 " FS
           MOVE 3 TO RRN
           MOVE "NEW" TO RLF-REC
           REWRITE RLF-REC
           DISPLAY "rewrite 3 " FS
           MOVE 1 TO RRN
           DELETE RLF RECORD
           DISPLAY "delete 1 " FS
           READ RLF
           DISPLAY "read 1 after delete " FS
           CLOSE RLF
           STOP RUN.
"""


def _docker(image: str, workdir: Path, script: str):
    cmd = ["docker", "run", "--rm", "--network", "none", "-w", "/w", "-v", f"{workdir}:/w",
           image, "sh", "-c", script]
    return subprocess.run(cmd, capture_output=True, timeout=600)


@pytest.mark.parametrize("label,source,program", [
    ("indexed", INDEXED, "KEYRND"),
    ("relative", RELATIVE, "RELRND"),
])
def test_random_access_matches_gnucobol(tmp_path, label, source, program):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    result = TransformationProducer().transform(source, program)
    assert result.success is True, result.errors
    cobol_dir, java_dir = tmp_path / "cobol", tmp_path / "java"
    for root in (cobol_dir, java_dir):
        (root / "src").mkdir(parents=True)
        os.chmod(root, 0o777)
        os.chmod(root / "src", 0o777)
    (cobol_dir / "src" / f"{program}.cob").write_text(source, encoding="utf-8", newline="\n")
    for generated in result.generated_files:
        (java_dir / "src" / generated.filename).write_text(
            generated.source_code, encoding="utf-8", newline="\n")
    main = result.generated_files[0].class_name

    cobol = _docker(ORACLE_IMAGE, cobol_dir,
                    f"cobc -x /w/src/{program}.cob -o /tmp/p && /tmp/p")
    java = _docker(JAVA_IMAGE, java_dir,
                   f"mkdir -p /tmp/c && javac -nowarn -d /tmp/c /w/src/*.java && java -cp /tmp/c {main}")

    assert cobol.returncode == 0, cobol.stderr.decode(errors="replace")
    assert java.returncode == 0, java.stderr.decode(errors="replace")
    assert java.stdout.decode() == cobol.stdout.decode()
    assert len(cobol.stdout.decode().splitlines()) >= 8
