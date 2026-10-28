"""Arithmetic statement continuation across physical lines.

COBOL is free-format: a statement routinely wraps onto the next line.  The
logical-line joiner in ``CobolParser.parse`` only folded the
``MOVE``/``ADD ... TO`` and ``IF ... <operator>`` forms, so a wrapped
``COMPUTE``/``SUBTRACT``/``MULTIPLY``/``DIVIDE`` reached the statement parsers
as separate fragments:

* the verb line produced an **empty** IR node
  (``Statement did not parse into IR: COMPUTE (COMPUTE WS-A =)``);
* each following line was reported as its own
  ``Skipped unsupported statement`` — including fragments as short as
  ``- WS-DEDUCTIONS.``.

Capability analysis aggregates those diagnostics into ``UNSUPPORTED`` and the
plan skips the program, so a purely cosmetic line wrap failed the run with a
message indistinguishable from a genuinely unsupported construct.  Observed on
the ``PAYMAIN`` workload (``PAYMAIN.zip``), whose three-line ``COMPUTE`` was
rejected while its single-line siblings transformed.

Contract pinned here:

* a wrapped arithmetic/MOVE statement parses into the same IR as its
  single-line spelling, with zero diagnostics;
* the wrapped program is reported ``SUPPORTED`` by capability analysis, so the
  transformation plan transforms it;
* an EVALUATE ``WHEN`` branch (whose statements are written without a
  terminating period) is **never** absorbed into the preceding statement —
  without that guard the ``WHEN`` clause vanished and the 88-level condition
  name was emitted as a bare Java identifier.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.ir import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MoveStatement,
    MultiplyStatement,
    SubtractStatement,
)
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import CapabilityLevel

HEADER = """IDENTIFICATION DIVISION.
PROGRAM-ID. TST.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(7)V99.
01 WS-B PIC 9(7)V99.
01 WS-C PIC 9(7)V99.
PROCEDURE DIVISION.
MAIN.
"""


def _parse(proc: str) -> tuple[CobolParser, list]:
    parser = CobolParser()
    program = parser.parse(HEADER + proc + "    STOP RUN.\n")
    statements = [s for para in program.paragraphs for s in para.statements]
    return parser, statements


def _unsupported(parser: CobolParser) -> list[str]:
    return [
        d.message
        for d in parser.diagnostics.all
        if d.code is DiagnosticCode.UNSUPPORTED_CONSTRUCT
    ]


class TestWrappedArithmeticParses:
    """A line wrap must be invisible to the IR."""

    def test_compute_wrapped_after_equals(self) -> None:
        parser, statements = _parse(
            "    COMPUTE WS-C =\n"
            "        WS-A + WS-B\n"
            "        - WS-A.\n"
        )
        computes = [s for s in statements if isinstance(s, ComputeStatement)]
        assert len(computes) == 1
        assert computes[0].target == "WS-C"
        assert computes[0].expression == "WS-A + WS-B - WS-A"
        assert not _unsupported(parser)

    def test_compute_wrapped_mid_expression(self) -> None:
        parser, statements = _parse(
            "    COMPUTE WS-C = WS-A\n"
            "        + WS-B.\n"
        )
        computes = [s for s in statements if isinstance(s, ComputeStatement)]
        assert len(computes) == 1
        assert computes[0].target == "WS-C"
        assert computes[0].expression == "WS-A + WS-B"
        assert not _unsupported(parser)

    def test_subtract_wrapped_before_from(self) -> None:
        parser, statements = _parse(
            "    SUBTRACT WS-A\n        FROM WS-B.\n"
        )
        found = [s for s in statements if isinstance(s, SubtractStatement)]
        assert len(found) == 1
        assert found[0].source == "WS-A"
        assert found[0].from_field == "WS-B"
        assert not _unsupported(parser)

    def test_multiply_wrapped_before_by(self) -> None:
        parser, statements = _parse(
            "    MULTIPLY WS-A\n        BY WS-B.\n"
        )
        found = [s for s in statements if isinstance(s, MultiplyStatement)]
        assert len(found) == 1
        assert found[0].source == "WS-A"
        assert found[0].multiplicand == "WS-B"
        assert not _unsupported(parser)

    def test_divide_wrapped_before_into(self) -> None:
        parser, statements = _parse(
            "    DIVIDE WS-A\n        INTO WS-B.\n"
        )
        found = [s for s in statements if isinstance(s, DivideStatement)]
        assert len(found) == 1
        assert found[0].source == "WS-B"
        assert found[0].divisor == "WS-A"
        assert not _unsupported(parser)

    def test_add_with_giving_on_third_line(self) -> None:
        parser, statements = _parse(
            "    ADD WS-A\n        TO WS-B\n        GIVING WS-C.\n"
        )
        found = [s for s in statements if isinstance(s, AddStatement)]
        assert len(found) == 1
        assert found[0].giving_target == "WS-C"
        assert not _unsupported(parser)

    def test_move_wrapped_after_to(self) -> None:
        parser, statements = _parse(
            "    MOVE WS-A\n        TO WS-B.\n"
        )
        found = [s for s in statements if isinstance(s, MoveStatement)]
        assert len(found) == 1
        assert found[0].target == "WS-B"
        assert not _unsupported(parser)

    def test_single_line_form_is_unchanged(self) -> None:
        parser, statements = _parse("    COMPUTE WS-C = WS-A + WS-B.\n")
        computes = [s for s in statements if isinstance(s, ComputeStatement)]
        assert len(computes) == 1
        assert computes[0].expression == "WS-A + WS-B"
        assert not _unsupported(parser)


class TestContinuationNeverSwallowsTheNextStatement:
    """The join guards are part of the contract, not an implementation detail."""

    def test_evaluate_when_branch_is_not_absorbed(self) -> None:
        source = """IDENTIFICATION DIVISION.
