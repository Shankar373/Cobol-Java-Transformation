"""Hermetic tests for an INDEXED RECORD KEY that is not the first field (roadmap unit 29); GnuCOBOL proof:
tests/integration/test_keyed_offset_oracle.py."""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from engine.transformation.java_generator import JavaGenerator

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. KPOS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "KPOS.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS KF-KEY
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-DATA PIC X(4).
           05 KF-KEY PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       01 WS-COPY PIC X(8).
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           MOVE "AAAA" TO KF-DATA
           MOVE "K002" TO KF-KEY
           WRITE KF-REC
           CLOSE KF
           OPEN INPUT KF
           MOVE "K002" TO KF-KEY
           READ KF{into}
           CLOSE KF
           STOP RUN.
"""


def _java(into: str = "") -> str:
    return JavaGenerator().generate(CobolParser().parse(SOURCE.format(into=into)))[0].source_code


def _classify(tmp_path: Path, text: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "KPOS.cob").write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit29")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == "KPOS")


def test_the_record_image_is_assembled_key_first_and_split_in_declared_order():
    java = _java()
    # WRITE: the key field leads the image; READ: the image is split key first (offset 0), then the data field
    assert ('CobolFileIo.write("KPOS.DAT", CobolFileIo.pad(KF_KEY, 4, false) + CobolFileIo.pad(KF_DATA, 4, false), 4)'
            in java)
    assert "KF_KEY = CobolFileIo.pad(_read_0, 8, false).substring(0, 4);" in java
    assert "KF_DATA = CobolFileIo.pad(_read_0, 8, false).substring(4, 8);" in java


def test_a_key_that_is_not_the_first_field_is_supported_and_read_into_is_refused(tmp_path):
    assert _classify(tmp_path, SOURCE.format(into="")).level is CapabilityLevel.SUPPORTED
    (tmp_path / "into").mkdir()
    refused = _classify(tmp_path / "into", SOURCE.format(into=" INTO WS-COPY"))
    assert refused.level is CapabilityLevel.UNSUPPORTED
    assert "READ ... INTO with a RECORD KEY that is not the first field" in refused.reason


def test_a_failed_start_and_end_of_file_leave_no_position_but_a_failed_keyed_read_keeps_it():
    # runtime contract pinned by the GnuCOBOL differential: only START (and the end of the file) clear the position
    assert COBOL_FILE_IO_JAVA.count("NOPOS.add(path);") >= 4  # every failed START
    assert "a failed keyed READ names its key as the key of reference" in COBOL_FILE_IO_JAVA
    assert "clearEof(path);\n        NOPOS.remove(path);\n        REF.remove(path);" in COBOL_FILE_IO_JAVA


def test_dynamic_read_next_takes_its_failure_status_from_the_runtime():
    java = JavaGenerator().generate(CobolParser().parse(
        SOURCE.format(into="").replace("           CLOSE KF\n           STOP RUN.",
                                       "           READ KF NEXT\n           CLOSE KF\n           STOP RUN.")))[0].source_code
    assert "CobolFileIo.readNextSeq(" in java and "CobolFileIo.statusSeq(" in java
