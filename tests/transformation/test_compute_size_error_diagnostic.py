"""COMPUTE ``ON SIZE ERROR`` visibility (Workstream A).

``COMPUTE WS-C = WS-A + WS-B ON SIZE ERROR DISPLAY "E".`` used to match the
COMPUTE regex with the clause *inside* the expression group, so
``ComputeStatement.expression`` contained ``ON SIZE ERROR DISPLAY "E"`` and no
diagnostic named the loss.  The statement is still classified SUPPORTED by the
mapper (it is a ComputeStatement), so the verdict could claim support for
overflow semantics it never implemented.

Contract pinned here:

* the clause is removed from the expression and named by an
  ``UNSUPPORTED_CONSTRUCT`` diagnostic;
* the certified COMPUTE form stays diagnostic-free;
* the real discovery + analyzer path never reports SUPPORTED for a program
  that uses the clause.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import ComputeStatement
from engine.transformation.semantic_capability import CapabilityLevel

HEADER = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(4).
01 WS-B PIC 9(4).
01 WS-C PIC 9(4).
PROCEDURE DIVISION.
MAIN.
"""


def _parse(proc: str) -> tuple[CobolParser, list]:
    parser = CobolParser()
    program = parser.parse(HEADER + proc + "    STOP RUN.\n")
    statements = [s for para in program.paragraphs for s in para.statements]
    return parser, statements


def _size_error_messages(parser: CobolParser) -> list[str]:
    return [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
        and "SIZE ERROR" in d.message.upper()
    ]


class TestSizeErrorIsNamed:
    def test_upper_case_form_is_diagnosed_and_removed(self) -> None:
        parser, statements = _parse(
            '    COMPUTE WS-C = WS-A + WS-B ON SIZE ERROR DISPLAY "E".\n'
        )
        computes = [s for s in statements if isinstance(s, ComputeStatement)]
        assert len(computes) == 1
        assert "SIZE ERROR" not in computes[0].expression.upper()
        assert _size_error_messages(parser)

    def test_lower_case_form_is_diagnosed(self) -> None:
        parser, _ = _parse(
            '    compute ws-c = ws-a + ws-b on size error display "e".\n'
        )
        assert _size_error_messages(parser)

    def test_certified_compute_stays_quiet(self) -> None:
        parser, statements = _parse("    COMPUTE WS-C = WS-A + WS-B.\n")
        computes = [s for s in statements if isinstance(s, ComputeStatement)]
        assert len(computes) == 1
        assert computes[0].expression == "WS-A + WS-B"
        assert not _size_error_messages(parser)


class TestVerdictNeverSupportsSizeError:
    def test_program_is_not_supported(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "cobol"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "tst.cbl").write_text(
            HEADER
            + '    COMPUTE WS-C = WS-A + WS-B ON SIZE ERROR DISPLAY "E".\n'
            + "    STOP RUN.\n",
            encoding="utf-8",
        )
        app = ApplicationDiscovery().discover(src_dir, application_id="APP")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        assert programs[0].level is not CapabilityLevel.SUPPORTED

    def test_plain_compute_stays_supported(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "cobol"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "tst.cbl").write_text(
            HEADER + "    COMPUTE WS-C = WS-A + WS-B.\n    STOP RUN.\n",
            encoding="utf-8",
        )
        app = ApplicationDiscovery().discover(src_dir, application_id="APP")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        assert programs[0].level is CapabilityLevel.SUPPORTED
