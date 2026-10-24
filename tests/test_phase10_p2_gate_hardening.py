"""Phase 10 P2: central-gate and pipeline hardening (fail-open leftovers).

Red-first evidence: every test in this file fails against unmodified code.

* P2-a  ``evaluate_central_status(generation_success: bool = True)`` had a
        fail-open default — a bare call with a perfect runtime and a perfect
        ledger verified without anyone stating the transformation succeeded.
* P2-c  an unknown ``component_type`` was silently dropped from the
        dependency ledger (``_kind_for`` -> ``None`` -> ``continue``) instead
        of surfacing as a visible, blocked, required entry.
* P2-d  ``executed_check_count`` was carried on ``RuntimeLaneEvidence`` but
        never consulted by the gate: a VERIFIED verdict claiming zero
        executed checks could still open the central gate.
* P2-e  a non-enum ``verdict.state`` (plain string) crashed
        ``runtime_evidence_from_result`` with ``AttributeError`` (``.value``).
* P2-f  ``generation_success`` stayed ``True`` after an assembly failure —
        the report claimed a successful generation for a candidate project
        that was never produced.
* P2-i  the frontend ``kindOrder`` omitted ``PARAMETER``/``MQ``/``IMS``, so
        those ledger kinds never render in "Dependencies"; a source-parity
        test pins every ``DependencyKind`` to the UI list.

Engine-only (no fastapi/pydantic): safe for the dependency-free
capability-truth gate in .github/workflows/ci.yml.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from engine.modernization.capability_analyzer import (
    CapabilityLevel,
    CapabilityReport,
)
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    ProofState,
    RuntimeLaneEvidence,
    build_dependency_ledger,
    evaluate_central_status,
    runtime_evidence_from_result,
)

PERFECT_RUNTIME = RuntimeLaneEvidence(
    verdict_state="VERIFIED",
    executed_check_count=4,
    evidence_complete=True,
    evidence_integrity_valid=True,
    oracle_exit_code=0,
    candidate_exit_code=0,
)

_HELLO_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM  PIC 9(4) VALUE 42.
       PROCEDURE DIVISION.
           DISPLAY WS-NUM
           STOP RUN.
"""


def _component(component_id: str, component_type: str, level):
    return SimpleNamespace(
        component_id=component_id,
        component_type=component_type,
        level=level,
        reason="",
    )


def _report(*components, generation_success: bool = True):
    return SimpleNamespace(
        application_id="app-p2",
        generation_success=generation_success,
        overall_capability="SUPPORTED",
        capability_report=CapabilityReport(
            application_id="app-p2",
            components=tuple(components),
            overall_level=CapabilityLevel.SUPPORTED,
        ),
    )


