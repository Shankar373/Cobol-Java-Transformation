"""CALL parameter-passing modes: deterministic lowering contracts.

The oracle proof lives in
``tests/integration/test_call_passing_mode_oracle_proof.py`` (Docker-gated).
These tests pin the deterministic, always-running side:

* the capability registry separates ``BY CONTENT`` (oracle-proven SUPPORTED)
  from ``BY VALUE`` (mapper implemented, no available oracle -> PARTIAL);
* source detection sees the caller's USING clause without matching data names;
* the parser records one mode per argument;
* the analyzer derives the verdict from the parsed ``passing_modes`` flag, not
  from a raw source guess;
* the mapper emits sync-in for every mode and sync-out only for BY REFERENCE.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer, CapabilityLevel
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.cobol_to_java_mapping import (
    map_cobol_programs_to_application,
)
from engine.transformation.ir import CallStatement
from engine.transformation.java_generator import JavaGenerator
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    CapabilityLevel as RegistryLevel,
    scan_constructs,
)

BY_CONTENT_REGISTRY = "BY CONTENT"
BY_VALUE_REGISTRY = "BY VALUE"


def _program(pid: str, body: str) -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        f"PROGRAM-ID. {pid}.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-VALUE PIC 9(4) VALUE 100.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-LOGIC.\n"
        f"{body}\n"
        "    STOP RUN.\n"
    )


CALLEE = textwrap.dedent(
    """\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. MODIFY.
    DATA DIVISION.
    LINKAGE SECTION.
    01 LS-VALUE PIC 9(4).
    PROCEDURE DIVISION USING LS-VALUE.
    MAIN-LOGIC.
        ADD 50 TO LS-VALUE.
        GOBACK.
    """
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestPassingModeRegistry:
    def test_by_content_is_oracle_proven_supported(self) -> None:
        entry = CONSTRUCT_REGISTRY[BY_CONTENT_REGISTRY]
        assert entry.level is RegistryLevel.SUPPORTED
        assert "GnuCOBOL" in entry.evidence
        assert "byte-identical" in entry.evidence

    def test_by_value_is_partial_pending_an_oracle(self) -> None:
        entry = CONSTRUCT_REGISTRY[BY_VALUE_REGISTRY]
        assert entry.level is RegistryLevel.PARTIAL
        # The exact blocker must be named, not glossed over.
        assert "-Wunfinished" in entry.evidence
        assert "SIGSEGV" in entry.evidence

    def test_unparsed_passing_phrase_fails_closed(self) -> None:
        for key in (BY_CONTENT_REGISTRY, BY_VALUE_REGISTRY):
            assert (
                CONSTRUCT_REGISTRY[key].effective_source_level
                is RegistryLevel.UNSUPPORTED
            ), key


# ---------------------------------------------------------------------------
# Source detection
# ---------------------------------------------------------------------------

class TestPassingModeSourceScan:
    def test_by_content_and_by_value_are_detected(self) -> None:
        source = _program(
            "MODCALL",
            """    CALL "MODIFY" USING BY CONTENT WS-VALUE.
    CALL "MODIFY" USING BY VALUE WS-VALUE.""",
        )
        found = scan_constructs(source)
        assert BY_CONTENT_REGISTRY in found
        assert BY_VALUE_REGISTRY in found

    def test_data_names_containing_by_value_do_not_match(self) -> None:
        source = _program(
            "NAMES",
            """    MOVE 1 TO WS-BY-VALUE.
    DISPLAY WS-BY-CONTENT.""",
        )
        found = scan_constructs(source)
        assert BY_CONTENT_REGISTRY not in found
        assert BY_VALUE_REGISTRY not in found

    def test_data_division_value_clause_does_not_match(self) -> None:
        source = textwrap.dedent(
            """\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. VALUES.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-COUNT PIC 9(4) VALUE 10.
            PROCEDURE DIVISION.
            MAIN-LOGIC.
                DISPLAY WS-COUNT.
                STOP RUN.
            """
        )
        found = scan_constructs(source)
        assert BY_VALUE_REGISTRY not in found


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestPassingModeParsing:
    @pytest.mark.parametrize(
        ("clause", "expected"),
        [
            ("USING BY VALUE WS-VALUE", ("VALUE",)),
            ("USING BY CONTENT WS-VALUE", ("CONTENT",)),
            ("USING WS-VALUE", ("REFERENCE",)),
            (
                "USING BY REFERENCE WS-VALUE BY CONTENT WS-VALUE2",
                ("REFERENCE", "CONTENT"),
            ),
        ],
    )
    def test_one_mode_per_argument(self, clause: str, expected: tuple[str, ...]) -> None:
        source = textwrap.dedent(
            f"""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. MODCALL.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-VALUE PIC 9(4) VALUE 100.
            01 WS-VALUE2 PIC 9(4) VALUE 200.
            PROCEDURE DIVISION.
            MAIN-LOGIC.
                CALL "MODIFY" {clause}.
                STOP RUN.
            """
        )
        program = CobolParser().parse(source)
        call = program.paragraphs[0].statements[0]
        assert isinstance(call, CallStatement)
        assert call.passing_modes == expected


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

def _analyze(tmp_path: Path, source: str, pid: str) -> CapabilityLevel:
    (tmp_path / f"{pid}.cob").write_text(source, encoding="utf-8")
    (tmp_path / "MODIFY.cob").write_text(CALLEE, encoding="utf-8")
    app = ApplicationDiscovery().discover(str(tmp_path), application_id="modes")
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    program = [
        c for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == pid
    ]
    assert len(program) == 1, report.components
    return CapabilityLevel(program[0].level.value)


class TestPassingModeAnalysis:
    def test_by_content_program_is_supported(self, tmp_path: Path) -> None:
        source = _program(
            "MODCALL",
            '    CALL "MODIFY" USING BY CONTENT WS-VALUE.',
        )
        assert _analyze(tmp_path, source, "MODCALL") is CapabilityLevel.SUPPORTED

    def test_by_value_program_is_partial_not_supported(self, tmp_path: Path) -> None:
        source = _program(
            "MODCALL",
            '    CALL "MODIFY" USING BY VALUE WS-VALUE.',
        )
        assert _analyze(tmp_path, source, "MODCALL") is CapabilityLevel.PARTIAL


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------

def _generated_sources(mode_clause: str) -> dict[str, str]:
    caller = _program("MAIN", f'    CALL "MODIFY" {mode_clause}.')
    mentioned = CobolParser().parse(caller)
    callee = CobolParser().parse(CALLEE)
    java_app = map_cobol_programs_to_application(
        programs=(mentioned, callee),
        application_id="modes",
    )
    return {
        f.class_name: f.source_code
        for f in JavaGenerator().generate_from_java(java_app)
    }


class TestPassingModeLowering:
    def test_by_content_writes_in_but_never_back(self) -> None:
        sources = _generated_sources("USING BY CONTENT WS-VALUE")
        main = sources["Main"]
        assert "Modify.LS_VALUE = WS_VALUE;" in main
        assert "WS_VALUE = Modify.LS_VALUE;" not in main

    def test_by_reference_writes_back(self) -> None:
        sources = _generated_sources("USING BY REFERENCE WS-VALUE")
        main = sources["Main"]
        assert "Modify.LS_VALUE = WS_VALUE;" in main
        assert "WS_VALUE = Modify.LS_VALUE;" in main

    def test_by_value_dispatches_without_write_back(self) -> None:
        sources = _generated_sources("USING BY VALUE WS-VALUE")
        main = sources["Main"]
        assert "Modify.LS_VALUE = WS_VALUE;" in main
        assert "WS_VALUE = Modify.LS_VALUE;" not in main
