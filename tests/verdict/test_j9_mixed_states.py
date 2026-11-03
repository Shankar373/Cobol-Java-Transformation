"""J-9 regression tests: mixed execution states must not certify equivalence.

Verdict derivation must never return VERIFIED when any required execution is
unavailable or when both sides did not complete normally. Mixed statuses
across multiple executions for one runtime are treated as compromised
ground truth (UNAVAILABLE for oracle, ERROR for candidate timeout/error).
"""
from __future__ import annotations

import pytest

from engine.domain.identities import (
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
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
)
from engine.verdict.derivation import derive_verdict
from tests.common import make_hash


def _manifest(run_id, oracle_execs, cand_execs, comparisons=()):
    return EvidenceManifest(
        manifest_version="1.0",
        run_id=run_id,
        workload_id=WorkloadId(value="wl-j9"),
        source_identity=SourceIdentity(
            source_id="src", source_hash=make_hash("src"), file_count=1, total_size_bytes=1
        ),
        candidate_identity=CandidateIdentity(
            candidate_id="cand", candidate_hash=make_hash("cand"),
            source_hash=make_hash("src"), file_count=1, total_size_bytes=1
        ),
        oracle_identity=OracleIdentity(
            oracle_id="gnucobol", image_digest="sha256:" + "a" * 64,
            compiler_version="3.1.2",
        ),
        environment_identities=(),
        controlled_input=InputIdentity(input_id="inp", stdin_hash=make_hash("in")),
        execution_evidence=tuple(oracle_execs + cand_execs),
        artifact_evidence=(),
        comparison_evidence=tuple(comparisons),
    )


def _exec(run_id, eid, runtime_id, status, timeout=False):
    return ExecutionEvidence(
        execution_id=ExecutionId(value=eid),
        run_id=run_id,
        runtime_id=runtime_id,
        command="cmd",
        working_directory="/w",
        environment_variables={},
        start_time="t0",
        end_time="t1",
        exit_code=0 if status == "normal" else 1,
        stdout_hash=make_hash("o"),
        stderr_hash=make_hash("e"),
        generated_files={},
        source_tree_hash_before=make_hash("b"),
        source_tree_hash_after=make_hash("a"),
        termination_status=status,
        timeout_applied=timeout,
    )


def test_mixed_oracle_normal_and_nonzero_is_unavailable():
    run_id = RunId(value="run-mixed-oracle")
    oe1 = _exec(run_id, "o1", "oracle-gnucobol", "normal")
    oe2 = _exec(run_id, "o2", "oracle-gnucobol", "nonzero_exit")
    ce = _exec(run_id, "c1", "candidate-java", "normal")
    m = _manifest(run_id, [oe1, oe2], [ce])
    v = derive_verdict(m)
    assert v.state == VerdictState.UNAVAILABLE


def test_mixed_oracle_normal_and_timeout_is_unavailable_or_error():
    run_id = RunId(value="run-mixed-oracle-to")
    oe1 = _exec(run_id, "o1", "oracle-gnucobol", "normal")
    oe2 = _exec(run_id, "o2", "oracle-gnucobol", "timeout", timeout=True)
    ce = _exec(run_id, "c1", "candidate-java", "normal")
    m = _manifest(run_id, [oe1, oe2], [ce])
    v = derive_verdict(m)
    # timeout_applied -> ERROR takes precedence over UNAVAILABLE
    assert v.state in (VerdictState.ERROR, VerdictState.UNAVAILABLE)


def test_mixed_candidate_normal_and_timeout_is_error():
    run_id = RunId(value="run-mixed-cand-to")
    oe = _exec(run_id, "o1", "oracle-gnucobol", "normal")
    ce1 = _exec(run_id, "c1", "candidate-java", "normal")
    ce2 = _exec(run_id, "c2", "candidate-java", "timeout", timeout=True)
    m = _manifest(run_id, [oe], [ce1, ce2])
    v = derive_verdict(m)
    assert v.state == VerdictState.ERROR


def test_mixed_candidate_normal_and_error_is_error():
    run_id = RunId(value="run-mixed-cand-err")
    oe = _exec(run_id, "o1", "oracle-gnucobol", "normal")
    ce1 = _exec(run_id, "c1", "candidate-java", "normal")
    ce2 = _exec(run_id, "c2", "candidate-java", "error")
    m = _manifest(run_id, [oe], [ce1, ce2])
    v = derive_verdict(m)
    assert v.state == VerdictState.ERROR


def test_all_normal_single_exec_can_verify_with_match():
    # sanity: single normal pair with matching comparison -> VERIFIED
    run_id = RunId(value="run-ok")
    oe = _exec(run_id, "o1", "oracle-gnucobol", "normal")
    ce = _exec(run_id, "c1", "candidate-java", "normal")
    from engine.domain.identities import ArtifactIdentity
    oa = ArtifactIdentity(artifact_id="ao", artifact_type="STDOUT", logical_name="STDOUT",
                          producer_role="ORACLE", content_hash=make_hash("o"), size_bytes=1)
    ca = ArtifactIdentity(artifact_id="ac", artifact_type="STDOUT", logical_name="STDOUT",
                          producer_role="CANDIDATE", content_hash=make_hash("o"), size_bytes=1)
    oae = ArtifactEvidence(artifact=oa, execution_id=ExecutionId(value="o1"),
                           capture_time="t", content_hash=make_hash("o"), size_bytes=1)
    cae = ArtifactEvidence(artifact=ca, execution_id=ExecutionId(value="c1"),
                           capture_time="t", content_hash=make_hash("o"), size_bytes=1)
    from tests.common import make_hash as _mh
    comp = ComparisonEvidence(comparison_id="comp", run_id=run_id,
                              comparator_id="STDOUT_COMPARATOR", comparator_version="1",
                              oracle_artifact_id="ao", candidate_artifact_id="ac",
                              artifact_type="STDOUT", result="MATCH",
                              normalization_applied=(), differences=(),
                              field_level_results=(), content_hash=_mh("comp"))
    m = EvidenceManifest(
        manifest_version="1.0", run_id=run_id,
        workload_id=WorkloadId(value="wl-j9"),
        source_identity=SourceIdentity(source_id="src", source_hash=make_hash("src"),
                                      file_count=1, total_size_bytes=1),
        candidate_identity=CandidateIdentity(candidate_id="cand", candidate_hash=make_hash("cand"),
                                            source_hash=make_hash("src"), file_count=1, total_size_bytes=1),
        oracle_identity=OracleIdentity(oracle_id="gnucobol", image_digest="sha256:" + "a" * 64,
                                      compiler_version="3.1.2"),
        environment_identities=(),
        controlled_input=InputIdentity(input_id="inp", stdin_hash=make_hash("in")),
        execution_evidence=(oe, ce),
        artifact_evidence=(oae, cae),
        comparison_evidence=(comp,),
    )
    v = derive_verdict(m)
    assert v.state == VerdictState.VERIFIED
