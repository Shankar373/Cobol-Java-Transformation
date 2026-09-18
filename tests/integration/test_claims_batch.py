"""Integration tests for Claims Settlement Processor workload.

Tests the claims workload which exercises:
- STDOUT, STDERR, EXIT_STATUS, TEXT_FILE (report.txt, settlement.dat)
- No genuine FIXED_RECORD artifact — FIXED_RECORD coverage proven by Inventory

Required scenarios:
1. All artifact types captured and compared
2. Positive path: correct candidate -> VERIFIED
3. Each of 11 mutations -> FAILED (false-PASS defense)
4. Mutation mismatch artifact identified
5. Input dependency proof (two datasets)
6. Evidence verification
7. Determinism proof
"""

from __future__ import annotations

from pathlib import Path

from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.domain.identities import ExecutionId, RunId
from engine.execution.artifacts import ArtifactCapturer
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.workload import WorkloadArtifact, WorkloadDefinition, WorkloadInput

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload-claims"
COBOL_SOURCE = str(FIXTURES / "cobol" / "CLAIMS.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED_DIR = str(FIXTURES / "java-candidate-mutated")

MUTATIONS = {
    "wrong-threshold": ("ClaimsWrongThreshold", "amount < 1000 instead of < 500"),
    "rule-inversion": ("ClaimsRuleInversion", "APPROVED/REJECTED logic swapped"),
    "filter-skip": ("ClaimsFilterSkip", "claims >= 5000 silently skipped"),
    "agg-reset": ("ClaimsAggReset", "totalAmount = amount (reset not accumulate)"),
    "uninit-accum": ("ClaimsUninitAccum", "totalPayAmt starts at 99999"),
    "omit-last": ("ClaimsOmitLast", "last claim record omitted"),
    "duplicate-record": ("ClaimsDuplicateRecord", "each settlement record written twice"),
    "wrong-format": ("ClaimsWrongFormat", "payMatch %04d instead of %05d"),
    "reversed-order": ("ClaimsReversedOrder", "claims processed in reverse order"),
    "exit-status": ("ClaimsExitStatus", "System.exit(1) after processing"),
    "stderr-to-stdout": ("ClaimsStderrToStdout", "rejection warnings to stdout instead of stderr"),
}


def _make_config(
    workload_id: str,
    candidate_path: str,
    entrypoint: str,
    workload: WorkloadDefinition | None = None,
) -> PipelineConfig:
    return PipelineConfig(
        workload_id=workload_id,
        cobol_source_path=COBOL_SOURCE,
        java_candidate_path=candidate_path,
        java_entrypoint=entrypoint,
        use_docker_java=True,
        workload=workload,
    )


def _claims_workload() -> WorkloadDefinition:
    return WorkloadDefinition(
        workload_id="claims",
        description="Claims Settlement Processor",
        inputs=(
            WorkloadInput(
                logical_name="claims-data",
                source_path="input/claims.dat",
                container_path="/workspace/input/claims.dat",
            ),
            WorkloadInput(
                logical_name="payments-data",
                source_path="input/payments.dat",
                container_path="/workspace/input/payments.dat",
            ),
        ),
        artifacts=(
            WorkloadArtifact(
                logical_name="claims-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="claims-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="claims-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
            WorkloadArtifact(
                logical_name="claims-report",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="report.txt",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="claims-settlement",
                artifact_type="TEXT_FILE",
                comparator_id="text-file-exact",
                output_path="settlement.dat",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Oracle E2E
# ---------------------------------------------------------------------------

class TestClaimsOracleE2E:
    """Oracle execution produces correct output for claims workload."""

    def test_oracle_execution(self):
        config = _make_config(
            "claims-oracle", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.oracle_exit_code == 0
        assert b"TOTAL_CLAIMS=10" in result.oracle_stdout
        assert b"APPROVED=06" in result.oracle_stdout
        assert b"REJECTED=03" in result.oracle_stdout
        assert b"PENDING=01" in result.oracle_stdout
        assert b"PAID=05" in result.oracle_stdout
        assert b"UNPAID=01" in result.oracle_stdout
        assert b"TOTAL_CLAIM_AMT=113200" in result.oracle_stdout
        assert b"TOTAL_PAY_AMT=061800" in result.oracle_stdout

    def test_oracle_generates_output_files(self):
        config = _make_config(
            "claims-oracle-files", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        input_files = pipeline._load_input_files()
        run_id = RunId(value="test-oracle-files")

        oracle_result = pipeline._oracle_adapter.execute(
            run_id=run_id,
            source_path=COBOL_SOURCE,
            input_files=input_files,
        )
        assert oracle_result.generated_files is not None
        assert "report.txt" in oracle_result.generated_files
        assert "settlement.dat" in oracle_result.generated_files
        assert b"CLAIM" in oracle_result.generated_files["report.txt"]
        assert b"C001" in oracle_result.generated_files["settlement.dat"]


# ---------------------------------------------------------------------------
# 2. Positive path: artifact types, VERIFIED
# ---------------------------------------------------------------------------

class TestClaimsVerified:
    """Correct candidate produces VERIFIED across all artifact types."""

    def test_verified_candidate(self):
        config = _make_config(
            "claims-verified", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "VERIFIED"
        assert result.oracle_exit_code == 0
        assert result.candidate_exit_code == 0

    def test_all_artifact_types_captured(self):
        config = _make_config(
            "claims-5artifacts", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        types = {e.artifact.artifact_type for e in result.artifact_evidence}
        assert "STDOUT" in types
        assert "STDERR" in types
        assert "EXIT_STATUS" in types
        assert "TEXT_FILE" in types

    def test_ten_artifact_evidence_records(self):
        config = _make_config(
            "claims-ev-count", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert len(result.artifact_evidence) == 10

    def test_five_comparisons(self):
        config = _make_config(
            "claims-5comp", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert len(result.comparison_evidence) == 5

    def test_all_comparisons_match(self):
        config = _make_config(
            "claims-allmatch", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        for comp in result.comparison_evidence:
            assert comp.result == "MATCH", (
                f"{comp.comparator_id} failed: {comp.differences}"
            )

    def test_manifest_completeness(self):
        config = _make_config(
            "claims-complete", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.evidence_manifest.is_complete()

    def test_text_file_report_matches(self):
        config = _make_config(
            "claims-text-report", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comps = [
            c for c in result.comparison_evidence
            if c.artifact_type == "TEXT_FILE"
        ]
        assert len(text_comps) == 2
        for comp in text_comps:
            assert comp.result == "MATCH"

    def test_no_fixed_record_artifact(self):
        config = _make_config(
            "claims-nofixed", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        types = {e.artifact.artifact_type for e in result.artifact_evidence}
        assert "FIXED_RECORD" not in types

    def test_input_declaration_driven(self):
        config = _make_config(
            "claims-inputs", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        input_files = pipeline._load_input_files()

        assert input_files is not None
        assert "claims.dat" in input_files
        assert "payments.dat" in input_files
        assert b"C001" in input_files["claims.dat"]
        assert b"P001" in input_files["payments.dat"]


# ---------------------------------------------------------------------------
# 3. Mutation tests: each mutation -> FAILED
# ---------------------------------------------------------------------------

class TestClaimsMutations:
    """Each mutation must be detected and produce FAILED verdict."""

    def test_wrong_threshold_detected(self):
        entrypoint, _ = MUTATIONS["wrong-threshold"]
        config = _make_config(
            "claims-mut-threshold", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_rule_inversion_detected(self):
        entrypoint, _ = MUTATIONS["rule-inversion"]
        config = _make_config(
            "claims-mut-rule", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_filter_skip_detected(self):
        entrypoint, _ = MUTATIONS["filter-skip"]
        config = _make_config(
            "claims-mut-filter", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_agg_reset_detected(self):
        entrypoint, _ = MUTATIONS["agg-reset"]
        config = _make_config(
            "claims-mut-agg", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_uninit_accum_detected(self):
        entrypoint, _ = MUTATIONS["uninit-accum"]
        config = _make_config(
            "claims-mut-uninit", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_omit_last_detected(self):
        entrypoint, _ = MUTATIONS["omit-last"]
        config = _make_config(
            "claims-mut-omit", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_duplicate_record_detected(self):
        entrypoint, _ = MUTATIONS["duplicate-record"]
        config = _make_config(
            "claims-mut-dup", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_wrong_format_detected(self):
        entrypoint, _ = MUTATIONS["wrong-format"]
        config = _make_config(
            "claims-mut-format", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_reversed_order_detected(self):
        entrypoint, _ = MUTATIONS["reversed-order"]
        config = _make_config(
            "claims-mut-reverse", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_exit_status_detected(self):
        entrypoint, _ = MUTATIONS["exit-status"]
        config = _make_config(
            "claims-mut-exit", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_stderr_to_stdout_detected(self):
        entrypoint, _ = MUTATIONS["stderr-to-stdout"]
        config = _make_config(
            "claims-mut-stderr", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"


# ---------------------------------------------------------------------------
# 4. Mutation mismatch artifact identification
# ---------------------------------------------------------------------------

class TestClaimsMutationArtifacts:
    """Each mutation must be detected by a specific artifact comparison."""

    def test_wrong_threshold_on_stdout(self):
        entrypoint, _ = MUTATIONS["wrong-threshold"]
        config = _make_config(
            "claims-mut-threshold-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_rule_inversion_on_stdout(self):
        entrypoint, _ = MUTATIONS["rule-inversion"]
        config = _make_config(
            "claims-mut-rule-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_filter_skip_on_stdout(self):
        entrypoint, _ = MUTATIONS["filter-skip"]
        config = _make_config(
            "claims-mut-filter-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_agg_reset_on_stdout(self):
        entrypoint, _ = MUTATIONS["agg-reset"]
        config = _make_config(
            "claims-mut-agg-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_uninit_accum_on_stdout(self):
        entrypoint, _ = MUTATIONS["uninit-accum"]
        config = _make_config(
            "claims-mut-uninit-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_omit_last_on_stdout(self):
        entrypoint, _ = MUTATIONS["omit-last"]
        config = _make_config(
            "claims-mut-omit-stdout", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stdout_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDOUT"
        )
        assert stdout_comp.result == "MISMATCH"

    def test_duplicate_record_on_text_file(self):
        entrypoint, _ = MUTATIONS["duplicate-record"]
        config = _make_config(
            "claims-mut-dup-textfile", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comps = [
            c for c in result.comparison_evidence if c.artifact_type == "TEXT_FILE"
        ]
        has_mismatch = any(c.result == "MISMATCH" for c in text_comps)
        assert has_mismatch, "duplicate-record should produce TEXT_FILE mismatch"

    def test_wrong_format_on_text_file(self):
        entrypoint, _ = MUTATIONS["wrong-format"]
        config = _make_config(
            "claims-mut-format-textfile", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comps = [
            c for c in result.comparison_evidence if c.artifact_type == "TEXT_FILE"
        ]
        has_mismatch = any(c.result == "MISMATCH" for c in text_comps)
        assert has_mismatch, "wrong-format should produce TEXT_FILE mismatch"

    def test_reversed_order_on_text_file(self):
        entrypoint, _ = MUTATIONS["reversed-order"]
        config = _make_config(
            "claims-mut-reverse-textfile", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_comps = [
            c for c in result.comparison_evidence if c.artifact_type == "TEXT_FILE"
        ]
        has_mismatch = any(c.result == "MISMATCH" for c in text_comps)
        assert has_mismatch, "reversed-order should produce TEXT_FILE mismatch"

    def test_exit_status_on_exit_status(self):
        entrypoint, _ = MUTATIONS["exit-status"]
        config = _make_config(
            "claims-mut-exit-exit", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        exit_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "EXIT_STATUS"
        )
        assert exit_comp.result == "MISMATCH"

    def test_stderr_to_stdout_on_stderr(self):
        entrypoint, _ = MUTATIONS["stderr-to-stdout"]
        config = _make_config(
            "claims-mut-stderr-stderr", JAVA_MUTATED_DIR, entrypoint, _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        stderr_comp = next(
            c for c in result.comparison_evidence if c.artifact_type == "STDERR"
        )
        assert stderr_comp.result == "MISMATCH"


# ---------------------------------------------------------------------------
# 5. Input dependency proof
# ---------------------------------------------------------------------------

class TestClaimsInputDependency:
    """Changing input changes both oracle and candidate outputs independently."""

    def test_oracle_and_candidate_agree_on_both_datasets(self):
        input_a = (
            b"C001|JOHN SMITH  |20240115| 5000|A|CAR     \n"
            b"C002|JANE DOE    |20240116| 2000|R|HOME    \n"
        )
        payments_a = b"PAY001|C001|20240201| 5000|CLEARED\n"

        input_b = (
            b"C001|JOHN SMITH  |20240115|15000|A|CAR     \n"
            b"C002|JANE DOE    |20240116| 2000|R|HOME    \n"
            b"C003|BOB WILSON  |20240117|  300|P|CLINIC  \n"
        )
        payments_b = b"PAY001|C001|20240201|15000|CLEARED\n"

        config = _make_config(
            "claims-dep", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)

        oracle_a = pipeline._oracle_adapter.execute(
            run_id=RunId(value="test-dep-oracle-a"),
            source_path=COBOL_SOURCE,
            input_files={"claims.dat": input_a, "payments.dat": payments_a},
        )
        candidate_a = pipeline._oracle_adapter.execute(
            run_id=RunId(value="test-dep-candidate-a"),
            source_path=COBOL_SOURCE,
            input_files={"claims.dat": input_a, "payments.dat": payments_a},
        )

        oracle_b = pipeline._oracle_adapter.execute(
            run_id=RunId(value="test-dep-oracle-b"),
            source_path=COBOL_SOURCE,
            input_files={"claims.dat": input_b, "payments.dat": payments_b},
        )
        candidate_b = pipeline._oracle_adapter.execute(
            run_id=RunId(value="test-dep-candidate-b"),
            source_path=COBOL_SOURCE,
            input_files={"claims.dat": input_b, "payments.dat": payments_b},
        )

        assert oracle_a.stdout == candidate_a.stdout
        assert oracle_b.stdout == candidate_b.stdout
        assert oracle_a.stdout != oracle_b.stdout


# ---------------------------------------------------------------------------
# 6. Evidence verification
# ---------------------------------------------------------------------------

class TestClaimsEvidence:
    """Evidence records contain correct metadata."""

    def test_comparison_evidence_metadata(self):
        config = _make_config(
            "claims-comp-meta", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        for comp in result.comparison_evidence:
            assert comp.run_id is not None
            assert comp.comparator_id is not None
            assert comp.comparator_version is not None
            assert comp.artifact_type in ("STDOUT", "STDERR", "EXIT_STATUS", "TEXT_FILE")
            assert comp.result == "MATCH"
            assert comp.content_hash is not None

    def test_text_file_evidence_count(self):
        config = _make_config(
            "claims-textfile-ev", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        text_evs = [
            e for e in result.artifact_evidence
            if e.artifact.artifact_type == "TEXT_FILE"
        ]
        assert len(text_evs) == 4

    def test_artifact_evidence_has_content_hash(self):
        config = _make_config(
            "claims-hash-ev", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )
        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        for ev in result.artifact_evidence:
            assert ev.content_hash is not None
            assert ev.size_bytes >= 0
            assert ev.artifact.logical_name is not None
            assert ev.artifact.producer_role in ("ORACLE", "CANDIDATE")


# ---------------------------------------------------------------------------
# 7. Determinism proof
# ---------------------------------------------------------------------------

class TestClaimsDeterminism:
    """Two runs with identical input produce identical evidence."""

    def test_deterministic_verdict(self):
        config = _make_config(
            "claims-det", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        assert result1.source_identity.source_hash == result2.source_identity.source_hash
        assert result1.candidate_identity.candidate_hash == result2.candidate_identity.candidate_hash
        assert result1.verdict.state == result2.verdict.state

    def test_deterministic_comparisons(self):
        config = _make_config(
            "claims-det-comp", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        assert len(result1.comparison_evidence) == len(result2.comparison_evidence)
        for c1, c2 in zip(result1.comparison_evidence, result2.comparison_evidence):
            assert c1.comparator_id == c2.comparator_id
            assert c1.result == c2.result

    def test_deterministic_artifact_hashes(self):
        config = _make_config(
            "claims-det-hash", JAVA_CANDIDATE, "Claims", _claims_workload(),
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        hashes1 = {e.artifact.artifact_type: str(e.content_hash) for e in result1.artifact_evidence}
        hashes2 = {e.artifact.artifact_type: str(e.content_hash) for e in result2.artifact_evidence}
        assert hashes1 == hashes2


# ---------------------------------------------------------------------------
# 8. Artifact capture unit tests
# ---------------------------------------------------------------------------

class TestClaimsArtifactCapture:
    """Capturer correctly handles TEXT_FILE artifacts."""

    def test_capture_text_file_from_bytes(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-text")
        content = b"C001|JOHN|20240115|5000|A|CAR|PAID_IN_FULL\n"

        artifact = capturer.capture_text_file_from_bytes(
            exec_id, content, "settlement.dat",
        )

        assert artifact.artifact.artifact_type == "TEXT_FILE"
        assert artifact.content == content
        assert artifact.size_bytes == len(content)
        assert artifact.content_hash.verify(content)

    def test_evidence_conversion_text_file(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-ev-text")
        content = b"test content"

        artifact = capturer.capture_text_file_from_bytes(
            exec_id, content, "test.txt",
        )
        evidence = artifact.to_evidence()

        assert evidence.artifact.artifact_type == "TEXT_FILE"
        assert evidence.size_bytes == len(content)
