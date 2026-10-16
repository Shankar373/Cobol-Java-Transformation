"""BL-071 executed proof: generated JCL projects compile and start.

Phase 5 §76 audit probe 16 proved the generated JCL Spring Boot project
did **not** compile in the canonical offline Maven lane while the
adapter docstring claimed "it compiles, starts" (missing
``spring-boot-starter-batch`` in the offline precache).  This test is
the end-to-end evidence that closes the gap:

    fixtures/workload-jcl
        -> modernize_jcl_workload   (JCL lane consumer)
        -> jcl_to_spring_boot       (JCL-owned adapter)
        -> SpringBootGenerator      (shared generator, unmodified)
        -> DockerSpringBootCandidateAdapter.compile (offline Maven)
        -> DockerSpringBootCandidateAdapter.execute (java -jar)

The claim under test is exactly what the adapter documents: the project
compiles, starts, and prints what each JCL step would do.  No JES/z/OS
runtime equivalence is claimed anywhere (the JCL lane remains
structural-only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_phase4_business_logic_verified import requires_docker

from engine.candidate.docker_spring_boot_adapter import (
    CandidateManifest,
    DockerSpringBootCandidateAdapter,
)
from engine.domain.identities import RunId
from engine.transformation.jcl_consumer import modernize_jcl_workload
from engine.transformation.jcl_spring_boot_adapter import jcl_to_spring_boot
from engine.transformation.spring_boot_generator import SpringBootGenerator

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "workload-jcl"


@pytest.fixture(scope="module")
def compiled_project(tmp_path_factory) -> tuple[Path, CandidateManifest, object]:
    """Generate once, compile once; both tests assert on the same build."""
    app_dir = tmp_path_factory.mktemp("jcl-spring-boot")

    result = modernize_jcl_workload(FIXTURES, application_id="jcl-e2e")
    assert result.job_count >= 1

    spring_app = jcl_to_spring_boot(
        result.profile.application, base_package="com.generated.jcl"
    )
    files = SpringBootGenerator().generate_project(spring_app)
    for generated in files:
        target = app_dir / generated.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.source_code, encoding="utf-8")

    manifest = CandidateManifest(
        candidate_id="jcl-e2e",
        workload_id="jcl-e2e",
        source_hash="jcl-e2e",
        generated_files={
            str(generated.path).replace("\\", "/"): "jcl-e2e"
            for generated in files
        },
        entrypoint="com.generated.jcl.JclBatchApplication",
    )

    compile_result = DockerSpringBootCandidateAdapter().compile(
        str(app_dir), manifest
    )
    return app_dir, manifest, compile_result


@requires_docker
class TestGeneratedJclSpringBootProjectBuildsAndRuns:
    def test_generated_project_compiles_in_the_offline_maven_lane(
        self, compiled_project
    ) -> None:
        _app_dir, _manifest, compile_result = compiled_project
        assert compile_result.success, (
            "generated JCL Spring Boot project failed to compile offline: "
            f"{compile_result.compilation_errors}"
        )
        assert compile_result.class_files, "compile produced no JAR"

    def test_generated_project_starts_and_prints_every_step_marker(
        self, compiled_project
    ) -> None:
        app_dir, manifest, compile_result = compiled_project
        assert compile_result.success

        execution = DockerSpringBootCandidateAdapter().execute(
            RunId(value="jcl-e2e-run"), str(app_dir), manifest
        )
        stdout = execution.stdout.decode("utf-8", errors="replace")
        assert execution.exit_code == 0, (
            f"generated JCL app failed to start: exit={execution.exit_code} "
            f"stderr={execution.stderr[:500]!r} stdout={stdout[:500]!r}"
        )
        # The structural job services print one marker per invoked step.
        assert "[STEP01]" in stdout, stdout[:1000]
