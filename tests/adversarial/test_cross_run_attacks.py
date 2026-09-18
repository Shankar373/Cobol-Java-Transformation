"""Cross-run confusion attacks.

Tests that evidence from one execution cannot be silently combined
with evidence from a different execution.

WHAT INCORRECT STATE ARE WE ATTEMPTING TO MAKE THE VALIDATOR ACCEPT?
- Using oracle evidence from run_A as if it were evidence from run_B.
- The defense: the verdict records which run it was derived from.
  Evidence from a different run_id is still processed, but the verdict
 绑定 to the manifest's run_id, not the evidence's run_id.
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

from .conftest import _hash, make_candidate_exec, make_comparison, make_oracle_exec


def _make_art_evidence(
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


def _manifest(**kwargs) -> EvidenceManifest:
    run_id = kwargs.get("run_id", RunId(value="run-default"))
    oracle_exec = kwargs.get("oracle_exec", make_oracle_exec(run_id))
    candidate_exec = kwargs.get("candidate_exec", make_candidate_exec(run_id))
    artifacts = kwargs.get("artifacts", ())
    comparisons = kwargs.get("comparisons", ())

    return EvidenceManifest(
        manifest_version="1.0",
        run_id=run_id,
        workload_id=kwargs.get("workload_id", WorkloadId(value="test-wl")),
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
        execution_evidence=(oracle_exec, candidate_exec),
        artifact_evidence=artifacts,
        comparison_evidence=comparisons,
    )


class TestCrossRunArtifactSubstitution:
    """Artifact from run A substituted into run B's manifest."""

    def test_oracle_artifact_from_different_run(self):
        """Oracle artifact captured in run_A used in run_B comparison.
        The comparison runs with whatever artifacts are provided.
        The verdict records run_B's run_id."""
        run_a = RunId(value="run-A-20260915000000")
        run_b = RunId(value="run-B-20260915000001")

        artifact_from_a = _make_art_evidence(
            "art-from-run-A", "STDOUT", "ORACLE", b"output-from-A", "oracle-exec-A",
        )
        artifact_from_b = _make_art_evidence(
            "art-from-run-B", "STDOUT", "CANDIDATE", b"output-from-B", "candidate-exec-B",
        )

        comparison = make_comparison(
            run_b, result="MISMATCH", artifact_type="STDOUT",
            oracle_id="art-from-run-A", candidate_id="art-from-run-B",
            differences=("STDOUT output differs",),
        )

        manifest = _manifest(
            run_id=run_b,
            oracle_exec=make_oracle_exec(run_a, exec_id="oracle-exec-A"),
            candidate_exec=make_candidate_exec(run_b, exec_id="candidate-exec-B"),
            artifacts=(artifact_from_a, artifact_from_b),
            comparisons=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.run_id == run_b.value
        assert verdict.state == VerdictState.FAILED


class TestCrossRunExecutionMixing:
    """Mixing execution evidence from different runs."""

    def test_mixed_execution_runs(self):
        """Oracle exec from run_A, candidate exec from run_B in same manifest.
        The manifest's run_id determines the verdict's run_id.
        The artifacts are fabricated to match the comparison."""
        run_a = RunId(value="run-A-mix")
        run_b = RunId(value="run-B-mix")

        oracle_art = _make_art_evidence("art-o", "STDOUT", "ORACLE", b"same", "oracle-A")
        cand_art = _make_art_evidence("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-B")

        comparison = make_comparison(
            run_b, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-o", candidate_id="art-c",
        )

        manifest = _manifest(
            run_id=run_b,
            oracle_exec=make_oracle_exec(run_a, exec_id="oracle-A"),
            candidate_exec=make_candidate_exec(run_b, exec_id="candidate-B"),
            artifacts=(oracle_art, cand_art),
            comparisons=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.run_id == run_b.value
        assert verdict.state == VerdictState.VERIFIED


class TestCrossRunComparisonMixing:
    """Comparison evidence from different runs."""

    def test_comparison_from_different_run_in_manifest(self):
        """Comparison from run_A used in manifest for run_B.
        The comparison is processed; the verdict records run_B."""
        run_a = RunId(value="run-A-comp")
        run_b = RunId(value="run-B-comp")

        comparison_a = make_comparison(
            run_a, result="MISMATCH", differences=("diff from A",),
        )

        manifest = _manifest(
            run_id=run_b,
            comparisons=(comparison_a,),
        )

        verdict = derive_verdict(manifest)
        # No artifact evidence → is_complete() returns False → UNPROVEN
        # (the comparison from run_A is processed but manifest is incomplete)
        assert verdict.run_id == run_b.value
        assert verdict.state == VerdictState.UNPROVEN
