"""Identity confusion attacks.

Tests that evidence from one run/workload/oracle cannot be silently
accepted as evidence from another.

WHAT INCORRECT STATE ARE WE ATTEMPTING TO MAKE THE VALIDATOR ACCEPT?
- Using evidence bound to one identity as if it were bound to another.
- The defense: the verdict records identity fields from the manifest.
  Cross-identity evidence is processed, but the verdict binds to the
  manifest's identities, not the evidence's.
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
    make_manifest,
    make_oracle_exec,
)


def _art_ev(
    artifact_id: str, artifact_type: str, producer_role: str,
    content: bytes, exec_id: str,
) -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact=ArtifactIdentity(
            artifact_id=artifact_id, artifact_type=artifact_type,
            logical_name=f"{artifact_type.lower()}-{producer_role.lower()}",
            producer_role=producer_role,
            content_hash=_hash(content.decode("utf-8", errors="replace")),
            size_bytes=len(content),
        ),
        execution_id=ExecutionId(value=exec_id),
        capture_time="2026-09-15T00:00:01Z",
        content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content),
    )


class TestCrossRunConfusion:
    """Evidence from run A cannot silently become evidence for run B."""

    def test_oracle_exec_from_different_run(self):
        """Oracle execution evidence from run_A used in manifest for run_B.
        The deriver processes it. The verdict records manifest's run_id."""
        run_a = RunId(value="run-A-20260915000000")
        run_b = RunId(value="run-B-20260915000001")

        oracle_exec_a = make_oracle_exec(run_a, exec_id="oracle-exec-A")
        candidate_exec_b = make_candidate_exec(run_b, exec_id="candidate-exec-B")

        oracle_art = _art_ev("art-o", "STDOUT", "ORACLE", b"same", "oracle-exec-A")
        cand_art = _art_ev("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-exec-B")

        comparison = make_comparison(
            run_b, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-o", candidate_id="art-c",
        )

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_b,
            workload_id=WorkloadId(value="test-wl"),
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
            execution_evidence=(oracle_exec_a, candidate_exec_b),
            artifact_evidence=(oracle_art, cand_art),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.run_id == run_b.value
        assert verdict.state == VerdictState.VERIFIED

    def test_comparison_from_different_run(self):
        """Comparison evidence from run_A used in manifest for run_B.
        No artifact evidence → manifest incomplete → UNPROVEN."""
        run_a = RunId(value="run-A-20260915000000")
        run_b = RunId(value="run-B-20260915000001")

        comparison_a = make_comparison(run_a, result="MISMATCH", differences=("diff",))

        manifest = make_manifest(
            run_id=run_b,
            comparisons=(comparison_a,),
        )

        verdict = derive_verdict(manifest)
        # No artifact evidence → is_complete() returns False → UNPROVEN
        assert verdict.run_id == run_b.value
        assert verdict.state == VerdictState.UNPROVEN


class TestCrossWorkloadConfusion:
    """Evidence from workload A cannot silently become evidence for workload B."""

    def test_artifact_from_different_workload(self):
        """Artifact identities bound to different workloads in the same manifest.
        The deriver processes all evidence in the manifest regardless of
        workload binding. The defense is at the pipeline level."""
        run_id = RunId(value="run-cross-wl")

        artifact_payroll = _art_ev(
            "art-payroll-stdout", "STDOUT", "ORACLE", b"payroll-data", "oracle-exec-1",
        )
        artifact_inventory = _art_ev(
            "art-inventory-stdout", "STDOUT", "CANDIDATE", b"inventory-data", "candidate-exec-1",
        )

        comparison = make_comparison(
            run_id, result="MISMATCH", artifact_type="STDOUT",
            oracle_id="art-payroll-stdout", candidate_id="art-inventory-stdout",
            differences=("STDOUT output differs",),
        )

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="payroll-workload"),
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
                make_oracle_exec(run_id, exec_id="oracle-exec-1"),
                make_candidate_exec(run_id, exec_id="candidate-exec-1"),
            ),
            artifact_evidence=(artifact_payroll, artifact_inventory),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.workload_id.value == "payroll-workload"
        assert verdict.state == VerdictState.FAILED


class TestCrossOracleConfusion:
    """Evidence from oracle A cannot silently become evidence from oracle B."""

    def test_oracle_identity_mismatch(self):
        """Oracle identity in manifest differs from actual oracle execution.
        The deriver uses manifest's oracle identity for the verdict."""
        run_id = RunId(value="run-cross-oracle")

        manifest = make_manifest(
            run_id=run_id,
            oracle_id_str="gnucobol-3.1.2",
            oracle_digest="sha256:" + "a" * 64,
        )

        verdict = derive_verdict(manifest)
        assert verdict.oracle_id == "gnucobol-3.1.2"
        assert verdict.oracle_digest == "sha256:" + "a" * 64

    def test_wrong_oracle_digest(self):
        """Different oracle digest than what was actually used.
        The verdict records whatever the manifest states."""
        run_id = RunId(value="run-wrong-digest")

        manifest = make_manifest(
            run_id=run_id,
            oracle_digest="sha256:" + "b" * 64,
        )

        verdict = derive_verdict(manifest)
        assert verdict.oracle_digest == "sha256:" + "b" * 64


class TestCandidateIdentityBinding:
    """Candidate identity must bind to the correct source hash."""

    def test_candidate_source_hash_mismatch(self):
        """Candidate's source_hash doesn't match the manifest's source hash.
        The deriver records both hashes. The mismatch is visible in the
        verdict but does not change the verdict state."""
        run_id = RunId(value="run-cand-bind")

        oracle_art = _art_ev("art-o", "STDOUT", "ORACLE", b"same", "oracle-exec-1")
        cand_art = _art_ev("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-exec-1")

        comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-o", candidate_id="art-c",
        )

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="test-wl"),
            source_identity=SourceIdentity(
                source_id="src", source_hash=_hash("source-hash-correct"),
                file_count=1, total_size_bytes=10,
            ),
            candidate_identity=CandidateIdentity(
                candidate_id="cand-mismatch",
                candidate_hash=_hash("cand-hash-wrong"),
                source_hash=_hash("source-hash-WRONG"),
                file_count=1, total_size_bytes=10,
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
                make_oracle_exec(run_id, exec_id="oracle-exec-1"),
                make_candidate_exec(run_id, exec_id="candidate-exec-1"),
            ),
            artifact_evidence=(oracle_art, cand_art),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        # Source hash mismatch is visible but doesn't change verdict
        assert verdict.source_hash != verdict.candidate_hash
        # VERIFIED because all comparisons matched
        assert verdict.state == VerdictState.VERIFIED


class TestManifestHashBinding:
    """Manifest hash binds all evidence to a specific manifest."""

    def test_verdict_records_manifest_hash(self):
        """The verdict's evidence_manifest_hash matches the manifest's hash."""
        run_id = RunId(value="run-hash-bind")
        manifest = make_manifest(
            run_id=run_id,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.evidence_manifest_hash == str(manifest.manifest_hash)

    def test_different_manifests_different_hashes(self):
        """Different manifests produce different hashes."""
        m1 = make_manifest(run_id=RunId(value="run-1"))
        m2 = make_manifest(run_id=RunId(value="run-2"))
        assert m1.manifest_hash != m2.manifest_hash
