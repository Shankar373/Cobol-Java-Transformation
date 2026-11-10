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
    ({"extra": "           START KF KEY < KF-ALT\n"}, "START ... KEY < KF-ALT is not certified"),
    ({"extra": "           START KF KEY <= KF-KEY\n"}, "START ... KEY <= KF-KEY is not certified"),
    ({"extra": "           START KF KEY >= KF-DATA\n"}, "is not a record key"),
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


BROWSING = "           START KF KEY >= KF-ALT\n           READ KF NEXT\n           READ KF NEXT\n"


@pytest.mark.parametrize("extra", [
    BROWSING,
    "           START KF KEY = KF-UNQ\n           START KF KEY > KF-KEY\n           READ KF NEXT\n",
    "           START KF KEY < KF-KEY\n           READ KF NEXT\n",
])
def test_browsing_in_the_proven_shape_is_certified(extra):
    program, diagnostics = _program(extra=extra)
    assert diagnostics == [] and alternate_key_problem(program, program.file_definitions[0]) == ""


@pytest.mark.parametrize("kwargs, why", [
    ({"access": "RANDOM", "extra": BROWSING}, "only with ACCESS MODE DYNAMIC"),
    ({"fields": "           05 KF-ALT PIC X(3).\n           05 KF-UNQ PIC X(2).\n", "extra": BROWSING},
     "three or four PIC X(2) fields"),
    ({"fields": "           05 KF-ALT PIC X(2).\n           05 KF-UNQ PIC X(2).\n           05 F1 PIC X(2).\n"
                "           05 F2 PIC X(2).\n", "extra": BROWSING}, "three or four PIC X(2) fields"),
    ({"extra": "           CLOSE KF\n           OPEN INPUT KF\n" + BROWSING}, "opened OUTPUT or I-O, not INPUT"),
    ({"extra": "           READ KF NEXT AT END DISPLAY \"END\"\n           END-READ\n"}, "AT END / INVALID KEY phrases"),
    ({"extra": "           READ KF NEXT INTO KF-REC\n"}, "without READ ... INTO"),
])
def test_browsing_outside_the_proven_shape_is_refused_by_name(kwargs, why):
    program, _ = _program(**kwargs)
    problem = alternate_key_problem(program, program.file_definitions[0])
    assert why in problem, problem


def test_browsing_needs_exactly_two_alternate_keys_one_duplicate_and_one_unique():
    one = _source(extra=BROWSING).replace("               ALTERNATE RECORD KEY IS KF-UNQ\n", "")
    program = CobolParser().parse(one)
    assert "exactly two alternate keys" in alternate_key_problem(program, program.file_definitions[0])
    two_duplicates = _source(extra=BROWSING).replace("KF-UNQ\n", "KF-UNQ WITH DUPLICATES\n", 1)
    program = CobolParser().parse(two_duplicates)
    assert "one WITH DUPLICATES and one unique" in alternate_key_problem(program, program.file_definitions[0])
