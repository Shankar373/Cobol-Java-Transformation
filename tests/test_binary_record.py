"""Hermetic tests for COMP / COMP-3 leaves in file records (roadmap unit 28); GnuCOBOL proof:
tests/integration/test_binary_record_oracle.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.binary_record import certified_binary_record, record_problem
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.packed_support_template import COBOL_PACKED_JAVA

SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT BF ASSIGN TO "BIN.DAT"
               ORGANIZATION IS {organization}
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD BF.
       01 BF-REC.
{leaves}       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT BF
           MOVE "AB" TO F1
           MOVE -123 TO F2
           WRITE BF-REC
           CLOSE BF
           STOP RUN.
"""

LEAVES = (
    "           05 F1 PIC X(2).\n"
    "           05 F2 PIC S9(5) COMP-3.\n"
    "           05 F3 PIC 9(4)V99 COMP.\n"
)


def _source(leaves: str = LEAVES, organization: str = "SEQUENTIAL") -> str:
    return SOURCE.format(leaves=leaves, organization=organization)


def _fd(leaves: str = LEAVES, organization: str = "SEQUENTIAL"):
    program = CobolParser().parse(_source(leaves, organization))
    return program.file_definitions[0]


def test_binary_widths_follow_the_digit_count():
    from engine.transformation.binary_record import leaf_encoding

    widths = {}
    for digits, usage in ((1, "COMP"), (2, "COMP"), (3, "COMP"), (4, "COMP"), (5, "COMP"), (9, "COMP"),
                          (10, "COMP"), (18, "COMP"), (1, "COMP-3"), (4, "COMP-3"), (5, "COMP-3"), (18, "COMP-3")):
        fd = _fd(f"           05 F1 PIC S9({digits}) {usage}.\n")
        widths[(digits, usage)] = leaf_encoding(fd.record_items[0]).width
    assert widths == {(1, "COMP"): 1, (2, "COMP"): 1, (3, "COMP"): 2, (4, "COMP"): 2, (5, "COMP"): 4, (9, "COMP"): 4,
                      (10, "COMP"): 8, (18, "COMP"): 8, (1, "COMP-3"): 1, (4, "COMP-3"): 3, (5, "COMP-3"): 3,
                      (18, "COMP-3"): 10}


def test_a_record_sequential_binary_record_is_certified_and_generates_without_a_layout_diagnostic():
    fd = _fd()
    assert certified_binary_record(fd) and record_problem(fd) == ""
    parser = CobolParser()
    program = parser.parse(_source())
    assert not [d for d in parser.diagnostics.all if "not a certified layout" in d.message]
    java = JavaGenerator().generate(program)[0].source_code
    assert 'CobolFileIo.setBinary("BIN.DAT")' in java
    assert "CobolPacked.packed(" in java and "CobolPacked.binary(" in java
    assert "final class CobolPacked" in java


@pytest.mark.parametrize("leaves, organization, why", [
    ("           05 F1 PIC X(2).\n           05 F2 PIC S9(5) COMP-3.\n", "LINE SEQUENTIAL", "LINE SEQUENTIAL"),
    ("           05 F1 PIC X(2).\n           05 F2 PIC S9(5) COMP-5.\n", "SEQUENTIAL", "COMP-5"),
    ("           05 F1 PIC X(2).\n           05 FILLER PIC X(2).\n           05 F2 PIC S9(5) COMP-3.\n",
     "SEQUENTIAL", "FILLER"),
    ("           05 F1 PIC X(2).\n           05 F2 PIC S9(5) COMP-3.\n           05 F3 REDEFINES F2 PIC X(3).\n",
     "SEQUENTIAL", "REDEFINES"),
    ("           05 F1 PIC X(2).\n           05 F2 PIC S9(5) COMP-3.\n           05 F4 PIC S9(3).\n",
     "SEQUENTIAL", "signed or scaled"),
    ("           05 F1 PIC X(2).\n           05 F2 PIC S9(19) COMP-3.\n", "SEQUENTIAL", "1 to 18 digits"),
])
def test_forms_outside_the_subset_are_refused_by_name(leaves, organization, why):
    fd = _fd(leaves, organization)
    assert not certified_binary_record(fd)
    assert why in record_problem(fd)


def _classify(tmp_path: Path, text: str):
    src = tmp_path / "src"
    src.mkdir()
    (src / "BIN.cob").write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(src, application_id="unit28")
    report = CapabilityAnalyzer(docker_available=True).analyze(app, source_root=src)
    return next(c for c in report.components if c.component_type == "PROGRAM" and c.component_id == "BIN")


def test_the_analyzer_certifies_a_binary_record_and_refuses_the_rest(tmp_path):
    assert _classify(tmp_path, _source()).level is CapabilityLevel.SUPPORTED
    (tmp_path / "x").mkdir()
    refused = _classify(tmp_path / "x", _source(
        "           05 F1 PIC X(2).\n           05 F2 PIC S9(5) COMP-5.\n"))
    assert refused.level is not CapabilityLevel.SUPPORTED


def test_the_runtime_template_defines_the_documented_encodings():
    for name in ("packed", "unpackDecimal", "unpackLong", "binary", "unbinary", "unbinaryDecimal"):
        assert f"static " in COBOL_PACKED_JAVA and f" {name}(" in COBOL_PACKED_JAVA, name
    assert "0xD" in COBOL_PACKED_JAVA and "0xC" in COBOL_PACKED_JAVA and "0xF" in COBOL_PACKED_JAVA
