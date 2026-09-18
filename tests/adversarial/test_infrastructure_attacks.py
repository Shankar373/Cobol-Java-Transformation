"""Infrastructure attack tests.

Tests that infrastructure failures (timeout, error, Docker unavailable)
cannot produce VERIFIED.

WHAT INCORRECT STATE ARE WE ATTEMPTING TO MAKE THE VALIDATOR ACCEPT?
- Making a timeout, error, or infrastructure failure produce VERIFIED.
- The defense: the VerdictDeriver checks for errors, timeouts, and
  unavailability BEFORE checking comparison results.
"""

from __future__ import annotations

import pytest

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


class TestTimeoutAttacks:
    """Timeout conditions must not produce VERIFIED."""

    def test_oracle_timeout(self):
        """Oracle timeout → ERROR."""
        run_id = RunId(value="run-timeout-oracle")
        oracle_exec = make_oracle_exec(run_id, status="timeout", timeout=True)
        candidate_exec = make_candidate_exec(run_id)

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR

    def test_candidate_timeout(self):
        """Candidate timeout → ERROR."""
        run_id = RunId(value="run-timeout-candidate")
        oracle_exec = make_oracle_exec(run_id)
        candidate_exec = make_candidate_exec(run_id, status="timeout", timeout=True)

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR

    def test_both_timeout(self):
        """Both timeout → ERROR."""
        run_id = RunId(value="run-timeout-both")
        oracle_exec = make_oracle_exec(run_id, status="timeout", timeout=True)
        candidate_exec = make_candidate_exec(run_id, status="timeout", timeout=True)

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            comparisons=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR


class TestErrorStates:
    """Error conditions must not produce VERIFIED."""

    def test_oracle_error(self):
        """Oracle error → ERROR."""
        run_id = RunId(value="run-error-oracle")
        oracle_exec = make_oracle_exec(run_id, status="error")
        candidate_exec = make_candidate_exec(run_id)

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR

    def test_candidate_error(self):
        """Candidate error → ERROR."""
        run_id = RunId(value="run-error-candidate")
        oracle_exec = make_oracle_exec(run_id)
        candidate_exec = make_candidate_exec(run_id, status="error")

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.ERROR


