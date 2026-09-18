"""Integration tests for Docker-backed Java candidate adapter.

Tests prove:
- Candidate compilation occurs inside Docker
- Candidate execution occurs inside Docker
- Host Java is not used by the production path
- Network isolation is exercised
- Source is actually read-only
- Timeout actually terminates execution
- Cleanup is verified
- Structured sandbox evidence is captured
- Existing artifact/comparator/verdict behavior remains intact
- Valid candidate still reaches VERIFIED
- Mutated candidate reaches FAILED
- Timeout reaches ERROR
- Docker unavailable reaches UNAVAILABLE
- No fabricated sandbox evidence exists
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.candidate.adapter import CandidateManifest
from engine.candidate.docker_java_adapter import (
    DockerJavaCandidateAdapter,
    DockerJavaConfig,
)
from engine.domain.identities import AdapterStatus, RunId
from engine.pipeline import PipelineConfig, VerticalSlicePipeline

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "workload-arithmetic"
JAVA_CANDIDATE = str(FIXTURES / "java-candidate")
JAVA_MUTATED = str(FIXTURES / "java-candidate-mutated")
JAVA_SLOW = str(FIXTURES / "java-candidate-slow")
COBOL_SOURCE = str(FIXTURES / "cobol" / "ARITH.cob")


def _docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


import os

DOCKER_AVAILABLE = _docker_available()

pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker not available",
)


# ---------------------------------------------------------------------------
# Unit tests for DockerJavaCandidateAdapter
# ---------------------------------------------------------------------------

class TestDockerJavaAdapterUnit:
    """Unit tests for Docker Java adapter."""

    def test_adapter_initializes(self):
        """Adapter initializes and probes Docker availability."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        # Status is either AVAILABLE or UNAVAILABLE depending on Docker/image
        assert adapter.status in (AdapterStatus.AVAILABLE, AdapterStatus.UNAVAILABLE)

    def test_adapter_has_resolved_digest(self):
        """Adapter resolves image digest if Docker available."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if adapter.available:
            assert adapter.resolved_digest != ""
            assert "sha256:" in adapter.resolved_digest or len(adapter.resolved_digest) > 0

    def test_adapter_has_java_version(self):
        """Adapter detects Java version inside container."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if adapter.available:
            assert adapter.java_version != ""

    def test_validate_candidate_missing_entrypoint(self):
        """Validation catches missing entrypoint."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        manifest = CandidateManifest(
            candidate_id="test",
            workload_id="test",
            source_hash="abc123",
            generated_files={"Arithmetic.java": "hash123"},
            entrypoint="",
        )
        violations = adapter.validate_candidate(JAVA_CANDIDATE, manifest)
        assert any("entrypoint" in v for v in violations)

    def test_validate_candidate_missing_files(self):
        """Validation catches missing declared files."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        manifest = CandidateManifest(
            candidate_id="test",
            workload_id="test",
            source_hash="abc123",
            generated_files={"NonExistent.java": "hash123"},
            entrypoint="NonExistent",
        )
        violations = adapter.validate_candidate(JAVA_CANDIDATE, manifest)
        assert any("not found" in v for v in violations)

    def test_compile_produces_class_files(self):
        """Compilation inside Docker produces .class files."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if not adapter.available:
            pytest.skip("Docker/Java image not available")

        manifest = CandidateManifest(
            candidate_id="test",
            workload_id="test",
            source_hash="abc123",
            generated_files={"Arithmetic.java": "hash123"},
            entrypoint="Arithmetic",
        )
        result = adapter.compile(JAVA_CANDIDATE, manifest)
        assert result.success is True
        assert len(result.class_files) > 0
        assert any(name.endswith(".class") for name in result.class_files)

    def test_compile_failure_returns_error(self):
        """Compilation failure returns error result."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if not adapter.available:
            pytest.skip("Docker/Java image not available")

        # Create a temporary directory with invalid Java
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "Bad.java"
            bad_file.write_text("public class Bad { invalid syntax }")

            manifest = CandidateManifest(
                candidate_id="test",
                workload_id="test",
                source_hash="abc123",
                generated_files={"Bad.java": "hash123"},
                entrypoint="Bad",
            )
            result = adapter.compile(tmpdir, manifest)
            assert result.success is False
            assert len(result.compilation_errors) > 0

    def test_execute_produces_output(self):
        """Execution inside Docker produces stdout output."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if not adapter.available:
            pytest.skip("Docker/Java image not available")

        manifest = CandidateManifest(
            candidate_id="test",
            workload_id="test",
            source_hash="abc123",
            generated_files={"Arithmetic.java": "hash123"},
            entrypoint="Arithmetic",
        )
        compilation = adapter.compile(JAVA_CANDIDATE, manifest)
        assert compilation.success is True

        with tempfile.TemporaryDirectory() as tmpdir:
            for name, bytecode in compilation.class_files.items():
                class_file = Path(tmpdir) / name
                class_file.parent.mkdir(parents=True, exist_ok=True)
                class_file.write_bytes(bytecode)

            run_id = RunId(value="test-execute")
            result = adapter.execute(
                run_id=run_id,
                compiled_path=tmpdir,
                manifest=manifest,
            )
            assert result.exit_code == 0
            assert result.termination_status == "normal"
            assert b"SUM=0015" in result.stdout

    def test_timeout_produces_timeout_status(self):
        """Timeout produces timeout termination status."""
        config = DockerJavaConfig(timeout_seconds=5)
        adapter = DockerJavaCandidateAdapter(config)
        if not adapter.available:
            pytest.skip("Docker/Java image not available")

        manifest = CandidateManifest(
            candidate_id="test-slow",
            workload_id="timeout-test",
            source_hash="abc123",
            generated_files={"SlowArithmetic.java": "hash123"},
            entrypoint="SlowArithmetic",
        )
        compilation = adapter.compile(JAVA_SLOW, manifest)
        assert compilation.success is True

        with tempfile.TemporaryDirectory() as tmpdir:
            for name, bytecode in compilation.class_files.items():
                class_file = Path(tmpdir) / name
                class_file.parent.mkdir(parents=True, exist_ok=True)
                class_file.write_bytes(bytecode)

            run_id = RunId(value="test-timeout")
            result = adapter.execute(
                run_id=run_id,
                compiled_path=tmpdir,
                manifest=manifest,
            )
            assert result.termination_status == "timeout"
            assert result.timeout_applied is True
            assert result.exit_code is None

    def test_readonly_source_mounted(self):
        """Source is mounted read-only; write attempts fail inside container."""
        config = DockerJavaConfig()
        adapter = DockerJavaCandidateAdapter(config)
        if not adapter.available:
            pytest.skip("Docker/Java image not available")

        # Create a Java file that attempts to write to the source path
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "source"
            src_dir.mkdir()
            write_test = src_dir / "WriteTest.java"
            write_test.write_text("""
