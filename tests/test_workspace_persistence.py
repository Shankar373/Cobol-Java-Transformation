"""P0 durable-workspace regression suite (backup coverage + restart survival).

``CONTROL_PLANE_WORKSPACE_DIR`` decides where the three *durable* artifact
sites land:

* ingest workspace (uploaded COBOL)        — ``api.ingestion.ingest_zip``
* upload workspace (``cobol_source_path``) — ``Service.upload_cobol_source``
* pipeline output (``generated_app_path``) — ``Service._generate_application``

Before this control all three called bare ``tempfile.mkdtemp()``, so in
production they landed in ``$TMPDIR`` — the ``/app/tmp`` tmpfs. The named
``control-plane-work`` volume therefore received no writes at all:
``scripts/backup/backup.sh`` tarred an empty volume (a backup that would
restore nothing), and every container recreate deleted the exact bytes the
evidence seal hashes, so ``GET /runs/{id}/download`` 404'd and revalidation
could never re-verify after a restart.

Red-first: with the env var set, each of the three sites below must create
its directory under the configured root (they failed before ``api/paths.py``
existed only in the sense that no such knob existed — the deployment
contract tests additionally pin compose/Dockerfile so production cannot
silently regress to tmpfs).

Unset (development and the whole test suite) the behaviour must stay
byte-identical to the historical code: ``tempfile.mkdtemp`` with no ``dir``.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.ingestion import ingest_zip
from api.models import RunStage
from api.paths import (
    WORKSPACE_DIR_ENV,
    new_workspace,
    workspace_root,
    workspace_root_problems,
)
from api.service import Service
from api.store import ApplicationRecord, RunRecord, Store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


VALID_ZIP = _zip_bytes([("MAIN.cob", b"       PROGRAM-ID. X.\n")])


def _is_under(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# api.paths unit behaviour
# ---------------------------------------------------------------------------


class TestWorkspaceRootConfig:
    def test_unset_root_is_none(self, monkeypatch):
        monkeypatch.delenv(WORKSPACE_DIR_ENV, raising=False)
        assert workspace_root() is None

    def test_whitespace_only_root_is_none(self, monkeypatch):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, "   ")
        assert workspace_root() is None

    def test_configured_root_is_a_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "durable"))
        assert workspace_root() == tmp_path / "durable"

    def test_default_matches_historical_tempdir_behaviour(self, monkeypatch):
        """No env var → byte-identical to the pre-fix bare mkdtemp call."""
        monkeypatch.delenv(WORKSPACE_DIR_ENV, raising=False)
        ws = new_workspace(prefix="legacy-behaviour-")
        try:
            assert _is_under(ws, Path(tempfile.gettempdir()))
            assert ws.name.startswith("legacy-behaviour-")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_configured_root_is_created_and_used(self, monkeypatch, tmp_path):
        root = tmp_path / "not-created-yet"
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(root))
        ws = new_workspace(prefix="durable-")
        try:
            assert root.is_dir(), "the configured root must be created"
            assert _is_under(ws, root)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_unusable_root_fails_loudly_naming_the_variable(
        self, monkeypatch, tmp_path
    ):
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"I am a file, not a directory")
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(blocker / "sub"))
        with pytest.raises(OSError, match=WORKSPACE_DIR_ENV):
            new_workspace(prefix="doomed-")


class TestReadinessProbe:
    def test_unset_root_is_not_a_problem(self, monkeypatch):
        monkeypatch.delenv(WORKSPACE_DIR_ENV, raising=False)
        assert workspace_root_problems() == []

    def test_writable_root_is_not_a_problem(self, monkeypatch, tmp_path):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "ok"))
        assert workspace_root_problems() == []

    def test_unusable_root_is_reported(self, monkeypatch, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"I am a file, not a directory")
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(blocker / "sub"))
        problems = workspace_root_problems()
        assert problems, "a configured-but-unusable root must fail readiness"
        assert WORKSPACE_DIR_ENV in problems[0]

    def test_probe_leaves_no_residue(self, monkeypatch, tmp_path):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "clean"))
        workspace_root_problems()
        assert list((tmp_path / "clean").iterdir()) == []


# ---------------------------------------------------------------------------
# The three durable call sites
# ---------------------------------------------------------------------------


class TestIngestWorkspaceIsDurable:
    def test_ingest_lands_under_configured_root(self, monkeypatch, tmp_path):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "work"))
        ws = ingest_zip(VALID_ZIP, "app-durable-ingest")
        try:
            assert _is_under(Path(ws), tmp_path / "work")
            assert (Path(ws) / "MAIN.cob").is_file()
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_rejected_ingest_still_cleans_up_under_configured_root(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "work"))
        from api.ingestion import IngestionError

        with pytest.raises(IngestionError):
            ingest_zip(_zip_bytes([("../../escape.cbl", b"x")]), "app-hostile")
        root = tmp_path / "work"
        if root.exists():
            assert list(root.iterdir()) == []


class TestUploadWorkspaceIsDurable:
    def test_uploaded_source_lands_under_configured_root(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "work"))
        svc = Service(Store(db_path=tmp_path / "upload-durable.db"))
        app = svc.create_application(
            name="durable-upload", description="d",
            workload_id="wl-durable", java_entrypoint="Main",
        )
        svc.upload_cobol_source(app.id, {"MAIN.cob": b"       PROGRAM-ID. X.\n"})
        app = svc.get_application(app.id)
        assert app.cobol_source_path is not None
        assert _is_under(Path(app.cobol_source_path), tmp_path / "work")


class TestGenerationOutputIsDurable:
    def test_pipeline_output_lands_under_configured_root(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "work"))
        captured: dict = {}

        class FakePipeline:
            def __init__(self, config):
                captured["config"] = config

            def execute(self, progress=None):
                return SimpleNamespace(
                    generation_success=True,
                    generated_project_dir=captured["config"].output_dir,
                    generated_entrypoint="Main",
                    discovered_programs=(),
                    generated_program_ids=(),
                    limitations=(),
                    recommendations=(),
                    generation_errors=(),
                    to_dict=lambda: {},
                )

        # The import inside _generate_application resolves this name at call
        # time, so the source module is the patch target.
        monkeypatch.setattr(
            "engine.modernization.pipeline.UniversalModernizationPipeline",
            FakePipeline,
        )
        monkeypatch.setattr(
            "engine.docker_cli.check_docker_available",
            lambda *args, **kwargs: False,
        )

        store = Store(db_path=tmp_path / "gen-durable.db")
        svc = Service(store)
        app = ApplicationRecord(
            id="app-gen-durable", name="gen-durable", description="",
            workload_id="wl-gen-durable", java_entrypoint="Main",
            cobol_source_path="/source",
        )
        store.add_application(app)
        run = RunRecord(
            id="run-gen-durable", application_id=app.id,
            workload_id=app.workload_id, stage=RunStage.TRANSFORMING,
        )
        store.add_run(run)

        output_dir = None
        try:
            svc._generate_application(app, run)
            output_dir = captured["config"].output_dir
            assert _is_under(Path(output_dir), tmp_path / "work"), (
                "the generated bundle must be created on the durable volume: "
                "it is referenced by generated_app_path, hashed by the "
                "evidence seal, and served by /runs/{id}/download - the "
                "$TMPDIR tmpfs loses all of it on restart"
            )
            assert Path(output_dir).is_dir()
            # The seal must verify against the durable bytes in place...
            from api.artifact_seal import verify_generated_seal
            from api.errors import ConflictError

            fresh = store.get_run(run.id)
            assert fresh.generated_seal is not None
            verify_generated_seal(Path(output_dir), fresh.generated_seal)
            # ...and must refuse substitution of those same durable bytes.
            (Path(output_dir) / "planted.java").write_text("evil")
            with pytest.raises(ConflictError):
                verify_generated_seal(Path(output_dir), fresh.generated_seal)
        finally:
            if output_dir:
                shutil.rmtree(output_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Deployment contract: production must point the knob at the volume
# ---------------------------------------------------------------------------


class TestDeploymentContract:
    def test_compose_pins_the_durable_root_to_the_named_volume(self):
        text = (REPO_ROOT / "docker-compose.production.yml").read_text(
            encoding="utf-8"
        )
        assert "CONTROL_PLANE_WORKSPACE_DIR: /app/workspaces" in text, (
            "compose must send durable artifacts to the control-plane-work "
            "volume, otherwise backups tar an empty volume"
        )
        assert "control-plane-work:/app/workspaces" in text

    def test_compose_keeps_tmpfs_as_scratch_only(self):
        text = (REPO_ROOT / "docker-compose.production.yml").read_text(
            encoding="utf-8"
        )
        assert "TMPDIR: /app/tmp" in text
        assert "/app/tmp:rw,noexec,nosuid" in text

    def test_production_image_defaults_to_the_durable_root(self):
        text = (REPO_ROOT / "Dockerfile.production").read_text(encoding="utf-8")
        assert (
            "ENV CONTROL_PLANE_WORKSPACE_DIR=/app/workspaces" in text
        ), "the production image must default to the volume even outside compose"

    def test_example_env_documents_the_variable(self):
        text = (REPO_ROOT / ".env.production.example").read_text(
            encoding="utf-8"
        )
        assert WORKSPACE_DIR_ENV in text
