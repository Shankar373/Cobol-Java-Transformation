"""No-silent-loss gate: `LOCAL-STORAGE SECTION` and the `REPLACE` directive.

The universality requirements list both as recognised COBOL constructs that a
transformation must account for.  Neither was parsed, classified, or even
mentioned anywhere in the engine — a program that used them would transform
as if they were absent, so the loss would be invisible to a reviewer.  This
file pins the fix at three layers:

1. the parser emits an explicit `UNSUPPORTED_CONSTRUCT` diagnostic the moment
   it sees either construct (fail-closed, never silent);
2. the capability registry classifies both `UNSUPPORTED` at IR level *and*
   source-only level, so a program containing them can never be reported
   SUPPORTED;
3. the source scanner detects both (with the pre-procedure scan the analyzer
   already performs for data-division constructs), and detection never
   misfires on near-miss identifiers or on `COPY ... REPLACING`.

No transformation is claimed for either construct — only honest detection and
classification.  Nothing here is skipped or weakened.
"""

from __future__ import annotations

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.diagnostics import DiagnosticCode
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    scan_constructs,
)

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)


def _diag_codes(source: str) -> list[DiagnosticCode]:
    parser = CobolParser()
    parser.parse(source)
    return [d.code for d in parser.diagnostics.all]


def _diag_messages(source: str) -> str:
    parser = CobolParser()
    parser.parse(source)
    return " | ".join(d.message for d in parser.diagnostics.all)


LOCAL_STORAGE_PROGRAM = HEADER.format(pid="LSDEMO") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-OUT  PIC X(10).\n"
    "       LOCAL-STORAGE SECTION.\n"
    "       01  LS-ACCUM  PIC 9(5) VALUE ZERO.\n"
    "       PROCEDURE DIVISION.\n"
    "           MOVE WS-OUT TO WS-OUT.\n"
    "           STOP RUN.\n"
)

REPLACE_PROGRAM = HEADER.format(pid="REPDEMO") + (
    "       REPLACE ==OLD-TOKEN== BY ==NEW-TOKEN==.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-OUT  PIC X(10).\n"
    "       PROCEDURE DIVISION.\n"
    "           MOVE WS-OUT TO WS-OUT.\n"
    "           END-REPLACE.\n"
    "           STOP RUN.\n"
)

CONTROL_PROGRAM = HEADER.format(pid="PLAIN") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-OUT  PIC X(10).\n"
    "       PROCEDURE DIVISION.\n"
    "           MOVE WS-OUT TO WS-OUT.\n"
    "           STOP RUN.\n"
)


class TestParserEmitsExplicitDiagnostics:
    def test_local_storage_section_is_diagnosed(self) -> None:
        assert DiagnosticCode.UNSUPPORTED_CONSTRUCT in _diag_codes(
            LOCAL_STORAGE_PROGRAM
        ), _diag_messages(LOCAL_STORAGE_PROGRAM)

    def test_local_storage_diagnostic_names_the_construct(self) -> None:
        messages = _diag_messages(LOCAL_STORAGE_PROGRAM)
        assert "LOCAL-STORAGE" in messages, messages

    def test_replace_directive_is_diagnosed(self) -> None:
        assert DiagnosticCode.UNSUPPORTED_CONSTRUCT in _diag_codes(
            REPLACE_PROGRAM
        ), _diag_messages(REPLACE_PROGRAM)

    def test_replace_diagnostic_names_the_construct(self) -> None:
        messages = _diag_messages(REPLACE_PROGRAM)
        assert "REPLACE" in messages, messages

    def test_control_program_is_never_diagnosed(self) -> None:
        """A clean program must not gain a spurious unsupported diagnostic."""
        messages = _diag_messages(CONTROL_PROGRAM)
        assert "LOCAL-STORAGE" not in messages, messages
        assert "REPLACE" not in messages, messages


class TestRegistryClassification:
    def test_local_storage_registry_entry_fails_closed(self) -> None:
        entry = CONSTRUCT_REGISTRY["LOCAL-STORAGE"]
        assert entry.level is CapabilityLevel.UNSUPPORTED, entry
        assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, entry

    def test_replace_registry_entry_fails_closed(self) -> None:
        entry = CONSTRUCT_REGISTRY["REPLACE"]
        assert entry.level is CapabilityLevel.UNSUPPORTED, entry
        assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, entry


class TestSourceScanDetection:
    def test_local_storage_is_detected_in_pre_procedure_scan(self) -> None:
        found = scan_constructs(LOCAL_STORAGE_PROGRAM, restrict_to_procedure=False)
        assert "LOCAL-STORAGE" in found, sorted(found)

    def test_replace_is_detected_in_pre_procedure_scan(self) -> None:
        found = scan_constructs(REPLACE_PROGRAM, restrict_to_procedure=False)
        assert "REPLACE" in found, sorted(found)

    def test_control_program_detects_neither_construct(self) -> None:
        found = scan_constructs(CONTROL_PROGRAM, restrict_to_procedure=False)
        assert "LOCAL-STORAGE" not in found, sorted(found)
        assert "REPLACE" not in found, sorted(found)

    def test_copy_replacing_is_not_mistaken_for_replace_directive(self) -> None:
        """`COPY ... REPLACING` is a different construct and must not fire."""
        copy_replacing = (
            "       PROCEDURE DIVISION.\n"
            "           COPY MYBOOK REPLACING ==A== BY ==B==.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(copy_replacing, restrict_to_procedure=False)
        assert "REPLACE" not in found, sorted(found)

    def test_near_miss_identifiers_never_detect(self) -> None:
        """Hyphen-suffixed data names are not the constructs themselves."""
        near_misses = (
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  WS-LOCAL-STORAGE-FLAG  PIC X.\n"
            "       01  WS-REPLACE-COUNT       PIC 9.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(near_misses, restrict_to_procedure=False)
        assert "LOCAL-STORAGE" not in found, sorted(found)
        assert "REPLACE" not in found, sorted(found)

    def test_detection_is_deterministic(self) -> None:
        first = scan_constructs(LOCAL_STORAGE_PROGRAM, restrict_to_procedure=False)
        second = scan_constructs(LOCAL_STORAGE_PROGRAM, restrict_to_procedure=False)
        assert first == second
        assert "LOCAL-STORAGE" in first


class TestCapabilityVerdicts:
    def _program_component(self, tmp_path, source: str, program_id: str):
        src = tmp_path / "cobol"
        src.mkdir(parents=True, exist_ok=True)
        (src / f"{program_id}.cob").write_text(source, encoding="utf-8")
        app = ApplicationDiscovery().discover(src, application_id="ls-replace")
        report = CapabilityAnalyzer(docker_available=True).analyze(
            app, source_root=src
        )
        return next(
            c
            for c in report.components
            if c.component_type == "PROGRAM" and c.component_id == program_id
        )

    def test_local_storage_program_is_never_reported_supported(self, tmp_path) -> None:
        program = self._program_component(tmp_path, LOCAL_STORAGE_PROGRAM, "LSDEMO")
        assert program.level is not CapabilityLevel.SUPPORTED, program

    def test_replace_program_is_never_reported_supported(self, tmp_path) -> None:
        program = self._program_component(tmp_path, REPLACE_PROGRAM, "REPDEMO")
        assert program.level is not CapabilityLevel.SUPPORTED, program
