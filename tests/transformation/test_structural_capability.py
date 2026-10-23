"""Regression tests for REDEFINES / OCCURS / 88-level capability honesty (BL-003).

OCCURS and 88-level now have deterministic lowering with GnuCOBOL 3.1.2
oracle proof (``tests/integration/test_structural_oracle_proof.py``):

* fixed-size ``OCCURS n TIMES`` is PARTIAL — arrays and 1-based→0-based
  subscripts are proven, while ``OCCURS DEPENDING ON`` fails closed with
  ``UNSUPPORTED_CONSTRUCT`` and whole-record references to an occurring group
  are outside the certified subset;
* 88-level condition names are SUPPORTED for single values, THRU ranges and
  content equality; a VALUE term with no certified lowering is reported
  UNSUPPORTED by the analyzer;
* REDEFINES is PARTIAL: elementary alphanumeric overlays are proven, while
  numeric views, groups and every other writer fail closed (numeric
  reinterpretation of overwritten bytes is GnuCOBOL-specific undefined data).
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
    def test_structural_keys_reflect_proof(self) -> None:
        assert CONSTRUCT_REGISTRY["REDEFINES"].level is CapabilityLevel.PARTIAL
        assert CONSTRUCT_REGISTRY["OCCURS"].level is CapabilityLevel.PARTIAL
        assert CONSTRUCT_REGISTRY["88-LEVEL"].level is CapabilityLevel.SUPPORTED

    def test_structural_keys_fail_closed(self) -> None:
        for key in ("REDEFINES", "OCCURS", "88-LEVEL"):
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.effective_source_level is not CapabilityLevel.SUPPORTED


class TestFixtureClassification:
    def _fixture_level(self, name: str, *, docker: bool = False) -> CapabilityLevel:
        fixture = (
            Path(__file__).resolve().parents[2] / "fixtures" / name / "cobol"
        )
        app = ApplicationDiscovery().discover(fixture)
        report = CapabilityAnalyzer(docker_available=docker).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        return programs[0].level

    def test_redefines_fixture_fails_closed(self) -> None:
        # The shipped fixture redefines a numeric item as text; GnuCOBOL's
        # numeric reinterpretation of non-digit bytes is compiler-specific
        # undefined data, so this chain is UNSUPPORTED (not silently lowered).
        level = self._fixture_level("workload-redefines")
        assert level is CapabilityLevel.UNSUPPORTED

    def test_occurs_is_partial_with_proven_subset(self) -> None:
        level = self._fixture_level("workload-occurs")
        assert level is CapabilityLevel.PARTIAL

    def test_level88_supported_with_proof(self) -> None:
        # Docker availability distinguishes "construct supported" from
        # "runtime verification unavailable"; this fixture is construct-only
        # SUPPORTED when the runtime lane is present.
        level = self._fixture_level("workload-level88", docker=True)
        assert level is CapabilityLevel.SUPPORTED


class TestMinimalPrograms:
    def test_certified_88_level_is_supported(self, tmp_path) -> None:
        assert _classify(_88, tmp_path) is CapabilityLevel.SUPPORTED

    def test_88_level_bare_identifier_value_fails_closed(self, tmp_path) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. L88BAD.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-STATUS PIC 9(2) VALUE 10.
   88 STAT-OK VALUE WS-OTHER.
01 WS-OTHER PIC 9(2) VALUE 0.
PROCEDURE DIVISION.
MAIN.
    DISPLAY "HELLO".
    STOP RUN.
"""
        assert _classify(src, tmp_path) is CapabilityLevel.UNSUPPORTED

    def test_occurs_depending_on_blocked(self, tmp_path) -> None:
        level = _classify(_OCCURS_DEPENDING, tmp_path)
        # Variable-length tables are rejected at parse time, never lowered to
        # a silently wrong fixed size.
        assert level is CapabilityLevel.UNSUPPORTED

    def test_generic_set_still_unsupported(self, tmp_path) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. SETIDX.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-I PIC 9(2) VALUE 1.
01 WS-T PIC 9(3) OCCURS 3 TIMES.
PROCEDURE DIVISION.
MAIN.
    SET WS-I TO 2.
    DISPLAY "HI".
    STOP RUN.
"""
        assert _classify(src, tmp_path) is CapabilityLevel.UNSUPPORTED

    def test_set_condition_to_true_is_supported(self, tmp_path) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. SETCOND.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-STATUS PIC 9(2) VALUE 0.
   88 STAT-OK VALUE 00.
PROCEDURE DIVISION.
MAIN.
    SET STAT-OK TO TRUE.
    DISPLAY "HI".
    STOP RUN.
"""
        assert _classify(src, tmp_path) is CapabilityLevel.SUPPORTED

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


class TestStructuralNearMisses:
    """Data names that merely contain a construct word are not the construct."""

    def test_identifier_near_misses_never_detect(self) -> None:
        from engine.transformation.semantic_capability import scan_constructs

        near_misses = "\n".join((
            "01 WS-OCCURS-COUNT PIC 9(4).",
            "01 WS-REDEFINES-FLAG PIC X.",
            "01 WS-88-LEVEL-CODE PIC X(4).",
            "01 OCCURS-TOTAL PIC 9(4).",
            "01 REDEFINES-COUNT PIC 9(4).",
        ))
        found = scan_constructs(near_misses, restrict_to_procedure=False)
        assert "OCCURS" not in found, found
        assert "REDEFINES" not in found, found
        assert "88-LEVEL" not in found, found

    def test_real_clauses_still_detect(self) -> None:
        from engine.transformation.semantic_capability import scan_constructs

        source = (
            "01 WS-A PIC X(10).\n"
            "01 WS-R REDEFINES WS-A PIC X(10).\n"
            "01 WS-T PIC 9(3) OCCURS 3 TIMES.\n"
            "01 WS-STATUS PIC 9(2).\n"
            "    88 STAT-OK VALUE 00.\n"
        )
        found = scan_constructs(source, restrict_to_procedure=False)
        assert {"REDEFINES", "OCCURS", "88-LEVEL"} <= found, found