PROGRAM-ID. LEVEL88-DEMO.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-STATUS         PIC 9(2) VALUE 10.
    88  STAT-OK            VALUE 00.
    88  STAT-WARNING       VALUE 01 THRU 09.
01  WS-RESULT         PIC X(20) VALUE SPACES.
PROCEDURE DIVISION.
MAIN-LOGIC.
    EVALUATE TRUE
        WHEN STAT-OK
            MOVE "STATUS OK" TO WS-RESULT
        WHEN STAT-WARNING
            MOVE "STATUS WARNING" TO WS-RESULT
    END-EVALUATE.
    STOP RUN.
"""
        parser = CobolParser()
        program = parser.parse(source)
        # EVALUATE is lowered to IF/ELSE, so the branch statements are nested —
        # assert on what the mapper actually emits, which is the contract.
        assert not _unsupported(parser)

        generated = JavaGenerator().generate(program)[0].source_code
        # Both branch bodies survive (neither MOVE was absorbed into a WHEN).
        assert '"STATUS OK"' in generated, generated
        assert '"STATUS WARNING"' in generated, generated
        # The 88-level condition name is still lowered, never a bare identifier.
        assert "STAT_WARNING" not in generated, generated

    def test_following_statement_is_not_swallowed(self) -> None:
        parser, statements = _parse(
            "    COMPUTE WS-C = WS-A + WS-B\n"
            "    DISPLAY \"AFTER\"\n"
        )
        # DISPLAY begins a new statement, so the unterminated COMPUTE stops
        # before it instead of absorbing the DISPLAY.
        displays = [s for s in statements if type(s).__name__ == "DisplayStatement"]
        assert len(displays) == 1

    def test_paragraph_heading_is_not_swallowed(self) -> None:
        parser = CobolParser()
        program = parser.parse(
            HEADER
            + "    COMPUTE WS-C = WS-A + WS-B\n"
            + "SECOND-PARA.\n"
            + "    STOP RUN.\n"
        )
        names = [p.name for p in program.paragraphs]
        assert "SECOND-PARA" in names, names


class TestWrappedProgramIsTransformable:
    """The real-world impact: a line wrap must not fail the run."""

    def test_capability_stays_supported(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "cobol"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "tst.cbl").write_text(
            HEADER
            + "    COMPUTE WS-C =\n"
            + "        WS-A + WS-B\n"
            + "        - WS-A.\n"
            + "    DISPLAY WS-C.\n"
            + "    STOP RUN.\n",
            encoding="utf-8",
        )
        app = ApplicationDiscovery().discover(src_dir, application_id="APP")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [
            c for c in report.components if c.component_type == "PROGRAM"
        ]
        assert len(programs) == 1
        assert programs[0].level is CapabilityLevel.SUPPORTED, programs[0].reason
