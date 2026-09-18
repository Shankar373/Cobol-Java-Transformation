"""Metamorphic / invariant testing.

Tests that key invariants hold across different input combinations.
"""

from __future__ import annotations

import pytest

from engine.comparators.framework import (
    StderrComparator,
    StdoutComparator,
    TextFileComparator,
)
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


def _art(aid: str, role: str, content: bytes, atype: str = "STDOUT",
         rc: int | None = None) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=aid, artifact_type=atype, logical_name=atype.lower(),
        producer_role=role, content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content), record_count=rc,
    )


class TestMetamorphicDeterminism:
    """Same input must produce same output across re-executions."""

    def test_stdout_comparator_deterministic(self):
        comp = StdoutComparator()
        ora = _art("ora", "ORACLE", b"hello")
        cand = _art("cand", "CANDIDATE", b"hello")

        r1 = comp.compare(ora, b"hello", cand, b"hello")
        r2 = comp.compare(ora, b"hello", cand, b"hello")
        assert r1.result == r2.result
        assert r1.differences == r2.differences

    def test_text_file_comparator_deterministic(self):
        comp = TextFileComparator()
        ora = _art("ora", "ORACLE", b"A\nB\nC", atype="TEXT_FILE")
        cand = _art("cand", "CANDIDATE", b"A\nB\nC", atype="TEXT_FILE")

        r1 = comp.compare(ora, b"A\nB\nC", cand, b"A\nB\nC")
        r2 = comp.compare(ora, b"A\nB\nC", cand, b"A\nB\nC")
        assert r1.result == r2.result

    def test_verdict_derivation_deterministic(self):
        run_id = RunId(value="run-determinism")
        manifest1 = make_manifest(
            run_id=run_id,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )
        manifest2 = make_manifest(
            run_id=run_id,
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

        v1 = derive_verdict(manifest1)
        v2 = derive_verdict(manifest2)
        assert v1.state == v2.state
        assert v1.executed_check_count == v2.executed_check_count


class TestMetamorphicIdentity:
    """Identical content must produce MATCH regardless of artifact metadata."""

    def test_same_content_different_ids(self):
        comp = StdoutComparator()
        ora1 = _art("ora-v1", "ORACLE", b"data")
        ora2 = _art("ora-v2", "ORACLE", b"data")
        cand1 = _art("cand-v1", "CANDIDATE", b"data")
        cand2 = _art("cand-v2", "CANDIDATE", b"data")

        r1 = comp.compare(ora1, b"data", cand1, b"data")
        r2 = comp.compare(ora2, b"data", cand2, b"data")
        assert r1.result.value == r2.result.value == "MATCH"

    def test_different_content_same_ids(self):
        comp = StdoutComparator()
        ora = _art("ora", "ORACLE", b"different")
        cand = _art("cand", "CANDIDATE", b"data")

        r = comp.compare(ora, b"different", cand, b"data")
        assert r.result.value == "MISMATCH"


class TestMetamorphicSymmetry:
    """Comparison is symmetric: if A=B then B=A."""

    def test_stdout_symmetry(self):
        comp = StdoutComparator()
        ora = _art("ora", "ORACLE", b"X")
        cand = _art("cand", "CANDIDATE", b"Y")

        r1 = comp.compare(ora, b"X", cand, b"Y")
        r2 = comp.compare(cand, b"Y", ora, b"X")
        # Both should be MISMATCH (content differs)
        assert r1.result.value == r2.result.value == "MISMATCH"

    def test_stdout_symmetry_match(self):
        comp = StdoutComparator()
        ora = _art("ora", "ORACLE", b"same")
        cand = _art("cand", "CANDIDATE", b"same")

        r1 = comp.compare(ora, b"same", cand, b"same")
        r2 = comp.compare(cand, b"same", ora, b"same")
        assert r1.result.value == r2.result.value == "MATCH"


class TestMetamorphicTransitivity:
    """If A=MATCH B and B=MATCH C, then A=MATCH C."""

    def test_transitivity(self):
        comp = StdoutComparator()
        a = _art("a", "ORACLE", b"data")
        b = _art("b", "CANDIDATE", b"data")
        c = _art("c", "CANDIDATE", b"data")

        r_ab = comp.compare(a, b"data", b, b"data")
        r_bc = comp.compare(b, b"data", c, b"data")
        r_ac = comp.compare(a, b"data", c, b"data")

        assert r_ab.result.value == "MATCH"
        assert r_bc.result.value == "MATCH"
        assert r_ac.result.value == "MATCH"


class TestMetamorphicEmptyEquivalence:
    """Empty outputs are equivalent if both empty."""

    def test_empty_stdout_match(self):
        comp = StdoutComparator()
        ora = _art("ora", "ORACLE", b"")
        cand = _art("cand", "CANDIDATE", b"")
        r = comp.compare(ora, b"", cand, b"")
        assert r.result.value == "MATCH"

    def test_empty_stderr_match(self):
        comp = StderrComparator()
        ora = _art("ora", "ORACLE", b"", atype="STDERR")
        cand = _art("cand", "CANDIDATE", b"", atype="STDERR")
        r = comp.compare(ora, b"", cand, b"")
        assert r.result.value == "MATCH"

    def test_empty_text_file_match(self):
        comp = TextFileComparator()
        ora = _art("ora", "ORACLE", b"", atype="TEXT_FILE")
        cand = _art("cand", "CANDIDATE", b"", atype="TEXT_FILE")
        r = comp.compare(ora, b"", cand, b"")
        assert r.result.value == "MATCH"


class TestMetamorphicZeroChecksNeverVerified:
    """Zero comparison checks can never produce VERIFIED."""

    @pytest.mark.parametrize("n_artifacts", [0, 1, 3, 10])
    def test_zero_comparisons(self, n_artifacts: int):
        from engine.domain.identities import (
            RunId,
        )

        run_id = RunId(value=f"run-zero-{n_artifacts}")

        artifacts = tuple(
            ArtifactEvidence(
                artifact=ArtifactIdentity(
                    artifact_id=f"art-{i}", artifact_type="STDOUT",
                    logical_name=f"out-{i}", producer_role="ORACLE",
                    content_hash=_hash(f"data-{i}"), size_bytes=len(f"data-{i}"),
                ),
                execution_id=ExecutionId(value=f"exec-{i}"),
                capture_time="2026-09-15T00:00:01Z",
                content_hash=_hash(f"data-{i}"),
                size_bytes=len(f"data-{i}"),
            )
            for i in range(n_artifacts)
        )

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
            artifact_evidence=artifacts,
            comparison_evidence=(),  # ZERO comparisons
        )

        verdict = derive_verdict(manifest)
        assert verdict.state != VerdictState.VERIFIED
