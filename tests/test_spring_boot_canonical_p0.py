"""M5 tests — Spring Boot is the canonical generated application.

Proves the production chain preserves its boundaries while the product
output becomes a native Spring Boot project:

    CobolApplication
    -> (existing) map_cobol_programs_to_application -> JavaApplication
    -> (existing) map_java_application_to_spring_boot -> SpringBootApplication
    -> (existing) SpringBootGenerator -> Spring Boot project
    -> DockerSpringBootCandidateAdapter (Maven build + JAR run)

Docker-free: the verification pipeline is replaced with a recording fake
at the api.service boundary. Runtime proof lives in the M5 report, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import api.service as svc_mod
from api.models import RunStage
from api.service import Service
from api.store import Store


def _cobol(program_id: str, marker: str, field: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"       01 {field} PIC X(20) VALUE 'X'.\n"
        "       PROCEDURE DIVISION.\n"
        f"       MAIN-{program_id}.\n"
        f'           DISPLAY "{marker}" {field}.\n'
        "           STOP RUN.\n"
    )


ALPHA = _cobol("ALPHA", "SPRING-ALPHA-11", "WS-ALPHA-FIELD")
BETA = _cobol("BETA", "SPRING-BETA-22", "WS-BETA-FIELD")

SPRING_ENTRY = "com.generated.app.Application"
SERVICE_A = Path("src/main/java/com/generated/app/service/Alpha.java")
SERVICE_B = Path("src/main/java/com/generated/app/service/Beta.java")


class _FakeResult:
    evidence_manifest = None
    verdict = None


@pytest.fixture()
def fake_pipeline(monkeypatch):
    captured: list = []

    class _FakePipeline:
        def __init__(self, config, candidate_adapter=None):
            captured.append((config, candidate_adapter))

        def run(self, controlled_input=None, progress=None):
            return _FakeResult()

    monkeypatch.setattr(svc_mod, "VerticalSlicePipeline", _FakePipeline)
    return captured


@pytest.fixture()
def svc():
    return Service(Store())


def _await_terminal(svc: Service, run_id: str, timeout_s: float = 180.0):
    """Poll a run until COMPLETED/FAILED (tolerates sync and background
    modernize contracts)."""
    import time

    deadline = time.time() + timeout_s
    while True:
        run = svc.get_run(run_id)
        if run.stage in (RunStage.COMPLETED, RunStage.FAILED):
            return run
        if time.time() > deadline:
            raise TimeoutError(f"run {run_id} stuck at {run.stage}")
        time.sleep(1)


def _make_app(svc: Service, files: dict[str, str]) -> str:
    app = svc.create_application(
        name="spring-app", description="d", workload_id="wl-spring",
        java_entrypoint="Main",
    )
    svc.upload_cobol_source(
        app.id, {name: content.encode() for name, content in files.items()}
    )
    return app.id


# ---------------------------------------------------------------------------
# Mapping layer: JavaApplication -> SpringBootApplication
# ---------------------------------------------------------------------------

class TestSpringMapping:
    def test_java_application_maps_to_spring_boot(self) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "A.cob").write_text(ALPHA, encoding="utf-8")
            discovered = ApplicationDiscovery().discover(tmp, application_id="t")
        programs = tuple(u.program for u in discovered.programs)
        java_app = map_cobol_programs_to_application(programs, application_id="t")

        spring_app = map_java_application_to_spring_boot(java_app)

        assert spring_app.validate() == []
        assert len(spring_app.services) == 1
        assert spring_app.services[0].source_program == "ALPHA"
        assert spring_app.entry_point is not None
        assert spring_app.entry_point.class_name == "Application"

    def test_multiple_programs_survive_mapping(self, tmp_path: Path) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )

        (tmp_path / "A.cob").write_text(ALPHA, encoding="utf-8")
        (tmp_path / "B.cob").write_text(BETA, encoding="utf-8")
        discovered = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        programs = tuple(u.program for u in discovered.programs)
        java_app = map_cobol_programs_to_application(programs, application_id="t")

        spring_app = map_java_application_to_spring_boot(java_app)

        assert spring_app.validate() == []
        by_program = {s.source_program: s for s in spring_app.services}
        assert set(by_program) == {"ALPHA", "BETA"}
        # Each service carries its own program's methods, not the other's.
        alpha_methods = {m.name for m in by_program["ALPHA"].methods}
        beta_methods = {m.name for m in by_program["BETA"].methods}
        assert alpha_methods != beta_methods


# ---------------------------------------------------------------------------
# Project generation: expected program classes + entrypoint
# ---------------------------------------------------------------------------

class TestSpringProjectGeneration:
    def test_project_contains_expected_classes(self, tmp_path: Path) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )
        from engine.transformation.spring_boot_generator import SpringBootGenerator

        (tmp_path / "A.cob").write_text(ALPHA, encoding="utf-8")
        (tmp_path / "B.cob").write_text(BETA, encoding="utf-8")
        discovered = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        programs = tuple(u.program for u in discovered.programs)
        java_app = map_cobol_programs_to_application(programs, application_id="t")
        spring_app = map_java_application_to_spring_boot(java_app)

        files = SpringBootGenerator().generate_project(spring_app)
        by_path = {
            (f.path or f.filename).replace("\\", "/"): f for f in files
        }
        service_a = str(SERVICE_A).replace("\\", "/")
        service_b = str(SERVICE_B).replace("\\", "/")

        assert "pom.xml" in by_path
        assert "src/main/java/com/generated/app/Application.java" in by_path
        assert service_a in by_path
        assert service_b in by_path
        assert "SPRING-ALPHA-11" in by_path[service_a].source_code
        assert "SPRING-BETA-22" in by_path[service_b].source_code

    def test_entrypoint_is_spring_application(self, tmp_path: Path) -> None:
        from engine.transformation.application_discovery import ApplicationDiscovery
        from engine.transformation.cobol_to_java_mapping import (
            map_cobol_programs_to_application,
        )
        from engine.transformation.java_to_spring_mapping import (
            map_java_application_to_spring_boot,
        )

        (tmp_path / "A.cob").write_text(ALPHA, encoding="utf-8")
        discovered = ApplicationDiscovery().discover(str(tmp_path), application_id="t")
        programs = tuple(u.program for u in discovered.programs)
        java_app = map_cobol_programs_to_application(programs, application_id="t")
        spring_app = map_java_application_to_spring_boot(java_app)

        entry = spring_app.entry_point
        assert entry is not None
        assert f"{entry.package}.{entry.class_name}" == SPRING_ENTRY


# ---------------------------------------------------------------------------
# Canonical API path uses the generated Spring Boot artifact
# ---------------------------------------------------------------------------

class TestCanonicalSpringPath:
    def test_normal_path_produces_spring_project(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"A.cob": ALPHA, "B.cob": BETA})
        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.COMPLETED
        app = svc.get_application(app_id)
        project = Path(app.generated_app_path)
        assert (project / "pom.xml").exists()
        assert (project / SERVICE_A).exists()
        assert (project / SERVICE_B).exists()
        assert app.generated_entrypoint == SPRING_ENTRY
        assert set(app.generated_program_ids) == {"ALPHA", "BETA"}

    def test_no_upload_required_for_spring_path(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"A.cob": ALPHA})
        assert svc.get_application(app_id).java_candidate_path is None

        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.COMPLETED
        assert (Path(svc.get_application(app_id).generated_app_path) / "pom.xml").exists()

    def test_spring_boot_adapter_selected(
        self, svc: Service, fake_pipeline
    ) -> None:
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        app_id = _make_app(svc, {"A.cob": ALPHA})
        _await_terminal(svc, svc.modernize(app_id).id)

        config, adapter = fake_pipeline[0]
        assert isinstance(adapter, DockerSpringBootCandidateAdapter)
        assert config.java_candidate_path == svc.get_application(app_id).generated_app_path
        assert config.java_entrypoint == SPRING_ENTRY

    def test_no_host_java_fallback_selected(
        self, svc: Service, fake_pipeline
    ) -> None:
        from engine.candidate.docker_java_adapter import DockerJavaCandidateAdapter
        from engine.candidate.java_adapter import RealJavaCandidateAdapter

        app_id = _make_app(svc, {"A.cob": ALPHA})
        _await_terminal(svc, svc.modernize(app_id).id)

        _, adapter = fake_pipeline[0]
        assert not isinstance(adapter, RealJavaCandidateAdapter)
        assert not isinstance(adapter, DockerJavaCandidateAdapter)

    def test_spring_mapping_failure_is_controlled(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.java_to_spring_mapping as spring_map

        def _boom(application, **kwargs):
            raise RuntimeError("synthetic mapping boom")

        monkeypatch.setattr(
            spring_map, "map_java_application_to_spring_boot", _boom
        )

        app_id = _make_app(svc, {"A.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.FAILED
        assert "assembly failed" in run.error.lower() or "spring boot mapping failed" in run.error.lower()
        assert fake_pipeline == []
