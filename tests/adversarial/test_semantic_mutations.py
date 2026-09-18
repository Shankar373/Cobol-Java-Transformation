"""Semantic mutation and property-based tests.

Properties that MUST hold for the validation engine:

1. If oracle record set != candidate record set → comparison must not be MATCH
2. If one required record is removed → result must not be VERIFIED
3. If one record byte changes → result must not be VERIFIED
4. If one key changes → result must not be VERIFIED
5. If canonical semantic states are identical → comparison must be MATCH
6. Deterministic: same input → same output (tested separately)
"""

from __future__ import annotations

import pytest

from engine.comparators.framework import (
    FixedRecordComparator,
    TextFileComparator,
    create_default_registry,
)
from engine.domain.identities import ArtifactIdentity, ExecutionId
from engine.verdict.derivation import derive_verdict

from .conftest import _hash


def _art(aid: str, role: str, content: bytes, atype: str = "TEXT_FILE",
         rc: int | None = None) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=aid, artifact_type=atype, logical_name=atype.lower(),
        producer_role=role, content_hash=_hash(content.decode("utf-8", errors="replace")),
        size_bytes=len(content), record_count=rc,
    )


class TestRecordSetInvariants:
    """Property: different record sets must not produce MATCH."""

    def setup_method(self):
        self.comp = TextFileComparator()
        self.ora = _art("ora", "ORACLE", b"")
        self.cand = _art("cand", "CANDIDATE", b"")

    @pytest.mark.parametrize("oracle_data,candidate_data", [
        (b"A\nB\nC", b"A\nB"),          # missing record
        (b"A\nB", b"A\nB\nC"),          # extra record
        (b"A\nB\nC", b"A\nX\nC"),       # changed record
        (b"A\nB\nC", b"C\nB\nA"),       # reordered
        (b"A\nB\nC", b"A\nB\nC\nD\nE"), # two extra
        (b"", b"A"),                     # empty vs non-empty
    ])
    def test_different_record_sets_mismatch(self, oracle_data, candidate_data):
        r = self.comp.compare(self.ora, oracle_data, self.cand, candidate_data)
        assert r.result.value == "MISMATCH"


