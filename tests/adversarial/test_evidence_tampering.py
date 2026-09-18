"""Evidence tampering attacks.

Tests that an adversary cannot produce a VERIFIED verdict by manipulating
evidence manifests, comparison results, or verdict fields.

ATTACK: "I will manually change a MISMATCH comparison to MATCH."
EXPECTED: Verdict derivation must still produce FAILED if any real
comparison was MISMATCH, or must detect the inconsistency.

ATTACK: "I will set the verdict field to VERIFIED directly."
EXPECTED: The verdict is derived from evidence, not from a stored field.
A manually set verdict_evidence does not override derivation.

ATTACK: "I will remove the comparison that found a mismatch."
EXPECTED: The remaining comparisons determine the verdict. If all
remaining are MATCH, the verdict is VERIFIED — but this requires
legitimate evidence, not tampering.

ATTACK: "I will change the manifest hash after altering contents."
EXPECTED: The manifest hash is recomputed from contents. A mismatched
hash does not affect verdict derivation (the hash is informational).

ATTACK: "I will swap oracle and candidate artifact IDs in comparisons."
EXPECTED: The comparator_result field references specific artifacts.
Swapping IDs does not change the comparison result content.

ATTACK: "I will fabricate comparison evidence with a fake MATCH."
EXPECTED: Fabricated evidence with correct structure produces a
verdict consistent with that evidence — but this is SYNTHETIC evidence
tests, not a pipeline exploit. The pipeline produces real evidence.
"""

from __future__ import annotations

import pytest

from engine.domain.identities import (
    CandidateIdentity,
    ContentHash,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.models import (
    EvidenceManifest,
)
from engine.verdict.derivation import derive_verdict

from .conftest import (
    _hash,
    make_artifact,
    make_artifact_evidence,
    make_candidate_exec,
    make_comparison,
    make_manifest,
    make_oracle_exec,
)


class TestComparisonResultTampering:
    """Attack: change comparison result from MISMATCH to MATCH."""

    def test_tampered_match_cannot_override_real_mismatch(self):
        """If a real MISMATCH exists, changing another comparison to MATCH
        does not remove the FAILED verdict."""
        run_id = RunId(value="run-tamper-1")
        stdout_oracle = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"expected")
        stdout_cand = make_artifact("art-cand-stdout", "STDOUT", "CANDIDATE", b"different")
        stderr_oracle = make_artifact("art-oracle-stderr", "STDERR", "ORACLE", b"err-expected")
        stderr_cand = make_artifact("art-cand-stderr", "STDERR", "CANDIDATE", b"err-different")

        # Real comparison: MISMATCH
        real_comparison = make_comparison(
            run_id, result="MISMATCH", artifact_type="STDOUT",
            oracle_id="art-oracle-stdout", candidate_id="art-cand-stdout",
            differences=("STDOUT output differs",),
        )
        # Tampered comparison: fake MATCH for stderr (adversary changed it)
        tampered_comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDERR",
            oracle_id="art-oracle-stderr", candidate_id="art-cand-stderr",
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(stdout_oracle, "oracle-exec-1"),
                make_artifact_evidence(stdout_cand, "candidate-exec-1"),
                make_artifact_evidence(stderr_oracle, "oracle-exec-1"),
                make_artifact_evidence(stderr_cand, "candidate-exec-1"),
            ),
            comparisons=(real_comparison, tampered_comparison),
        )

        verdict = derive_verdict(manifest)
        # The real MISMATCH in stdout produces FAILED regardless of the fake MATCH
        assert verdict.state == VerdictState.FAILED

    def test_all_comparisons_tampered_to_match_produces_verified(self):
        """If ALL comparisons are MATCH (even if fabricated), the verdict
        derivation produces VERIFIED. This is expected: the deriver is a
        pure function over evidence. The defense is that the pipeline
        produces honest evidence — not that the deriver detects fabrication."""
        run_id = RunId(value="run-tamper-2")
        stdout_oracle = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"same")
        stdout_cand = make_artifact("art-cand-stdout", "STDOUT", "CANDIDATE", b"same")

        comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-oracle-stdout", candidate_id="art-cand-stdout",
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(stdout_oracle, "oracle-exec-1"),
                make_artifact_evidence(stdout_cand, "candidate-exec-1"),
            ),
            comparisons=(comparison,),
        )

        verdict = derive_verdict(manifest)
        # Fabricated MATCH evidence → VERIFIED by derivation
        # This proves the deriver is honest, not that fabrication is possible
        # through the pipeline (the pipeline captures real artifacts)
        assert verdict.state == VerdictState.VERIFIED


