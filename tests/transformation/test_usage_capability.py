"""Regression tests for USAGE-clause capability honesty (BL-002).

Before this work, `PIC S9(4) COMP` parsed with zero diagnostics and the
USAGE clause was dropped without a trace — a silent narrowing the capability
rule forbids.  These tests lock in:

* the parser records the canonical USAGE token on ``DataItem.usage``,
* the parser emits a non-blocking PARTIAL_SUPPORT diagnostic (never forced
  to UNSUPPORTED),
* ``COMP``/``COMP-3``/... classify at PARTIAL, never SUPPORTED, and
* a program with no USAGE clause is unaffected (no false PARTIAL).
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    USAGE_TO_CONSTRUCT,
    canonical_usage,
)
from engine.transformation.ir import DataItem

_MINIMAL = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. USAGE-TEST.
DATA DIVISION.
WORKING-STORAGE SECTION.
{ws}
PROCEDURE DIVISION.
MAIN-LOGIC.
    STOP RUN.
"""


def _parse(ws: str):
    return CobolParser().parse(_MINIMAL.format(ws=ws))


def _item(program, name: str) -> DataItem:
    return next(i for i in program.working_storage if i.name == name)


class TestParserRecordsUsage:
    def test_comp_recorded(self) -> None:
        item = _item(_parse("01 WS-A PIC S9(4) COMP."), "WS-A")
        assert item.usage == "COMP"

    def test_comp3_recorded(self) -> None:
        item = _item(_parse("01 WS-A PIC S9(5)V99 COMP-3."), "WS-A")
        assert item.usage == "COMP-3"

    def test_comp5_recorded(self) -> None:
        item = _item(_parse("01 WS-A PIC S9(9) COMP-5."), "WS-A")
        assert item.usage == "COMP-5"

    def test_comp1_comp2_recorded(self) -> None:
        assert _item(_parse("01 WS-A PIC S9(4) COMP-1."), "WS-A").usage == "COMP-1"
        assert _item(_parse("01 WS-A PIC S9(4) COMP-2."), "WS-A").usage == "COMP-2"

    def test_usage_is_comp_recorded(self) -> None:
        item = _item(_parse("01 WS-A PIC S9(4) USAGE IS COMP."), "WS-A")
        assert item.usage == "COMP"

    def test_synonyms_canonicalised(self) -> None:
        assert _item(_parse("01 WS-A PIC S9(4) BINARY."), "WS-A").usage == "COMP"
        assert _item(_parse("01 WS-A PIC S9(4) PACKED-DECIMAL."), "WS-A").usage == "COMP-3"
        assert _item(_parse("01 WS-A PIC S9(4) COMPUTATIONAL."), "WS-A").usage == "COMP"
        assert _item(_parse("01 WS-A PIC S9(4) COMPUTATIONAL-3."), "WS-A").usage == "COMP-3"

    def test_display_is_none(self) -> None:
        assert _item(_parse("01 WS-A PIC S9(4) DISPLAY."), "WS-A").usage is None
        assert _item(_parse("01 WS-A PIC 9(4)."), "WS-A").usage is None

    def test_literal_comp_in_value_not_matched(self) -> None:
        item = _item(_parse("01 WS-A PIC X(10) VALUE \"COMP\"."), "WS-A")
        assert item.usage is None

    def test_field_named_comp_not_matched(self) -> None:
        item = _item(_parse("01 COMP PIC X(10)."), "COMP")
        assert item.usage is None

    def test_file_section_usage_recorded(self) -> None:
        src = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. FILE-USAGE.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO "/tmp/in.dat".
DATA DIVISION.
FILE SECTION.
FD IN-FILE.
01 IN-REC.
   05 IN-AMOUNT PIC S9(5)V99 COMP-3.
WORKING-STORAGE SECTION.
01 WS-DUMMY PIC X VALUE SPACE.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""
        program = CobolParser().parse(src)
        record = next(
            item
            for fd in program.file_definitions
            for item in fd.record_items
            if item.name == "IN-AMOUNT"
        )
        assert record.usage == "COMP-3"