class TestNonzeroExitBehavior:
    """Nonzero exit semantics: oracle nonzero → UNAVAILABLE,
    candidate nonzero → still comparable."""

    def test_oracle_nonzero_exit(self):
        """Oracle nonzero exit → UNAVAILABLE (oracle can't serve as ground truth)."""
        run_id = RunId(value="run-nonzero-oracle")
        oracle_exec = make_oracle_exec(run_id, status="nonzero_exit")
        candidate_exec = make_candidate_exec(run_id)

        oracle_art = _art_ev("art-o", "STDOUT", "ORACLE", b"same", "oracle-exec-1")
        cand_art = _art_ev("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-exec-1")

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            artifacts=(oracle_art, cand_art),
            comparisons=(make_comparison(
                run_id, result="MATCH", artifact_type="STDOUT",
                oracle_id="art-o", candidate_id="art-c",
            ),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_candidate_nonzero_exit_still_comparable(self):
        """Candidate nonzero exit → still comparable if oracle succeeded.
        The program ran but failed logically; output can still be compared."""
        run_id = RunId(value="run-nonzero-candidate")
        oracle_exec = make_oracle_exec(run_id)
        candidate_exec = make_candidate_exec(run_id, status="nonzero_exit")

        oracle_art = _art_ev("art-o", "STDOUT", "ORACLE", b"same", "oracle-exec-1")
        cand_art = _art_ev("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-exec-1")

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            artifacts=(oracle_art, cand_art),
            comparisons=(make_comparison(
                run_id, result="MATCH", artifact_type="STDOUT",
                oracle_id="art-o", candidate_id="art-c",
            ),),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.VERIFIED


class TestUnavailableInfrastructure:
    """Missing executions → UNAVAILABLE."""

    def test_no_oracle_execution(self):
        """No oracle execution → UNAVAILABLE."""
        run_id = RunId(value="run-no-oracle")
        candidate_exec = make_candidate_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl"),
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
            execution_evidence=(candidate_exec,),
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_no_candidate_execution(self):
        """No candidate execution → UNAVAILABLE."""
        run_id = RunId(value="run-no-candidate")
        oracle_exec = make_oracle_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl"),
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
            execution_evidence=(oracle_exec,),
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE

    def test_all_oracle_executions_failed(self):
        """All oracle executions with error/timeout/nonzero → UNAVAILABLE.
        Note: timeout_applied=True triggers ERROR first (step 1), so we use
        status='nonzero_exit' without timeout_applied to reach step 2."""
        run_id = RunId(value="run-all-oracle-fail")
        # Use nonzero_exit and error (not timeout_applied, which triggers ERROR)
        oracle_exec1 = make_oracle_exec(run_id, exec_id="o1", status="error")
        oracle_exec2 = make_oracle_exec(run_id, exec_id="o2", status="nonzero_exit")
        candidate_exec = make_candidate_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl"),
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
            execution_evidence=(oracle_exec1, oracle_exec2, candidate_exec),
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        # error triggers ERROR at step 1 (before UNAVAILABLE check)
        assert verdict.state == VerdictState.ERROR

    def test_all_oracle_nonzero_exit(self):
        """All oracle executions with nonzero_exit → UNAVAILABLE.
        nonzero_exit does NOT trigger timeout_applied, so reaches step 2."""
        run_id = RunId(value="run-all-oracle-nonzero")
        oracle_exec1 = make_oracle_exec(run_id, exec_id="o1", status="nonzero_exit")
        oracle_exec2 = make_oracle_exec(run_id, exec_id="o2", status="nonzero_exit")
        candidate_exec = make_candidate_exec(run_id)

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl"),
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
            execution_evidence=(oracle_exec1, oracle_exec2, candidate_exec),
            artifact_evidence=(),
            comparison_evidence=(),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state == VerdictState.UNAVAILABLE


class TestUnsupportedArtifactTypes:
    """Unsupported artifact types → UNSUPPORTED (fail-closed).

    ArtifactIdentity validates type at construction, so INDEXED/DATABASE
    cannot be created through the normal API. This proves the first line
    of defense: invalid types are rejected at the identity layer.
    The _check_for_unsupported method in VerdictDeriver is defense-in-depth.
    """

    def test_unsupported_type_rejected_at_construction(self):
        """INDEXED type rejected by ArtifactIdentity.__post_init__."""
        with pytest.raises(ValueError, match="artifact_type must be one of"):
            ArtifactIdentity(
                artifact_id="art-indexed",
                artifact_type="INDEXED",
                logical_name="indexed-data",
                producer_role="ORACLE",
                content_hash=_hash("data"),
                size_bytes=4,
            )

    def test_database_type_rejected_at_construction(self):
        """DATABASE type rejected by ArtifactIdentity.__post_init__."""
        with pytest.raises(ValueError, match="artifact_type must be one of"):
            ArtifactIdentity(
                artifact_id="art-db",
                artifact_type="DATABASE",
                logical_name="db-data",
                producer_role="ORACLE",
                content_hash=_hash("data"),
                size_bytes=4,
            )

    def test_json_type_rejected_at_construction(self):
        """JSON type rejected by ArtifactIdentity.__post_init__."""
        with pytest.raises(ValueError, match="artifact_type must be one of"):
            ArtifactIdentity(
                artifact_id="art-json",
                artifact_type="JSON",
                logical_name="json-data",
                producer_role="ORACLE",
                content_hash=_hash("data"),
                size_bytes=4,
            )

    def test_check_for_unsupported_directly(self):
        """VerdictDeriver._check_for_unsupported detects unsupported types
        in artifact evidence (defense-in-depth, if somehow bypassed)."""
        from engine.verdict.derivation import VerdictDeriver

        # Create a manifest with a "corrupted" artifact type by using
        # dataclasses.field init and object.__setattr__ to bypass frozen validation
        artifact = ArtifactIdentity.__new__(ArtifactIdentity)
        object.__setattr__(artifact, 'artifact_id', 'art-bypassed')
        object.__setattr__(artifact, 'artifact_type', 'INDEXED')
        object.__setattr__(artifact, 'logical_name', 'bypassed')
        object.__setattr__(artifact, 'producer_role', 'ORACLE')
        object.__setattr__(artifact, 'content_hash', _hash('data'))
        object.__setattr__(artifact, 'size_bytes', 4)
        object.__setattr__(artifact, 'record_count', None)

        artifact_ev = ArtifactEvidence(
            artifact=artifact,
            execution_id=ExecutionId(value="exec-1"),
            capture_time="2026-09-15T00:00:01Z",
            content_hash=_hash("data"),
            size_bytes=4,
        )

        run_id = RunId(value="run-unsupported-bypass")
        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=run_id,
            workload_id=WorkloadId(value="wl"),
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
            artifact_evidence=(artifact_ev,),
            comparison_evidence=(make_comparison(run_id, result="MATCH"),),
        )

        deriver = VerdictDeriver()
        result = deriver._check_for_unsupported(manifest)
        assert result == VerdictState.UNSUPPORTED


class TestNoInfrastructureFailureBecomesVerified:
    """Property: no infrastructure failure may produce VERIFIED."""

    @pytest.mark.parametrize("oracle_status,candidate_status,timeout_oracle,timeout_candidate,expected", [
        ("error", "normal", False, False, "ERROR"),
        ("normal", "error", False, False, "ERROR"),
        ("timeout", "normal", True, False, "ERROR"),
        ("normal", "timeout", False, True, "ERROR"),
        ("nonzero_exit", "normal", False, False, "UNAVAILABLE"),
        ("normal", "nonzero_exit", False, False, "VERIFIED"),
        ("error", "error", False, False, "ERROR"),
        ("timeout", "timeout", True, True, "ERROR"),
        ("nonzero_exit", "nonzero_exit", False, False, "UNAVAILABLE"),
    ])
    def test_infrastructure_states(
        self, oracle_status, candidate_status,
        timeout_oracle, timeout_candidate, expected,
    ):
        run_id = RunId(value=f"run-infra-{oracle_status}-{candidate_status}")

        oracle_exec = make_oracle_exec(
            run_id, status=oracle_status, timeout=timeout_oracle,
        )
        candidate_exec = make_candidate_exec(
            run_id, status=candidate_status, timeout=timeout_candidate,
        )

        oracle_art = _art_ev("art-o", "STDOUT", "ORACLE", b"same", "oracle-exec-1")
        cand_art = _art_ev("art-c", "STDOUT", "CANDIDATE", b"same", "candidate-exec-1")

        comparison = make_comparison(
            run_id, result="MATCH", artifact_type="STDOUT",
            oracle_id="art-o", candidate_id="art-c",
        )

        manifest = _manifest(
            run_id=run_id,
            oracle_exec=oracle_exec,
            candidate_exec=candidate_exec,
            artifacts=(oracle_art, cand_art),
            comparisons=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state.value == expected
