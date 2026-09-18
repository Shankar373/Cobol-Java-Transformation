"""Integration tests for the first vertical slice.

Tests real execution paths:
- Real Docker GnuCOBOL oracle execution
- Real javac/java candidate execution
- Real artifact capture
- Real typed comparator execution
- Real evidence manifest generation
- Real verdict derivation
- Mutation validation
- Negative paths
- Reproducibility
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.candidate.java_adapter import RealJavaCandidateAdapter
from engine.domain.identities import (
    AdapterStatus,
    ContentHash,
    ExecutionId,
    RunId,
)
from engine.execution.artifacts import ArtifactCapturer
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.pipeline import PipelineConfig, VerticalSlicePipeline

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workload-arithmetic"
COBOL_SOURCE = str(FIXTURES / "cobol" / "ARITH.cob")
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_CANDIDATE_MUTATED = str(FIXTURES / "java-candidate-mutated")


# ---------------------------------------------------------------------------
# ORACLE E2E
# ---------------------------------------------------------------------------

class TestOracleE2E:
    """Real Docker GnuCOBOL execution tests."""

    def test_oracle_adapter_probe(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
        )
        adapter = DockerOracleAdapter(config)
        status = adapter.probe()
        assert status in (AdapterStatus.AVAILABLE, AdapterStatus.UNAVAILABLE)

    def test_oracle_real_execution(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=60,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-oracle-e2e")

        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)

        assert result.exit_code == 0
        assert result.termination_status == "normal"
        assert b"SUM=0015" in result.stdout
        assert b"DIFF=0005" in result.stdout
        assert b"PROD=00000050" in result.stdout
        assert result.source_tree_hash_before is not None
        assert result.source_tree_hash_after is not None

    def test_oracle_source_hash_integrity(self):
        config = OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2",
            image_digest="sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780",
            compiler_version="3.1.2.0",
            timeout_seconds=60,
        )
        adapter = DockerOracleAdapter(config)
        run_id = RunId(value="test-oracle-hash")

        result = adapter.execute(run_id=run_id, source_path=COBOL_SOURCE)

        assert result.source_tree_hash_before == result.source_tree_hash_after


# ---------------------------------------------------------------------------
# JAVA E2E
# ---------------------------------------------------------------------------

class TestJavaE2E:
    """Real javac/java execution tests."""

    def test_java_adapter_probe(self):
        adapter = RealJavaCandidateAdapter()
        status = adapter.probe()
        assert status in (AdapterStatus.AVAILABLE, AdapterStatus.UNAVAILABLE)

    def test_java_compilation(self):
        adapter = RealJavaCandidateAdapter()
        from engine.candidate.adapter import CandidateManifest

        manifest = CandidateManifest(
            candidate_id="test-candidate",
            workload_id="test-workload",
            source_hash="abc123",
            generated_files={"Arithmetic.java": "hash123"},
            entrypoint="Arithmetic",
        )

        result = adapter.compile(JAVA_CANDIDATE, manifest)

        assert result.success is True
        assert len(result.class_files) > 0

    def test_java_execution(self):
        adapter = RealJavaCandidateAdapter()
        from engine.candidate.adapter import CandidateManifest

        manifest = CandidateManifest(
            candidate_id="test-candidate",
            workload_id="test-workload",
            source_hash="abc123",
            generated_files={"Arithmetic.java": "hash123"},
            entrypoint="Arithmetic",
        )

        compilation = adapter.compile(JAVA_CANDIDATE, manifest)
        assert compilation.success is True

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, bytecode in compilation.class_files.items():
                class_file = Path(tmpdir) / name
                class_file.parent.mkdir(parents=True, exist_ok=True)
                class_file.write_bytes(bytecode)

            run_id = RunId(value="test-java-e2e")
            result = adapter.execute(
                run_id=run_id,
                compiled_path=tmpdir,
                manifest=manifest,
            )

            assert result.exit_code == 0
            assert result.termination_status == "normal"
            assert b"SUM=0015" in result.stdout
            assert b"DIFF=0005" in result.stdout


# ---------------------------------------------------------------------------
# DIFFERENTIAL E2E
# ---------------------------------------------------------------------------

class TestDifferentialE2E:
    """End-to-end differential validation tests."""

    def test_verified_candidate(self):
        config = PipelineConfig(
            workload_id="test-differential",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=False,
        )

        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "VERIFIED"
        assert result.oracle_exit_code == 0
        assert result.candidate_exit_code == 0
        assert len(result.artifact_evidence) == 6
        assert len(result.comparison_evidence) == 3

        for comp in result.comparison_evidence:
            assert comp.result == "MATCH"

    def test_manifest_completeness(self):
        config = PipelineConfig(
            workload_id="test-manifest",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=False,
        )

        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.evidence_manifest.is_complete()
        assert result.evidence_manifest.manifest_version == "1.0"
        assert result.evidence_manifest.run_id == result.run_id
        assert result.evidence_manifest.workload_id == result.workload_id


# ---------------------------------------------------------------------------
# MUTATION E2E
# ---------------------------------------------------------------------------

class TestMutationE2E:
    """Real mutation detection through production path."""

    def test_mutated_candidate_detected(self):
        config = PipelineConfig(
            workload_id="test-mutation",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE_MUTATED,
            java_entrypoint="Arithmetic",
            use_docker_java=False,
        )

        pipeline = VerticalSlicePipeline(config)
        result = pipeline.run()

        assert result.verdict.state.value == "FAILED"
        assert result.oracle_exit_code == 0
        assert result.candidate_exit_code == 0

        stdout_comp = next(
            c for c in result.comparison_evidence if c.comparator_id == "stdout-exact"
        )
        assert stdout_comp.result == "MISMATCH"


# ---------------------------------------------------------------------------
# NEGATIVE E2E
# ---------------------------------------------------------------------------

class TestNegativeE2E:
    """Negative path tests through production paths."""

    def test_invalid_contract_no_contract(self):
        from engine.contracts.models import ContractRegistry
        from engine.contracts.validator import (
            ContractValidationError,
            ContractValidator,
            NoContractError,
        )

        registry = ContractRegistry()
        validator = ContractValidator(registry=registry)
        with pytest.raises((NoContractError, ContractValidationError)):
            validator.require_all_contracts()

    def test_unsupported_artifact_type(self):
        from engine.domain.identities import ArtifactIdentity

        with pytest.raises(ValueError):
            ArtifactIdentity(
                artifact_id="test",
                artifact_type="UNSUPPORTED_TYPE",
                logical_name="test",
                producer_role="ORACLE",
                content_hash=ContentHash.from_bytes(b"test"),
                size_bytes=4,
            )

    def test_wrong_hash_detection(self):

        correct_hash = ContentHash.from_bytes(b"test data")
        wrong_hash = ContentHash.from_bytes(b"different data")

        assert correct_hash != wrong_hash
        assert not wrong_hash.verify(b"test data")

    def test_timeout_error_state(self):
        from engine.domain.identities import (
            InputIdentity,
            OracleIdentity,
            RunId,
            SourceIdentity,
            WorkloadId,
        )
        from engine.evidence.models import EvidenceManifest
        from engine.verdict.derivation import VerdictDeriver

        manifest = EvidenceManifest(
            manifest_version="1.0",
            run_id=RunId(value="test-timeout"),
            workload_id=WorkloadId(value="test-timeout"),
            source_identity=SourceIdentity(
                source_id="src",
                source_hash=ContentHash.from_bytes(b"src"),
                file_count=1,
                total_size_bytes=3,
            ),
            candidate_identity=None,
            oracle_identity=OracleIdentity(
                oracle_id="gnucobol-3.1.2",
                image_digest="sha256:" + "a" * 64,
                compiler_version="3.1.2.0",
            ),
            environment_identities=(),
            controlled_input=InputIdentity(input_id="inp"),
            execution_evidence=(),
            artifact_evidence=(),
            comparison_evidence=(),
        )

        deriver = VerdictDeriver()
        verdict = deriver.derive(manifest)
        assert verdict.state.value in ("UNPROVEN", "UNAVAILABLE", "ERROR")

    def test_real_timeout_produces_error_verdict(self):
        """Real timeout test: Java process exceeds configured timeout."""
        from engine.candidate.adapter import CandidateManifest
        from engine.candidate.java_adapter import RealJavaCandidateAdapter

        SLOW_JAVA = str(FIXTURES / "java-candidate-slow")

        adapter = RealJavaCandidateAdapter()
        if not adapter.available:
            pytest.skip("Java not available")

        manifest = CandidateManifest(
            candidate_id="slow-candidate",
            workload_id="timeout-test",
            source_hash="abc123",
            generated_files={"SlowArithmetic.java": "hash123"},
            entrypoint="SlowArithmetic",
        )

        compilation = adapter.compile(SLOW_JAVA, manifest)
        assert compilation.success is True

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, bytecode in compilation.class_files.items():
                class_file = Path(tmpdir) / name
                class_file.parent.mkdir(parents=True, exist_ok=True)
                class_file.write_bytes(bytecode)

            run_id = RunId(value="test-real-timeout")
            result = adapter.execute(
                run_id=run_id,
                compiled_path=tmpdir,
                manifest=manifest,
            )

            assert result.termination_status == "timeout"
            assert result.timeout_applied is True
            assert result.exit_code is None
            assert b"timeout" in result.stderr.lower() or result.stdout == b""


# ---------------------------------------------------------------------------
# REPRODUCIBILITY
# ---------------------------------------------------------------------------

class TestReproducibility:
    """Reproducibility tests for the vertical slice."""

    def test_deterministic_verdict(self):
        config = PipelineConfig(
            workload_id="test-repro",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=False,
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        assert result1.source_identity.source_hash == result2.source_identity.source_hash
        assert result1.oracle_identity == result2.oracle_identity
        assert result1.candidate_identity.candidate_hash == result2.candidate_identity.candidate_hash
        assert result1.verdict.state == result2.verdict.state
        assert all(
            c1.result == c2.result
            for c1, c2 in zip(result1.comparison_evidence, result2.comparison_evidence)
        )

    def test_deterministic_comparisons(self):
        config = PipelineConfig(
            workload_id="test-repro-comp",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=False,
        )

        pipeline1 = VerticalSlicePipeline(config)
        result1 = pipeline1.run()

        pipeline2 = VerticalSlicePipeline(config)
        result2 = pipeline2.run()

        for c1, c2 in zip(result1.comparison_evidence, result2.comparison_evidence):
            assert c1.comparator_id == c2.comparator_id
            assert c1.result == c2.result
            assert c1.differences == c2.differences


# ---------------------------------------------------------------------------
# ARTIFACT CAPTURE
# ---------------------------------------------------------------------------

class TestArtifactCapture:
    """Real artifact capture tests."""

    def test_capture_stdout(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-stdout")
        content = b"SUM=0015\nDIFF=0005\n"

        artifact = capturer.capture_stdout(exec_id, content, "test-stdout")

        assert artifact.artifact.artifact_type == "STDOUT"
        assert artifact.content == content
        assert artifact.size_bytes == len(content)
        assert artifact.content_hash.verify(content)

    def test_capture_stderr(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-stderr")
        content = b"warning: unused variable"

        artifact = capturer.capture_stderr(exec_id, content, "test-stderr")

        assert artifact.artifact.artifact_type == "STDERR"
        assert artifact.content == content
        assert artifact.size_bytes == len(content)

    def test_capture_exit_status(self):
        capturer = ArtifactCapturer()
        exec_id = ExecutionId(value="test-capture-exit")

        artifact = capturer.capture_exit_status(exec_id, 0)

        assert artifact.artifact.artifact_type == "EXIT_STATUS"
        assert artifact.content == b"0"
        assert artifact.size_bytes == 1
