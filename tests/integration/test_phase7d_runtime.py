"""Phase 7D: Generated Spring Boot -> Maven -> Docker -> Real Behavioral Equivalence.

This module proves the FULL chain:
  COBOL source -> transformation -> generated Spring Boot project
  -> Maven build inside Docker -> JAR execution inside Docker
  -> artifact capture -> behavioral comparison -> VERIFIED

ABSOLUTE RULES:
- No fake execution, no synthetic evidence
- No pre-built Java candidate substitution for generated Spring Boot proof
- No host Maven, no host Java fallback
- No hardcoded VERIFIED/FAILED
- Docker is the production runtime boundary
- Existing DockerJavaCandidateAdapter remains unchanged
- Stop after Phase 7D
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

import pytest

from engine.candidate.adapter import CandidateManifest, CompilationResult
from engine.candidate.docker_spring_boot_adapter import (
    DockerSpringBootCandidateAdapter,
    DockerSpringBootConfig,
)
from engine.candidate.image_provenance import load_adapter_provenance
from engine.contracts.models import NormalizationPolicy, OrderingPolicy
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    RunId,
    VerdictState,
)
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.transformation.cobol_to_java_mapping import map_cobol_program_to_java
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_ir import JavaApplication
from engine.transformation.java_to_spring_mapping import map_java_application_to_spring_boot
from engine.transformation.spring_boot_generator import SpringBootGenerator
from engine.workload import WorkloadArtifact, WorkloadDefinition


ARITH_COBOL = Path("fixtures/workload-arithmetic/cobol/ARITH.cob")


def _oracle_config() -> OracleAdapterConfig:
    return OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2",
        image_digest=(
            "sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780"
        ),
        compiler_version="3.1.2.0",
        timeout_seconds=30,
    )


def _arith_workload() -> WorkloadDefinition:
    """Workload definition for ARITH arithmetic program."""
    return WorkloadDefinition(
        workload_id="arith",
        description="ARITH arithmetic validation workload",
        artifacts=(
            WorkloadArtifact(
                logical_name="arith-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="arith-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name="arith-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )


def _generate_springboot_project(cobol_path: Path) -> tuple[list, str]:
    """Run the full transformation chain and return (files, source_hash)."""
    source = cobol_path.read_text()
    source_hash = hashlib.sha256(source.encode()).hexdigest()

    parser = CobolParser()
    cobol_ir = parser.parse(source)
    java_prog = map_cobol_program_to_java(cobol_ir)

    java_app = JavaApplication(
        application_id=cobol_ir.program_id or "UNKNOWN",
        programs=(java_prog,),
        dependencies=(),
        shared_file_resources=(),
        shared_database_resources=(),
        shared_transaction_boundaries=(),
        source_paths=(str(cobol_path),),
    )

    spring_app = map_java_application_to_spring_boot(java_app)
    generator = SpringBootGenerator()
    files = generator.generate_project(spring_app)
    return files, source_hash


def _stage_project(files: list, source_hash: str) -> tuple[str, CandidateManifest]:
    """Write generated files to a temp directory and return (path, manifest)."""
    tmpdir = tempfile.mkdtemp(prefix="phase7d-test-")
    for f in files:
        fp = Path(tmpdir) / f.path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f.source_code)

    manifest = CandidateManifest(
        candidate_id="generated-springboot-arith",
        workload_id="arith",
        source_hash=source_hash,
        generated_files=[f.path for f in files],
        entrypoint="com.generated.app.Application",
        java_version="21",
        dependencies=["spring-boot-starter", "spring-context"],
    )
    return tmpdir, manifest


def _extract_app_output(raw: str) -> list[str]:
    """Extract application output lines, filtering out Spring Boot log noise."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") or s.startswith(".") or s.startswith("/"):
            continue
        if any(
            x in s
            for x in [
                "Spring Boot",
                "Started Application",
                "Starting Application",
                "No active profile",
                "====",
                "PID",
                "process running",
                "___",
                "replacing main",
            ]
        ):
            continue
        lines.append(s)
    return lines


def _normalize_numbers(text: str) -> str:
    """Strip leading zeros from numeric values for comparison."""
    return re.sub(r"=(\d+)", lambda m: "=" + (m.group(1).lstrip("0") or "0"), text)


# ============================================================
# CATEGORY A: Adapter Availability
# ============================================================


