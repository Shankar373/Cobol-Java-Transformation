"""Phase D TASK 4: integrated application proof (positive lane).

One realistic application exercising COPYBOOK, static CALL and sequential
FILE paths, plus a JCL job stream, joined into a single auditable result:

    JCL -> MAIN -> COPYBOOK TAXREC + CALL CALC + LINE SEQUENTIAL FILE
         -> UniversalModernizationPipeline (phases 1-5)
         -> VerticalSlicePipeline          (phases 6-11)
         -> dependency ledger -> central status

The COBOL <-> Java runtime lane is expected to reach a genuine, evidence
backed VERIFIED.  The application-level central status is expected to be
NOT VERIFIED because JCL has no runtime lane in this repository, which is
the honest answer for a workload that declares JCL.

Docker-free classes always run; the runtime class skips without Docker.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.modernization.capability_analyzer import CapabilityAnalyzer
from engine.modernization.integrated_proof import (
    CentralStatus,
    DependencyKind,
    ProofState,
    integrated_proof_from_pipelines,
    runtime_evidence_from_result,
)
from engine.modernization.modernization_planner import ModernizationPlanner
from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.jcl_consumer import modernize_jcl_workload

import os
import subprocess


FIXTURE_ROOT = "fixtures/workload-integrated"
COBOL_DIR = f"{FIXTURE_ROOT}/cobol"
ENTRYPOINT = "INTGMAIN"


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


needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker not available")


def _discover():
    return ApplicationDiscovery().discover(COBOL_DIR, application_id="integrated")


class TestIntegratedDiscovery:
    def test_both_programs_discovered(self):
        app = _discover()
        assert {p.program_id for p in app.programs} == {"INTGMAIN", "INTGCALC"}

    def test_copybook_discovered(self):
        app = _discover()
        assert "TAXREC" in set(app.copybooks)

    def test_call_edge_resolved(self):
        app = _discover()
        call_edges = [e for e in app.edges if e.edge_type == "CALL"]
        assert len(call_edges) == 1
        assert (call_edges[0].source, call_edges[0].target) == ("INTGMAIN", "INTGCALC")
        assert "resolution=RESOLVED" in call_edges[0].metadata

    def test_copy_edge_present(self):
        app = _discover()
        assert any(
            e.edge_type == "COPY" and e.target == "TAXREC" for e in app.edges
        )

    def test_file_edges_name_declared_files_not_records(self):
        app = _discover()
        file_targets = {e.target for e in app.edges if e.edge_type.startswith("FILE_")}
        assert file_targets == {"TAX-OUT", "TAX-IN"}

    def test_file_dependency_operations_are_resolved(self):
        app = _discover()
        main = app.get_program("INTGMAIN")
        assert main is not None
        deps = {(d.operation, d.file_name) for d in main.file_dependencies}
        assert deps == {
            ("OPEN", "TAX-OUT"),
            ("OPEN", "TAX-IN"),
            ("READ", "TAX-IN"),
            ("WRITE", "TAX-OUT"),
        }

    def test_discovery_has_no_errors(self):
        app = _discover()
        assert app.discovery_errors == ()


class TestIntegratedCapability:
    def test_every_component_supported(self):
        app = _discover()
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        for component in report.components:
            assert component.level.value == "SUPPORTED", component

    def test_capability_covers_all_four_lanes(self):
        app = _discover()
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        types = {c.component_type for c in report.components}
        assert {"PROGRAM", "COPYBOOK", "CALL", "FILE"} <= types

    def test_overall_capability_supported(self):
        app = _discover()
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        assert report.overall_level.value == "SUPPORTED"


class TestIntegratedPlan:
    def test_two_programs_both_transformable(self):
        plan = ModernizationPlanner(docker_available=True).plan(
            COBOL_DIR, application_id="integrated"
        )
        assert plan.total_programs == 2
        assert plan.supported_programs == 2
        assert plan.unsupported_programs == 0

    def test_call_relationship_recorded(self):
        plan = ModernizationPlanner(docker_available=True).plan(
            COBOL_DIR, application_id="integrated"
        )
        rel = {(r.caller, r.target) for r in plan.call_relationships}
        assert rel == {("INTGMAIN", "INTGCALC")}


class TestIntegratedGeneration:
    def test_generation_succeeds_for_all_programs(self, tmp_path):
        report = UniversalModernizationPipeline(
            ModernizationConfig(
                source_dir=COBOL_DIR,
                output_dir=str(tmp_path / "out"),
                application_id="integrated",
                entrypoint=ENTRYPOINT,
                docker_available=True,
            )
        ).execute()
        assert report.generation_success is True
        assert report.generation_errors == ()
        assert report.skipped_count == 0
        assert set(report.generated_program_ids) == {"INTGMAIN", "INTGCALC"}


class TestJclLane:
    def test_jcl_workload_modernizes_full(self):
        result = modernize_jcl_workload(FIXTURE_ROOT)
        assert result.status == "FULL"
        assert result.unsupported_constructs == ()
        assert result.has_errors is False
        assert result.job_count >= 1
        assert result.step_count >= 1


@pytest.fixture(scope="module")
def integrated_proof():
    """Run the full join once: modernization report + runtime lane + gate."""
    from api.workload_contract import resolve_certification_contract
    from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
    from engine.pipeline import PipelineConfig, VerticalSlicePipeline

    out_dir = Path(tempfile.mkdtemp(prefix="integrated-modernization-"))
    report = UniversalModernizationPipeline(
        ModernizationConfig(
            source_dir=COBOL_DIR,
            output_dir=str(out_dir),
            application_id="integrated",
            entrypoint=ENTRYPOINT,
            docker_available=True,
        )
    ).execute()
    assert report.generation_success is True, report.generation_errors

    contract = resolve_certification_contract("integrated")
    pipeline = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="integrated",
            cobol_source_path=COBOL_DIR,
            java_candidate_path=report.generated_project_dir,
            java_entrypoint="com.generated.app.Application",
            workload=contract.workload,
            use_docker_java=True,
        ),
        candidate_adapter=DockerSpringBootCandidateAdapter(),
    )
    result = pipeline.run()
    evidence = runtime_evidence_from_result(result)
    proof = integrated_proof_from_pipelines(
        workload_id="integrated",
        report=report,
        runtime=evidence,
        jcl_status=modernize_jcl_workload(FIXTURE_ROOT).status,
    )
    return report, result, evidence, proof


@needs_docker
class TestIntegratedRuntimeProof:
    """The full join: modernization report + runtime lane + central status."""

    def test_runtime_verdict_is_verified(self, integrated_proof):
        _, result, _, _ = integrated_proof
        from engine.domain.identities import VerdictState

        assert result.verdict.state == VerdictState.VERIFIED

    def test_runtime_evidence_is_complete_and_valid(self, integrated_proof):
        _, _, evidence, _ = integrated_proof
        assert evidence.verdict_is_verified
        assert evidence.evidence_complete is True
        assert evidence.evidence_integrity_valid is True

    def test_all_four_artifacts_match(self, integrated_proof):
        _, result, _, _ = integrated_proof
        results = {c.artifact_type: c.result for c in result.comparison_evidence}
        assert set(results) == {"STDOUT", "STDERR", "EXIT_STATUS", "FIXED_RECORD"}
        assert set(results.values()) == {"MATCH"}

    def test_exit_codes_are_zero_and_equal(self, integrated_proof):
        _, _, evidence, _ = integrated_proof
        assert evidence.oracle_exit_code == 0
        assert evidence.candidate_exit_code == 0

    def test_runtime_proven_lanes_are_proven(self, integrated_proof):
        _, _, _, proof_result = integrated_proof
        runtime_kinds = {
            DependencyKind.PROGRAM,
            DependencyKind.COPYBOOK,
            DependencyKind.CALL,
            DependencyKind.FILE,
        }
        entries = [e for e in proof_result.dependency_ledger if e.kind in runtime_kinds]
        assert len(entries) >= 4
        for entry in entries:
            assert entry.visible is True
            assert entry.capability_level.value == "SUPPORTED"
            assert entry.proof_state is ProofState.PROVEN, entry

    def test_jcl_is_visible_classified_and_partial(self, integrated_proof):
        _, _, _, proof_result = integrated_proof
        jcl = [e for e in proof_result.dependency_ledger if e.kind == DependencyKind.JCL]
        assert len(jcl) == 1
        assert jcl[0].visible is True
        assert jcl[0].proof_state is ProofState.PARTIAL
        assert jcl[0].required is True

    def test_central_status_is_not_verified_because_jcl_has_no_runtime_lane(
        self, integrated_proof,
    ):
        _, _, _, proof_result = integrated_proof
        assert proof_result.runtime_verdict_is_verified is True
        assert proof_result.central_status is CentralStatus.NOT_VERIFIED
        assert any("JCL" in reason for reason in proof_result.blocking_reasons)

    def test_gate_only_downgrades(self, integrated_proof):
        _, _, _, proof_result = integrated_proof
        unproven = proof_result.unproven_dependencies
        assert unproven
        assert len(proof_result.blocking_reasons) == len(unproven) + (
            0 if proof_result.generation_success else 1
        )
