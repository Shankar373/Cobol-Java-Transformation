"""Regression tests for BY CONTENT / BY VALUE capability honesty (BL-004).

The mapper implements sync-in for every passing mode and sync-out for BY
REFERENCE only (correct COBOL value semantics: BY CONTENT / BY VALUE lose the
callee's writes).  Before this work there was no registry key, so these modes
were capability-invisible.  They now classify PARTIAL (implemented, runtime
proof pending) and are never reported SUPPORTED.
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


_BY_CONTENT = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. BC.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(4) VALUE 100.
PROCEDURE DIVISION.
MAIN.
    CALL "SUB" USING BY CONTENT WS-A.
    STOP RUN.
"""

_BY_VALUE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. BV.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(4) VALUE 100.
PROCEDURE DIVISION.
MAIN.
    CALL "SUB" USING BY VALUE WS-A.
    STOP RUN.
"""

_BY_REFERENCE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. BR.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9(4) VALUE 100.
PROCEDURE DIVISION.
MAIN.
    CALL "SUB" USING BY REFERENCE WS-A.
    STOP RUN.
"""


class TestRegistry:
    def test_passing_mode_keys_partial(self) -> None:
        for key in ("BY CONTENT", "BY VALUE"):
            assert CONSTRUCT_REGISTRY[key].level is CapabilityLevel.PARTIAL, key

    def test_passing_mode_keys_fail_closed(self) -> None:
        for key in ("BY CONTENT", "BY VALUE"):
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.effective_source_level is not CapabilityLevel.SUPPORTED


class TestFixtureClassification:
    def _fixture_level(self, name: str, program_id: str) -> CapabilityLevel:
        fixture = (
            Path(__file__).resolve().parents[2] / "fixtures" / name / "cobol"
        )
        app = ApplicationDiscovery().discover(fixture)
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        programs = [
            c for c in report.components
            if c.component_type == "PROGRAM" and c.component_id == program_id
        ]
        assert len(programs) == 1
        return programs[0].level

    def test_by_content_main_is_partial(self) -> None:
        assert self._fixture_level("workload-by-content", "MAIN") is CapabilityLevel.PARTIAL

    def test_by_value_main_is_partial(self) -> None:
        assert self._fixture_level("workload-by-value", "MAIN") is CapabilityLevel.PARTIAL


class TestMinimalPrograms:
    def test_by_content_is_partial(self, tmp_path) -> None:
        assert _classify(_BY_CONTENT, tmp_path) is CapabilityLevel.PARTIAL

    def test_by_value_is_partial(self, tmp_path) -> None:
        assert _classify(_BY_VALUE, tmp_path) is CapabilityLevel.PARTIAL

    def test_by_reference_not_partial(self, tmp_path) -> None:
        # BY REFERENCE writes flow back and stay covered by the CALL SUPPORTED
        # verdict, so no PARTIAL passing-mode finding is emitted.
        assert _classify(_BY_REFERENCE, tmp_path) is not CapabilityLevel.PARTIAL


class TestMatrixDocumentsPassingModes:
    def test_keys_documented(self) -> None:
        from tests.test_silent_loss_registry import _matrix_text

        text = _matrix_text()
        for key in ("BY CONTENT", "BY VALUE"):
            assert key in text, f"Matrix missing {key}"