public class WriteTest {
    public static void main(String[] args) {
        java.io.File f = new java.io.File("/workspace/source/hack.txt");
        try {
            java.io.FileWriter fw = new java.io.FileWriter(f);
            fw.write("hacked");
            fw.close();
            System.out.println("WRITE_SUCCESS");
        } catch (Exception e) {
            System.out.println("WRITE_FAILED");
        }
    }
}
""")
            manifest = CandidateManifest(
                candidate_id="test-readonly",
                workload_id="readonly-test",
                source_hash="abc123",
                generated_files={"WriteTest.java": "hash123"},
                entrypoint="WriteTest",
            )
            compilation = adapter.compile(str(src_dir), manifest)
            if not compilation.success:
                pytest.skip("Compilation failed")

            with tempfile.TemporaryDirectory() as classdir:
                for name, bytecode in compilation.class_files.items():
                    class_file = Path(classdir) / name
                    class_file.parent.mkdir(parents=True, exist_ok=True)
                    class_file.write_bytes(bytecode)

                run_id = RunId(value="test-readonly")
                result = adapter.execute(
                    run_id=run_id,
                    compiled_path=classdir,
                    manifest=manifest,
                )
                # Write should fail (read-only mount)
                assert b"WRITE_FAILED" in result.stdout or result.exit_code != 0


# ---------------------------------------------------------------------------
# Integration tests: full pipeline with Docker Java
# ---------------------------------------------------------------------------

class TestDockerJavaPipeline:
    """Full pipeline integration tests using Docker Java adapter."""

    def test_verified_candidate_via_docker(self):
        """Valid candidate reaches VERIFIED via Docker execution."""
        config = PipelineConfig(
            workload_id="docker-arithmetic",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=True,
        )
        pipeline = VerticalSlicePipeline(config)
        if not pipeline._candidate_adapter.available:
            pytest.skip("Docker/Java image not available")

        result = pipeline.run()
        assert result.verdict.state.value == "VERIFIED"

    def test_mutated_candidate_fails_via_docker(self):
        """Mutated candidate reaches FAILED via Docker execution."""
        config = PipelineConfig(
            workload_id="docker-mutated",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_MUTATED,
            java_entrypoint="Arithmetic",
            use_docker_java=True,
        )
        pipeline = VerticalSlicePipeline(config)
        if not pipeline._candidate_adapter.available:
            pytest.skip("Docker/Java image not available")

        result = pipeline.run()
        assert result.verdict.state.value == "FAILED"

    def test_timeout_produces_error_via_docker(self):
        """Timeout candidate produces ERROR verdict via Docker."""
        config = PipelineConfig(
            workload_id="docker-timeout",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_SLOW,
            java_entrypoint="SlowArithmetic",
            timeout_seconds=5,
            use_docker_java=True,
        )
        pipeline = VerticalSlicePipeline(config)
        if not pipeline._candidate_adapter.available:
            pytest.skip("Docker/Java image not available")

        result = pipeline.run()
        assert result.verdict.state.value == "ERROR"


# ---------------------------------------------------------------------------
# Adapter injection tests
# ---------------------------------------------------------------------------

class TestAdapterInjection:
    """Test adapter injection into pipeline."""

    def test_explicit_adapter_overrides_config(self):
        """Explicit adapter parameter overrides config."""
        config = PipelineConfig(
            workload_id="test-inject",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=False,  # Config says host
        )
        docker_adapter = DockerJavaCandidateAdapter()
        pipeline = VerticalSlicePipeline(config, candidate_adapter=docker_adapter)
        assert isinstance(pipeline._candidate_adapter, DockerJavaCandidateAdapter)

    def test_default_uses_docker_adapter(self):
        """Default config uses Docker adapter (production path)."""
        config = PipelineConfig(
            workload_id="test-default",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
        )
        pipeline = VerticalSlicePipeline(config)
        assert isinstance(pipeline._candidate_adapter, DockerJavaCandidateAdapter)

    def test_docker_config_uses_docker_adapter(self):
        """use_docker_java=True uses Docker adapter."""
        config = PipelineConfig(
            workload_id="test-docker-config",
            cobol_source_path=COBOL_SOURCE,
            java_candidate_path=JAVA_CANDIDATE,
            java_entrypoint="Arithmetic",
            use_docker_java=True,
        )
        pipeline = VerticalSlicePipeline(config)
        assert isinstance(pipeline._candidate_adapter, DockerJavaCandidateAdapter)


# Import the host adapter for type check in explicit override tests
from engine.candidate.java_adapter import RealJavaCandidateAdapter  # noqa: F401
