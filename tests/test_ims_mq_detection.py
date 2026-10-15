"""Phase 7 focused gate: IMS (`EXEC DLI`) and IBM MQ (`EXEC MQI`) detection + classification.

Master README §27 (MQ) and §28 (IMS) require these subsystems to be
classified explicitly and require unknown IMS constructs never to pass
through silently.  Roadmap P3-4 defines the authorized increment: source
patterns, registry keys, blocked verdicts, negatives — no runtime, no
equivalence claim (Rung 0 -> 1 -> 2).

Acceptance (docs/BACKLOG.md BL-084 / BL-085):
1. detection fires for a real `EXEC DLI` / `EXEC MQI` statement and never
   for a control program, comment text or string-literal text;
2. the registry classifies both constructs `UNSUPPORTED` at IR level and
   at source-only level (fail closed);
3. the analyzer's PROGRAM reason names `EXEC DLI` / `EXEC MQI` and the
   verdict is never `SUPPORTED` — the plan still blocks;
4. repeated scans are identical (deterministic, no model in the loop);
5. the pre-existing fail-closed `unparsed_statement` diagnostics remain,
   and no existing test is weakened.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.modernization_planner import (
    ModernizationPlanner,
    ModernizationStatus,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    scan_constructs,
)

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)

IMS_PROGRAM = HEADER.format(pid="IMSDEMO") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-CUST-REC.\n"
    "           05  WS-CUST-ID     PIC X(10).\n"
    "       PROCEDURE DIVISION.\n"
    "           EXEC DLI GU\n"
    "                PCB NAME=IMSPCB\n"
    "                SEGMENT NAME=CUSTOMER\n"
    "           END-EXEC.\n"
    "           DISPLAY WS-CUST-ID.\n"
    "           STOP RUN.\n"
)

MQ_PROGRAM = HEADER.format(pid="MQDEMO") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-MSG-TEXT  PIC X(80).\n"
    "       PROCEDURE DIVISION.\n"
    "           EXEC MQI PUT Q(HQUEUE) MSGDESC(WS-DESC)\n"
    "                BUFFER(WS-MSG-TEXT) BUFLEN(80)\n"
    "           END-EXEC.\n"
    "           DISPLAY WS-MSG-TEXT.\n"
    "           STOP RUN.\n"
)

CONTROL_PROGRAM = HEADER.format(pid="PLAIN") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-MSG-TEXT  PIC X(80).\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY WS-MSG-TEXT.\n"
    "           STOP RUN.\n"
)


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text, encoding="utf-8")
    return src


def _program_component(tmp_path: Path, source: str, program_id: str):
    src = _write(tmp_path, {f"{program_id}.cob": source})
    app = ApplicationDiscovery().discover(src, application_id="phase7-detect")
    report = CapabilityAnalyzer(docker_available=True).analyze(
        app, source_root=src
    )
    return next(
        c
        for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == program_id
    )


class TestSourceScanDetection:
    def test_exec_dli_statement_is_detected(self) -> None:
        found = scan_constructs(IMS_PROGRAM)
        assert "EXEC DLI" in found, sorted(found)

    def test_exec_mqi_statement_is_detected(self) -> None:
        found = scan_constructs(MQ_PROGRAM)
        assert "EXEC MQI" in found, sorted(found)

    def test_control_program_detects_neither_construct(self) -> None:
        found = scan_constructs(CONTROL_PROGRAM)
        assert "EXEC DLI" not in found, sorted(found)
        assert "EXEC MQI" not in found, sorted(found)

    def test_comment_and_string_literal_text_never_detect(self) -> None:
        """Comment lines and string-literal data are not statements (BL-034 masking)."""
        masked = (
            "       PROCEDURE DIVISION.\n"
            "     *    EXEC DLI GU PCB NAME=COMMENTED\n"
            "           DISPLAY \"EXEC MQI PUT Q(HQUEUE)\".\n"
            "     *>   EXEC DLI GU\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(masked)
        assert "EXEC DLI" not in found, sorted(found)
        assert "EXEC MQI" not in found, sorted(found)

    def test_word_boundary_never_matches_longer_identifiers(self) -> None:
        """`EXECUTE`, `EXEC-` prefixed data names and MQI-only text are not MQ detection."""
        near_misses = (
            "       PROCEDURE DIVISION.\n"
            "           EXECUTE IMMEDIATE WS-SQL.\n"
            "           MOVE WS-EXEC-MQI TO WS-X.\n"
            "           MOVE WS-DLI-COUNT TO WS-Y.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(near_misses)
        assert "EXEC DLI" not in found, sorted(found)
        assert "EXEC MQI" not in found, sorted(found)

    def test_cics_detection_does_not_cross_talk(self) -> None:
        cics = (
            "       PROCEDURE DIVISION.\n"
            "           EXEC CICS LINK PROGRAM 'SUB' END-EXEC.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(cics)
        assert "EXEC CICS" in found, sorted(found)
        assert "EXEC DLI" not in found, sorted(found)
        assert "EXEC MQI" not in found, sorted(found)

    def test_detection_is_deterministic(self) -> None:
        first = scan_constructs(IMS_PROGRAM) | scan_constructs(MQ_PROGRAM)
        second = scan_constructs(IMS_PROGRAM) | scan_constructs(MQ_PROGRAM)
        assert first == second
        assert "EXEC DLI" in first and "EXEC MQI" in first


class TestRegistryClassification:
    def test_exec_dli_registry_entry_fails_closed(self) -> None:
        entry = CONSTRUCT_REGISTRY["EXEC DLI"]
        assert entry.level is CapabilityLevel.UNSUPPORTED, entry
        assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, entry

    def test_exec_mqi_registry_entry_fails_closed(self) -> None:
        entry = CONSTRUCT_REGISTRY["EXEC MQI"]
        assert entry.level is CapabilityLevel.UNSUPPORTED, entry
        assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, entry


class TestCapabilityVerdicts:
    def test_exec_dli_program_verdict_names_ims_construct(self, tmp_path) -> None:
        program = _program_component(tmp_path, IMS_PROGRAM, "IMSDEMO")
        assert program.level is not CapabilityLevel.SUPPORTED, program
        assert program.level is not CapabilityLevel.PARTIAL, program
        assert program.level is CapabilityLevel.UNSUPPORTED, program
        assert "EXEC DLI" in program.reason, program.reason
        # Pre-existing fail-closed diagnostics must remain (nothing silently passes).
        assert "unparsed_statement" in program.reason, program.reason

    def test_exec_mqi_program_verdict_names_mq_construct(self, tmp_path) -> None:
        program = _program_component(tmp_path, MQ_PROGRAM, "MQDEMO")
        assert program.level is not CapabilityLevel.SUPPORTED, program
        assert program.level is not CapabilityLevel.PARTIAL, program
        assert program.level is CapabilityLevel.UNSUPPORTED, program
        assert "EXEC MQI" in program.reason, program.reason
        assert "unparsed_statement" in program.reason, program.reason

    def test_control_program_never_names_ims_or_mq(self, tmp_path) -> None:
        program = _program_component(tmp_path, CONTROL_PROGRAM, "PLAIN")
        assert "EXEC DLI" not in program.reason, program.reason
        assert "EXEC MQI" not in program.reason, program.reason

    def test_exec_dli_program_plan_still_blocks(self, tmp_path) -> None:
        src = _write(tmp_path, {"IMSDEMO.cob": IMS_PROGRAM})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="phase7-detect", entrypoint="IMSDEMO"
        )
        assert plan.overall_status is ModernizationStatus.BLOCKED, plan

    def test_exec_mqi_program_plan_still_blocks(self, tmp_path) -> None:
        src = _write(tmp_path, {"MQDEMO.cob": MQ_PROGRAM})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="phase7-detect", entrypoint="MQDEMO"
        )
        assert plan.overall_status is ModernizationStatus.BLOCKED, plan
