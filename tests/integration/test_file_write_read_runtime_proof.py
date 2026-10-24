"""Runtime proof for ``workload-file-write-read`` with *generated* Java.

Closes audit gaps in one module (all evidence is produced live in Docker —
GnuCOBOL oracle image + offline Maven build + pinned JRE image):

1. **Newly proven workload.** The fixture declared a four-artifact contract
   (STDOUT, STDERR, EXIT_STATUS, FIXED_RECORD ``wr.dat``) but had no runtime
   proof with generated Java — only contract-resolution tests existed.
   ``TestDeclaredContractProof`` compiles the real COBOL in the GnuCOBOL
   oracle, generates Spring Boot from the same COBOL, builds it in Docker,
   executes both, and compares all four artifacts.

2. **Real-evidence cohort check (EV-006/R9).** A run certified under the
   API's *default* contract (STDOUT + EXIT_STATUS only) must not mark the
   FILE dependencies PROVEN, and must not certify the application — even
   though the runtime verdict itself is honestly VERIFIED for what it
   compared.  ``TestDefaultContractRun`` pins that with live pipeline
   evidence (the unit-level binding is covered in
   ``tests/test_file_dependency_proof_binding.py``).

3. **Negative lane (task: deliberate behavioural mismatch).** A mutated
   *generated* candidate must fail the comparison, and the FILE dependency
   must not be marked PROVEN afterwards.

4. **Determinism.** Repeated transformations of identical input produce
   byte-identical generated Java (not merely an identical input hash).

5. **No silent skip.** When runtime proof is explicitly requested
   (``RUN_DOCKER_TESTS=1``) but the Docker runtime is unavailable, the run
   *fails* instead of skipping — an unexecuted test must never pass as
   proof.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.workload_contract import resolve_certification_contract
from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
from engine.domain.identities import VerdictState
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    ProofState,
    integrated_proof_from_pipelines,
    runtime_evidence_from_result,
)
from engine.modernization.pipeline import (
    ModernizationConfig,
    UniversalModernizationPipeline,
)
from engine.pipeline import PipelineConfig, VerticalSlicePipeline

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "workload-file-write-read"
COBOL_DIR = FIXTURE_ROOT / "cobol"
JAVA_ENTRYPOINT = "com.generated.app.Application"


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version"],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


DOCKER_AVAILABLE = _docker_available()
RUNTIME_REQUESTED = bool(os.environ.get("RUN_DOCKER_TESTS"))

needs_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE, reason="Docker not available"
)


def runtime_proof_environment_failure(
    requested: bool, docker_available: bool
) -> str | None:
    """Failure message when requested runtime proof has no runtime.

    ``None`` means the environment is honest: either proof was not
    requested, or the runtime it needs is present.  Non-``None`` must make
    the run *fail* — an unexecuted test can never pass as proof.
    """
    if requested and not docker_available:
        return (
            "RUN_DOCKER_TESTS=1 but the Docker runtime is unavailable: "
            "runtime proof cannot execute and an unexecuted test must not "
            "be reported as proof"
        )
    return None


# ---------------------------------------------------------------------------
# Environment honesty: requesting runtime proof without a runtime fails.
# ---------------------------------------------------------------------------


def test_runtime_proof_environment_failure_matrix():
    """The gate fails exactly when proof was requested without a runtime."""
    assert runtime_proof_environment_failure(True, False), (
        "requested proof without runtime must produce a failure message"
    )
    assert runtime_proof_environment_failure(True, True) is None
    assert runtime_proof_environment_failure(False, False) is None, (
        "proof not requested: absence of a runtime is a skip, not a failure"
    )


@pytest.mark.skipif(
    not RUNTIME_REQUESTED,
    reason="RUN_DOCKER_TESTS not set (runtime proof not requested)",
)
def test_requested_runtime_proof_has_a_runtime():
    """``RUN_DOCKER_TESTS=1`` without Docker must fail, never silently skip."""
    message = runtime_proof_environment_failure(
        requested=True, docker_available=DOCKER_AVAILABLE
    )
    if message:
        pytest.fail(message)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _generate(output_dir: str):
    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=str(COBOL_DIR),
            output_dir=output_dir,
            application_id="file-write-read",
            entrypoint="FILE-WRITE-READ",
            docker_available=True,
        )
    ).execute()
    assert report.generation_success is True, getattr(
        report, "generation_errors", None
    )
    return report


@pytest.fixture(scope="module")
def generated_report():
    """Generate the Spring Boot project once; reused by every runtime lane."""
    out_dir = tempfile.mkdtemp(prefix="fw-proof-generation-")
    return _generate(out_dir)


def _run_pipeline(candidate_path: Path, contract, modernization_report):
    pipeline = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="file-write-read",
            cobol_source_path=str(COBOL_DIR),
            java_candidate_path=str(candidate_path),
            java_entrypoint=JAVA_ENTRYPOINT,
            workload=contract.workload,
            use_docker_java=True,
        ),
        candidate_adapter=DockerSpringBootCandidateAdapter(),
    )
    result = pipeline.run()
    evidence = runtime_evidence_from_result(result)
    proof = integrated_proof_from_pipelines(
        workload_id="file-write-read",
        report=modernization_report,
        runtime=evidence,
        jcl_status="NOT_PRESENT",
    )
    return SimpleNamespace(result=result, evidence=evidence, proof=proof)


# ---------------------------------------------------------------------------
# 1. Declared contract: all four artifacts compared, FILE deps proven
# ---------------------------------------------------------------------------


@needs_docker
class TestDeclaredContractProof:
    @pytest.fixture(scope="class")
    def run(self, generated_report):
        contract = resolve_certification_contract("file-write-read")
        assert contract.workload is not None
        return _run_pipeline(
            Path(generated_report.generated_project_dir),
            contract,
            generated_report,
        )

    def test_runtime_verdict_is_verified(self, run):
        assert run.result.verdict.state is VerdictState.VERIFIED, (
            run.result.verdict.state
        )

    def test_all_four_declared_artifacts_match(self, run):
        results = {c.artifact_type: c.result for c in run.result.comparison_evidence}
        assert set(results) == {"STDOUT", "STDERR", "EXIT_STATUS", "FIXED_RECORD"}
        assert set(results.values()) == {"MATCH"}, results

    def test_evidence_is_complete_and_valid(self, run):
        assert run.evidence.verdict_is_verified is True
        assert run.evidence.evidence_complete is True
        assert run.evidence.evidence_integrity_valid is True
        assert ("FIXED_RECORD", "MATCH") in run.evidence.artifact_results

    def test_file_dependencies_are_proven_by_file_evidence(self, run):
        file_entries = [
            e for e in run.proof.dependency_ledger
            if e.kind is DependencyKind.FILE
        ]
        assert file_entries, "the workload declares two sequential files"
        for entry in file_entries:
            assert entry.proof_state is ProofState.PROVEN, entry

    def test_application_is_certified(self, run):
        assert run.proof.central_status is CentralStatus.VERIFIED, (
            run.proof.to_dict()
        )


# ---------------------------------------------------------------------------
# 2. Default contract (STDOUT+EXIT_STATUS): verdict verified, files not proven
# ---------------------------------------------------------------------------


@needs_docker
class TestDefaultContractRun:
    """The cohort-promotion regression, with live evidence.

    The API's default contract compares stdout and exit status only.  A
    file-writing program will honestly reach a VERIFIED *runtime* verdict
    for what it compared — but the FILE dependencies were never compared,
    so they must stay unproven and the application must not be certified.
    """

    @pytest.fixture(scope="class")
    def run(self, generated_report):
        # An id that resolves to no fixture workload => API default contract.
        contract = resolve_certification_contract("undeclared-default-contract")
        assert contract.workload is not None
        return _run_pipeline(
            Path(generated_report.generated_project_dir),
            contract,
            generated_report,
        )

    def test_runtime_verdict_is_verified_for_what_it_compared(self, run):
        assert run.result.verdict.state is VerdictState.VERIFIED, (
            run.result.verdict.state
        )

    def test_no_file_artifact_was_compared(self, run):
        compared = {c.artifact_type for c in run.result.comparison_evidence}
        assert compared == {"STDOUT", "EXIT_STATUS"}, compared
        assert not any(
            t in {"TEXT_FILE", "FIXED_RECORD"}
            for (t, _) in run.evidence.artifact_results
        )

    def test_file_dependencies_are_not_proven(self, run):
        file_entries = [
            e for e in run.proof.dependency_ledger
            if e.kind is DependencyKind.FILE
        ]
        assert file_entries, "the workload declares two sequential files"
        for entry in file_entries:
            assert entry.proof_state is not ProofState.PROVEN, (
                "FILE dependency cohort-promoted without file comparison "
                f"evidence: {entry}"
            )
            assert entry.proof_state is ProofState.PARTIAL, entry
            assert "file artifact" in entry.reason, entry.reason

    def test_application_is_not_certified(self, run):
        assert run.proof.central_status is CentralStatus.NOT_VERIFIED, (
            run.proof.to_dict()
        )


# ---------------------------------------------------------------------------
# 3. Negative lane: mutated generated candidate must fail and not prove
# ---------------------------------------------------------------------------


@needs_docker
class TestMutatedGeneratedCandidate:
    @pytest.fixture(scope="class")
    def run(self, generated_report):
        source_project = Path(generated_report.generated_project_dir)
        mutated_project = Path(
            tempfile.mkdtemp(prefix="fw-proof-mutated-")
        )
        shutil.copytree(
            source_project,
            mutated_project,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("target", ".git", "__pycache__"),
        )

        service = next(
            mutated_project.glob("src/main/java/**/FileWriteRead.java"),
            None,
        )
        assert service is not None, (
            f"generated service not found under {mutated_project}"
        )
        source = service.read_text(encoding="utf-8")
        original = "VALUE-TWO---"
        assert source.count(original) == 1, (
            "mutation anchor must occur exactly once in the generated code"
        )
        service.write_text(
            source.replace(original, "VALUE-TWX---"), encoding="utf-8"
        )

        contract = resolve_certification_contract("file-write-read")
        return _run_pipeline(mutated_project, contract, generated_report)

    def test_comparison_fails_on_the_written_file(self, run):
        results = {c.artifact_type: c.result for c in run.result.comparison_evidence}
        assert results.get("FIXED_RECORD") == "MISMATCH", results

    def test_runtime_verdict_is_failed(self, run):
        assert run.result.verdict.state is VerdictState.FAILED, (
            run.result.verdict.state
        )

    def test_file_dependencies_are_not_proven_after_mismatch(self, run):
        file_entries = [
            e for e in run.proof.dependency_ledger
            if e.kind is DependencyKind.FILE
        ]
        assert file_entries
        for entry in file_entries:
            assert entry.proof_state is not ProofState.PROVEN, entry
        assert run.proof.central_status is CentralStatus.NOT_VERIFIED, (
            run.proof.to_dict()
        )


# ---------------------------------------------------------------------------
# 4. Determinism: repeated transformation => byte-identical Java
# ---------------------------------------------------------------------------


def _project_bytes(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class TestGenerationDeterminism:
    def test_repeated_transformation_is_byte_identical(self):
        first = Path(tempfile.mkdtemp(prefix="fw-determinism-a-"))
        second = Path(tempfile.mkdtemp(prefix="fw-determinism-b-"))
        report_a = _generate(str(first))
        report_b = _generate(str(second))

        files_a = _project_bytes(Path(report_a.generated_project_dir))
        files_b = _project_bytes(Path(report_b.generated_project_dir))

        assert files_a, "first generation produced no files"
        assert set(files_a) == set(files_b), (
            f"file sets differ: only-a={sorted(set(files_a) - set(files_b))} "
            f"only-b={sorted(set(files_b) - set(files_a))}"
        )
        differing = sorted(
            name for name in files_a if files_a[name] != files_b[name]
        )
        assert not differing, (
            f"generated Java is not byte-identical across runs: {differing}"
        )