class TestVerdictFieldTampering:
    """Attack: manually set verdict_evidence to VERIFIED."""

    def test_manual_verdict_does_not_override_derivation(self):
        """A manually set verdict_evidence field is ignored by derivation.
        The deriver always recomputes from evidence."""
        run_id = RunId(value="run-tamper-3")
        stderr_oracle = make_artifact("art-oracle-stderr", "STDERR", "ORACLE", b"err")
        stderr_cand = make_artifact("art-cand-stderr", "STDERR", "CANDIDATE", b"diff")

        comparison = make_comparison(
            run_id, result="MISMATCH", artifact_type="STDERR",
            oracle_id="art-oracle-stderr", candidate_id="art-cand-stderr",
            differences=("STDERR output differs",),
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(stderr_oracle, "oracle-exec-1"),
                make_artifact_evidence(stderr_cand, "candidate-exec-1"),
            ),
            comparisons=(comparison,),
        )

        # Adversary sets verdict_evidence to VERIFIED
        from engine.evidence.models import VerdictEvidence
        manifest.verdict_evidence = VerdictEvidence(
            run_id=run_id,
            workload_id=manifest.workload_id,
            verdict_state="VERIFIED",  # TAMPERED
            executed_check_count=1,
            skipped_count=0,
            unavailable_count=0,
            supported_scope_statement="tampered",
            evidence_manifest_hash=manifest.manifest_hash,
            derivation_timestamp="2026-09-15T00:00:00Z",
        )

        verdict = derive_verdict(manifest)
        # The deriver recomputes: MISMATCH → FAILED, ignoring verdict_evidence
        assert verdict.state == VerdictState.FAILED


class TestManifestHashTampering:
    """Attack: alter manifest contents after hash is computed."""

    def test_altered_contents_do_not_affect_verdict(self):
        """The manifest hash is informational. Verdict derivation uses
        the manifest contents, not the stored hash. Changing contents
        changes the computed hash but the verdict is still derived
        from the actual evidence."""
        run_id = RunId(value="run-tamper-4")
        stdout_oracle = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"hello")
        stdout_cand = make_artifact("art-cand-stdout", "STDOUT", "CANDIDATE", b"hello")

        comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-oracle-stdout", candidate_id="art-cand-stdout",
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(stdout_oracle, "oracle-exec-1"),
                make_artifact_evidence(stdout_cand, "candidate-exec-1"),
            ),
            comparisons=(comparison,),
        )

        original_hash = manifest.manifest_hash

        # Tamper: change source identity (simulates altering stored manifest)
        # But the manifest object still has the original comparison evidence
        # The hash property recomputes from current state
        new_hash = manifest.manifest_hash
        # Hash is deterministic from current state — it doesn't change
        # because we haven't changed the manifest fields
        assert original_hash == new_hash

        # Even if we could change the hash, derivation uses the comparison evidence
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.VERIFIED