class TestGenerationSuccessDefaultFailsClosed:
    """P2-a: the gate default must not be the fail-open value."""

    def test_bare_gate_call_without_generation_success_never_verifies(self):
        ledger = build_dependency_ledger(
            _report(_component("P1", "PROGRAM", CapabilityLevel.SUPPORTED)),
            PERFECT_RUNTIME,
        )
        status, reasons = evaluate_central_status(ledger, PERFECT_RUNTIME)
        assert status is CentralStatus.NOT_VERIFIED, reasons
        assert any("did not produce a candidate" in r for r in reasons), reasons

    def test_explicit_true_still_verifies_a_perfect_shape(self):
        ledger = build_dependency_ledger(
            _report(_component("P1", "PROGRAM", CapabilityLevel.SUPPORTED)),
            PERFECT_RUNTIME,
        )
        status, reasons = evaluate_central_status(
            ledger, PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.VERIFIED, reasons


class TestUnknownComponentTypeStaysVisible:
    """P2-c: an unclassifiable component blocks, never disappears."""

    def test_unknown_component_type_is_a_visible_blocked_entry(self):
        ledger = build_dependency_ledger(
            _report(_component("RPT1", "REPORT", CapabilityLevel.SUPPORTED)),
            PERFECT_RUNTIME,
        )
        by_id = {e.dependency_id: e for e in ledger}
        entry = by_id.get("REPORT:RPT1")
        assert entry is not None, sorted(by_id)
        assert entry.visible is True, entry
        assert entry.required is True, entry
        assert entry.kind is DependencyKind.UNKNOWN, entry
        assert entry.proof_state is ProofState.BLOCKED, entry
        assert "REPORT" in entry.reason, entry

    def test_unknown_component_type_forces_not_verified(self):
        ledger = build_dependency_ledger(
            _report(_component("RPT1", "REPORT", CapabilityLevel.SUPPORTED)),
            PERFECT_RUNTIME,
        )
        status, reasons = evaluate_central_status(
            ledger, PERFECT_RUNTIME, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED, reasons
        assert any("REPORT:RPT1" in r for r in reasons), reasons


class TestExecutedCheckCountGatesVerified:
    """P2-d: zero executed checks is incoherent evidence, not proof."""

    def test_verified_verdict_with_zero_executed_checks_never_verifies(self):
        ledger = build_dependency_ledger(
            _report(_component("P1", "PROGRAM", CapabilityLevel.SUPPORTED)),
            PERFECT_RUNTIME,
        )
        zero_checks = RuntimeLaneEvidence(
            verdict_state="VERIFIED",
            executed_check_count=0,
            evidence_complete=True,
            evidence_integrity_valid=True,
            oracle_exit_code=0,
            candidate_exit_code=0,
        )
        status, reasons = evaluate_central_status(
            ledger, zero_checks, generation_success=True
        )
        assert status is CentralStatus.NOT_VERIFIED, reasons
        assert any("executed" in r for r in reasons), reasons


class TestNonEnumVerdictStateNormalized:
    """P2-e: a plain-string verdict state must not crash evidence assembly."""

    def test_plain_string_verdict_state_does_not_crash(self):
        verdict = SimpleNamespace(
            state="VERIFIED",
            executed_check_count=3,
            evidence_manifest_hash="sha256:" + "d" * 64,
        )
        result = SimpleNamespace(
            evidence_manifest=None,
            verdict=verdict,
            oracle_exit_code=0,
            candidate_exit_code=0,
            comparison_evidence=(),
        )
        runtime = runtime_evidence_from_result(result)
        assert runtime.verdict_state == "VERIFIED"
        assert runtime.verdict_is_verified is True

    def test_missing_state_still_reads_not_run(self):
        result = SimpleNamespace(
            evidence_manifest=None,
            verdict=None,
            oracle_exit_code=None,
            candidate_exit_code=None,
            comparison_evidence=(),
        )
        runtime = runtime_evidence_from_result(result)
        assert runtime.verdict_state == "NOT_RUN"


class TestAssemblyFailureNeverClaimsGenerationSuccess:
    """P2-f: an assembly failure is a generation failure."""

    def test_assembly_exception_resets_generation_success(self, tmp_path, monkeypatch):
        import engine.modernization.pipeline as pipeline_mod
        from engine.modernization.pipeline import (
            ModernizationConfig,
            UniversalModernizationPipeline,
        )

        src = tmp_path / "src"
        src.mkdir()
        (src / "HELLO.cob").write_text(_HELLO_SOURCE, encoding="utf-8")

        class _FailingAdapter:
            def assemble(self, *args, **kwargs):
                raise RuntimeError("assembly boom")

        monkeypatch.setattr(
            pipeline_mod, "get_runtime_adapter", lambda target: _FailingAdapter()
        )
        report = UniversalModernizationPipeline(
            ModernizationConfig(
                source_dir=str(src),
                output_dir=str(tmp_path / "out"),
                application_id="asm-fail",
                entrypoint="HELLO",
                docker_available=True,
                target_runtime="plain_java",
            )
        ).execute()

        assert report.generation_success is False, (
            "P2-f: assembly failed but the report still claims generation"
            f" success (errors={report.generation_errors})"
        )
        assert any("Assembly failed" in e for e in report.generation_errors), (
            report.generation_errors
        )


class TestFrontendKindOrderParity:
    """P2-i: every ledger kind must be renderable by the UI component."""

    def test_integrated_proof_component_renders_every_dependency_kind(self):
        repo_root = Path(__file__).resolve().parent.parent
        component = (
            repo_root / "frontend" / "src" / "components" / "IntegratedProof.tsx"
        )
        assert component.exists(), component
        text = component.read_text(encoding="utf-8")
        marker = "const kindOrder = ["
        start = text.index(marker)
        end = text.index("]", start)
        kind_array = text[start:end]
        missing = [
            kind.value
            for kind in DependencyKind
            if f"'{kind.value}'" not in kind_array
        ]
        assert not missing, (
            f"DependencyKind members absent from the UI kindOrder: {missing}"
        )
