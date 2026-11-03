"""BL-033 focused gate: unresolvable/ambiguous COPYBOOK components never classify SUPPORTED.

Capability truth (README §54): the capability graph and the plan must never
assert the opposite of the same run's generation.  Generation deterministically
fails for an unresolvable COPY reference ("Missing COPY target: <name>"), so
the COPYBOOK component, the modernization plan, the transformation plan, and
the dependency ledger must all say so — while the consuming program keeps its
own verdict and resolved copybooks keep theirs.

Acceptance (docs/BACKLOG.md BL-033):
1. missing / ambiguous / quoted-unresolvable copybook components are never
   SUPPORTED;
2. the plan for such an application is not READY and carries MISSING_COPYBOOK;
3. the plan may not report "No blocking issues identified" while generation
   deterministically fails;
4. resolved copybooks keep their current verdicts;
5. no existing negative contract weakened.

All tests run the real discovery -> capability -> planner -> generation path
(no mocks).  ``docker_available=True`` only satisfies the planner/analyzer
infrastructure flag; no Docker daemon is required for these assertions.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import (
    CapabilityAnalyzer,
    CapabilityLevel,
)
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    ProofState,
    RuntimeLaneEvidence,
    integrated_proof_from_pipelines,
)
from engine.modernization.modernization_planner import (
    BlockingReason,
    ModernizationPlanner,
    ModernizationStatus,
    TransformationStrategy,
)
from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)
from engine.modernization.transformation_plan import (
    TransformationAction,
    TransformationPlanGenerator,
)
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    CopybookReference,
    Paragraph,
)

HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)


def _main(pid: str, copy_stmt: str) -> str:
    return HEADER.format(pid=pid) + (
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{copy_stmt}"
        "       PROCEDURE DIVISION.\n"
        '           DISPLAY "BL033".\n'
        "           STOP RUN.\n"
    )


MISSING_STMT = "       COPY MISSING-REC.\n"
AMBIGUOUS_STMT = "       COPY DUP-REC.\n"
QUOTED_STMT = "       COPY 'P2REC'.\n"
RESOLVED_STMT = "       COPY REALREC.\n"
REALREC = "       01  WS-REAL PIC X(4).\n"


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "cobol"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return src


def _discovery_and_capability(tmp_path: Path, files: dict[str, str]):
    src = _write(tmp_path, files)
    app = ApplicationDiscovery().discover(src, application_id="bl033")
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    return src, app, report


def _copybook_component(report, name: str):
    comps = [
        c for c in report.components
        if c.component_type == "COPYBOOK" and c.component_id == name
    ]
    assert len(comps) == 1, (
        f"expected exactly one COPYBOOK component {name!r}, got "
        f"{[(c.component_id, c.level.name) for c in report.components if c.component_type == 'COPYBOOK']}"
    )
    return comps[0]


def _program_component(report, name: str):
    comps = [
        c for c in report.components
        if c.component_type == "PROGRAM" and c.component_id == name
    ]
    assert len(comps) == 1
    return comps[0]


def _plan(src: Path, entrypoint: str = ""):
    return ModernizationPlanner(docker_available=True).plan(
        src, application_id="bl033", entrypoint=entrypoint,
    )


def _pipeline(tmp_path: Path, files: dict[str, str], entrypoint: str):
    src = _write(tmp_path, files)
    return UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(src),
            output_dir=str(tmp_path / "out"),
            application_id="bl033",
            entrypoint=entrypoint,
            docker_available=True,
        )
    ).execute()


PERFECT_RUNTIME = RuntimeLaneEvidence(
    verdict_state="VERIFIED",
    executed_check_count=4,
    evidence_complete=True,
    evidence_integrity_valid=True,
)


# ---------------------------------------------------------------------------
# Acceptance 1: unresolvable copybook components are never SUPPORTED
# ---------------------------------------------------------------------------


class TestUnresolvableComponentsNeverSupported:
    def test_missing_copybook_component_is_not_supported(self, tmp_path):
        _, app, report = _discovery_and_capability(
            tmp_path, {"M5.cob": _main("M5", MISSING_STMT)},
        )
        refs = [cb for u in app.programs for cb in u.copybooks]
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("MISSING-REC", "UNRESOLVED")
        ]
        comp = _copybook_component(report, "MISSING-REC")
        assert comp.level is CapabilityLevel.UNSUPPORTED
        # Reason names the copybook and its resolution status (§BL-033).
        assert "MISSING-REC" in comp.reason
        assert "UNRESOLVED" in comp.reason
        assert comp.details.get("resolution") == "UNRESOLVED"

    def test_ambiguous_copybook_component_is_not_supported(self, tmp_path):
        _, app, report = _discovery_and_capability(tmp_path, {
            "M6.cob": _main("M6", AMBIGUOUS_STMT),
            "a/DUP-REC.cpy": "       01  WS-DUP PIC X(4).\n",
            "b/DUP-REC.cpy": "       01  WS-DUP PIC X(4).\n",
        })
        refs = [cb for u in app.programs for cb in u.copybooks]
        assert [(r.copybook_name, r.resolution) for r in refs] == [
            ("DUP-REC", "AMBIGUOUS")
        ]
        comp = _copybook_component(report, "DUP-REC")
        assert comp.level is CapabilityLevel.UNSUPPORTED
        assert "DUP-REC" in comp.reason
        assert "AMBIGUOUS" in comp.reason
        assert comp.details.get("resolution") == "AMBIGUOUS"

    def test_quoted_missing_copybook_component_is_not_supported(self, tmp_path):
        _, _, report = _discovery_and_capability(
            tmp_path, {"M7.cob": _main("M7", QUOTED_STMT)},
        )
        comp = _copybook_component(report, "'P2REC'")
        assert comp.level is CapabilityLevel.UNSUPPORTED
        assert "'P2REC'" in comp.reason
        assert "UNRESOLVED" in comp.reason

    def test_mixed_resolution_copybook_component_is_not_supported(self, tmp_path):
        """Any consumer that cannot resolve the copybook disqualifies it."""
        cpy = tmp_path / "OK.cpy"
        cpy.write_text(REALREC, encoding="utf-8")
        unit_ok = CobolProgramUnit(
            program_id="P1", source_path="P1.cob",
            program=CobolProgram(
                program_id="P1",
                paragraphs=(Paragraph(name="MAIN", statements=()),),
                copybooks=("X",),
            ),
            copybooks=(CopybookReference(
                source_program="P1", copybook_name="X",
                resolution="RESOLVED", resolved_path=str(cpy),
            ),),
        )
        unit_bad = CobolProgramUnit(
            program_id="P2", source_path="P2.cob",
            program=CobolProgram(
                program_id="P2",
                paragraphs=(Paragraph(name="MAIN", statements=()),),
                copybooks=("X",),
            ),
            # Dataclass default: resolution="UNRESOLVED".
            copybooks=(CopybookReference(
                source_program="P2", copybook_name="X",
            ),),
        )
        app = CobolApplication(
            application_id="MIXED", programs=(unit_ok, unit_bad), copybooks=("X",),
        )
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        comp = _copybook_component(report, "X")
        assert comp.level is CapabilityLevel.UNSUPPORTED
        assert "X" in comp.reason
        assert "UNRESOLVED" in comp.reason


# ---------------------------------------------------------------------------
# Acceptance 2 + 3: the plan is not READY, carries MISSING_COPYBOOK, and may
# not claim "No blocking issues identified" while generation fails
# ---------------------------------------------------------------------------


class TestPlanReflectsGenerationFailure:
    def test_missing_copybook_plan_is_not_ready_and_carries_missing_copybook(
        self, tmp_path,
    ):
        src = _write(tmp_path, {"M5.cob": _main("M5", MISSING_STMT)})
        plan = _plan(src, entrypoint="M5")
        assert plan.overall_status is not ModernizationStatus.READY
        assert plan.overall_status is ModernizationStatus.BLOCKED
        summary = list(plan.blocking_summary)
        assert any("MISSING_COPYBOOK" in line for line in summary), summary
        assert not any(
            "No blocking issues identified" in line for line in summary
        ), summary
        # Serialization carries the same truth.
        assert any(
            "MISSING_COPYBOOK" in line for line in plan.to_dict()["blocking_summary"]
        )

    def test_ambiguous_copybook_plan_carries_missing_copybook(self, tmp_path):
        src = _write(tmp_path, {
            "M6.cob": _main("M6", AMBIGUOUS_STMT),
            "a/DUP-REC.cpy": "       01  WS-DUP PIC X(4).\n",
            "b/DUP-REC.cpy": "       01  WS-DUP PIC X(4).\n",
        })
        plan = _plan(src, entrypoint="M6")
        assert plan.overall_status is not ModernizationStatus.READY
        summary = list(plan.blocking_summary)
        assert any("MISSING_COPYBOOK" in line for line in summary), summary
        assert any("DUP-REC" in line for line in summary), summary

    def test_quoted_missing_copybook_plan_carries_missing_copybook(self, tmp_path):
        src = _write(tmp_path, {"M7.cob": _main("M7", QUOTED_STMT)})
        plan = _plan(src, entrypoint="M7")
        assert plan.overall_status is not ModernizationStatus.READY
        assert any(
            "MISSING_COPYBOOK" in line for line in plan.blocking_summary
        ), list(plan.blocking_summary)

    def test_copybook_plan_entry_cannot_proceed(self, tmp_path):
        src = _write(tmp_path, {"M5.cob": _main("M5", MISSING_STMT)})
        plan = _plan(src, entrypoint="M5")
        assert len(plan.copybook_relationships) == 1
        cb = plan.copybook_relationships[0]
        assert cb.copybook_name == "MISSING-REC"
        assert cb.capability_level is CapabilityLevel.UNSUPPORTED
        assert cb.may_proceed is False
        assert BlockingReason.MISSING_COPYBOOK in cb.blocking_reasons
        assert cb.transformation_strategy is TransformationStrategy.SKIP


# ---------------------------------------------------------------------------
# Generation stays fail-closed (unchanged negative contract) and the consuming
# program keeps its own verdict
# ---------------------------------------------------------------------------


class TestGenerationContractUnchanged:
    def test_missing_copybook_generation_still_fails_closed(self, tmp_path):
        report = _pipeline(
            tmp_path, {"M5.cob": _main("M5", MISSING_STMT)}, "M5",
        )
        assert report.generation_success is False
        assert any(
            "Missing COPY target" in e for e in report.generation_errors
        ), report.generation_errors

    def test_missing_copybook_program_verdict_is_unchanged(self, tmp_path):
        _, _, report = _discovery_and_capability(
            tmp_path, {"M5.cob": _main("M5", MISSING_STMT)},
        )
        prog = _program_component(report, "M5")
        assert prog.level is CapabilityLevel.SUPPORTED

    def test_missing_copybook_ledger_entry_is_blocked_even_with_perfect_runtime(
        self, tmp_path,
    ):
        report = _pipeline(
            tmp_path, {"M5.cob": _main("M5", MISSING_STMT)}, "M5",
        )
        proof = integrated_proof_from_pipelines(
            workload_id="bl033", report=report, runtime=PERFECT_RUNTIME,
        )
        assert proof.central_status is CentralStatus.NOT_VERIFIED
        entries = [
            e for e in proof.dependency_ledger
            if e.kind is DependencyKind.COPYBOOK
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry.visible is True
        assert entry.required is True
        assert entry.capability_level is CapabilityLevel.UNSUPPORTED
        assert entry.proof_state is ProofState.BLOCKED

    def test_transformation_plan_generator_skips_unresolved_copybook(self, tmp_path):
        _, app, report = _discovery_and_capability(
            tmp_path, {"M5.cob": _main("M5", MISSING_STMT)},
        )
        plan = TransformationPlanGenerator().generate(app, report)
        cb_plans = [
            c for c in plan.components if c.component_type == "COPYBOOK"
        ]
        assert len(cb_plans) == 1
        assert cb_plans[0].action is TransformationAction.SKIP


# ---------------------------------------------------------------------------
# Acceptance 4: resolved copybooks keep their current verdicts
# ---------------------------------------------------------------------------


class TestResolvedCopybooksUnchanged:
    def test_resolved_copybook_keeps_supported_verdict(self, tmp_path):
        _, _, report = _discovery_and_capability(tmp_path, {
            "M8.cob": _main("M8", RESOLVED_STMT),
            "REALREC.cpy": REALREC,
        })
        comp = _copybook_component(report, "REALREC")
        assert comp.level is CapabilityLevel.SUPPORTED
        assert comp.details.get("resolution") == "RESOLVED"

    def test_resolved_copybook_plan_stays_ready_and_may_proceed(self, tmp_path):
        src = _write(tmp_path, {
            "M8.cob": _main("M8", RESOLVED_STMT),
            "REALREC.cpy": REALREC,
        })
        plan = _plan(src, entrypoint="M8")
        assert plan.overall_status is ModernizationStatus.READY
        cb = plan.copybook_relationships[0]
        assert cb.capability_level is CapabilityLevel.SUPPORTED
        assert cb.may_proceed is True
        assert cb.blocking_reasons == ()

    def test_resolved_copybook_generation_succeeds(self, tmp_path):
        report = _pipeline(
            tmp_path,
            {"M8.cob": _main("M8", RESOLVED_STMT), "REALREC.cpy": REALREC},
            "M8",
        )
        assert report.generation_success is True, report.generation_errors
