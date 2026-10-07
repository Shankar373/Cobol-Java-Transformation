"""CALL linkage arity mismatch hardening (Phase-D D2 follow-up).

Deterministic capability diagnostics for statically resolved CALLs whose
caller USING argument count disagrees with the callee's declared LINKAGE
SECTION top-level items. Must never silently reach SUPPORTED/VERIFIED.
"""

from __future__ import annotations

from pathlib import Path

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.modernization_planner import ModernizationPlanner
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.semantic_capability import CapabilityLevel


def _write(tmp: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (tmp / name).write_text(text)


HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. {pid}.\n"
)

MATCHED_CALLER = HEADER + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC 9(4) VALUE 1.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'CALLEE' USING WS-A.\n"
    "           STOP RUN.\n"
)

TOO_MANY_CALLER = HEADER + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC 9(4) VALUE 1.\n"
    "       01 WS-B PIC 9(4) VALUE 2.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'CALLEE' USING WS-A WS-B.\n"
    "           STOP RUN.\n"
)

CALLEE_ONE = HEADER + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-MARK PIC X VALUE 'M'.\n"
    "       LINKAGE SECTION.\n"
    "       01 LS-A PIC 9(4).\n"
    "       PROCEDURE DIVISION USING LS-A.\n"
    "           EXIT PROGRAM.\n"
)

CALLEE_TWO = HEADER + (
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-MARK PIC X VALUE 'M'.\n"
    "       LINKAGE SECTION.\n"
    "       01 LS-A PIC 9(4).\n"
    "       01 LS-B PIC 9(4).\n"
    "       PROCEDURE DIVISION USING LS-A LS-B.\n"
    "           EXIT PROGRAM.\n"
)

CALLEE_NO_LINKAGE = HEADER + (
    "       PROCEDURE DIVISION.\n"
    "           EXIT PROGRAM.\n"
)


def _call_components(app):
    report = CapabilityAnalyzer(docker_available=True).analyze(app)
    return [c for c in report.components if c.component_type == "CALL"]


class TestLinkageArity:
    def test_matching_linkage_remains_supported(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": MATCHED_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_ONE.format(pid="CALLEE"),
        })
        app = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        calls = _call_components(app)
        assert len(calls) == 1
        assert calls[0].level == CapabilityLevel.SUPPORTED
        assert "arity mismatch" not in calls[0].reason

    def test_caller_too_many_arguments_is_unsupported(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": TOO_MANY_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_ONE.format(pid="CALLEE"),
        })
        app = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        calls = _call_components(app)
        assert any(
            c.level == CapabilityLevel.UNSUPPORTED
            and "arity mismatch" in c.reason
            for c in calls
        ), calls

    def test_caller_too_few_arguments_is_unsupported(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": MATCHED_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_TWO.format(pid="CALLEE"),
        })
        app = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        calls = _call_components(app)
        assert any(
            c.level == CapabilityLevel.UNSUPPORTED
            and "arity mismatch" in c.reason
            for c in calls
        ), calls

    def test_no_linkage_with_arguments_is_unsupported(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": MATCHED_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_NO_LINKAGE.format(pid="CALLEE"),
        })
        app = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        calls = _call_components(app)
        assert any(
            c.level == CapabilityLevel.UNSUPPORTED
            and "arity mismatch" in c.reason
            for c in calls
        ), calls

    def test_mismatch_cannot_reach_supported_or_verified(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": TOO_MANY_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_ONE.format(pid="CALLEE"),
        })
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level == CapabilityLevel.UNSUPPORTED
        assert cr.may_proceed is False

    def test_matching_linkage_does_not_block_plan(self, tmp_path):
        _write(tmp_path, {
            "MAIN.cob": MATCHED_CALLER.format(pid="CALLER"),
            "CALLEE.cob": CALLEE_ONE.format(pid="CALLEE"),
        })
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level == CapabilityLevel.SUPPORTED

    def test_unresolved_target_keeps_existing_behavior(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(
            HEADER.format(pid="LONELY") + (
                "       PROCEDURE DIVISION.\n"
                "           CALL 'NOSUCH'.\n"
                "           STOP RUN.\n"
            )
        )
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level == CapabilityLevel.PARTIAL
        assert "arity mismatch" not in (cr.capability_reason or "")

    def test_dynamic_call_keeps_existing_behavior(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(
            HEADER.format(pid="DYN") + (
                "       DATA DIVISION.\n"
                "       WORKING-STORAGE SECTION.\n"
                "       01 WS-PROG PIC X(8) VALUE 'CALCEE'.\n"
                "       PROCEDURE DIVISION.\n"
                "           CALL WS-PROG.\n"
                "           STOP RUN.\n"
            )
        )
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level == CapabilityLevel.UNSUPPORTED
        assert "arity mismatch" not in (cr.capability_reason or "")

    def test_cyclic_call_keeps_existing_behavior(self, tmp_path):
        (tmp_path / "A.cob").write_text(
            HEADER.format(pid="CYCA") + (
                "       PROCEDURE DIVISION.\n           CALL 'CYCB'.\n           STOP RUN.\n"
            )
        )
        (tmp_path / "B.cob").write_text(
            HEADER.format(pid="CYCB") + (
                "       PROCEDURE DIVISION.\n           CALL 'CYCA'.\n           STOP RUN.\n"
            )
        )
        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        assert any("Cyclic" in r or "cyclic" in r for r in plan.blocking_summary)

    def test_valid_call_chain_fixture_has_no_mismatch(self):
        app = ApplicationDiscovery().discover(
            "fixtures/workload-call-chain/cobol", application_id="t"
        )
        calls = _call_components(app)
        assert len(calls) == 2
        for c in calls:
            assert c.level == CapabilityLevel.SUPPORTED
            assert "arity mismatch" not in c.reason

    def test_copybook_fixture_has_no_mismatch(self):
        app = ApplicationDiscovery().discover(
            "fixtures/workload-copybook/cobol", application_id="t"
        )
        calls = _call_components(app)
        assert calls == []
