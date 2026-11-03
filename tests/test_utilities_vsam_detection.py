"""Phase 7 focused gate: external utilities / system services / VSAM detection (roadmap P3-5).

Master README §29 requires external utilities and system services to be
Detected → Classified (then strategy/verification — none exist, so the
classification is UNSUPPORTED and the plan stays BLOCKED).  Roadmap P3-5
defines the authorized increment: source patterns + registry keys +
negatives — no IR, no mapper, no VSAM runtime, no equivalence claim
(Rung 0 -> 1 -> 2).

Acceptance (docs/BACKLOG.md BL-086):
1. detection fires for real `RELEASE`, `IDCAMS`, `ORGANIZATION INDEXED`,
   `ORGANIZATION RELATIVE`, `ACCESS DYNAMIC` and `RECORD KEY` phrases and
   never for a control program, comment text or string-literal text;
2. the registry classifies utilities `UNSUPPORTED` and the indexed/relative
   FILE-CONTROL keys `SUPPORTED` for the certified subset (BL-134), with
   source-only `UNSUPPORTED` (fail closed when no FileDefinition IR exists);
3. the analyzer's PROGRAM reason names the construct; a VSAM program that
   relies on an ALTERNATE RECORD KEY stays `UNSUPPORTED`, a relative program
   without `ACCESS MODE IS DYNAMIC` stays `UNSUPPORTED` (outside the
   certified subset), while the certified indexed/relative subset is
   `SUPPORTED` with a `TRANSFORM` plan;
4. repeated scans are deterministic;
5. no existing test is weakened.
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

NEW_KEYS = (
    "RELEASE",
    "IDCAMS",
    "ORGANIZATION INDEXED",
    "ORGANIZATION RELATIVE",
    "ACCESS DYNAMIC",
    "RECORD KEY",
)

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)

UTILITIES_PROGRAM = HEADER.format(pid="UTILDEMO") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-OUT-REC PIC X(80).\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           RELEASE WS-OUT-REC.\n"
    "           ALTER WS-PROC TO PROCEED TO IDCAMS.\n"
    "           STOP RUN.\n"
    "       WS-PROC.\n"
    "           DISPLAY 'IN PROC'.\n"
    "       IDCAMS.\n"
    "           DISPLAY WS-OUT-REC.\n"
    "           STOP RUN.\n"
)

VSAM_PROGRAM = HEADER.format(pid="VSAMDEMO") + (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT VSAM-FILE ASSIGN TO '/workspace/data/vsam.dat'\n"
    "               ORGANIZATION IS INDEXED\n"
    "               ACCESS MODE IS DYNAMIC\n"
    "               RECORD KEY IS VSAM-KEY\n"
    "               ALTERNATE RECORD KEY IS VSAM-ALT-KEY\n"
    "               FILE STATUS IS WS-STATUS.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  VSAM-FILE.\n"
    "       01  VSAM-REC.\n"
    "           05  VSAM-KEY      PIC X(10).\n"
    "           05  VSAM-ALT-KEY  PIC X(10).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-STATUS PIC XX.\n"
    "       PROCEDURE DIVISION.\n"
    "           OPEN I-O VSAM-FILE.\n"
    "           CLOSE VSAM-FILE.\n"
    "           STOP RUN.\n"
)

RELATIVE_PROGRAM = HEADER.format(pid="RELDEMO") + (
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT REL-FILE ASSIGN TO '/workspace/data/rel.dat'\n"
    "               ORGANIZATION IS RELATIVE\n"
    "               RELATIVE KEY IS REL-SLOT\n"
    "               FILE STATUS IS WS-STATUS.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD  REL-FILE.\n"
    "       01  REL-REC PIC X(20).\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-STATUS PIC XX.\n"
    "       01  REL-SLOT  PIC 9(4).\n"
    "       PROCEDURE DIVISION.\n"
    "           OPEN I-O REL-FILE.\n"
    "           CLOSE REL-FILE.\n"
    "           STOP RUN.\n"
)

CONTROL_PROGRAM = HEADER.format(pid="PLAINUTIL") + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-X PIC X(10).\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY WS-X.\n"
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
    app = ApplicationDiscovery().discover(src, application_id="phase7-p35")
    report = CapabilityAnalyzer(docker_available=True).analyze(
        app, source_root=src
    )
    return next(
        c
        for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == program_id
    )


class TestSourceScanDetection:
    def test_release_statement_is_detected(self) -> None:
        assert "RELEASE" in scan_constructs(UTILITIES_PROGRAM)

    def test_idcams_reference_is_detected(self) -> None:
        assert "IDCAMS" in scan_constructs(UTILITIES_PROGRAM)

    def test_indexed_vsam_phrases_are_detected(self) -> None:
        found = scan_constructs(VSAM_PROGRAM, restrict_to_procedure=False)
        assert "ORGANIZATION INDEXED" in found, sorted(found)
        assert "ACCESS DYNAMIC" in found, sorted(found)
        assert "RECORD KEY" in found, sorted(found)

    def test_relative_organization_is_detected(self) -> None:
        found = scan_constructs(RELATIVE_PROGRAM, restrict_to_procedure=False)
        assert "ORGANIZATION RELATIVE" in found, sorted(found)

    def test_control_program_detects_none_of_the_new_keys(self) -> None:
        found = scan_constructs(CONTROL_PROGRAM, restrict_to_procedure=False)
        for key in NEW_KEYS:
            assert key not in found, (key, sorted(found))

    def test_comment_and_string_literal_text_never_detect(self) -> None:
        masked = (
            "       PROCEDURE DIVISION.\n"
            "     *    RELEASE WS-COMMENT.\n"
            "           DISPLAY \"RELEASE WS-STRING\".\n"
            "     *>   IDCAMS COPY STEP.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(masked)
        assert "RELEASE" not in found, sorted(found)
        assert "IDCAMS" not in found, sorted(found)

    def test_word_boundary_never_matches_longer_identifiers(self) -> None:
        near_misses = (
            "       PROCEDURE DIVISION.\n"
            "           MOVE WS-RELEASE-CODE TO WS-Y.\n"
            "           MOVE WS-IDCAMS-COUNT TO WS-Z.\n"
            "           STOP RUN.\n"
        )
        found = scan_constructs(near_misses)
        assert "RELEASE" not in found, sorted(found)
        assert "IDCAMS" not in found, sorted(found)

    def test_detection_is_deterministic(self) -> None:
        first = scan_constructs(UTILITIES_PROGRAM) | scan_constructs(
            VSAM_PROGRAM, restrict_to_procedure=False
        )
        second = scan_constructs(UTILITIES_PROGRAM) | scan_constructs(
            VSAM_PROGRAM, restrict_to_procedure=False
        )
        assert first == second
        for key in ("RELEASE", "IDCAMS", "ORGANIZATION INDEXED", "ACCESS DYNAMIC", "RECORD KEY"):
            assert key in first, sorted(first)


class TestRegistryClassification:
    def test_utilities_fail_closed(self) -> None:
        for key in ("RELEASE", "IDCAMS"):
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.level is CapabilityLevel.UNSUPPORTED, (key, entry)
            assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, (
                key,
                entry,
            )

    def test_file_control_keys_are_supported_but_fail_closed_without_ir(self) -> None:
        # 2026-10-22 (BL-134): the indexed/relative SELECT clauses are SUPPORTED
        # for the certified subset (byte-identical to GnuCOBOL 3.1.2 on the
        # shipped fixtures), and the evidence text must carry the non-claim.
        # A source phrase with no FileDefinition IR still fails closed.
        for key in (
            "ORGANIZATION INDEXED",
            "ORGANIZATION RELATIVE",
            "ACCESS DYNAMIC",
            "RECORD KEY",
        ):
            entry = CONSTRUCT_REGISTRY[key]
            assert entry.level is CapabilityLevel.SUPPORTED, (key, entry)
            assert entry.effective_source_level is CapabilityLevel.UNSUPPORTED, (
                key,
                entry,
            )
            assert "PROVEN" in entry.evidence, (key, entry)
            if key.startswith("ORGANIZATION"):
                assert "file-image equivalence is not claimed" in entry.evidence, (
                    key,
                    entry,
                )


class TestCapabilityVerdicts:
    def test_utilities_program_verdict_names_the_constructs(self, tmp_path) -> None:
        program = _program_component(tmp_path, UTILITIES_PROGRAM, "UTILDEMO")
        assert program.level is CapabilityLevel.UNSUPPORTED, program
        assert "RELEASE" in program.reason, program.reason
        assert "IDCAMS" in program.reason, program.reason

    def test_vsam_program_verdict_names_the_constructs(self, tmp_path) -> None:
        program = _program_component(tmp_path, VSAM_PROGRAM, "VSAMDEMO")
        assert program.level is CapabilityLevel.UNSUPPORTED, program
        # ALTERNATE RECORD KEY is the real blocker: it has no lowering, so the
        # program must not inherit the certified indexed subset's SUPPORTED.
        assert "RECORD KEY" in program.reason, program.reason
        assert "ALTERNATE RECORD KEY" in program.reason, program.reason
        assert "no alternate-index lowering" in program.reason, program.reason

    def test_relative_program_without_certified_access_mode_fails_closed(
        self, tmp_path
    ) -> None:
        # RELATIVE_PROGRAM declares no ACCESS MODE (COBOL default SEQUENTIAL),
        # which is outside the certified subset (DYNAMIC only), so the verdict
        # must fail closed — strictly stronger than the pre-BL-134 PARTIAL —
        # and the reason must name the file and why it is outside the subset.
        program = _program_component(tmp_path, RELATIVE_PROGRAM, "RELDEMO")
        assert program.level is CapabilityLevel.UNSUPPORTED, program
        assert "file REL-FILE" in program.reason, program.reason
        assert "outside the certified subset" in program.reason, program.reason
        assert "ACCESS MODE DYNAMIC" in program.reason, program.reason

    def test_relative_program_in_certified_subset_is_supported_and_plans(
        self, tmp_path
    ) -> None:
        # Positive control for BL-134: same program with ACCESS MODE IS DYNAMIC
        # is inside the certified subset → SUPPORTED program, READY plan.
        src = RELATIVE_PROGRAM.replace(
            "               ORGANIZATION IS RELATIVE\n",
            "               ORGANIZATION IS RELATIVE\n"
            "               ACCESS MODE IS DYNAMIC\n",
        )
        program = _program_component(tmp_path, src, "RELDEMO")
        assert program.level is CapabilityLevel.SUPPORTED, program

        plan_src = _write(tmp_path, {"RELDEMO.cob": src})
        plan = ModernizationPlanner(docker_available=True).plan(
            plan_src, application_id="phase7-p35", entrypoint="RELDEMO"
        )
        assert plan.overall_status is ModernizationStatus.READY, plan

    def test_control_program_never_names_the_new_keys(self, tmp_path) -> None:
        program = _program_component(tmp_path, CONTROL_PROGRAM, "PLAINUTIL")
        for key in NEW_KEYS:
            assert key not in program.reason, program.reason

    def test_utilities_program_plan_still_blocks(self, tmp_path) -> None:
        src = _write(tmp_path, {"UTILDEMO.cob": UTILITIES_PROGRAM})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="phase7-p35", entrypoint="UTILDEMO"
        )
        assert plan.overall_status is ModernizationStatus.BLOCKED, plan

    def test_vsam_program_plan_still_blocks(self, tmp_path) -> None:
        src = _write(tmp_path, {"VSAMDEMO.cob": VSAM_PROGRAM})
        plan = ModernizationPlanner(docker_available=True).plan(
            src, application_id="phase7-p35", entrypoint="VSAMDEMO"
        )
        assert plan.overall_status is ModernizationStatus.BLOCKED, plan
