"""Readiness probe (`GET /ready`) — P1 production-readiness gap closure.

``/health`` answers 200 as long as the process is alive, so a control plane
whose SQLite file went read-only or whose durable workspace root became
unusable still looked "healthy" to compose and to any orchestrator. The
RUNBOOK and PRODUCTION docs both recorded that gap ("Readiness — NOT
IMPLEMENTED").

``/ready`` closes it and this suite pins:

* 200 + ``status: ready`` when the gating checks pass (development
  defaults: reachable DB, workspace/staging unset);
* 503 + ``status: not_ready`` when a **gating** check fails — unusable
  ``CONTROL_PLANE_WORKSPACE_DIR``, unusable ``SANDBOX_STAGING_DIR``, or an
  unreachable/read-only database;
* ``docker`` is reported but explicitly non-gating (a host-daemon outage
  cannot be fixed by restarting this container — restarting would loop),
  so a Docker-less host still gets 200 with ``docker.ok: false``;
* the probe is reachable **without** a token, like ``/health`` (orchestrators
  cannot authenticate) while leaking nothing sensitive;
* ``Store.probe_database`` really distinguishes a writable file from a
  missing/read-only one.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.app as app_mod
from api.app import app
from api.paths import WORKSPACE_DIR_ENV
from api.store import Store

client = TestClient(app)

STAGING_ENV = "SANDBOX_STAGING_DIR"


class TestReadinessHappyPath:
    def test_ready_with_development_defaults(self):
        resp = client.get("/ready")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ready"
        checks = body["checks"]
        for name in ("database", "workspace", "staging", "docker", "jobs"):
            assert name in checks, f"/ready must report {name}"
        assert checks["database"]["ok"] is True
        assert checks["docker"]["gating"] is False, (
            "a host docker outage must not gate readiness: restarting this "
            "container cannot fix the daemon and would restart-loop"
        )
        assert checks["jobs"]["gating"] is False
        assert isinstance(checks["jobs"]["limit"], int)

    def test_ready_is_reachable_without_a_token(self, monkeypatch):
        """Probes cannot authenticate, exactly like /health."""
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")
        resp = client.get("/ready")
        assert resp.status_code == 200, resp.text

    def test_ready_never_leaks_the_token(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")
        resp = client.get("/ready")
        assert "sekret-token" not in resp.text

    def test_other_routes_still_require_the_token(self, monkeypatch):
        """The exemption is exactly /health and /ready — nothing wider."""
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")
        assert client.get("/runs/any").status_code == 401
        assert client.get("/applications").status_code == 401
        assert client.get("/health").status_code == 200


class TestReadinessGatingFailures:
    def test_unusable_workspace_root_returns_503(self, monkeypatch, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"I am a file, not a directory")
        monkeypatch.setenv(WORKSPACE_DIR_ENV, str(blocker / "sub"))
        resp = client.get("/ready")
        assert resp.status_code == 503, resp.text
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["workspace"]["ok"] is False
        assert WORKSPACE_DIR_ENV in body["checks"]["workspace"]["detail"]

    def test_unusable_staging_root_returns_503(self, monkeypatch, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"I am a file, not a directory")
        monkeypatch.setenv(STAGING_ENV, str(blocker / "sub"))
        resp = client.get("/ready")
        assert resp.status_code == 503, resp.text
        assert resp.json()["checks"]["staging"]["ok"] is False

    def test_writable_staging_root_is_ready(self, monkeypatch, tmp_path):
        monkeypatch.setenv(STAGING_ENV, str(tmp_path / "staging"))
        resp = client.get("/ready")
        assert resp.status_code == 200, resp.text
        assert resp.json()["checks"]["staging"]["ok"] is True

    def test_database_failure_returns_503(self, monkeypatch):
        monkeypatch.setattr(
            app_mod._store, "probe_database", lambda: (False, "disk says no")
        )
        resp = client.get("/ready")
        assert resp.status_code == 503, resp.text
        body = resp.json()
        assert body["checks"]["database"] == {
            "ok": False,
            "detail": "disk says no",
        }


class TestDockerCheckIsReportedNotGating:
    def test_dockerless_host_still_ready(self, monkeypatch):
        monkeypatch.setattr(
            "engine.docker_cli.check_docker_available",
            lambda *a, **k: False,
        )
        resp = client.get("/ready")
        assert resp.status_code == 200, resp.text
        docker_check = resp.json()["checks"]["docker"]
        assert docker_check["ok"] is False
        assert docker_check["gating"] is False


class TestProbeDatabase:
    def test_writable_file_reports_ok(self, tmp_path):
        store = Store(db_path=tmp_path / "probe.db")
        ok, detail = store.probe_database()
        assert ok is True, detail
        assert "writable" in detail

    def test_missing_file_reports_failure(self, tmp_path):
        store = Store(db_path=tmp_path / "probe2.db")
        # Simulate the file disappearing (volume unmounted / renamed).
        store._db_path = str(tmp_path / "gone" / "missing.db")
        ok, detail = store.probe_database()
        assert ok is False
        assert detail

    def test_memory_store_reports_ok(self):
        store = Store()
        ok, detail = store.probe_database()
        assert ok is True, detail

    def test_probe_does_not_disturb_the_live_connection(self, tmp_path):
        """A separate probe connection must leave the service's data intact."""
        from api.store import ApplicationRecord

        store = Store(db_path=tmp_path / "probe3.db")
        store.add_application(
            ApplicationRecord(
                id="app-probe",
                name="probe",
                description="",
                workload_id="wl-probe",
                java_entrypoint="Main",
            )
        )
        ok, _ = store.probe_database()
        assert ok is True
        assert store.get_application("app-probe") is not None
