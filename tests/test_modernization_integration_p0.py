"""Integration tests — canonical API modernization flow (P0).

Proves the REAL SystemaOps MVP workflow is wired to program-level
transformation:

    COBOL ZIP/upload
    -> secure ingestion
    -> ApplicationDiscovery
    -> ApplicationGenerator (per-program, no concatenation)
    -> generated-app/ (the verification candidate)
    -> verification pipeline (Docker candidate selection)
    -> downloadable generated-application ZIP

Docker-free by construction: the verification pipeline is replaced with a
recording fake at the exact boundary the service imports
(api.service.VerticalSlicePipeline). These tests prove STRUCTURAL
integration (wiring, provenance, adapter selection) — NOT execution.
Fresh generated-Java -> Docker build/run -> oracle -> VERIFIED remains
blocked until Docker is available.

Coverage:
  A. Normal modernization needs no uploaded Java candidate.
  B. Service invokes ApplicationGenerator.
  C. Multiple COBOL programs -> multiple generated Java classes.
  D. No COBOL source concatenation occurs.
  E. Generated artifact becomes the candidate path.
  F. Normal path selects Docker candidate execution (use_docker_java=True).
  G. RealJavaCandidateAdapter is never selected for the normal path.
  H. Download packages the generated artifact (never an upload).
  I. COPYBOOK does not become an executable generated class.
  J. ApplicationGenerator failure surfaces as controlled modernization failure.
  K. Entrypoint comes from generated application metadata.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.service as svc_mod
from api.models import RunStage
from api.service import Service, ServiceError
from api.store import Store
from engine.transformation.application_generator import ApplicationGenerationResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


ALPHA = _cobol("ALPHA", "ALPHA-MARKER-INT-1", "WS-ALPHA-FIELD")
BETA = _cobol("BETA", "BETA-MARKER-INT-2", "WS-BETA-FIELD")

MAIN_WITH_COPY = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAINPROG.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-X PIC X(5) VALUE 'X'.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "MAINPROG-MARKER-INT-3" WS-X.\n'
    "           STOP RUN.\n"
)
COMMON_COPYBOOK = "       01 COMMON-REC PIC X(20).\n"


class _FakeResult:
    evidence_manifest = None
    verdict = None


@pytest.fixture()
def fake_pipeline(monkeypatch):
    """Replace the verification pipeline with a recording fake.

    Captures (config, candidate_adapter) pairs so tests can prove which
    candidate adapter the service selected for each path.
    """
    captured: list = []

    class _FakePipeline:
        def __init__(self, config, candidate_adapter=None):
            captured.append((config, candidate_adapter))

        def run(self, controlled_input=None, progress=None):
            return _FakeResult()

    monkeypatch.setattr(svc_mod, "VerticalSlicePipeline", _FakePipeline)
    return captured


def _pipeline_config(captured):
    return captured[0][0]


def _pipeline_adapter(captured):
    return captured[0][1]


SPRING_ENTRY = "com.generated.app.Application"
SERVICE_A = Path("src/main/java/com/generated/app/service/Alpha.java")
SERVICE_B = Path("src/main/java/com/generated/app/service/Beta.java")


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
        name="int-app", description="d", workload_id="wl-int", java_entrypoint="Main"
    )
    svc.upload_cobol_source(
        app.id, {name: content.encode() for name, content in files.items()}
    )
    return app.id


# ---------------------------------------------------------------------------
# A. Normal modernization needs no uploaded Java candidate
# ---------------------------------------------------------------------------

class TestNoUploadedCandidateRequired:
    def test_modernize_without_candidate_completes(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        app = svc.get_application(app_id)
        assert app.java_candidate_path is None  # no upload ever happened

        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.COMPLETED
        assert run.error is None
        # The pipeline ran exactly once against the generated artifact.
        assert len(fake_pipeline) == 1


# ---------------------------------------------------------------------------
# B. Service invokes ApplicationGenerator
# ---------------------------------------------------------------------------

class TestGeneratorInvoked:
    def test_service_calls_application_generator(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.application_generator as ag_mod

        calls: list = []
        real_generate = ag_mod.ApplicationGenerator.generate

        def _spy(self, application, entrypoint="", **kwargs):
            calls.append((application, entrypoint))
            return real_generate(self, application, entrypoint, **kwargs)

        monkeypatch.setattr(ag_mod.ApplicationGenerator, "generate", _spy)

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        _await_terminal(svc, svc.modernize(app_id).id)

        assert len(calls) == 1
        discovered_app, _ = calls[0]
        assert {u.program_id for u in discovered_app.programs} == {"ALPHA", "BETA"}


# ---------------------------------------------------------------------------
# C. Multiple programs -> multiple generated classes
# ---------------------------------------------------------------------------

class TestMultiProgramGeneration:
    def test_two_programs_two_services(self, svc: Service, fake_pipeline) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        _await_terminal(svc, svc.modernize(app_id).id)

        app = svc.get_application(app_id)
        assert set(app.generated_program_ids) == {"ALPHA", "BETA"}
        assert set(app.discovered_program_ids) == {"ALPHA", "BETA"}

        project = Path(app.generated_app_path)
        assert (project / "pom.xml").exists()
        assert (project / SERVICE_A).exists()
        assert (project / SERVICE_B).exists()
        assert "Alpha" in (project / SERVICE_A).read_text(encoding="utf-8")
        assert "Beta" in (project / SERVICE_B).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# D. No COBOL source concatenation
# ---------------------------------------------------------------------------

class TestNoConcatenation:
    def test_sources_untouched_and_classes_isolated(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED

        app = svc.get_application(app_id)
        src_dir = Path(app.cobol_source_path)
        # Source tree untouched: each file holds only its own program.
        assert "BETA" not in (src_dir / "ALPHA.cob").read_text(encoding="utf-8")
        assert "ALPHA" not in (src_dir / "BETA.cob").read_text(encoding="utf-8")

        project = Path(app.generated_app_path)
        alpha_src = (project / SERVICE_A).read_text(encoding="utf-8")
        beta_src = (project / SERVICE_B).read_text(encoding="utf-8")
        assert "ALPHA-MARKER-INT-1" in alpha_src
        assert "BETA-MARKER-INT-2" not in alpha_src
        assert "BETA-MARKER-INT-2" in beta_src
        assert "ALPHA-MARKER-INT-1" not in beta_src

    def test_old_concatenation_path_removed(self) -> None:
        assert not hasattr(Service, "_run_transformation")


# ---------------------------------------------------------------------------
# E. Generated artifact becomes the candidate path
# ---------------------------------------------------------------------------

class TestCandidateProvenance:
    def test_candidate_path_is_generated_dir(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        _await_terminal(svc, svc.modernize(app_id).id)

        app = svc.get_application(app_id)
        assert app.generated_app_path is not None
        assert app.java_candidate_path == app.generated_app_path
        assert (
            _pipeline_config(fake_pipeline).java_candidate_path
            == app.generated_app_path
        )


# ---------------------------------------------------------------------------
# F + G. Docker candidate selection, no host adapter
# ---------------------------------------------------------------------------

class TestDockerCandidateSelection:
    def test_normal_path_uses_docker_java(self, svc: Service, fake_pipeline) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        _await_terminal(svc, svc.modernize(app_id).id)
        assert _pipeline_config(fake_pipeline).use_docker_java is True

    def test_normal_path_injects_spring_boot_adapter(
        self, svc: Service, fake_pipeline
    ) -> None:
        from engine.candidate.docker_spring_boot_adapter import (
            DockerSpringBootCandidateAdapter,
        )

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        _await_terminal(svc, svc.modernize(app_id).id)
        assert isinstance(
            _pipeline_adapter(fake_pipeline), DockerSpringBootCandidateAdapter
        )

    def test_host_adapter_never_wired_in_service(self) -> None:
        source = Path(svc_mod.__file__).read_text(encoding="utf-8")
        # No import and no instantiation of the host-execution adapter
        # (docstrings may name it only to document the prohibition).
        assert "from engine.candidate.java_adapter import" not in source
        assert "RealJavaCandidateAdapter(" not in source
        assert "use_docker_java=False" not in source


# ---------------------------------------------------------------------------
# H. Download packages the generated artifact
# ---------------------------------------------------------------------------

def _fresh_client():
    import api.app as app_mod

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    return TestClient(app_mod.app)


def _await_run_http(client, run_id: str, timeout_s: float = 180.0) -> dict:
    """Poll GET /runs/{id} until terminal (sync/background tolerant)."""
    import time

    deadline = time.time() + timeout_s
    while True:
        body = client.get(f"/runs/{run_id}").json()
        if body["stage"] in ("COMPLETED", "FAILED"):
            return body
        if time.time() > deadline:
            raise TimeoutError(f"run {run_id} stuck at {body['stage']}")
        time.sleep(1)


class TestDownloadProvenance:
    def test_download_contains_generated_classes(self, fake_pipeline) -> None:
        client = _fresh_client()
        app_id = client.post(
            "/applications",
            json={"name": "dl", "workload_id": "wl-dl"},
        ).json()["id"]
        client.post(
            f"/applications/{app_id}/upload",
            files=[
                ("files", ("ALPHA.cob", io.BytesIO(ALPHA.encode()), "text/plain")),
                ("files", ("BETA.cob", io.BytesIO(BETA.encode()), "text/plain")),
            ],
        )
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        assert _await_run_http(client, run_id)["stage"] == "COMPLETED"

        resp = client.get(f"/runs/{run_id}/download")
        assert resp.status_code == 200
        service_a = str(SERVICE_A).replace("\\", "/")
        service_b = str(SERVICE_B).replace("\\", "/")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
        assert "pom.xml" in names
        assert service_a in names
        assert service_b in names
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert "ALPHA-MARKER-INT-1" in zf.read(service_a).decode()
            assert "BETA-MARKER-INT-2" in zf.read(service_b).decode()

    def test_download_without_generated_artifact_is_404(self, fake_pipeline) -> None:
        client = _fresh_client()
        app_id = client.post(
            "/applications",
            json={"name": "up-only", "workload_id": "wl-up"},
        ).json()["id"]
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("A.cob", io.BytesIO(ALPHA.encode()), "text/plain"))],
        )
        # Internal/test-only path: validates the UPLOAD, generates nothing.
        client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Up.java", io.BytesIO(b"public class Up {}"), "text/plain"))],
        )
        run_id = client.post(
            f"/applications/{app_id}/modernize",
            json={"use_uploaded_candidate": True},
        ).json()["run_id"]
        _await_run_http(client, run_id)

        resp = client.get(f"/runs/{run_id}/download")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# I. Copybook handling
# ---------------------------------------------------------------------------

class TestCopybookNotExecutable:
    def test_copybook_produces_no_java_class(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(
            svc, {"MAIN.cob": MAIN_WITH_COPY, "COMMON.cpy": COMMON_COPYBOOK}
        )
        run = _await_terminal(svc, svc.modernize(app_id).id)
        assert run.stage == RunStage.COMPLETED

        app = svc.get_application(app_id)
        assert app.generated_program_ids == ("MAINPROG",)
        names = [
            p.name for p in Path(app.generated_app_path).rglob("*.java")
        ]
        # Shared data model exists under model/ ...
        assert "CommonRecord.java" in names
        # ... but no executable program class was generated for the copybook.
        assert "Common.java" not in names
        assert app.generated_entrypoint != "com.generated.app.model.CommonRecord"


# ---------------------------------------------------------------------------
# J. Controlled generation failure
# ---------------------------------------------------------------------------

class TestGenerationFailure:
    def test_generator_failure_fails_run_cleanly(
        self, svc: Service, fake_pipeline, monkeypatch
    ) -> None:
        import engine.transformation.application_generator as ag_mod

        def _fail(self, application, entrypoint=""):
            return ApplicationGenerationResult(
                success=False, errors=("synthetic generation boom",)
            )

        monkeypatch.setattr(ag_mod.ApplicationGenerator, "generate", _fail)

        app_id = _make_app(svc, {"ALPHA.cob": ALPHA})
        run = _await_terminal(svc, svc.modernize(app_id).id)

        assert run.stage == RunStage.FAILED
        assert "generation" in run.error.lower()
        # Validation never ran against a phantom candidate.
        assert fake_pipeline == []


# ---------------------------------------------------------------------------
# K. Entrypoint from generated metadata
# ---------------------------------------------------------------------------

class TestGeneratedEntrypoint:
    def test_entrypoint_matches_generator_metadata(
        self, svc: Service, fake_pipeline
    ) -> None:
        app_id = _make_app(svc, {"ALPHA.cob": ALPHA, "BETA.cob": BETA})
        _await_terminal(svc, svc.modernize(app_id).id)

        app = svc.get_application(app_id)
        assert app.generated_entrypoint == SPRING_ENTRY
        # The pipeline received the generated entrypoint, not a filesystem guess.
        assert (
            _pipeline_config(fake_pipeline).java_entrypoint
            == app.generated_entrypoint
        )
