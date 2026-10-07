"""Integrated application proof: dependency ledger + central status gate.

Phase D TASK 4 joins the two production pipelines into one auditable object:

    UniversalModernizationPipeline   (phases 1-5: discovery, capability,
                                      plan, transform, assemble)
            +
    VerticalSlicePipeline            (phases 6-11: oracle, build, execute,
                                      compare, evidence, verdict)
            +
    JCL / DB2 / CICS lanes           (parsed and classified, no runtime)

Every dependency the application declares is recorded once, made *visible*,
*classified* with the capability vocabulary, and then given a proof state.
The central application status is a pure function of that ledger plus the
runtime lane evidence.

The gate only ever downgrades:

    central VERIFIED  <=  runtime verdict is VERIFIED
                      AND evidence manifest is complete
                      AND evidence integrity validated
                      AND every required dependency is PROVEN

JCL, DB2 and CICS have no runtime lane in this repository (see
``docs/CAPABILITY_MATRIX.md``), so they can never reach PROVEN.  A workload
that declares them therefore resolves to NOT VERIFIED at the application
level even when the COBOL to Java runtime lane itself is VERIFIED — which is
the intended, evidence-backed answer for ``fixtures/workload-integrated``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.modernization.capability_analyzer import CapabilityLevel
from engine.modernization.pipeline import ModernizationReport

__all__ = [
    "CentralStatus",
    "DependencyKind",
    "DependencyLedgerEntry",
    "IntegratedProofResult",
    "ProofState",
    "RuntimeLaneEvidence",
    "build_dependency_ledger",
    "evaluate_central_status",
    "integrated_proof_from_pipelines",
    "jcl_ledger_entry",
    "runtime_evidence_from_result",
]


class ProofState(str, Enum):
    """How far a declared dependency has actually been proven."""

    PROVEN = "PROVEN"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNPROVEN = "UNPROVEN"


class DependencyKind(str, Enum):
    """Kinds of dependency that can appear in the ledger."""

    PROGRAM = "PROGRAM"
    COPYBOOK = "COPYBOOK"
    CALL = "CALL"
    FILE = "FILE"
    JCL = "JCL"
    DB2 = "DB2"
    CICS = "CICS"
    PARAMETER = "PARAMETER"


class CentralStatus(str, Enum):
    """Application-level status for the whole integrated workload."""

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"


#: Dependency kinds whose proof requires the COBOL <-> Java runtime lane.
RUNTIME_PROVEN_KINDS = frozenset({
    DependencyKind.PROGRAM,
    DependencyKind.COPYBOOK,
    DependencyKind.CALL,
    DependencyKind.FILE,
    DependencyKind.PARAMETER,
})

#: Dependency kinds with no runtime lane in this repository.  They can be
#: parsed and classified, never proven by execution.
NON_RUNTIME_KINDS = frozenset({
    DependencyKind.JCL,
    DependencyKind.DB2,
    DependencyKind.CICS,
})


@dataclass(frozen=True)
class DependencyLedgerEntry:
    """One declared dependency: visible -> classified -> proven/blocked."""

    dependency_id: str
    kind: DependencyKind
    visible: bool
    capability_level: CapabilityLevel
    proof_state: ProofState
    required: bool
    reason: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "dependency_id": self.dependency_id,
            "kind": self.kind.value,
            "visible": self.visible,
            "capability_level": self.capability_level.value,
            "proof_state": self.proof_state.value,
            "required": self.required,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeLaneEvidence:
    """The slice of VerticalSlicePipeline evidence the gate consumes."""

    verdict_state: str = "NOT_RUN"
    executed_check_count: int = 0
    evidence_complete: bool = False
    evidence_integrity_valid: bool = False
    oracle_exit_code: int | None = None
    candidate_exit_code: int | None = None
    artifact_results: tuple[tuple[str, str], ...] = ()

    @property
    def verdict_is_verified(self) -> bool:
        return self.verdict_state == "VERIFIED"


@dataclass(frozen=True)
class IntegratedProofResult:
    """Auditable join of modernization report + runtime lane + ledger."""

    workload_id: str
    application_id: str
    dependency_ledger: tuple[DependencyLedgerEntry, ...]
    runtime: RuntimeLaneEvidence
    jcl_status: str
    central_status: CentralStatus
    blocking_reasons: tuple[str, ...] = ()
    generation_success: bool = False
    overall_capability: str = ""

    @property
    def required_dependencies(self) -> tuple[DependencyLedgerEntry, ...]:
        return tuple(e for e in self.dependency_ledger if e.required)

    @property
    def unproven_dependencies(self) -> tuple[DependencyLedgerEntry, ...]:
        return tuple(
            e for e in self.required_dependencies
            if e.proof_state is not ProofState.PROVEN
        )

    @property
    def runtime_verdict_is_verified(self) -> bool:
        return self.runtime.verdict_is_verified

    def to_dict(self) -> dict[str, object]:
        return {
            "workload_id": self.workload_id,
            "application_id": self.application_id,
            "central_status": self.central_status.value,
            "blocking_reasons": list(self.blocking_reasons),
            "generation_success": self.generation_success,
            "overall_capability": self.overall_capability,
            "jcl_status": self.jcl_status,
            "runtime": {
                "verdict_state": self.runtime.verdict_state,
                "executed_check_count": self.runtime.executed_check_count,
                "evidence_complete": self.runtime.evidence_complete,
                "evidence_integrity_valid": self.runtime.evidence_integrity_valid,
                "oracle_exit_code": self.runtime.oracle_exit_code,
                "candidate_exit_code": self.runtime.candidate_exit_code,
                "artifact_results": [list(a) for a in self.runtime.artifact_results],
            },
            "dependency_ledger": [e.to_dict() for e in self.dependency_ledger],
        }


def _proof_state_for(
    kind: DependencyKind,
    capability_level: CapabilityLevel,
    runtime: RuntimeLaneEvidence,
) -> tuple[ProofState, str]:
    """Classify proof state for one dependency.

    Fail-closed ordering: capability first (an unsupported dependency can
    never be proven), then runtime evidence.
    """
    if capability_level in (CapabilityLevel.UNSUPPORTED, CapabilityLevel.UNAVAILABLE):
        return ProofState.BLOCKED, (
            f"{kind.value} capability is {capability_level.value}; "
            "transformation is blocked"
        )
    if capability_level in (CapabilityLevel.PARTIAL, CapabilityLevel.UNKNOWN):
        return ProofState.PARTIAL, (
            f"{kind.value} capability is {capability_level.value}; "
            "only partial evidence exists"
        )

    if kind in NON_RUNTIME_KINDS:
        return ProofState.PARTIAL, (
            f"{kind.value} has no runtime lane in this repository; the "
            "construct is parsed and classified but never executed, so it "
            "cannot be claimed proven"
        )

    if not runtime.verdict_is_verified:
        if runtime.verdict_state == "NOT_RUN":
            return ProofState.UNPROVEN, (
                f"{kind.value} capability is SUPPORTED but the runtime lane "
                "was not executed"
            )
        return ProofState.PARTIAL, (
            f"{kind.value} capability is SUPPORTED but the runtime verdict "
            f"is {runtime.verdict_state}"
        )

    if not (runtime.evidence_complete and runtime.evidence_integrity_valid):
        return ProofState.PARTIAL, (
            f"{kind.value} ran under a VERIFIED verdict but the evidence "
            "manifest is incomplete or failed integrity validation"
        )

    return ProofState.PROVEN, (
        f"{kind.value} capability is SUPPORTED and behaviour was proven by "
        "the COBOL/Java runtime lane"
    )


def jcl_ledger_entry(jcl_status: str) -> DependencyLedgerEntry:
    """Ledger entry for the JCL lane.

    JCL modernization success only reaches PARTIAL: the job stream is parsed
    and classified, but this repository has no JCL runtime lane, so a FULL
    status can never be PROVEN.  Anything short of FULL is BLOCKED.
    """
    full = jcl_status == "FULL"
    return DependencyLedgerEntry(
        dependency_id=f"JCL:{jcl_status}",
        kind=DependencyKind.JCL,
        visible=True,
        capability_level=CapabilityLevel.PARTIAL if full else CapabilityLevel.UNSUPPORTED,
        proof_state=ProofState.PARTIAL if full else ProofState.BLOCKED,
        required=True,
        reason=(
            "JCL has no runtime lane in this repository; the job "
            "stream is parsed and classified but never executed"
            if full
            else f"JCL modernization status is {jcl_status}"
        ),
    )


def build_dependency_ledger(
    report: ModernizationReport,
    runtime: RuntimeLaneEvidence,
    *,
    extra_dependencies: tuple[DependencyLedgerEntry, ...] = (),
    jcl_status: str = "NOT_PRESENT",
) -> tuple[DependencyLedgerEntry, ...]:
    """Derive one ledger entry per declared dependency in the report.

    Capability components are the *visible + classified* half of the ledger;
    ``extra_dependencies`` carries lanes the modernization report does not
    model (JCL/DB2/CICS), pre-classified by their own analyzers.
    """
    entries: list[DependencyLedgerEntry] = []
    seen: set[str] = set()

    capability_report = report.capability_report
    if capability_report is not None:
        for component in capability_report.components:
            kind = _kind_for(component.component_type)
            if kind is None:
                continue
            dependency_id = (
                component.component_id
                if component.component_type == "PROGRAM"
                else f"{component.component_type}:{component.component_id}"
            )
            if dependency_id in seen:
                continue
            seen.add(dependency_id)
            proof_state, reason = _proof_state_for(
                kind, component.level, runtime,
            )
            entries.append(DependencyLedgerEntry(
                dependency_id=dependency_id,
                kind=kind,
                visible=True,
                capability_level=component.level,
                proof_state=proof_state,
                required=True,
                reason=reason,
            ))

    for entry in extra_dependencies:
        if entry.dependency_id in seen:
            continue
        seen.add(entry.dependency_id)
        entries.append(entry)

    if jcl_status not in ("", "NOT_PRESENT"):
        entry = jcl_ledger_entry(jcl_status)
        if entry.dependency_id not in seen:
            seen.add(entry.dependency_id)
            entries.append(entry)

    return tuple(entries)


def evaluate_central_status(
    ledger: tuple[DependencyLedgerEntry, ...],
    runtime: RuntimeLaneEvidence,
    *,
    generation_success: bool = True,
) -> tuple[CentralStatus, tuple[str, ...]]:
    """Pure gate.  Returns the central status and its blocking reasons.

    The gate can only downgrade.  VERIFIED requires all four conditions:
    runtime VERIFIED, complete evidence, validated integrity, and every
    required dependency PROVEN.
    """
    reasons: list[str] = []

    if not generation_success:
        reasons.append("transformation did not produce a candidate")

    if not runtime.verdict_is_verified:
        reasons.append(f"runtime verdict is {runtime.verdict_state}")
    else:
        if not runtime.evidence_complete:
            reasons.append("runtime evidence manifest is incomplete")
        if not runtime.evidence_integrity_valid:
            reasons.append("runtime evidence failed integrity validation")

    for entry in ledger:
        if entry.required and entry.proof_state is not ProofState.PROVEN:
            reasons.append(
                f"{entry.dependency_id}: {entry.proof_state.value} "
                f"({entry.reason})"
            )

    status = CentralStatus.VERIFIED if not reasons else CentralStatus.NOT_VERIFIED
    return status, tuple(reasons)


def integrated_proof_from_pipelines(
    *,
    workload_id: str,
    report: ModernizationReport,
    runtime: RuntimeLaneEvidence,
    jcl_status: str = "NOT_PRESENT",
    extra_dependencies: tuple[DependencyLedgerEntry, ...] = (),
) -> IntegratedProofResult:
    """Join the modernization report, runtime evidence and JCL lane."""
    ledger = build_dependency_ledger(
        report,
        runtime,
        extra_dependencies=extra_dependencies,
        jcl_status=jcl_status,
    )
    central_status, reasons = evaluate_central_status(
        ledger,
        runtime,
        generation_success=report.generation_success,
    )
    return IntegratedProofResult(
        workload_id=workload_id,
        application_id=report.application_id,
        dependency_ledger=ledger,
        runtime=runtime,
        jcl_status=jcl_status,
        central_status=central_status,
        blocking_reasons=reasons,
        generation_success=report.generation_success,
        overall_capability=report.overall_capability,
    )


def _kind_for(component_type: str) -> DependencyKind | None:
    try:
        return DependencyKind(component_type)
    except ValueError:
        return None


def runtime_evidence_from_result(result) -> RuntimeLaneEvidence:
    """Build the gate's runtime evidence from a ``PipelineResult``.

    Evidence completeness and integrity are re-checked here rather than
    trusted from the verdict, so a VERIFIED verdict that somehow lost its
    manifest can never open the central gate.
    """
    from engine.evidence.integrity import (
        EvidenceIntegrityValidator,
        ValidatedEvidenceManifest,
    )

    manifest = getattr(result, "evidence_manifest", None)
    complete = bool(manifest is not None and manifest.is_complete())
    valid = False
    if manifest is not None:
        try:
            outcome = EvidenceIntegrityValidator().validate(manifest)
        except Exception:
            outcome = None
        valid = isinstance(outcome, ValidatedEvidenceManifest)

    verdict = getattr(result, "verdict", None)
    return RuntimeLaneEvidence(
        verdict_state=getattr(verdict, "state", None).value
        if getattr(verdict, "state", None) is not None
        else "NOT_RUN",
        executed_check_count=int(getattr(verdict, "executed_check_count", 0) or 0),
        evidence_complete=complete,
        evidence_integrity_valid=valid,
        oracle_exit_code=getattr(result, "oracle_exit_code", None),
        candidate_exit_code=getattr(result, "candidate_exit_code", None),
        artifact_results=tuple(
            (c.artifact_type, c.result)
            for c in getattr(result, "comparison_evidence", ()) or ()
        ),
    )
