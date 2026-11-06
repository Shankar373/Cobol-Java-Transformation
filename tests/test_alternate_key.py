"""Hermetic tests for ALTERNATE RECORD KEY on INDEXED files (roadmap unit 30); GnuCOBOL proof:
tests/integration/test_alternate_key_oracle.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.alternate_key import alternate_key_problem, alternate_ordinal
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from engine.transformation.java_generator import JavaGenerator

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "ALT.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS {access}
               RECORD KEY IS KF-KEY
               ALTERNATE RECORD KEY IS KF-ALT WITH DUPLICATES
               ALTERNATE RECORD KEY IS KF-UNQ
{status}               .
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KF-KEY PIC X(2).
{fields}       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN I-O KF
           MOVE "BB" TO KF-ALT
           READ KF KEY IS KF-ALT
{extra}           CLOSE KF
           STOP RUN.
"""

FIELDS = "           05 KF-ALT PIC X(2).\n           05 KF-UNQ PIC X(2).\n"


def _source(access="DYNAMIC", status="               FILE STATUS IS FS\n", fields=FIELDS, extra=""):
    return SOURCE.format(access=access, status=status, fields=fields, extra=extra)


def _program(**kwargs):
    parser = CobolParser()
    program = parser.parse(_source(**kwargs))
    return program, [d.message for d in parser.diagnostics.all if d.code.name == "UNSUPPORTED_CONSTRUCT"]


def test_a_dynamic_file_with_duplicate_and_unique_alternate_keys_is_certified():
    program, diagnostics = _program()
    fd = program.file_definitions[0]
    assert diagnostics == [] and alternate_key_problem(program, fd) == ""
    assert [alternate_ordinal(fd, name) for name in ("KF-ALT", "KF-UNQ", "KF-KEY", "OTHER")] == [1, 2, 0, 0]
    assert [key.is_duplicated for key in fd.alternate_keys] == [True, False]


def test_the_lowering_registers_the_keys_and_reads_through_the_alternate_index():
    java = JavaGenerator().generate(_program()[0])[0].source_code
    assert 'CobolFileIo.altKey("ALT.DAT", 1, 2, 2, true)' in java
    assert 'CobolFileIo.altKey("ALT.DAT", 2, 4, 2, false)' in java
    assert 'CobolFileIo.readAlt("ALT.DAT", 1, KF_ALT)' in java


@pytest.mark.parametrize("kwargs, why", [
    ({"access": "SEQUENTIAL"}, "only with ACCESS MODE DYNAMIC or RANDOM"),
    ({"status": ""}, "no FILE STATUS clause"),
    ({"fields": "           05 KF-ALT PIC X(2).\n"}, "KF-UNQ is not a single elementary field"),
    ({"fields": "           05 KF-ALT PIC 9(2).\n           05 KF-UNQ PIC X(2).\n"}, "is numeric"),
    ({"extra": "           START KF KEY >= KF-ALT\n"}, "START on a file with alternate keys is not certified"),
    ({"extra": "           READ KF KEY IS KF-DATA\n"}, "is not a record key"),
])
def test_forms_outside_the_subset_are_refused_by_name(kwargs, why):
    program, diagnostics = _program(**kwargs)
    problem = alternate_key_problem(program, program.file_definitions[0])
    assert why in problem, problem
    assert any("ALTERNATE RECORD KEY on file KF is recognised but not lowered" in d for d in diagnostics)


def _classify(tmp_path: Path, text: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ALT.cob").write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit30")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == "ALT")


def test_the_analyzer_certifies_the_subset_and_refuses_the_rest(tmp_path):
    assert _classify(tmp_path, _source()).level is CapabilityLevel.SUPPORTED
    (tmp_path / "seq").mkdir()
    refused = _classify(tmp_path / "seq", _source(access="SEQUENTIAL"))
    assert refused.level is CapabilityLevel.UNSUPPORTED
    assert "ALTERNATE RECORD KEY" in refused.reason


def test_the_runtime_template_defines_the_alternate_key_contract():
    for name in ("altKey", "readAlt", "startAlt"):
        assert f"static " in COBOL_FILE_IO_JAVA and f" {name}(" in COBOL_FILE_IO_JAVA, name
    # 02 for a duplicate of a WITH DUPLICATES key, 22 for a unique one, write order ranks duplicates
    assert 'status = "02";' in COBOL_FILE_IO_JAVA and 'return "22";' in COBOL_FILE_IO_JAVA
    assert "no position" in COBOL_FILE_IO_JAVA and "NOPOS" in COBOL_FILE_IO_JAVA