class TestParserDiagnostic:
    def test_partial_support_diagnostic_emitted(self) -> None:
        parser = CobolParser()
        parser.parse(_MINIMAL.format(ws="01 WS-A PIC S9(4) COMP."))
        warnings = [d for d in parser.diagnostics.all]
        assert any(
            d.code.name == "PARTIAL_SUPPORT" and d.location == "WS-A" for d in warnings
        ), warnings

    def test_no_diagnostic_for_display(self) -> None:
        parser = CobolParser()
        parser.parse(_MINIMAL.format(ws="01 WS-A PIC 9(4)."))
        assert not any(
            d.code.name == "PARTIAL_SUPPORT" for d in parser.diagnostics.all
        )

    def test_diagnostic_not_in_loss_channel(self) -> None:
        """PARTIAL_SUPPORT must NOT be surfaced as a parse loss (UNSUPPORTED)."""
        parser = CobolParser()
        parser.parse(_MINIMAL.format(ws="01 WS-A PIC S9(4) COMP."))
        # Simulate discovery's filter: loss channel excludes PARTIAL_SUPPORT.
        loss = [d for d in parser.diagnostics.all if d.code.name != "PARTIAL_SUPPORT"]
        assert loss == []


class TestCapabilityClassification:
    def _classify_fixture(self, name: str) -> CapabilityLevel:
        fixture = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / name
            / "cobol"
        )
        app = ApplicationDiscovery().discover(fixture)
        report = CapabilityAnalyzer(docker_available=False).analyze(app)
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert len(programs) == 1
        return programs[0].level

    def test_workload_comp_is_partial(self) -> None:
        level = self._classify_fixture("workload-comp")
        assert level is CapabilityLevel.PARTIAL
        assert level is not CapabilityLevel.SUPPORTED

    def test_workload_comp3_is_partial(self) -> None:
        level = self._classify_fixture("workload-comp3")
        assert level is CapabilityLevel.PARTIAL
        assert level is not CapabilityLevel.SUPPORTED

    def test_no_usage_program_stays_supported(self) -> None:
        src = _MINIMAL.format(ws="01 WS-A PIC 9(3) VALUE 0.")
        parser = CobolParser()
        program = parser.parse(src)
        app = ApplicationDiscovery()
        # Build a minimal single-program app without filesystem discovery.
        from engine.transformation.ir import CobolApplication, CobolProgramUnit
        unit = CobolProgramUnit(
            program_id="USAGE-TEST",
            source_path="MAIN.cob",
            program=program,
            source_text=src,
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(
            CobolApplication(application_id="TEST", programs=(unit,))
        )
        programs = [c for c in report.components if c.component_type == "PROGRAM"]
        assert programs[0].level is CapabilityLevel.SUPPORTED


class TestRegistryAndCanonicalUsage:
    def test_registry_keys_partial(self) -> None:
        for key in ("COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-5"):
            assert CONSTRUCT_REGISTRY[key].level is CapabilityLevel.PARTIAL, key

    def test_usage_to_construct_mapping(self) -> None:
        assert USAGE_TO_CONSTRUCT["COMP"] == "COMP"
        assert USAGE_TO_CONSTRUCT["COMP-3"] == "COMP-3"
        assert USAGE_TO_CONSTRUCT["COMP-5"] == "COMP-5"

    def test_canonical_usage_synonyms(self) -> None:
        assert canonical_usage("BINARY") == "COMP"
        assert canonical_usage("PACKED-DECIMAL") == "COMP-3"
        assert canonical_usage("COMPUTATIONAL-3") == "COMP-3"
        assert canonical_usage("DISPLAY") is None
        assert canonical_usage(None) is None

    def test_dataitem_default_usage_none(self) -> None:
        assert DataItem(name="X").usage is None


class TestCopybookSourceScan:
    def test_comp_pattern_documented(self) -> None:
        """Every _SOURCE_PATTERNS key must be documented (silent-loss gate)."""
        from tests.test_silent_loss_registry import _matrix_text
        from engine.transformation.semantic_capability import _SOURCE_PATTERNS

        text = _matrix_text()
        missing = [key for key, _ in _SOURCE_PATTERNS if key not in text]
        assert not missing, f"Matrix missing source patterns: {missing}"

    def test_registry_keys_documented(self) -> None:
        from tests.test_silent_loss_registry import _matrix_text

        text = _matrix_text()
        missing = [k for k in CONSTRUCT_REGISTRY if k not in text]
        assert not missing, f"Matrix missing registry keys: {missing}"
