"""Phase 9 batch P2b — build/execute + differential evidence for the §32
non-Spring targets.

Docker-free: target-runtime adapter selection and the Maven lane's neutral
validation.  Docker-gated (``requires_docker``): fresh reference-versus-
candidate differential runs that BUILD each generated project offline, EXECUTE
the jar in Docker, run the independent GnuCOBOL oracle, and compare stdout —
the Phase 9 build/execution evidence (Phase 8 shipped generation only).
"""
from __future__ import annotations

import pathlib

import pytest

from tests.test_phase4_fresh_verified import (
    EXPECTED_STDOUT_LINES,
    FIXTURE_DIR,
    requires_docker,
)


# ---------------------------------------------------------------------------
# Docker-free: adapter selection by target_runtime
# ---------------------------------------------------------------------------
class TestTargetAdapterSelection:
    def test_spring_boot_selects_spring_lane(self):
        from engine.candidate.factory import candidate_adapter_for_target
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        assert isinstance(
            candidate_adapter_for_target("spring_boot"),
            DockerSpringBootCandidateAdapter,
        )

    @pytest.mark.parametrize("target", ["plain_java", "jakarta_ee"])
    def test_non_spring_targets_select_maven_lane(self, target):
        from engine.candidate.factory import candidate_adapter_for_target
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter

        adapter = candidate_adapter_for_target(target)
        assert isinstance(adapter, MavenProjectCandidateAdapter)

    def test_unknown_target_fails_closed(self):
        from engine.candidate.factory import candidate_adapter_for_target

        with pytest.raises(ValueError) as excinfo:
            candidate_adapter_for_target("tomcat")
        assert "invalid target_runtime" in str(excinfo.value)
        for target in ("spring_boot", "plain_java", "jakarta_ee"):
            assert target in str(excinfo.value)

    def test_maven_lane_validation_is_target_neutral(self, tmp_path):
        from engine.candidate.maven_adapter import MavenProjectCandidateAdapter
        from engine.candidate.adapter import CandidateManifest

        (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
        manifest = CandidateManifest(
            candidate_id="c",
            workload_id="w",
            source_hash="h",
            generated_files={"pom.xml": "h"},
            entrypoint="Main",
        )
        # A dependency-free Maven project validates; no Spring required and
        # the wording must not claim Spring Boot.
        violations = MavenProjectCandidateAdapter().validate_candidate(
            str(tmp_path), manifest
        )
        assert violations == []


# ---------------------------------------------------------------------------
# Docker-gated: fresh reference-vs-candidate differential (build+execute)
# ---------------------------------------------------------------------------
def _generate_target_project(tmp_path: pathlib.Path, target: str):
    """COBOL → shared IR → §32 target project (generation only)."""
    from engine.transformation.application_discovery import ApplicationDiscovery
    from engine.transformation.application_generator import ApplicationGenerator
    from engine.transformation.runtime_adapters import get_runtime_adapter

    app = ApplicationDiscovery().discover(
        str(FIXTURE_DIR), application_id=f"phase9-{target}"
    )
    gen = ApplicationGenerator().generate(
        app, entrypoint="MAIN", source_root=FIXTURE_DIR
    )
    assert gen.success, gen.errors

    outcome = get_runtime_adapter(target).assemble(
        gen.java_application,
        entry_program="MAIN",
        output_prefix=f"phase9-{target}-",
    )
    return pathlib.Path(outcome.project_dir), outcome.entrypoint


@requires_docker
@pytest.mark.parametrize("target", ["plain_java", "jakarta_ee"])
def test_target_builds_executes_and_matches_oracle(tmp_path, target):
    """Fresh end-to-end: BUILD (offline Maven) → EXECUTE (Docker jar) →
    independent GnuCOBOL oracle → stdout comparison → VERIFIED.

    This is the Phase 9 build/execution evidence for the §32 non-Spring
    targets (Phase 8 shipped generation only).  Every stage uses real
    production adapters; the verdict is derived from genuine stdout equality
    between the oracle and the freshly built candidate.
    """
    import uuid

    from engine.candidate.docker_spring_boot_adapter import CandidateManifest
    from engine.candidate.factory import candidate_adapter_for_target
    from engine.domain.identities import RunId, VerdictState
    from engine.oracle.adapter import OracleAdapterConfig
    from engine.oracle.docker_adapter import DockerOracleAdapter

    run_id = RunId(value=f"phase9-{target}-{uuid.uuid4().hex[:8]}")

    # --- Stage A: COBOL → target project (shared IR, single transform) ---
    project, entrypoint = _generate_target_project(tmp_path, target)
    assert (project / "pom.xml").exists()

    manifest = CandidateManifest(
        candidate_id=f"phase9-{target}",
        workload_id=f"wl-phase9-{target}",
        source_hash="test",
        generated_files={"pom.xml": "test"},
        entrypoint=entrypoint,
    )

    # --- Stage B: offline Maven build in Docker ---
    candidate_adapter = candidate_adapter_for_target(target)
    compile_result = candidate_adapter.compile(str(project), manifest)
    assert compile_result.success, compile_result.compilation_errors

    # --- Stage C: candidate execution (java -jar) in Docker ---
    exec_result = candidate_adapter.execute(run_id, str(project), manifest)
    candidate_stdout = exec_result.stdout.decode(errors="replace")

    # --- Stage D: independent GnuCOBOL oracle (reference) ---
    oracle_adapter = DockerOracleAdapter(
        OracleAdapterConfig(
            oracle_id="gnucobol-phase9",
            image_digest="",
            compiler_version="3.1.2.0",
        )
    )
    assert oracle_adapter.probe().value != "UNAVAILABLE", (
        "GnuCOBOL oracle image unavailable — cannot produce reference output"
    )
    oracle_result = oracle_adapter.execute(
        run_id=run_id,
        source_path=str(FIXTURE_DIR),
        entry_program="MAIN",
    )
    oracle_stdout = oracle_result.stdout.decode(errors="replace")

    # --- Stage E: both produce the expected observable output ---
    for line in EXPECTED_STDOUT_LINES:
        assert line in oracle_stdout, (
            f"Oracle missing {line!r}.\nOracle stdout: {oracle_stdout!r}"
        )
        assert line in candidate_stdout, (
            f"Candidate missing {line!r}.\nCandidate stdout: {candidate_stdout!r}"
        )

    # --- Stage F: differential stdout comparison → verdict ---
    def _normalise(s: str) -> list[str]:
        return [ln.rstrip() for ln in s.splitlines() if ln.strip()]

    oracle_lines = _normalise(oracle_stdout)
    candidate_lines = _normalise(candidate_stdout)

    verdict = (
        VerdictState.VERIFIED
        if oracle_lines == candidate_lines
        else VerdictState.FAILED
    )
    assert verdict == VerdictState.VERIFIED, (
        f"Expected VERIFIED for {target}; got {verdict.value}\n"
        f"Oracle stdout ({len(oracle_lines)} lines):    {oracle_lines}\n"
        f"Candidate stdout ({len(candidate_lines)} lines): {candidate_lines}\n"
    )
