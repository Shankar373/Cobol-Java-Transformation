"""Hermetic tests for ACCESS MODE SEQUENTIAL on INDEXED files (roadmap unit 27); GnuCOBOL proof:
tests/integration/test_keyed_sequential_oracle.py."""

from __future__ import annotations

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from engine.transformation.java_generator import JavaGenerator

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. KSL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KSL.DAT"
               ORGANIZATION IS INDEXED
{access}               RECORD KEY IS KF-KEY
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-KEY PIC X(4).
           05 KF-DATA PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN I-O KF
           READ KF
               AT END DISPLAY "END"
           END-READ
           REWRITE KF-REC
           DELETE KF RECORD
           MOVE "K001" TO KF-KEY
           START KF KEY >= KF-KEY
           MOVE "K009" TO KF-KEY
           WRITE KF-REC
           CLOSE KF
           STOP RUN.
"""


def _java(access: str) -> str:
    program = CobolParser().parse(SOURCE.format(access=access))
    return JavaGenerator().generate(program)[0].source_code


def test_sequential_access_lowers_every_verb_to_the_seq_entry_points():
    for access in ("               ACCESS MODE IS SEQUENTIAL\n", ""):  # the default is SEQUENTIAL
        java = _java(access)
        for call in ("readNextSeq", "statusSeq", "rewriteSeq", "deleteSeq", "startSeq", "writeSeq"):
            assert f"CobolFileIo.{call}(" in java, (access, call)


def test_dynamic_access_keeps_the_proven_keyed_entry_points():
    java = _java("               ACCESS MODE IS DYNAMIC\n")
    assert "CobolFileIo.readNextSeq(" not in java and "Seq(\"KSL.DAT\"" not in java
    assert "CobolFileIo.rewrite(" in java and "CobolFileIo.delete(" in java and "CobolFileIo.start(" in java


def test_at_end_runs_only_for_status_10():
    java = _java("               ACCESS MODE IS SEQUENTIAL\n")
    assert 'CobolFileIo.statusSeq("KSL.DAT")' in java
    assert '.equals("10")' in java or '"10".equals' in java


def test_runtime_template_defines_the_sequential_status_rules():
    for code in ('"21"', '"43"', '"46"', '"47"', '"48"', '"49"'):
        assert code in COBOL_FILE_IO_JAVA, code
    for name in ("readNextSeq", "statusSeq", "writeSeq", "rewriteSeq", "deleteSeq", "startSeq"):
        assert f"static String {name}(" in COBOL_FILE_IO_JAVA, name