class TestFixedRecordInvariants:
    """Property: FixedRecordComparator rejects mutations."""

    def setup_method(self):
        self.comp = FixedRecordComparator()

    def _art(self, aid: str, role: str, content: bytes, rc: int):
        return _art(aid, role, content, atype="FIXED_RECORD", rc=rc)

    def test_missing_record(self):
        oracle = self._art("ora", "ORACLE", b"AAAABBBBCCCC", rc=3)
        cand = self._art("cand", "CANDIDATE", b"AAAABBBB", rc=2)
        r = self.comp.compare(oracle, b"AAAABBBBCCCC", cand, b"AAAABBBB")
        assert r.result.value == "MISMATCH"

    def test_extra_record(self):
        oracle = self._art("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._art("cand", "CANDIDATE", b"AAAABBBBCCCC", rc=3)
        r = self.comp.compare(oracle, b"AAAABBBB", cand, b"AAAABBBBCCCC")
        assert r.result.value == "MISMATCH"

    def test_single_byte_change(self):
        oracle = self._art("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._art("cand", "CANDIDATE", b"AAABBBBB", rc=2)
        r = self.comp.compare(oracle, b"AAAABBBB", cand, b"AAABBBBB")
        assert r.result.value == "MISMATCH"

    def test_swapped_records(self):
        oracle = self._art("ora", "ORACLE", b"AAAABBBB", rc=2)
        cand = self._art("cand", "CANDIDATE", b"BBBBAAAA", rc=2)
        r = self.comp.compare(oracle, b"AAAABBBB", cand, b"BBBBAAAA")
        assert r.result.value == "MISMATCH"


class TestIdenticalStateMatches:
    """Property: identical semantic state must produce MATCH."""

    def setup_method(self):
        self.registry = create_default_registry()

    def test_identical_stdout(self):
        comp = self.registry.get("STDOUT")
        ora = _art("ora", "ORACLE", b"same", atype="STDOUT")
        cand = _art("cand", "CANDIDATE", b"same", atype="STDOUT")
        r = comp.compare(ora, b"same", cand, b"same")
        assert r.result.value == "MATCH"

    def test_identical_stderr(self):
        comp = self.registry.get("STDERR")
        ora = _art("ora", "ORACLE", b"same", atype="STDERR")
        cand = _art("cand", "CANDIDATE", b"same", atype="STDERR")
        r = comp.compare(ora, b"same", cand, b"same")
        assert r.result.value == "MATCH"

    def test_identical_exit_status(self):
        comp = self.registry.get("EXIT_STATUS")
        ora = _art("ora", "ORACLE", b"0", atype="EXIT_STATUS")
        cand = _art("cand", "CANDIDATE", b"0", atype="EXIT_STATUS")
        r = comp.compare(ora, b"0", cand, b"0")
        assert r.result.value == "MATCH"

    def test_identical_text_file(self):
        comp = self.registry.get("TEXT_FILE")
        ora = _art("ora", "ORACLE", b"line1\nline2", atype="TEXT_FILE")
        cand = _art("cand", "CANDIDATE", b"line1\nline2", atype="TEXT_FILE")
        r = comp.compare(ora, b"line1\nline2", cand, b"line1\nline2")
        assert r.result.value == "MATCH"

    def test_identical_fixed_record(self):
        comp = self.registry.get("FIXED_RECORD")
        ora = _art("ora", "ORACLE", b"AAAABBBB", atype="FIXED_RECORD", rc=2)
        cand = _art("cand", "CANDIDATE", b"AAAABBBB", atype="FIXED_RECORD", rc=2)
        r = comp.compare(ora, b"AAAABBBB", cand, b"AAAABBBB")
        assert r.result.value == "MATCH"


class TestVerdictDerivationInvariants:
    """Property: verdict derivation is a pure function with deterministic outcomes."""

    def test_all_match_produces_verified(self):
        """All MATCH comparisons → VERIFIED."""
        from engine.domain.identities import (
            CandidateIdentity,
            InputIdentity,
            OracleIdentity,
            RunId,
            SourceIdentity,
            WorkloadId,
        )
        from engine.evidence.models import (
            ArtifactEvidence,
            ComparisonEvidence,
            EvidenceManifest,
            ExecutionEvidence,
        )

        run_id = RunId(value="run-verified")
        oracle_exec = ExecutionEvidence(
            execution_id=ExecutionId(value="oracle-exec"),
            run_id=run_id, runtime_id="oracle-gnucobol-3.1.2",
            command="cobc -x prog", working_directory="/workspace",
            environment_variables={}, start_time="t0", end_time="t1",
            exit_code=0, stdout_hash=_hash("out"), stderr_hash=_hash("err"),
            generated_files={}, source_tree_hash_before=_hash("b"),
            source_tree_hash_after=_hash("a"),
            termination_status="normal", timeout_applied=False,
        )
        candidate_exec = ExecutionEvidence(
            execution_id=ExecutionId(value="candidate-exec"),
            run_id=run_id, runtime_id="candidate-java",
            command="java Main", working_directory="/workspace",
            environment_variables={}, start_time="t0", end_time="t1",
            exit_code=0, stdout_hash=_hash("out2"), stderr_hash=_hash("err2"),
            generated_files={}, source_tree_hash_before=_hash("b2"),
            source_tree_hash_after=_hash("a2"),
            termination_status="normal", timeout_applied=False,
        )

        oracle_art = ArtifactEvidence(
            artifact=ArtifactIdentity(
                artifact_id="art-o", artifact_type="STDOUT",
                logical_name="stdout-oracle", producer_role="ORACLE",
                content_hash=_hash("output"), size_bytes=6,
            ),
            execution_id=ExecutionId(value="oracle-exec"),
            capture_time="t1", content_hash=_hash("output"), size_bytes=6,
        )
        cand_art = ArtifactEvidence(
            artifact=ArtifactIdentity(
                artifact_id="art-c", artifact_type="STDOUT",
                logical_name="stdout-cand", producer_role="CANDIDATE",
                content_hash=_hash("output"), size_bytes=6,
            ),
            execution_id=ExecutionId(value="candidate-exec"),
            capture_time="t1", content_hash=_hash("output"), size_bytes=6,
        )

        comparison = ComparisonEvidence(
            comparison_id="comp-1", run_id=run_id,
            comparator_id="STDOUT_COMPARATOR", comparator_version="1.0.0",
            oracle_artifact_id="art-o", candidate_artifact_id="art-c",
            artifact_type="STDOUT", result="MATCH",
            normalization_applied=("crlf_to_lf",), differences=(),
            field_level_results=(), content_hash=_hash("comp-1"),
        )

        manifest = EvidenceManifest(
            manifest_version="1.0", run_id=run_id,
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
            execution_evidence=(oracle_exec, candidate_exec),
            artifact_evidence=(oracle_art, cand_art),
            comparison_evidence=(comparison,),
        )

        verdict = derive_verdict(manifest)
        assert verdict.state.value == "VERIFIED"
        assert verdict.executed_check_count == 1

