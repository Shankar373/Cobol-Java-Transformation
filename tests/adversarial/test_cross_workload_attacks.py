"""Cross-workload confusion attacks.

Tests that artifacts from one workload cannot be silently combined
with evidence from a different workload.
"""

from __future__ import annotations

from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    EvidenceManifest,
)
from engine.verdict.derivation import derive_verdict

from .conftest import (
    _hash,
    make_candidate_exec,
    make_comparison,
    make_oracle_exec,
)


class TestCrossWorkloadArtifactMixing:
    """Artifacts from different workloads in the same manifest."""

    def test_payroll_artifact_in_inventory_manifest(self):
        """Payroll artifact used in inventory workload manifest.
        The workload_id comes from the manifest, not from artifacts."""
        run_id = RunId(value="run-cross-wl-mix")

        # Artifact that came from a payroll execution
        payroll_artifact = ArtifactEvidence(
            artifact=ArtifactIdentity(
                artifact_id="art-payroll-stdout",
                artifact_type="STDOUT",
                logical_name="payroll-output",
                producer_role="ORACLE",
                content_hash=_hash("payroll-output-data"),
                size_bytes=18,
            ),
            execution_id=ExecutionId(value="oracle-exec-payroll"),
            capture_time="2026-09-15T00:00:01Z",
            content_hash=_hash("payroll-output-data"),
            size_bytes=18,
        )

        # Artifact from an inventory candidate
        inventory_artifact = ArtifactEvidence(
            artifact=ArtifactIdentity(
                artifact_id="art-inventory-cand",
                artifact_type="STDOUT",
                logical_name="inventory-output",
                producer_role="CANDIDATE",
                content_hash=_hash("inventory-output-data"),
                size_bytes=19,
            ),
            execution_id=ExecutionId(value="candidate-exec-inventory"),
            capture_time="2026-09-15T00:00:01Z",
            content_hash=_hash("inventory-output-data"),
            size_bytes=19,
        )

        comparison = make_comparison(
            run_id, result="MISMATCH", artifact_type="STDOUT",
            oracle_id="art-payroll-stdout", candidate_id="art-inventory-cand",
            differences=("STDOUT output differs",),
        )

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="inventory"),  # Inventory workload
            source_identity=SourceIdentity(
                source_id="src", source_hash=_hash("s"),
                file_count=1, total_size_bytes=10,
            ),
            candidate_identity=CandidateIdentity(
                candidate_id="cand", candidate_hash=_hash("c"),
                source_hash=_hash("s"), file_count=1, total_size_bytes=10,
            ),
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(
                input_id="inp", stdin_hash=_hash("inp"),
            ),
            execution_evidence=(
                make_oracle_exec(run_id, exec_id="oracle-exec-payroll"),
                make_candidate_exec(run_id, exec_id="candidate-exec-inventory"),
            ),
            artifact_evidence=(payroll_artifact, inventory_artifact),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        # Workload is "inventory" from the manifest
        assert verdict.workload_id.value == "inventory"
        # Comparison result determines verdict
        assert verdict.state == VerdictState.FAILED

    def test_multiple_workload_artifacts_same_type(self):
        """Multiple STDOUT artifacts from different workloads.
        All are processed; the verdict is derived from all comparisons."""
        run_id = RunId(value="run-multi-wl")

        artifacts = []
        for i, wl in enumerate(["payroll", "inventory", "claims"]):
            role = "ORACLE" if i % 2 == 0 else "CANDIDATE"
            artifacts.append(ArtifactEvidence(
                artifact=ArtifactIdentity(
                    artifact_id=f"art-{wl}-stdout",
                    artifact_type="STDOUT",
                    logical_name=f"{wl}-output",
                    producer_role=role,
                    content_hash=_hash(f"{wl}-data"),
                    size_bytes=len(f"{wl}-data"),
                ),
                execution_id=ExecutionId(value=f"exec-{wl}"),
                capture_time="2026-09-15T00:00:01Z",
                content_hash=_hash(f"{wl}-data"),
                size_bytes=len(f"{wl}-data"),
            ))

        comparison = make_comparison(run_id, result="MATCH")

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="claims"),  # Claims workload
            source_identity=SourceIdentity(
                source_id="src", source_hash=_hash("s"),
                file_count=1, total_size_bytes=10,
            ),
            candidate_identity=CandidateIdentity(
                candidate_id="cand", candidate_hash=_hash("c"),
                source_hash=_hash("s"), file_count=1, total_size_bytes=10,
            ),
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(
                input_id="inp", stdin_hash=_hash("inp"),
            ),
            execution_evidence=(
                make_oracle_exec(run_id),
                make_candidate_exec(run_id),
            ),
            artifact_evidence=tuple(artifacts),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.workload_id.value == "claims"
        assert verdict.state == VerdictState.VERIFIED
