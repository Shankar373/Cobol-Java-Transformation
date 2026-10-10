"""Regression tests for ROUNDED capability honesty (BL-005).

BL-005 claimed "ROUNDED is parsed into IR but no mapping evidence found".  That
premise is falsified: the flag already reaches the generated Java as a
``RoundingMode.HALF_UP`` selection on the receiving item (default stays ``DOWN``
truncation), with passing coverage in ``test_decimal_arithmetic_semantics.py``.
These tests register the honest verdict (SUPPORTED) and lock in that the flag
reaches Java, so it can never silently drift back to "unclassified".
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    scan_constructs,
)

_ROUNDED = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-ROUND.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC S9(3)V9 VALUE 2.5.
01 WS-RESULT PIC S9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT ROUNDED = WS-A.
    STOP RUN.
"""

_PLAIN = """\
>>SOURCE FORMAT FREE
IDENTIFICATION DIVISION.
PROGRAM-ID. NUMERIC-PLAIN.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC S9(3)V9 VALUE 2.5.
01 WS-RESULT PIC S9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    COMPUTE WS-RESULT = WS-A.
    STOP RUN.
"""


def _classify(source: str, tmp_path) -> CapabilityLevel:
    d = tmp_path / "src"
    d.mkdir()
    (d / "MAIN.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(d)
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    assert len(programs) == 1
    return programs[0].level


class TestRegistry:
    def test_rounded_is_supported(self) -> None:
        assert CONSTRUCT_REGISTRY["ROUNDED"].level is CapabilityLevel.SUPPORTED

    def test_rounded_source_pattern_detected(self) -> None:
        assert "ROUNDED" in scan_constructs(_ROUNDED)


class TestCapability:
    def test_rounded_program_is_supported(self, tmp_path) -> None:
        assert _classify(_ROUNDED, tmp_path) is CapabilityLevel.SUPPORTED

    def test_plain_program_is_supported(self, tmp_path) -> None:
        assert _classify(_PLAIN, tmp_path) is CapabilityLevel.SUPPORTED


class TestMappingEvidence:
    def _assignment(self, cobol: str, target: str) -> str:
        java = map_cobol_program_to_java(CobolParser().parse(cobol))
        statement = next(
            s for s in java.java_class.methods[0].body_statements
            if getattr(s, "target", None) == target
        )
        return JavaGenerator()._stmt_to_string(statement)

    def test_flag_reaches_java_as_half_up(self) -> None:
        source = self._assignment(_ROUNDED, "WS_RESULT")
        assert "java.math.RoundingMode.HALF_UP" in source

    def test_default_is_truncation(self) -> None:
        source = self._assignment(_PLAIN, "WS_RESULT")
        assert "java.math.RoundingMode.HALF_UP" not in source


class TestMatrixDocumentsRounded:
    def test_documented(self) -> None:
        from tests.test_silent_loss_registry import _matrix_text

        assert "ROUNDED" in _matrix_text()