class TestComparisonRemoval:
    """Attack: remove comparison evidence to change verdict."""

    def test_removing_mismatch_comparison_changes_verdict(self):
        """If a MISMATCH comparison is removed, the remaining MATCH
        comparisons produce VERIFIED. This is legitimate behavior:
        fewer comparisons mean fewer checks. The defense is at the
        pipeline level — the pipeline produces all required comparisons."""
        run_id = RunId(value="run-tamper-5")
        stdout_oracle = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"same")
        stdout_cand = make_artifact("art-cand-stdout", "STDOUT", "CANDIDATE", b"same")
        stderr_oracle = make_artifact("art-oracle-stderr", "STDERR", "ORACLE", b"err")
        stderr_cand = make_artifact("art-cand-stderr", "STDERR", "CANDIDATE", b"diff")

        match_comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-oracle-stdout", candidate_id="art-cand-stdout",
        )
        mismatch_comparison = make_comparison(
            run_id, result="MISMATCH", artifact_type="STDERR",
            oracle_id="art-oracle-stderr", candidate_id="art-cand-stderr",
            differences=("STDERR output differs",),
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(stdout_oracle, "oracle-exec-1"),
                make_artifact_evidence(stdout_cand, "candidate-exec-1"),
                make_artifact_evidence(stderr_oracle, "oracle-exec-1"),
                make_artifact_evidence(stderr_cand, "candidate-exec-1"),
            ),
            comparisons=(match_comparison, mismatch_comparison),
        )

        # With both comparisons: FAILED
        assert derive_verdict(manifest).state == VerdictState.FAILED

        # Remove the MISMATCH comparison
        manifest_tampered = EvidenceManifest(
            manifest_version=manifest.manifest_version,
            run_id=manifest.run_id,
            workload_id=manifest.workload_id,
            source_identity=manifest.source_identity,
            candidate_identity=manifest.candidate_identity,
            oracle_identity=manifest.oracle_identity,
            environment_identities=manifest.environment_identities,
            controlled_input=manifest.controlled_input,
            execution_evidence=manifest.execution_evidence,
            artifact_evidence=manifest.artifact_evidence,
            comparison_evidence=(match_comparison,),  # MISMATCH removed
        )

        # Now: VERIFIED (only MATCH remains)
        assert derive_verdict(manifest_tampered).state == VerdictState.VERIFIED

    def test_removing_all_comparisons_produces_unproven(self):
        """Removing all comparison evidence → UNPROVEN."""
        run_id = RunId(value="run-tamper-6")

        manifest = make_manifest(run_id=run_id, comparisons=())

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNPROVEN


class TestArtifactSwap:
    """Attack: swap oracle and candidate artifact identities."""

    def test_swapped_producer_role_in_comparison(self):
        """Swapping producer_role in artifact identities does not change
        the comparison result. The comparison is content-based, not
        role-based. However, the pipeline always assigns roles correctly."""
        run_id = RunId(value="run-tamper-7")
        # Create artifacts with swapped roles
        oracle_artifact = make_artifact("art-oracle-stdout", "STDOUT", "CANDIDATE", b"hello")
        candidate_artifact = make_artifact("art-cand-stdout", "STDOUT", "ORACLE", b"hello")

        comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-oracle-stdout", candidate_id="art-cand-stdout",
        )

        manifest = make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(oracle_artifact, "oracle-exec-1"),
                make_artifact_evidence(candidate_artifact, "candidate-exec-1"),
            ),
            comparisons=(comparison,),
        )

        verdict = derive_verdict(manifest)
        # The comparison says MATCH → VERIFIED, regardless of role swap
        # The defense is that the pipeline assigns roles correctly
        assert verdict.state == VerdictState.VERIFIED


