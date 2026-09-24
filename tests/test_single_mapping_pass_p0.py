"""Single COBOL->Java mapping pass (Lane A, API boundary only).

Proves the canonical flow:

    ApplicationDiscovery
    -> ApplicationGenerator.generate()          (ONE mapping pass)
    -> result.java_application                  (reused, never re-derived)
    -> map_java_application_to_spring_boot()
    -> SpringBootGenerator

Docker-free by construction: the verification pipeline is replaced with a
recording fake at the exact boundary the service imports
(api.service.VerticalSlicePipeline). Spies wrap REAL functions — no
verification result is faked.
"""

from __future__ import annotations

import ast
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


ALPHA = _cobol("ALPHA", "SINGLE-PASS-ALPHA-1", "WS-A-FIELD")


class _FakeResult:
    evidence_manifest = None
    verdict = None


@pytest.fixture()
def svc():
    return Service(Store())


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


def _await_terminal(svc: Service, run_id: str, timeout_s: float = 180.0):
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
        name="single-pass", description="d", workload_id="wl-sp",
        java_entrypoint="Main",
    )
    svc.upload_cobol_source(
        app.id, {name: content.encode() for name, content in files.items()}
    )
    return app.id


def _spy_generate(monkeypatch):
    """Wrap the REAL ApplicationGenerator.generate; record calls + results."""
    import engine.transformation.application_generator as ag_mod

    calls: list = []
    results: list = []
    real_generate = ag_mod.ApplicationGenerator.generate

    def _spy(self, application, entrypoint="", **kwargs):
        calls.append((application, entrypoint))
        result = real_generate(self, application, entrypoint, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(ag_mod.ApplicationGenerator, "generate", _spy)
    return calls, results


# ---------------------------------------------------------------------------
# 1. ApplicationGenerator.generate() is called exactly once
# ---------------------------------------------------------------------------

class TestGenerateCalledOnce:
    def test_generate_called_once(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        calls, _ = _spy_generate(monkeypatch)
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 2+4. result.java_application is reused: Spring mapping receives the SAME object
# ---------------------------------------------------------------------------

class TestJavaApplicationReused:
    def test_spring_mapping_receives_same_object(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.java_to_spring_mapping as j2s_mod

        _, results = _spy_generate(monkeypatch)

        received: list = []
        real_map = j2s_mod.map_java_application_to_spring_boot

        def _spy(application, base_package="com.generated.app",
                 entry_program="", **kwargs):
            received.append(application)
            return real_map(
                application, base_package=base_package,
                entry_program=entry_program, **kwargs,
            )


        monkeypatch.setattr(
            j2s_mod, "map_java_application_to_spring_boot", _spy
        )

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED

        assert len(results) == 1
        produced = results[0].java_application
        assert produced is not None
        assert len(received) == 1
        assert received[0] is produced


# ---------------------------------------------------------------------------
# 3. map_cobol_programs_to_application() is NOT called by the API service
# ---------------------------------------------------------------------------

class TestNoSecondCobolMapping:
    def test_api_service_never_calls_cobol_mapping(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.cobol_to_java_mapping as c2j_mod

        # ApplicationGenerator binds this name at ITS import time, so the
        # legitimate single mapping pass inside generate() bypasses this
        # wrapper. Any call recorded here comes from a late importer —
        # i.e. the API service duplicate this lane removes.
        late_calls: list = []
        real_map = c2j_mod.map_cobol_programs_to_application

        def _spy(*args, **kwargs):
            late_calls.append((args, kwargs))
            return real_map(*args, **kwargs)

        monkeypatch.setattr(
            c2j_mod, "map_cobol_programs_to_application", _spy
        )

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)

        # Transformation genuinely ran (guard against false-pass by skip).
        assert run.stage == RunStage.COMPLETED
        app = svc.get_application(app_id)
        assert app.generated_app_path is not None
        assert Path(app.generated_app_path, "pom.xml").exists()
        # ...yet no late-bound COBOL->Java mapping call occurred.
        assert late_calls == []

    def test_service_source_has_no_cobol_mapping_reference(self) -> None:
        source = Path(svc_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Docstrings/comments are Constants — only real code references count.
        code_refs = [
            n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name)
            and n.id == "map_cobol_programs_to_application"
        ]
        assert code_refs == []


# ---------------------------------------------------------------------------
# 5. Generated project is still written correctly
# ---------------------------------------------------------------------------

class TestProjectWritten:
    def test_generated_project_contents(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED

        app = svc.get_application(app_id)
        project = Path(app.generated_app_path)
        assert (project / "pom.xml").exists()
        service_file = project / "src/main/java/com/generated/app/service/Alpha.java"
        assert service_file.exists()
        assert "SINGLE-PASS-ALPHA-1" in service_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 6+7. DockerSpringBootCandidateAdapter; no uploaded candidate
# ---------------------------------------------------------------------------

class TestAdapterAndNoUpload:
    def test_normal_path_adapter_and_no_upload(
        self, svc: Service, fake_pipeline
    ) -> None:
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        assert svc.get_application(app_id).java_candidate_path is None

        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED

        assert len(fake_pipeline) == 1
        config, adapter = fake_pipeline[0]
        assert isinstance(adapter, DockerSpringBootCandidateAdapter)
        assert config.use_docker_java is True
        # Provenance: the pipeline validated the GENERATED project.
        assert config.java_candidate_path == \
            svc.get_application(app_id).generated_app_path


# ---------------------------------------------------------------------------
# 8. Async modernization remains 202 + polling
# ---------------------------------------------------------------------------

class TestAsyncPreserved:
    def test_modernize_202_then_poll_to_completed(
        self, fake_pipeline
    ) -> None:
        import api.app as app_mod

        store = Store()
        app_mod._store = store
        app_mod._service = Service(store)
        client = TestClient(app_mod.app)

        app_id = client.post(
            "/applications", json={"name": "sp-async", "workload_id": "wl-sp"}
        ).json()["id"]
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("ALPHA.cob", io.BytesIO(ALPHA.encode()),
                              "text/plain"))],
        )
        resp = client.post(f"/applications/{app_id}/modernize")
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        import time

        deadline = time.time() + 180
        while True:
            body = client.get(f"/runs/{run_id}").json()
            if body["stage"] in ("COMPLETED", "FAILED"):
                break
            assert time.time() < deadline
            time.sleep(1)
        assert body["stage"] == "COMPLETED"

        detail = client.get(f"/runs/{run_id}/detail").json()
        assert detail["application_name"] == "sp-async"
        assert detail["generated_files"], "expected generated file listing"


# ---------------------------------------------------------------------------
# 9. Dynamic application name unchanged by modernize
# ---------------------------------------------------------------------------

class TestDynamicNamePreserved:
    def test_name_survives_single_pass_modernize(
        self, svc: Service, fake_pipeline
    ) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("namedapp/ALPHA.cob", ALPHA)
        app = svc.create_application(
            name="application", description="d", workload_id="wl-sp",
            java_entrypoint="Main",
        )
        svc.ingest_application(app.id, buf.getvalue(), "namedapp.zip")
        assert svc.get_application(app.id).name == "namedapp"

        run = _await_terminal(svc, svc.modernize(app.id).id)
        assert run.stage == RunStage.COMPLETED
        assert svc.get_application(app.id).name == "namedapp"


# ---------------------------------------------------------------------------
# 10. Missing java_application fails cleanly before Spring/Docker
# ---------------------------------------------------------------------------

class TestMissingJavaApplication:
    def test_none_java_application_fails_run(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.java_to_spring_mapping as j2s_mod
        from engine.transformation.application_generator import (
            ApplicationGenerationResult,
            ApplicationGenerator,
        )

        spring_calls: list = []
        real_map = j2s_mod.map_java_application_to_spring_boot

        def _spring_spy(application, **kwargs):
            spring_calls.append(application)
            return real_map(application, **kwargs)

        monkeypatch.setattr(
            j2s_mod, "map_java_application_to_spring_boot", _spring_spy
        )

        def _no_java_app(self, application, entrypoint="", **kwargs):
            # success=True but no JavaApplication: must still fail cleanly.
            programs = tuple(u.program_id for u in application.programs)
            return ApplicationGenerationResult(
                success=True, program_ids=programs, java_application=None
            )


        monkeypatch.setattr(
            ApplicationGenerator, "generate", _no_java_app
        )

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.FAILED
        assert "java application" in run.error.lower()
        assert spring_calls == []
        assert fake_pipeline == []
