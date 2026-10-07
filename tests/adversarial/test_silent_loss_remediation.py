"""Adversarial regression tests for silent semantic loss.

Each test proves that a COBOL feature the deterministic lane cannot map
becomes a visible, honest classification (UNSUPPORTED / diagnostic), and
that the parser no longer swallows following statements.  A later change
that reintroduces silent dropping will fail these tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser

MINIMUM_PROGRAM = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. ADVERSARIAL.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN-LOGIC.
{body}
    STOP RUN.
"""


def _capability_levels(cobol_body: str) -> tuple[CapabilityLevel, str]:
    """Classify a one-program application containing cobol_body."""
    source = MINIMUM_PROGRAM.format(body=cobol_body)
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "MAIN.cob").write_text(source, encoding="utf-8")
        app = ApplicationDiscovery().discover(Path(tmpdir))
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    assert len(programs) == 1
    return programs[0].level, programs[0].reason


class TestFileVerbClassification:
    """CLOSE/REWRITE/DELETE/START/INVALID KEY must never read as SUPPORTED."""

    @pytest.mark.parametrize(
        "verb_line",
        [
            "    CLOSE ACCT-FILE.",
            "    REWRITE ACCT-REC.",
            "    DELETE ACCT-FILE RECORD.",
            "    START ACCT-FILE KEY >= WS-A.",
            "    WRITE ACCT-REC INVALID KEY DISPLAY 'X'.",
        ],
    )
    def test_file_construct_is_not_supported(self, verb_line: str) -> None:
        level, reason = _capability_levels(verb_line)
        assert level is not CapabilityLevel.SUPPORTED, (
            f"{verb_line!r} must not be classified SUPPORTED; got {level} "
            f"({reason})"
        )
        assert level is not CapabilityLevel.PARTIAL, (
            f"{verb_line!r} must not be classified PARTIAL; got {level} "
            f"({reason})"
        )


class TestInvalidKeyNotSwallowed:
    """A clause body must not become top-level executable code."""

    def test_read_invalid_key_is_visible(self) -> None:
        level, reason = _capability_levels(
            "    READ ACCT-FILE INVALID KEY DISPLAY 'MISS'.\n"
        )
        assert level in (CapabilityLevel.UNSUPPORTED, CapabilityLevel.UNKNOWN)


class TestReadRunawayConsumption:
    """READ without AT END must not swallow the statements that follow it."""

    def test_read_does_not_swallow_following_statements(self) -> None:
        parser = CobolParser()
        program = parser.parse(
            MINIMUM_PROGRAM.format(
                body="    READ ACCT-FILE.\n    MOVE 1 TO WS-A.\n"
            )
        )
        from engine.transformation.ir import MoveStatement, ReadStatement

        statements = [
            stmt
            for paragraph in program.paragraphs
            for stmt in paragraph.statements
        ]
        types = [type(s).__name__ for s in statements]
        assert "ReadStatement" in types
        assert "MoveStatement" in types, (
            "Statements after a bare READ must still be parsed; got "
            f"{types}"
        )

    def test_unterminated_read_clause_is_a_diagnostic(self) -> None:
        parser = CobolParser()
        # No period terminates the sentence and no END-READ closes it; the
        # AT END clause must be surfaced as a diagnostic, not swallowed.
        parser.parse(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. X.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "01 WS-A PIC 9(3) VALUE 0.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-LOGIC.\n"
            "    READ ACCT-FILE\n"
            "      AT END\n"
            "        MOVE 1 TO WS-A\n"
        )
        diags = [d.message for d in parser.diagnostics.all]
        assert any("END-READ" in m for m in diags), (
            f"Unterminated AT END clause must be diagnosed, got {diags}"
        )


class TestEmptyIrFallbackDiagnostics:
    """Blank-IR fallbacks must emit a diagnostic, never pass silently."""

    @pytest.mark.parametrize(
        "body",
        [
            "    MOVE TO WS-A.",
            "    ADD WS-A.",
            "    SUBTRACT WS-A.",
            "    DIVIDE WS-A BY WS-B.",
            "    DIVIDE WS-A BY.",
            "    COMPUTE = WS-A.",
        ],
    )
    def test_empty_ir_statement_is_diagnosed(self, body: str) -> None:
        parser = CobolParser()
        parser.parse(MINIMUM_PROGRAM.format(body=body))
        messages = [d.message for d in parser.diagnostics.all]
        assert any("did not parse into IR" in m for m in messages), (
            f"Empty-IR fallback must be diagnosed, got {messages}"
        )


class TestDivideIntoSemantics:
    """DIVIDE a INTO b is implemented, not silently dropped."""

    def test_divide_into_produces_divide_statement(self) -> None:
        parser = CobolParser()
        program = parser.parse(
            MINIMUM_PROGRAM.format(body="    DIVIDE WS-A INTO WS-B.\n")
        )
        from engine.transformation.ir import DivideStatement

        statements = [
            stmt
            for paragraph in program.paragraphs
            for stmt in paragraph.statements
        ]
        divides = [s for s in statements if isinstance(s, DivideStatement)]
        assert len(divides) == 1
        # DIVIDE a INTO b == b / a
        assert divides[0].source == "WS-B"
        assert divides[0].divisor == "WS-A"
        assert divides[0].target == "WS-B"


class TestDiscoveryOfFixedFormatSource:
    """Fixed-format (sequenced) source must be discovered, not excluded."""

    def test_fixed_format_workload_is_discovered(self) -> None:
        fixture = (
            Path(__file__).resolve().parent.parent.parent
            / "fixtures"
            / "workload-db2"
            / "cobol"
        )
        app = ApplicationDiscovery().discover(fixture)
        ids = {p.program_id for p in app.programs}
        assert "ACCOUNT-DB2" in ids, (
            f"Fixed-format source must be discovered; got {ids}, "
            f"errors={app.discovery_errors}"
        )


class TestGoBackIsNotAParagraph:
    """GOBACK must not be misparsed as a paragraph heading."""

    def test_goback_does_not_split_paragraphs(self) -> None:
        parser = CobolParser()
        source = MINIMUM_PROGRAM.format(
            body="    DISPLAY 'HI'.\n    GOBACK.\n    MOVE 1 TO WS-A.\n"
        )
        program = parser.parse(source)
        names = [p.name for p in program.paragraphs]
        assert "GOBACK" not in names

    def test_goback_is_unsupported(self) -> None:
        level, _ = _capability_levels("    GOBACK.\n")
        assert level == CapabilityLevel.UNSUPPORTED


class TestTerminalExitProgram:
    """EXIT PROGRAM must be represented, never silently dropped."""

    def test_exit_program_produces_ir_node(self) -> None:
        from engine.transformation.ir import ExitProgramStatement

        parser = CobolParser()
        program = parser.parse(
            MINIMUM_PROGRAM.format(body="    DISPLAY 'HI'.\n    EXIT PROGRAM.\n")
        )
        statements = [
            stmt
            for paragraph in program.paragraphs
            for stmt in paragraph.statements
        ]
        assert any(isinstance(s, ExitProgramStatement) for s in statements)

    def test_bare_exit_is_not_a_paragraph(self) -> None:
        parser = CobolParser()
        program = parser.parse(
            MINIMUM_PROGRAM.format(body="    DISPLAY 'HI'.\n    EXIT.\n")
        )
        names = [p.name for p in program.paragraphs]
        assert "EXIT" not in names