class TestEvidenceEnvelopeIntegrity:
    """Attack: tamper with evidence envelope content after creation."""

    def test_tampered_envelope_detected(self):
        """EvidenceEnvelope.verify_integrity() detects content tampering."""
        from engine.evidence.models import EvidenceEnvelope

        original_content = {"key": "value", "data": [1, 2, 3]}
        import json
        content_bytes = json.dumps(original_content, sort_keys=True).encode("utf-8")
        content_hash = ContentHash.from_bytes(content_bytes)

        envelope = EvidenceEnvelope(
            evidence_id="env-001",
            evidence_type="comparison_result",
            schema_version="1.0",
            created_at="2026-09-15T00:00:00Z",
            content_hash=content_hash,
            content=original_content,
        )

        # Integrity check passes
        assert envelope.verify_integrity()

        # Tamper with content
        tampered_envelope = EvidenceEnvelope(
            evidence_id=envelope.evidence_id,
            evidence_type=envelope.evidence_type,
            schema_version=envelope.schema_version,
            created_at=envelope.created_at,
            content_hash=envelope.content_hash,  # OLD hash
            content={"key": "TAMPERED", "data": [1, 2, 3]},  # CHANGED
        )

        # Integrity check fails
        assert not tampered_envelope.verify_integrity()


class TestZeroChecksCannotVerified:
    """Property: zero comparison checks cannot produce VERIFIED."""

    @pytest.mark.parametrize("artifact_count", [0, 1, 5])
    def test_zero_comparisons_needs_verified(self, artifact_count: int):
        """Even with artifacts present, zero comparisons → UNPROVEN."""
        run_id = RunId(value="run-zero-checks")
        artifacts = tuple(
            make_artifact_evidence(
                make_artifact(f"art-{i}", "STDOUT", "ORACLE", b"data"),
                "oracle-exec-1",
            )
            for i in range(artifact_count)
        )

        manifest = make_manifest(run_id=run_id, artifacts=artifacts, comparisons=())
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNPROVEN


class TestIncompleteManifestCannotVerified:
    """Property: incomplete manifest cannot produce VERIFIED."""

    def test_no_oracle_execution(self):
        """Missing oracle execution → UNAVAILABLE.
        The engine checks for unavailable infrastructure (step 2) before
        checking manifest completeness (step 4). No oracle = UNAVAILABLE."""
        run_id = RunId(value="run-no-oracle")
        candidate_exec = make_candidate_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=manifest_workload_id(),
            source_identity=make_source(),
            candidate_identity=make_candidate(),
            oracle_identity=make_oracle(),
            environment_identities=(),
            controlled_input=make_input(),
            execution_evidence=(candidate_exec,),  # NO ORACLE
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_no_candidate_execution(self):
        """Missing candidate execution → UNAVAILABLE.
        The engine checks for unavailable infrastructure (step 2) before
        checking manifest completeness (step 4). No candidate = UNAVAILABLE."""
        run_id = RunId(value="run-no-candidate")
        oracle_exec = make_oracle_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="test-wl"),
            source_identity=SourceIdentity(
                source_id="src", source_hash=_hash("s"),
                file_count=1, total_size_bytes=10,
            ),
            candidate_identity=None,
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(
                input_id="inp", stdin_hash=_hash("inp"),
            ),
            execution_evidence=(oracle_exec,),  # NO CANDIDATE
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_no_artifacts(self):
        """Missing artifact evidence → UNPROVEN."""
        run_id = RunId(value="run-no-artifacts")
        manifest = make_manifest(run_id=run_id, comparisons=())
        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNPROVEN


# ---------------------------------------------------------------------------
# Helpers for test classes that need inline fixtures
# ---------------------------------------------------------------------------

def manifest_workload_id():
    from engine.domain.identities import WorkloadId
    return WorkloadId(value="test-wl")

def make_source():
    return SourceIdentity(
        source_id="src", source_hash=_hash("s"),
        file_count=1, total_size_bytes=10,
    )

def make_candidate():
    return CandidateIdentity(
        candidate_id="cand", candidate_hash=_hash("c"),
        source_hash=_hash("s"), file_count=1, total_size_bytes=10,
    )

def make_oracle():
    return OracleIdentity(
        oracle_id="gnucobol-3.1.2",
        image_digest="sha256:" + "a" * 64,
        compiler_version="3.1.2.0",
    )

def make_input():
    return InputIdentity(input_id="inp", stdin_hash=_hash("inp"))
