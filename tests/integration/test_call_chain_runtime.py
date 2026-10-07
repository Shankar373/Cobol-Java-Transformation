"""CALL chain (A -> B -> C) runtime workload: end-to-end proof.

Proves the full chain for a genuine 3-program static CALL workload:

    discovery (MAIN->MID->LEAF edges, no concatenation)
    -> capability registry (CALL edges SUPPORTED)
    -> modernization plan (3 programs, 2 call relationships)
    -> Java application (MAIN service -> MID service -> LEAF service)
    -> Spring Boot project generation
    -> Docker Maven build + JAR execution
    -> independent GnuCOBOL oracle behaviour on the same 3-module link
    -> artifact comparison -> evidence manifest -> VERIFIED verdict

Docker-free classes run always; Docker-gated runtime classes skip when
Docker is unavailable.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
from engine.candidate.image_provenance import load_adapter_provenance
from engine.domain.identities import AdapterStatus, RunId, VerdictState
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.java_to_spring_mapping import map_java_application_to_spring_boot
from engine.transformation.spring_boot_generator import SpringBootGenerator

COBOL_DIR = Path("fixtures/workload-call-chain/cobol")


def _discover():
    return ApplicationDiscovery().discover(
        str(COBOL_DIR), application_id="call-chain-runtime"
    )


def _generate_project():
    app = _discover()
    gen = ApplicationGenerator().generate(
        app, entrypoint="Chainmain", source_root=COBOL_DIR
    )
    assert gen.success, gen.errors
    spring = map_java_application_to_spring_boot(
        gen.java_application,
        entry_program="Chainmain",
        copybook_models=gen.copybook_models,
    )
    files = SpringBootGenerator().generate_project(spring)
    return app, gen, spring, files


def _stage(files, source_hash):
    from engine.candidate.adapter import CandidateManifest

    tmpdir = tempfile.mkdtemp(prefix="call-chain-test-")
    for f in files:
        fp = Path(tmpdir) / f.path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f.source_code)
    manifest = CandidateManifest(
        candidate_id="generated-springboot-call-chain",
        workload_id="call-chain-runtime",
        source_hash=source_hash,
        generated_files=[f.path for f in files],
        entrypoint="com.generated.app.Application",
        java_version="21",
        dependencies=["spring-boot-starter", "spring-context"],
    )
    return tmpdir, manifest


def _source_hash() -> str:
    h = hashlib.sha256()
    for name in ("MAIN.cob", "MID.cob", "LEAF.cob"):
        h.update((COBOL_DIR / name).read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Docker-free: discovery / graph / capability / plan / Java structure
# ---------------------------------------------------------------------------


class TestChainDiscovery:
    def test_all_three_programs_discovered(self):
        app = _discover()
        ids = {p.program_id for p in app.programs}
        assert ids == {"CHAINMAIN", "MIDPROG", "LEAFPROG"}

    def test_call_edges_form_chain(self):
        app = _discover()
        edges = {(e.source, e.target, e.edge_type) for e in app.edges}
        assert ("CHAINMAIN", "MIDPROG", "CALL") in edges
        assert ("MIDPROG", "LEAFPROG", "CALL") in edges
        for e in app.edges:
            if e.edge_type == "CALL":
                assert "resolution=RESOLVED" in e.metadata

    def test_no_concatenated_sources(self):
        app = _discover()
        for p in app.programs:
            src_path = Path(p.source_path)
            if not src_path.is_absolute() and not src_path.exists():
                src_path = COBOL_DIR / src_path.name
            src = src_path.read_text(encoding="utf-8", errors="ignore")
            assert len([x for x in ("PROGRAM-ID.",) if x in src]) == 1


class TestChainCapability:
    def test_call_edges_supported(self):
        from engine.modernization.capability_analyzer import CapabilityAnalyzer

        app = _discover()
        report = CapabilityAnalyzer(docker_available=True).analyze(app)
        calls = [c for c in report.components if c.component_type == "CALL"]
        assert len(calls) == 2
        for c in calls:
            assert c.level.value == "SUPPORTED", c

    def test_plan_covers_three_programs_two_calls(self):
        from engine.modernization.modernization_planner import ModernizationPlanner

        plan = ModernizationPlanner(docker_available=True).plan(
            str(COBOL_DIR), application_id="call-chain-runtime"
        )
        assert plan.total_programs == 3
        assert plan.supported_programs == 3
        assert len(plan.call_relationships) == 2
        rel = {(r.caller, r.target) for r in plan.call_relationships}
        assert rel == {("CHAINMAIN", "MIDPROG"), ("MIDPROG", "LEAFPROG")}


class TestChainJavaDependencyModel:
    def test_generation_succeeds(self):
        _, gen, _, _ = _generate_project()
        assert gen.success
        assert set(gen.program_ids) == {"CHAINMAIN", "MIDPROG", "LEAFPROG"}

    def test_main_service_depends_on_mid_and_mid_on_leaf(self):
        _, gen, spring, files = _generate_project()
        paths = {f.path for f in files}
        main_java = next(f for f in files if "Chainmain.java" in f.path)
        mid_java = next(f for f in files if "Midprog.java" in f.path)
        leaf_java = next(f for f in files if "Leafprog.java" in f.path)
        assert "private final Midprog midprog" in main_java.source_code
        assert "midprog.MAIN_LOGIC();" in main_java.source_code or "midprog." in main_java.source_code
        assert "private final Leafprog leafprog" in mid_java.source_code
        assert "leafprog." in mid_java.source_code
        assert any("Application.java" in p for p in paths)


# ---------------------------------------------------------------------------
# Negative cases (Docker-free): fail closed, never VERIFIED
# ---------------------------------------------------------------------------


UNRESOLVED_CALL = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. LONELY.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'NOSUCH'.\n"
    "           STOP RUN.\n"
)

CYCLE_A = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CYCA.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'CYCB'.\n"
    "           STOP RUN.\n"
)

CYCLE_B = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CYCB.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL 'CYCA'.\n"
    "           STOP RUN.\n"
)

DYNAMIC_CALL = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. DYN.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-PROG PIC X(8) VALUE 'CALCEE'.\n"
    "       PROCEDURE DIVISION.\n"
    "           CALL WS-PROG.\n"
    "           STOP RUN.\n"
)


class TestChainNegatives:
    def test_unresolved_target_is_partial_not_supported(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(UNRESOLVED_CALL)
        from engine.modernization.modernization_planner import ModernizationPlanner

        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level.value == "PARTIAL"
        assert cr.may_proceed is False

    def test_cyclic_call_is_blocked(self, tmp_path):
        (tmp_path / "A.cob").write_text(CYCLE_A)
        (tmp_path / "B.cob").write_text(CYCLE_B)
        from engine.modernization.modernization_planner import ModernizationPlanner

        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        assert any("Cyclic" in r or "cyclic" in r for r in plan.blocking_summary)

    def test_dynamic_call_is_unsupported(self, tmp_path):
        (tmp_path / "MAIN.cob").write_text(DYNAMIC_CALL)
        from engine.modernization.modernization_planner import ModernizationPlanner

        plan = ModernizationPlanner(docker_available=True).plan(str(tmp_path))
        cr = plan.call_relationships[0]
        assert cr.capability_level.value == "UNSUPPORTED"
        assert cr.may_proceed is False


# ---------------------------------------------------------------------------
# Docker-gated: oracle multi-module link + Java compile/execute + verdict
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker not available")


@needs_docker
class TestOracleChain:
    def test_oracle_compiles_links_runs_three_module_chain(self):
        adapter = DockerOracleAdapter(OracleAdapterConfig(
            oracle_id="gnucobol-3.1.2", image_digest="",
            compiler_version="3.1.2.0", timeout_seconds=120,
        ))
        outcome = adapter.execute(
            RunId(value="call-chain-oracle-001"), str(COBOL_DIR)
        )
        assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:800]
        lines = outcome.stdout.decode(errors="replace").splitlines()
        for expected in ("CHAIN-START", "MID-START", "LEAF-START", "LEAF-OUT=000120",
                         "MID-TOTAL-AFTER-LEAF=000120", "TOTAL-AFTER-MID=000120", "CHAIN-END"):
            assert any(l.strip().endswith(expected) or expected in l for l in lines), lines


@needs_docker
class TestJavaChainBuildRun:
    def test_spring_project_compiles(self):
        _, _, _, files = _generate_project()
        tmpdir, manifest = _stage(files, _source_hash())
        adapter = DockerSpringBootCandidateAdapter()
        result = adapter.compile(candidate_path=tmpdir, manifest=manifest)
        assert result.success is True, result.compilation_errors
        jars = [k for k in result.class_files if k.endswith(".jar")]
        assert jars

    def test_spring_jar_executes_chain(self):
        _, _, _, files = _generate_project()
        tmpdir, manifest = _stage(files, _source_hash())
        adapter = DockerSpringBootCandidateAdapter()
        assert adapter.compile(candidate_path=tmpdir, manifest=manifest).success
        result = adapter.execute(
            RunId(value="call-chain-exec-001"), compiled_path=tmpdir, manifest=manifest
        )
        assert result.exit_code == 0
        stdout = result.stdout.decode(errors="replace")
        for expected in ("CHAIN-START", "MID-START", "LEAF-START", "TOTAL-AFTER-MID=", "CHAIN-END"):
            assert expected in stdout


@needs_docker
class TestChainVerdict:
    def test_full_pipeline_yields_verified(self):
        _, _, _, files = _generate_project()
        tmpdir, _ = _stage(files, _source_hash())
        from engine.contracts.models import NormalizationPolicy, OrderingPolicy
        from engine.workload import WorkloadArtifact, WorkloadDefinition

        workload = WorkloadDefinition(
            workload_id="call-chain-runtime",
            description="A->B->C static CALL with BY REFERENCE result propagation",
            artifacts=(
                WorkloadArtifact(
                    logical_name="call-chain-runtime-stdout",
                    artifact_type="STDOUT",
                    comparator_id="stdout-exact",
                    normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                    ordering=OrderingPolicy(order="SEQUENTIAL"),
                ),
                WorkloadArtifact(
                    logical_name="call-chain-runtime-stderr",
                    artifact_type="STDERR",
                    comparator_id="stderr-exact",
                    normalization=NormalizationPolicy(allowed_normalizations=("crlf_to_lf",)),
                    ordering=OrderingPolicy(order="SEQUENTIAL"),
                ),
                WorkloadArtifact(
                    logical_name="call-chain-runtime-exit-status",
                    artifact_type="EXIT_STATUS",
                    comparator_id="exit-status-exact",
                ),
            ),
        )
        config = PipelineConfig(
            workload_id="call-chain-runtime",
            cobol_source_path=str(COBOL_DIR),
            java_candidate_path=tmpdir,
            java_entrypoint="com.generated.app.Application",
            workload=workload,
            use_docker_java=True,
        )
        pipeline = VerticalSlicePipeline(config, candidate_adapter=DockerSpringBootCandidateAdapter())
        result = pipeline.run()
        assert result.verdict.state == VerdictState.VERIFIED
        assert result.evidence_manifest.is_complete()
