"""Regression tests for REDEFINES / OCCURS / 88-level capability honesty (BL-003).

These constructs parse into IR (``DataItem.redefines`` / ``occurs`` / level 88)
but the deterministic mapper has no overlay, table-lowering or condition-name
lowering — the generated Java for the shipped fixtures does not compile.  They
must never be reported SUPPORTED.  They classify UNKNOWN (fail-closed) until a
full-ladder runtime proof exists.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.semantic_capability import CONSTRUCT_REGISTRY


def _classify(source: str, tmp_path) -> CapabilityLevel:
    d = tmp_path / "src"
    d.mkdir()
    (d / "MAIN.cob").write_text(source, encoding="utf-8")
    app = ApplicationDiscovery().discover(d)
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    programs = [c for c in report.components if c.component_type == "PROGRAM"]
    assert len(programs) == 1
    return programs[0].level


_88 = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. L88.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-STATUS PIC 9(2) VALUE 10.
   88 STAT-OK VALUE 00.
PROCEDURE DIVISION.
MAIN.
    DISPLAY "HELLO".
    STOP RUN.
"""

_OCCURS_DEPENDING = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. ODO.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-N PIC 9(2) VALUE 5.
01 WS-TABLE PIC 9(3) OCCURS 1 TO 10 TIMES DEPENDING ON WS-N.
PROCEDURE DIVISION.
MAIN.
    DISPLAY "HELLO".
    STOP RUN.
"""


class TestRegistry:
    def test_structural_keys_unknown(self) -> None:
        for key in ("REDEFINES", "OCCURS", "88-LEVEL"):
            assert CONSTRUCT_REGISTRY[key].level is CapabilityLevel.UNKNOWN, key

    def test_structural_keys_fail_closed(self) -> None:
        for key in ("REDEFINES", "OCCURS", "88-LEVEL"):
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.effective_source_level is not CapabilityLevel.SUPPORTED


class TestFixtureClassification:
    def _fixture_level(self, name: str) -> CapabilityLevel:
        fixture = (
            Path(__file__).resolve().parents[2] / "fixtures" / name / "cobol"
        )
        app = ApplicationDiscovery().discover(fixture)
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        return programs[0].level

    def test_redefines_not_supported(self) -> None:
        level = self._fixture_level("workload-redefines")
        assert level is not CapabilityLevel.SUPPORTED

    def test_occurs_not_supported(self) -> None:
        level = self._fixture_level("workload-occurs")
        assert level is CapabilityLevel.UNKNOWN

    def test_level88_not_supported(self) -> None:
        level = self._fixture_level("workload-level88")
        assert level is not CapabilityLevel.SUPPORTED


class TestMinimalPrograms:
    def test_88_level_is_unknown(self, tmp_path) -> None:
        assert _classify(_88, tmp_path) is CapabilityLevel.UNKNOWN

    def test_occurs_depending_on_blocked(self, tmp_path) -> None:
        level = _classify(_OCCURS_DEPENDING, tmp_path)
        assert level is not CapabilityLevel.SUPPORTED

    def test_plain_program_stays_supported(self, tmp_path) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. PLAIN.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(3) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DISPLAY "HI".
    STOP RUN.
"""
        assert _classify(src, tmp_path) is CapabilityLevel.SUPPORTED


class TestMatrixDocumentsStructuralKeys:
    def test_keys_documented(self) -> None:
        from tests.test_silent_loss_registry import _matrix_text

        text = _matrix_text()
        for key in ("REDEFINES", "OCCURS", "88-LEVEL"):
            assert key in text, f"Matrix missing {key}"
