"""MULTIPLY statement forms — no diagnostic-free empty IR (BL-069).

Before BL-069 ``_parse_multiply`` matched only the strict
``MULTIPLY x BY y [GIVING z] [ROUNDED]`` spelling; every other standard
form — the multi-recipient ``MULTIPLY a BY b, c``, the ``GIVING`` list
``MULTIPLY a BY b GIVING c, d``, and any form carrying the standard
``ON SIZE ERROR`` clause — fell into the no-match branch and returned an
**empty** ``MultiplyStatement(source="", multiplicand="")`` with **zero
diagnostics**.  ADD/SUBTRACT/DIVIDE in the same position route through
``_emit_unparsed`` and raise ``UNSUPPORTED_CONSTRUCT``, so MULTIPLY was
the arithmetic verb whose standard forms vanished silently — the §53.9/§60
defect class (the capability channel cannot see an empty node's loss).

The contract locked here, mirroring the ADD/SUBTRACT/DIVIDE rule:

* the certified simple form ``MULTIPLY a BY b [GIVING z] [ROUNDED]``
  parses with **no** diagnostic (regression);
* every other MULTIPLY spelling raises ``UNSUPPORTED_CONSTRUCT`` naming
  the statement — never a diagnostic-free empty node;
* the verdict path (real discovery + analyzer) never reports SUPPORTED
  for a program whose MULTIPLY failed to parse.

Dependency-free on purpose: this file is part of the capability-truth gate
(``.github/workflows/ci.yml``) and must run with pytest alone.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import MultiplyStatement
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


def _diag_codes(parser: CobolParser) -> list[str]:
    return [d.code.name for d in parser.diagnostics.all]


class TestSimpleMultiplyStaysCertified:
    """Regression: the certified form must keep parsing, diagnostic-free."""

    def test_simple_by_parses_without_diagnostic(self):
        parser, statements = _parse("    MULTIPLY WS-A BY WS-B.\n")
        multiplies = [s for s in statements if isinstance(s, MultiplyStatement)]
        assert len(multiplies) == 1
        assert multiplies[0].source == "WS-A"
        assert multiplies[0].multiplicand == "WS-B"
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)

    def test_giving_rounded_parses_without_diagnostic(self):
        parser, statements = _parse(
            "    MULTIPLY WS-A BY WS-B GIVING WS-C ROUNDED.\n"
        )
        multiplies = [s for s in statements if isinstance(s, MultiplyStatement)]
        assert len(multiplies) == 1
        assert multiplies[0].target == "WS-C"
        assert multiplies[0].rounded is True
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)

    def test_lowercase_simple_form_parses_without_diagnostic(self):
        parser, statements = _parse("    multiply ws-a by ws-b.\n")
        multiplies = [s for s in statements if isinstance(s, MultiplyStatement)]
        assert len(multiplies) == 1
        assert "UNSUPPORTED_CONSTRUCT" not in _diag_codes(parser)


class TestStandardFormsFailClosedWithDiagnostic:
    """The BL-069 defect: these returned an empty node with zero diagnostics."""

    def test_multi_recipient_by_list_is_diagnosed(self):
        parser, statements = _parse("    MULTIPLY WS-A BY WS-B, WS-C.\n")
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)
        # Following statements are never swallowed.
        assert any(type(s).__name__ == "StopRunStatement" for s in statements)

    def test_multi_result_giving_list_is_diagnosed(self):
        parser, _ = _parse("    MULTIPLY WS-A BY WS-B GIVING WS-C, WS-A.\n")
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)

    def test_on_size_error_form_is_diagnosed(self):
        parser, _ = _parse(
            '    MULTIPLY WS-A BY WS-B ON SIZE ERROR DISPLAY "E".\n'
        )
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)
        messages = [d.message for d in parser.diagnostics.all]
        assert any("MULTIPLY" in m for m in messages)

    def test_lowercase_on_size_error_form_is_diagnosed(self):
        parser, _ = _parse(
            '    multiply ws-a by ws-b on size error display "E".\n'
        )
        assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser)

    def test_no_diagnostic_free_empty_multiply_node(self):
        """Property: an empty MULTIPLY node can never exist without a
        diagnostic naming the statement (the ADD/SUBTRACT/DIVIDE channel
        returns an empty node *after* emitting — the diagnostic is the
        contract, not the node's absence)."""
        for proc in (
            "    MULTIPLY WS-A BY WS-B, WS-C.\n",
            "    MULTIPLY WS-A BY WS-B GIVING WS-C, WS-A.\n",
            '    MULTIPLY WS-A BY WS-B ON SIZE ERROR DISPLAY "E".\n',
        ):
            parser, statements = _parse(proc)
            for s in statements:
                if isinstance(s, MultiplyStatement) and not s.source:
                    messages = [d.message for d in parser.diagnostics.all]
                    assert any(
                        "MULTIPLY" in m and "did not parse" in m
                        for m in messages
                    ), f"undisgnosed empty MultiplyStatement for {proc!r}"
                    break
            assert "UNSUPPORTED_CONSTRUCT" in _diag_codes(parser), proc


class TestVerdictNeverSupportsUnparsedMultiply:
    """The real discovery + analyzer path must not report SUPPORTED."""

    def test_on_size_error_program_is_not_supported(self, tmp_path: Path):
        src_dir = tmp_path / "cobol"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "tst.cbl").write_text(
            HEADER
            + '    MULTIPLY WS-A BY WS-B ON SIZE ERROR DISPLAY "E".\n'
            "    STOP RUN.\n",
            encoding="utf-8",
        )
        app = ApplicationDiscovery().discover(src_dir, application_id="APP")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        assert programs[0].level is not CapabilityLevel.SUPPORTED

    def test_simple_multiply_program_stays_supported(self, tmp_path: Path):
        src_dir = tmp_path / "cobol"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "tst.cbl").write_text(
            HEADER + "    MULTIPLY WS-A BY WS-B.\n    STOP RUN.\n",
            encoding="utf-8",
        )
        app = ApplicationDiscovery().discover(src_dir, application_id="APP")
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        assert programs[0].level is CapabilityLevel.SUPPORTED
