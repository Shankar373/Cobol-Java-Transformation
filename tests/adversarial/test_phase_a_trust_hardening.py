"""Phase A — trust, identity and evidence integrity hardening tests.

Proves each new fail-closed control actually fires:

- the construction-time seal detects post-construction mutation
  (including domain-valid tampering that every cross-check accepts)
- source-tree mutation during execution is a violation
- oracle image identity recorded in evidence must match the manifest
- BUILD evidence can never satisfy the EXECUTE requirement, and the
  untrusted derivation clamps a would-be VERIFIED to ERROR
- unknown comparison results fail validation AND derivation
- comparator declarations must bind to the registered comparator
- execution/comparison evidence must carry the manifest workload id
- derive_verdict_untrusted can never return VERIFIED
- pipeline: compile failure is recorded as phase BUILD, never verified
- pipeline: comparator declaration mismatch fails closed
- pipeline: a declared input missing on disk fails closed
- oracle adapter (Docker): declared pin mismatch refuses to execute;
  auto-pin records the resolved immutable identity
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.domain.identities import (
    AdapterStatus,
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    IntegrityViolation,
    ValidatedEvidenceManifest,
    ViolationType,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import derive_verdict, derive_verdict_untrusted

validator = EvidenceIntegrityValidator()


def _h(s: str) -> ContentHash:
    return ContentHash.from_string(s)


# ---------------------------------------------------------------------------
# Manifest builders (self-contained; mirror the trust-boundary fixtures)
# ---------------------------------------------------------------------------

def _exec(
    run_id: RunId,
    exec_id: str,
    runtime_id: str = "oracle-gnucobol-3.1.2",
    status: str = "normal",
) -> ExecutionEvidence:
    return ExecutionEvidence(
        execution_id=ExecutionId(value=exec_id),
        run_id=run_id,
        runtime_id=runtime_id,
        command="cobc -x /workspace/prog.cbl",
        working_directory="/workspace",
        environment_variables={},
        start_time="2026-09-15T00:00:00Z",
        end_time="2026-09-15T00:00:01Z",
        exit_code=0 if status == "normal" else 1,
        stdout_hash=_h(f"stdout-{exec_id}"),
        stderr_hash=_h(f"stderr-{exec_id}"),
        generated_files={},
        source_tree_hash_before=_h("source-tree"),
        source_tree_hash_after=_h("source-tree"),
        termination_status=status,
        timeout_applied=False,
    )


def _art_ev(
    artifact_id: str,
    artifact_type: str,
    producer_role: str,
    content_hash_str: str,
    exec_id: str,
    size: int = 10,
) -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact=ArtifactIdentity(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            logical_name=f"{artifact_type.lower()}",
            producer_role=producer_role,
            content_hash=_h(content_hash_str),
            size_bytes=size,
        ),
        execution_id=ExecutionId(value=exec_id),
        capture_time="2026-09-15T00:00:01Z",
        content_hash=_h(content_hash_str),
        size_bytes=size,
    )


def _comp(
    run_id: RunId,
    result: str = "MATCH",
    oracle_id: str = "art-o",
    candidate_id: str = "art-c",
    artifact_type: str = "STDOUT",
) -> ComparisonEvidence:
    return ComparisonEvidence(
        comparison_id=f"comp-{oracle_id}-{candidate_id}",
        run_id=run_id,
        comparator_id=f"{artifact_type}_COMPARATOR",
        comparator_version="1.0.0",
        oracle_artifact_id=oracle_id,
        candidate_artifact_id=candidate_id,
        artifact_type=artifact_type,
        result=result,
        normalization_applied=("crlf_to_lf",) if artifact_type in ("STDOUT", "STDERR", "TEXT_FILE") else (),
        differences=(),
        field_level_results=(),
        content_hash=_h(f"comp-{result}-{oracle_id}-{candidate_id}"),
    )


def _clean_manifest(
    run_id: RunId | None = None,
    oracle_exec: ExecutionEvidence | None = None,
    candidate_exec: ExecutionEvidence | None = None,
    comparisons: tuple[ComparisonEvidence, ...] | None = None,
) -> EvidenceManifest:
    """A manifest that validates cleanly and naturally derives VERIFIED.

    Fields are passed at construction so the seal covers them (in-place
    mutation after construction is precisely what the seal must catch).
    """
    if run_id is None:
        run_id = RunId(value="run-phase-a-clean")
    if oracle_exec is None:
        oracle_exec = _exec(run_id, "oracle-exec-1")
    if candidate_exec is None:
        candidate_exec = _exec(run_id, "candidate-exec-1", runtime_id="candidate-java")
    if comparisons is None:
        comparisons = (_comp(run_id),)
    return EvidenceManifest(
        manifest_version="1.0",
        run_id=run_id,
        workload_id=WorkloadId(value="test-workload"),
        source_identity=SourceIdentity(
            source_id="cobol-source",
            source_hash=_h("source-hash"),
            file_count=1,
            total_size_bytes=100,
        ),
        candidate_identity=CandidateIdentity(
            candidate_id="java-candidate",
            candidate_hash=_h("candidate-hash"),
            source_hash=_h("source-hash"),
            file_count=1,
            total_size_bytes=100,
        ),
        oracle_identity=OracleIdentity(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2.0",
        ),
        environment_identities=(),
        controlled_input=InputIdentity(
            input_id="input-1",
            stdin_hash=_h("input-data"),
        ),
        execution_evidence=(oracle_exec, candidate_exec),
        artifact_evidence=(
            _art_ev("art-o", "STDOUT", "ORACLE", "output-data", "oracle-exec-1"),
            _art_ev("art-c", "STDOUT", "CANDIDATE", "output-data", "candidate-exec-1"),
        ),
        comparison_evidence=comparisons,
    )


def _types(result: object) -> set[ViolationType]:
    assert isinstance(result, list)
    return {v.violation_type for v in result}


# ===========================================================================
# Sanity baseline
# ===========================================================================

class TestCleanManifestBaseline:
    def test_clean_manifest_validates_and_naturally_verifies(self) -> None:
        manifest = _clean_manifest()
        result = validator.validate(manifest)
        assert isinstance(result, ValidatedEvidenceManifest)
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.VERIFIED


# ===========================================================================
# Construction-time seal
# ===========================================================================

class TestSealTampering:
    def test_in_place_comparison_flip_detected_by_seal(self) -> None:
        """A domain-valid flip (MATCH -> MISMATCH) that every cross-check
        accepts must still be caught by the construction-time seal."""
        manifest = _clean_manifest()
        assert isinstance(validator.validate(manifest), ValidatedEvidenceManifest)

        manifest.comparison_evidence = (
            replace(manifest.comparison_evidence[0], result="MISMATCH"),
        )

        result = validator.validate(manifest)
        assert ViolationType.MANIFEST_HASH_MISMATCH in _types(result)

    def test_cleared_seal_detected(self) -> None:
        manifest = _clean_manifest()
        manifest.sealed_hash = None

        result = validator.validate(manifest)
        assert ViolationType.MANIFEST_HASH_MISMATCH in _types(result)

    def test_input_identity_mutation_detected_by_seal(self) -> None:
        """Changing the controlled-input identity after construction is
        caught by the seal (inputs are graph-covered fields)."""
        manifest = _clean_manifest()
        manifest.controlled_input = InputIdentity(
            input_id="input-1",
            stdin_hash=_h("tampered-input-data"),
        )

        result = validator.validate(manifest)
        assert ViolationType.MANIFEST_HASH_MISMATCH in _types(result)


# ===========================================================================
# Source mutation
# ===========================================================================

class TestSourceMutation:
    def test_source_tree_mutation_detected(self) -> None:
        manifest = _clean_manifest()
        execs = list(manifest.execution_evidence)
        execs[0] = replace(
            execs[0], source_tree_hash_after=_h("rewritten-source-tree")
        )
        manifest.execution_evidence = tuple(execs)

        result = validator.validate(manifest)
        assert ViolationType.SOURCE_MUTATION in _types(result)


# ===========================================================================
# Oracle image identity binding
# ===========================================================================

class TestOracleImageBinding:
    def test_evidence_digest_must_match_manifest_identity(self) -> None:
        manifest = _clean_manifest()
        execs = list(manifest.execution_evidence)
        execs[0] = replace(execs[0], image_digest="sha256:" + "b" * 64)
        manifest.execution_evidence = tuple(execs)

        result = validator.validate(manifest)
        assert ViolationType.IMAGE_IDENTITY_MISMATCH in _types(result)

    def test_matching_evidence_digest_accepted(self) -> None:
        run_id = RunId(value="run-phase-a-digest-match")
        manifest = _clean_manifest(
            run_id=run_id,
            oracle_exec=replace(
                _exec(run_id, "oracle-exec-1"),
                image_digest="sha256:" + "a" * 64,
            ),
        )

        result = validator.validate(manifest)
        assert isinstance(result, ValidatedEvidenceManifest)


# ===========================================================================
# BUILD is never execution evidence
# ===========================================================================

class TestBuildIsNotExecution:
    def test_build_phase_fails_validation_and_clamps_verified(self) -> None:
        manifest = _clean_manifest()
        execs = list(manifest.execution_evidence)
        execs[1] = replace(execs[1], execution_phase="BUILD")
        manifest.execution_evidence = tuple(execs)

        result = validator.validate(manifest)
        assert ViolationType.MISSING_REQUIRED_EVIDENCE in _types(result)
        assert any(
            "build failure" in v.description for v in result
            if v.violation_type == ViolationType.MISSING_REQUIRED_EVIDENCE
        )

        verdict = derive_verdict_untrusted(manifest, result)
        assert verdict.state == VerdictState.ERROR
        assert verdict.state != VerdictState.VERIFIED


# ===========================================================================
# Unknown comparison results
# ===========================================================================

class TestUnknownComparisonResult:
    def test_unknown_result_fails_validation(self) -> None:
        manifest = _clean_manifest()
        manifest.comparison_evidence = (
            replace(manifest.comparison_evidence[0], result="MATCH-ISH"),
        )

        result = validator.validate(manifest)
        assert ViolationType.UNKNOWN_COMPARISON_RESULT in _types(result)

    def test_unknown_result_derives_error_not_match(self) -> None:
        manifest = _clean_manifest()
        manifest.comparison_evidence = (
            replace(manifest.comparison_evidence[0], result="MATCH-ISH"),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR


# ===========================================================================
# Comparator binding
# ===========================================================================

class TestComparatorBinding:
    def test_declared_comparator_must_bind_to_registered_one(self) -> None:
        manifest = _clean_manifest()
        manifest.comparison_evidence = (
            replace(
                manifest.comparison_evidence[0],
                comparator_id="exit-status-exact",
            ),
        )

        result = validator.validate(manifest)
        assert ViolationType.COMPARATOR_BINDING_MISMATCH in _types(result)

    def test_alias_comparator_id_accepted(self) -> None:
        run_id = RunId(value="run-phase-a-alias")
        manifest = _clean_manifest(
            run_id=run_id,
            comparisons=(
                replace(_comp(run_id), comparator_id="stdout-exact"),
            ),
        )

        result = validator.validate(manifest)
        assert isinstance(result, ValidatedEvidenceManifest)


# ===========================================================================
# Workload binding
# ===========================================================================

class TestWorkloadBinding:
    def test_foreign_workload_id_on_evidence_detected(self) -> None:
        manifest = _clean_manifest()
        foreign = WorkloadId(value="attacker-workload")
        manifest.execution_evidence = tuple(
            replace(e, workload_id=foreign)
            for e in manifest.execution_evidence
        )
        manifest.comparison_evidence = tuple(
            replace(c, workload_id=foreign)
            for c in manifest.comparison_evidence
        )

        result = validator.validate(manifest)
        assert ViolationType.WORKLOAD_BINDING_MISMATCH in _types(result)

    def test_manifest_workload_id_binding_accepted(self) -> None:
        run_id = RunId(value="run-phase-a-workload-ok")
        wl = WorkloadId(value="test-workload")
        manifest = _clean_manifest(
            run_id=run_id,
            oracle_exec=replace(_exec(run_id, "oracle-exec-1"), workload_id=wl),
            candidate_exec=replace(
                _exec(run_id, "candidate-exec-1", runtime_id="candidate-java"),
                workload_id=wl,
            ),
            comparisons=(replace(_comp(run_id), workload_id=wl),),
        )

        result = validator.validate(manifest)
        assert isinstance(result, ValidatedEvidenceManifest)


# ===========================================================================
# Untrusted derivation can never certify
# ===========================================================================

class TestUntrustedDerivationClamp:
    def test_untrusted_derivation_never_returns_verified(self) -> None:
        manifest = _clean_manifest()
        assert derive_verdict(manifest).state == VerdictState.VERIFIED

        violation = IntegrityViolation(
            violation_type=ViolationType.MANIFEST_HASH_MISMATCH,
            description="fabricated trust boundary violation",
            field_path="sealed_hash",
            expected="sha256 seal of the evidence graph",
            actual="tampered",
        )

        verdict = derive_verdict_untrusted(manifest, [violation])
        assert verdict.state == VerdictState.ERROR
        assert verdict.executed_check_count == 0
        assert verdict.supported_scope_statement == (
            "Evidence trust boundary violation"
        )
        assert verdict.differences == ("fabricated trust boundary violation",)


# ===========================================================================
# Pipeline-level fail-closed behaviour (Docker-free, fake adapters)
# ===========================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeOracle:
    def get_identity(self):
        from engine.domain.identities import OracleIdentity

        return OracleIdentity(
            oracle_id="test-oracle",
            image_digest="sha256:test",
            compiler_version="test",
        )

    def execute(self, run_id, source_path, input_data=None, input_files=None):
        from engine.oracle.adapter import OracleExecutionResult

        return OracleExecutionResult(
            execution_id=ExecutionId(value=f"oracle-{run_id.value}"),
            run_id=run_id,
            oracle_id="test-oracle",
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"oracle-out",
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
        )


class _FakeCandidate:
    def __init__(self, build_ok: bool = True):
        self._build_ok = build_ok

    def compile(self, candidate_path, manifest):
        from engine.candidate.adapter import CompilationResult

        if not self._build_ok:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=("synthetic build boom",),
            )
        return CompilationResult(success=True, class_files={"A.class": b"cafebabe"})

    def execute(self, run_id, compiled_path, manifest, input_data=None, input_files=None):
        from engine.candidate.adapter import CandidateExecutionResult

        return CandidateExecutionResult(
            execution_id=ExecutionId(value=f"candidate-{run_id.value}"),
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED,
            exit_code=0,
            stdout=b"oracle-out",
            stderr=b"",
            start_time=_now(),
            end_time=_now(),
            termination_status="normal",
            timeout_applied=False,
        )


def _make_pipeline(
    tmp_path: Path,
    build_ok: bool = True,
    workload=None,
    workload_id: str = "wl-phase-a",
) -> "object":
    from engine.pipeline import PipelineConfig, VerticalSlicePipeline

    src = tmp_path / "HELLO.cob"
    src.write_text("HELLO", encoding="utf-8")
    cand = tmp_path / "cand"
    cand.mkdir()
    config = PipelineConfig(
        workload_id=workload_id,
        cobol_source_path=str(src),
        java_candidate_path=str(cand),
        java_entrypoint="Main",
        workload=workload,
        use_docker_java=True,
    )
    pipe = VerticalSlicePipeline(config, candidate_adapter=_FakeCandidate(build_ok))
    pipe._oracle_adapter = _FakeOracle()
    return pipe


class TestPipelineFailClosed:
    def test_compile_failure_recorded_as_build_never_verified(
        self, tmp_path: Path
    ) -> None:
        result = _make_pipeline(tmp_path, build_ok=False).run()

        assert result.candidate_evidence.execution_phase == "BUILD"
        assert result.candidate_evidence.execution_id.value.endswith(
            "-compile-fail"
        )
        assert result.verdict.state != VerdictState.VERIFIED

    def test_successful_run_stamps_workload_and_execute_phase(
        self, tmp_path: Path
    ) -> None:
        result = _make_pipeline(tmp_path, workload_id="wl-stamp").run()

        assert result.candidate_evidence.execution_phase == "EXECUTE"
        assert result.candidate_evidence.workload_id == WorkloadId(
            value="wl-stamp"
        )
        assert result.oracle_evidence.workload_id == WorkloadId(value="wl-stamp")
        assert (
            result.candidate_evidence.source_tree_hash_before
            == result.candidate_evidence.source_tree_hash_after
        )
        assert all(
            c.workload_id == WorkloadId(value="wl-stamp")
            for c in result.comparison_evidence
        )

    def test_comparator_declaration_mismatch_fails_closed(
        self, tmp_path: Path
    ) -> None:
        from engine.workload import WorkloadArtifact, WorkloadDefinition

        workload = WorkloadDefinition(
            workload_id="wl-comparator-binding",
            description="declared comparator must bind to registry",
            artifacts=(
                WorkloadArtifact(
                    logical_name="stdout",
                    artifact_type="STDOUT",
                    comparator_id="exit-status-exact",
                ),
            ),
        )
        pipe = _make_pipeline(tmp_path, workload=workload)

        with pytest.raises(ValueError, match="Comparator binding mismatch"):
            pipe.run()

    def test_missing_declared_input_fails_closed(self, tmp_path: Path) -> None:
        from engine.workload import (
            WorkloadArtifact,
            WorkloadDefinition,
            WorkloadInput,
        )

        workload = WorkloadDefinition(
            workload_id="wl-missing-input",
            description="declared input must exist on disk",
            artifacts=(
                WorkloadArtifact(
                    logical_name="stdout",
                    artifact_type="STDOUT",
                    comparator_id="STDOUT_COMPARATOR",
                ),
            ),
            inputs=(
                WorkloadInput(
                    logical_name="claims",
                    container_path="/workspace/input/claims.dat",
                    source_path="input/claims.dat",
                ),
            ),
        )
        pipe = _make_pipeline(tmp_path, workload=workload)

        with pytest.raises(ValueError, match="Declared input"):
            pipe.run()


# ===========================================================================
# Oracle adapter pin behaviour (requires Docker + local oracle image)
# ===========================================================================

def _docker_oracle_adapter(image_digest: str):
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    return DockerOracleAdapter(
        OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest=image_digest,
            compiler_version="3.1.2.0",
        )
    )


class TestOraclePinEnforcement:
    def test_declared_pin_mismatch_refuses_to_execute(
        self, tmp_path: Path
    ) -> None:
        # Availability must be judged on an auto-pin adapter: probe() on a
        # wrong-pin adapter intentionally reports UNAVAILABLE (the pin cannot
        # be served), which is exactly the situation under test.
        if _docker_oracle_adapter("").probe() != AdapterStatus.AVAILABLE:
            pytest.skip("docker oracle image not available")

        adapter = _docker_oracle_adapter("sha256:" + "0" * 64)
        (tmp_path / "prog.cob").write_text("       IDENTIFICATION DIVISION.\n")
        result = adapter.execute(
            run_id=RunId(value="run-pin-mismatch"),
            source_path=str(tmp_path),
        )

        assert result.termination_status == "error"
        assert b"does not match" in result.stderr
        # Nothing ran, but the identity of the image Docker WOULD have run is
        # recorded — and it is neither the wrong declared pin nor unpinned.
        assert result.image_digest is not None
        assert result.image_digest != "sha256:" + "0" * 64
        assert result.image_digest.startswith("sha256:")
        assert adapter.get_identity().image_digest == result.image_digest

    def test_auto_pin_records_resolved_identity(self, tmp_path: Path) -> None:
        adapter = _docker_oracle_adapter("")
        if adapter.probe() != AdapterStatus.AVAILABLE:
            pytest.skip("docker oracle image not available")

        (tmp_path / "prog.cob").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           DISPLAY \"OK\".\n"
            "           STOP RUN.\n"
        )
        result = adapter.execute(
            run_id=RunId(value="run-auto-pin"),
            source_path=str(tmp_path),
        )

        assert result.image_digest is not None
        assert result.image_digest.startswith("sha256:")
        assert adapter.get_identity().image_digest == result.image_digest