class TestAdapterAvailability:
    """Verify Docker Spring Boot adapter is operational."""

    def test_adapter_available(self):
        """DockerSpringBootCandidateAdapter reports AVAILABLE."""
        adapter = DockerSpringBootCandidateAdapter()
        assert adapter.status == AdapterStatus.AVAILABLE

    def test_build_digest_verified(self):
        """Build image identity matches the provisioned immutable identity."""
        adapter = DockerSpringBootCandidateAdapter()
        provenance = load_adapter_provenance()
        assert provenance.validate() == []
        assert "sha256:" in adapter.build_identity
        assert adapter.build_identity == provenance.build_identity
        assert adapter.build_identity_kind == provenance.build_identity_kind

    def test_runtime_digest_verified(self):
        """Runtime image digest matches configured value."""
        adapter = DockerSpringBootCandidateAdapter()
        provenance = load_adapter_provenance()
        assert provenance.runtime_identity == DockerSpringBootConfig().runtime_digest
        assert "sha256:" in adapter.runtime_identity
        assert adapter.runtime_identity == DockerSpringBootConfig().runtime_digest


# ============================================================
# CATEGORY B: Transformation Chain
# ============================================================


class TestTransformationChain:
    """Verify the transformation pipeline produces valid Spring Boot projects."""

    def test_generate_project_from_arith_cobol(self):
        """ARITH.cob transforms to 5 Spring Boot files."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        assert len(files) == 5
        paths = {f.path for f in files}
        assert "pom.xml" in paths
        assert any("Application.java" in p for p in paths)
        assert any("Arithmetic.java" in p for p in paths)

    def test_pom_has_spring_boot_dependencies(self):
        """Generated POM includes spring-boot-starter and spring-context."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        pom = next(f for f in files if f.path == "pom.xml")
        assert "spring-boot-starter" in pom.source_code
        assert "spring-context" in pom.source_code

    def test_entry_point_has_commandline_runner(self):
        """Generated Application.java has CommandLineRunner for batch execution."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        app = next(f for f in files if "Application.java" in f.path)
        assert "CommandLineRunner" in app.source_code
        assert "System.exit(0)" in app.source_code

    def test_service_has_field_declarations(self):
        """Generated service class has field declarations from COBOL working storage."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        svc = next(f for f in files if "Arithmetic.java" in f.path)
        assert "private int WS_A" in svc.source_code
        assert "private int WS_B" in svc.source_code
        assert "private int WS_SUM" in svc.source_code

    def test_service_has_compute_logic(self):
        """Generated service has COMPUTE logic (SUM, DIFF, PROD, QUOT, REM)."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        svc = next(f for f in files if "Arithmetic.java" in f.path)
        assert "WS_SUM = (WS_A + WS_B)" in svc.source_code
        assert "WS_DIFF = (WS_A - WS_B)" in svc.source_code
        assert "WS_PROD = (WS_A * WS_B)" in svc.source_code
        assert "WS_QUOT = (WS_A / WS_B)" in svc.source_code
        assert "WS_REM = (WS_A % WS_B)" in svc.source_code

    def test_service_has_if_else_logic(self):
        """Generated service has IF/ELSE comparison logic."""
        files, _ = _generate_springboot_project(ARITH_COBOL)
        svc = next(f for f in files if "Arithmetic.java" in f.path)
        assert "if ((WS_A > WS_B))" in svc.source_code
        assert 'System.out.println("A_GT_B=TRUE")' in svc.source_code
        assert 'System.out.println("A_GT_B=FALSE")' in svc.source_code

    def test_source_hash_deterministic(self):
        """Same COBOL source produces same hash."""
        _, h1 = _generate_springboot_project(ARITH_COBOL)
        _, h2 = _generate_springboot_project(ARITH_COBOL)
        assert h1 == h2


# ============================================================
# CATEGORY C: Maven Build Inside Docker
# ============================================================


class TestMavenBuild:
    """Verify Maven builds successfully inside Docker container."""

    @pytest.fixture
    def compile_result(self):
        """Compile ARITHMETIC project and return result."""
        adapter = DockerSpringBootCandidateAdapter()
        files, source_hash = _generate_springboot_project(ARITH_COBOL)
        tmpdir, manifest = _stage_project(files, source_hash)
        result = adapter.compile(candidate_path=tmpdir, manifest=manifest)
        return result, tmpdir

    def test_maven_compile_success(self, compile_result):
        """Maven compilation succeeds inside Docker."""
        result, _ = compile_result
        assert result.success is True
        assert result.compilation_errors == ()

    def test_maven_produces_jar(self, compile_result):
        """Maven produces a JAR file."""
        result, _ = compile_result
        assert len(result.class_files) >= 1
        jar_names = [k for k in result.class_files if k.endswith(".jar")]
        assert len(jar_names) >= 1

    def test_jar_written_to_candidate_path(self, compile_result):
        """JAR file is written back to candidate_path/target/."""
        _, tmpdir = compile_result
        jar_files = list(Path(tmpdir).rglob("*.jar"))
        assert len(jar_files) >= 1

    def test_compile_time_reasonable(self, compile_result):
        """Maven compilation completes within reasonable time (< 120s)."""
        result, _ = compile_result
        assert result.compilation_time_ms < 120_000


# ============================================================
# CATEGORY D: Execution Inside Docker
# ============================================================


class TestDockerExecution:
    """Verify JAR execution inside Docker with security constraints."""

    @pytest.fixture
    def execution_result(self):
        """Compile and execute the ARITHMETIC project."""
        adapter = DockerSpringBootCandidateAdapter()
        files, source_hash = _generate_springboot_project(ARITH_COBOL)
        tmpdir, manifest = _stage_project(files, source_hash)

        compile_result = adapter.compile(candidate_path=tmpdir, manifest=manifest)
        assert compile_result.success

        run_id = RunId(value="test-exec-001")
        exec_result = adapter.execute(
            run_id=run_id,
            compiled_path=tmpdir,
            manifest=manifest,
        )
        return exec_result

    def test_execution_succeeds(self, execution_result):
        """JAR execution completes successfully."""
        assert execution_result.status in (AdapterStatus.AVAILABLE, AdapterStatus.SUCCEEDED)

    def test_exit_code_zero(self, execution_result):
        """Exit code is 0 (success)."""
        assert execution_result.exit_code == 0

    def test_stdout_has_sum(self, execution_result):
        """Output contains SUM=15."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        normalized = [_normalize_numbers(l) for l in app_output]
        assert "SUM=15" in normalized

    def test_stdout_has_diff(self, execution_result):
        """Output contains DIFF=5."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        normalized = [_normalize_numbers(l) for l in app_output]
        assert "DIFF=5" in normalized

    def test_stdout_has_prod(self, execution_result):
        """Output contains PROD=50."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        normalized = [_normalize_numbers(l) for l in app_output]
        assert "PROD=50" in normalized

    def test_stdout_has_quot(self, execution_result):
        """Output contains QUOT=2."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        normalized = [_normalize_numbers(l) for l in app_output]
        assert "QUOT=2" in normalized

    def test_stdout_has_rem(self, execution_result):
        """Output contains REM=0."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        normalized = [_normalize_numbers(l) for l in app_output]
        assert "REM=0" in normalized

    def test_stdout_has_comparisons(self, execution_result):
        """Output contains comparison results."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        assert "A_GT_B=TRUE" in app_output
        assert "A_EQ_B=FALSE" in app_output
        assert "A_LT_B=FALSE" in app_output

    def test_stdout_has_8_lines(self, execution_result):
        """Output contains exactly 8 application output lines."""
        stdout = execution_result.stdout.decode(errors="replace")
        app_output = _extract_app_output(stdout)
        assert len(app_output) == 8


# ============================================================
# CATEGORY E: Oracle Execution
# ============================================================


class TestOracleExecution:
    """Verify COBOL oracle executes correctly inside Docker."""

    @pytest.fixture
    def oracle_result(self):
        """Execute COBOL oracle for ARITH.cob."""
        adapter = DockerOracleAdapter(_oracle_config())
        result = adapter.execute(
            run_id=RunId(value="oracle-test-001"),
            source_path=str(ARITH_COBOL),
            input_data=None,
            input_files=None,
        )
        return result

    def test_oracle_exits_zero(self, oracle_result):
        """Oracle exits with code 0."""
        assert oracle_result.exit_code == 0

    def test_oracle_has_output(self, oracle_result):
        """Oracle produces output."""
        stdout = oracle_result.stdout.decode(errors="replace").strip()
        assert len(stdout) > 0

    def test_oracle_has_sum(self, oracle_result):
        """Oracle output contains SUM=0015."""
        stdout = oracle_result.stdout.decode(errors="replace")
        assert "SUM=0015" in stdout

    def test_oracle_has_comparisons(self, oracle_result):
        """Oracle output contains comparison results."""
        stdout = oracle_result.stdout.decode(errors="replace")
        assert "A_GT_B=TRUE" in stdout
        assert "A_EQ_B=FALSE" in stdout
        assert "A_LT_B=FALSE" in stdout


# ============================================================
# CATEGORY F: Behavioral Equivalence (THE VERDICT)
# ============================================================


class TestBehavioralEquivalence:
    """Compare generated Spring Boot output vs COBOL oracle output.

    This is the critical Phase 7D proof: generated code produces
    the SAME behavioral output as the COBOL oracle.
    Uses the production VerticalSlicePipeline with EvidenceIntegrityValidator
    and VerdictDeriver for certification.
    """

    @pytest.fixture
    def pipeline_result(self):
        """Run the full production pipeline for ARITH workload."""
        # Generate fresh Spring Boot project
        files, source_hash = _generate_springboot_project(ARITH_COBOL)
        tmpdir, _ = _stage_project(files, source_hash)

        # Configure production pipeline with Spring Boot adapter
        config = PipelineConfig(
            workload_id="arith",
            cobol_source_path=str(ARITH_COBOL),
            java_candidate_path=tmpdir,
            java_entrypoint="com.generated.app.Application",
            workload=_arith_workload(),
            use_docker_java=True,
        )
        # Use the DockerSpringBootCandidateAdapter for Spring Boot projects
        candidate_adapter = DockerSpringBootCandidateAdapter()
        pipeline = VerticalSlicePipeline(config, candidate_adapter=candidate_adapter)

        return pipeline.run()

    def test_exit_codes_match(self, pipeline_result):
        """Candidate and oracle have same exit code."""
        assert pipeline_result.oracle_exit_code == pipeline_result.candidate_exit_code

    def test_stdout_lines_match(self, pipeline_result):
        """Candidate and oracle produce identical STDOUT output."""
        stdout_comparisons = [
            c for c in pipeline_result.comparison_evidence
            if c.artifact_type == "STDOUT"
        ]
        assert len(stdout_comparisons) == 1
        # Production comparator confirms byte-for-byte match after framework log suppression
        assert stdout_comparisons[0].result == "MATCH"
        assert len(stdout_comparisons[0].differences) == 0

    def test_verdict_is_verified(self, pipeline_result):
        """Production verdict derivation yields VERIFIED with framework log suppression.
        
        COBOL PIC 9(n) produces zero-padded output which is now correctly
        matched by generated Java using String.format with PIC-derived width.
        Spring Boot framework startup logs are suppressed via
        spring.main.banner-mode=off and logging.level.root=OFF.
        """
        # The production verdict correctly identifies behavioral equivalence
        assert pipeline_result.verdict.state == VerdictState.VERIFIED
        assert pipeline_result.verdict.executed_check_count == 3
        # STDOUT comparison should be MATCH
        stdout_comparisons = [
            c for c in pipeline_result.comparison_evidence
            if c.artifact_type == "STDOUT"
        ]
        assert len(stdout_comparisons) == 1
        assert stdout_comparisons[0].result == "MATCH"
        # EXIT_STATUS should match (both exit 0)
        exit_comparisons = [
            c for c in pipeline_result.comparison_evidence
            if c.artifact_type == "EXIT_STATUS"
        ]
        assert len(exit_comparisons) == 1
        assert exit_comparisons[0].result == "MATCH"
        # STDERR - both oracle and candidate produce empty stderr
        stderr_comparisons = [
            c for c in pipeline_result.comparison_evidence
            if c.artifact_type == "STDERR"
        ]
        assert len(stderr_comparisons) == 1
        assert stderr_comparisons[0].result == "MATCH"

    def test_evidence_manifest_complete(self, pipeline_result):
        """Evidence manifest passes integrity validation and is complete."""
        assert pipeline_result.evidence_manifest.is_complete()

    def test_evidence_integrity_validated(self, pipeline_result):
        """Evidence integrity validator accepted the manifest."""
        from engine.evidence.integrity import EvidenceIntegrityValidator
        validator = EvidenceIntegrityValidator()
        result = validator.validate(pipeline_result.evidence_manifest)
        # Should return ValidatedEvidenceManifest, not violations
        from engine.evidence.integrity import ValidatedEvidenceManifest
        assert isinstance(result, ValidatedEvidenceManifest)

    def test_verdict_derived_from_manifest(self, pipeline_result):
        """Verdict was derived by production VerdictDeriver from validated manifest."""
        from engine.verdict.derivation import derive_verdict
        verdict = derive_verdict(pipeline_result.evidence_manifest)
        # Production verdict correctly identifies behavioral equivalence as VERIFIED
        assert verdict.state == VerdictState.VERIFIED
        assert verdict.workload_id.value == "arith"
        assert verdict.executed_check_count == 3
        assert len(verdict.differences) == 0
