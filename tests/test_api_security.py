"""API security tests (Phase B).

Covers the control plane's security envelope:

  * bearer-token authentication (opt-in via ``CONTROL_PLANE_API_TOKEN``),
    including the constant-time comparison guard;
  * upload path safety — traversal/drive letters rejected, colliding
    paths rejected, absolute paths contained inside the workspace,
    directory hierarchy preserved;
  * request/file/file-count limits -> 413 at the HTTP layer with the
    same defense-in-depth checks still present in the service layer;
  * background job concurrency limit -> 429, with slots released even
    when a worker raises;
  * unknown resources answer 404 (never 500) on every previously
    unguarded endpoint;
  * error bodies stay client-safe (truncated, no tracebacks/paths).
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.errors import ServiceError
from api.service import Service
from api.store import Store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    yield store


def _create_app(name: str, workload_id: str = "wl-upload-safety") -> str:
    resp = client.post(
        "/applications", json={"name": name, "workload_id": workload_id}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(app_id: str, entries: list[tuple[str, bytes]]):
    files = [
        ("files", (name, io.BytesIO(content), "text/plain"))
        for name, content in entries
    ]
    return client.post(f"/applications/{app_id}/upload", files=files)


# ---------------------------------------------------------------------------
# Bearer token authentication
# ---------------------------------------------------------------------------


class TestBearerTokenAuth:
    def test_auth_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)
        assert client.get("/health").status_code == 200
        assert client.get("/applications").status_code == 200

    def test_missing_credentials_rejected(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        resp = client.get("/applications")

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    def test_wrong_token_rejected(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        wrong = client.get(
            "/applications", headers={"Authorization": "Bearer wrong-token"}
        )
        empty = client.get("/applications", headers={"Authorization": "Bearer "})

        assert wrong.status_code == 401
        assert empty.status_code == 401

    def test_valid_bearer_token_accepted(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        ok = client.get(
            "/applications", headers={"Authorization": "Bearer sekret-token"}
        )
        # Mutated token must not authenticate even with a prefix match.
        mutated = client.get(
            "/applications", headers={"Authorization": "Bearer sekret-tokeX"}
        )

        assert ok.status_code == 200
        assert mutated.status_code == 401

    def test_x_api_key_header_accepted(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        resp = client.get("/applications", headers={"X-API-Key": "sekret-token"})

        assert resp.status_code == 200

    def test_health_stays_reachable_for_probes(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        resp = client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_token_comparison_is_constant_time(self):
        source = (Path(__file__).resolve().parent.parent / "api" / "app.py").read_text(
            encoding="utf-8"
        )
        assert "hmac.compare_digest" in source
        # No plain equality comparison of the presented token.
        assert "provided == token" not in source
        assert "token == provided" not in source


# ---------------------------------------------------------------------------
# Upload path safety
# ---------------------------------------------------------------------------


class TestUploadPathSafety:
    def test_parent_traversal_rejected(self):
        app_id = _create_app("traversal")

        resp = _upload(app_id, [("../evil.cob", b"EVIL")])

        assert resp.status_code == 400
        assert "'..' segment" in resp.json()["detail"]
        # Nothing was recorded, so no workspace path can be served.
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] is None

    def test_nested_traversal_rejected(self):
        app_id = _create_app("nested-traversal")

        resp = _upload(app_id, [("src/../../evil.cob", b"EVIL")])

        assert resp.status_code == 400

    def test_drive_letter_rejected_at_service_layer(self):
        """The transport may normalize names, but the service never trusts them.

        httpx strips ``C:\\`` from multipart filenames before they reach the
        app, so the drive-letter rule is exercised directly against the
        service layer (defense in depth for any other client).
        """
        with pytest.raises(ServiceError) as exc:
            Service._validate_upload({"C:\\evil.cob": b"EVIL"})
        assert "drive letter" in str(exc.value)

        with pytest.raises(ServiceError):
            Service._validate_upload({"D:/evil.cob": b"EVIL"})

    def test_drive_letter_name_is_contained_by_transport_normalization(self):
        app_id = _create_app("drive-letter")

        resp = _upload(app_id, [("C:\\evil.cob", b"EVIL")])

        # Even after the transport reduces the name to its final component,
        # the file is written only inside the per-application workspace.
        assert resp.status_code in (201, 400), resp.text
        if resp.status_code == 201:
            base = Path(resp.json()["cobol_source_path"])
            written = list(base.rglob("*"))
            assert written and all(
                p.resolve().is_relative_to(base.resolve()) for p in written
            )

    def test_colliding_paths_rejected(self):
        app_id = _create_app("collision")

        resp = _upload(
            app_id, [("src/A.cob", b"ONE"), ("src\\A.cob", b"TWO")]
        )

        assert resp.status_code == 400
        assert "same path" in resp.json()["detail"]
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] is None

    def test_directory_hierarchy_preserved(self):
        app_id = _create_app("hierarchy")

        resp = _upload(
            app_id,
            [("src/A.cob", b"AAA"), ("copy/B.cob", b"BBB"), ("A.cob", b"ROOT")],
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["files_received"] == 3
        base = Path(resp.json()["cobol_source_path"])
        assert (base / "src" / "A.cob").read_bytes() == b"AAA"
        assert (base / "copy" / "B.cob").read_bytes() == b"BBB"
        assert (base / "A.cob").read_bytes() == b"ROOT"
        # No flattening: same file name in two directories stays distinct.
        assert (base / "A.cob").exists() and (base / "src" / "A.cob").exists()

    def test_absolute_path_contained_in_workspace(self):
        app_id = _create_app("absolute")

        resp = _upload(app_id, [("/etc/passwd", b"pwned")])

        # Whether the transport keeps the leading separator or reduces the
        # name, the entry may only ever land inside the workspace.
        assert resp.status_code in (201, 400), resp.text
        if resp.status_code != 201:
            return
        base = Path(resp.json()["cobol_source_path"])
        written = [p for p in base.rglob("*") if p.is_file()]
        assert written
        assert all(p.resolve().is_relative_to(base.resolve()) for p in written)
        if (base / "etc" / "passwd").exists():
            assert (base / "etc" / "passwd").read_bytes() == b"pwned"

    def test_unusable_names_rejected_at_service_layer(self):
        for name in ("./", "", ".", "/"):
            with pytest.raises(ServiceError) as exc:
                Service._validate_upload({name: b"X"})
            assert "no usable file name" in str(exc.value)

    def test_unusable_name_upload_leaves_no_workspace(self):
        app_id = _create_app("bad-names")

        resp = _upload(app_id, [("./", b"X")])

        if resp.status_code == 400:
            assert client.get(f"/applications/{app_id}").json()[
                "cobol_source_path"
            ] is None
        else:
            # Transport reduced the name to a usable component; the file
            # must still be confined to the workspace.
            base = Path(resp.json()["cobol_source_path"])
            assert all(
                p.resolve().is_relative_to(base.resolve())
                for p in base.rglob("*")
            )


# ---------------------------------------------------------------------------
# Upload limits (413)
# ---------------------------------------------------------------------------


class TestUploadLimits:
    def test_file_count_limit_returns_413(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_UPLOAD_FILES", "1")
        app_id = _create_app("too-many-files")

        resp = _upload(app_id, [("A.cob", b"A"), ("B.cob", b"B")])

        assert resp.status_code == 413
        assert "Too many files" in resp.json()["detail"]

    def test_file_size_limit_returns_413(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_FILE_BYTES", "16")
        app_id = _create_app("file-too-big")

        resp = _upload(app_id, [("A.cob", b"x" * 32)])

        assert resp.status_code == 413
        assert "byte limit" in resp.json()["detail"]

    def test_request_size_limit_returns_413(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_REQUEST_BYTES", "8")
        app_id = _create_app("request-too-big")

        resp = _upload(app_id, [("A.cob", b"x" * 32)])

        assert resp.status_code == 413

    def test_limits_reject_before_anything_is_written(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_FILE_BYTES", "4")
        app_id = _create_app("no-write")

        resp = _upload(app_id, [("A.cob", b"too much")])

        assert resp.status_code == 413
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] is None

    def test_invalid_limit_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_FILE_BYTES", "not-a-number")
        app_id = _create_app("bad-env")

        resp = _upload(app_id, [("A.cob", b"fine")])

        assert resp.status_code == 201

    def test_service_layer_enforces_file_count_independently(
        self, monkeypatch
    ):
        """Defense in depth: the service rejects over-limit uploads too."""
        monkeypatch.setenv("CONTROL_PLANE_MAX_UPLOAD_FILES", "2")
        files = {f"{i}.cob": b"x" for i in range(3)}

        with pytest.raises(ServiceError) as exc:
            Service._validate_upload(files)
        assert "Too many files" in str(exc.value)

    def test_service_layer_rejects_non_binary_content(self):
        with pytest.raises(ServiceError):
            Service._validate_upload({"A.cob": "not-bytes"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Background job concurrency limit (429)
# ---------------------------------------------------------------------------


class TestJobConcurrencyLimit:
    def _blocking_worker(self, release: threading.Event, started: threading.Event):
        def worker(self_svc, *args, **kwargs):
            started.set()
            release.wait(timeout=15)

        return worker

    def test_concurrent_job_limit_returns_429_and_releases_slots(
        self, monkeypatch
    ):
        import api.app as app_mod

        monkeypatch.setenv("CONTROL_PLANE_MAX_CONCURRENT_JOBS", "1")
        started = threading.Event()
        release = threading.Event()
        worker = self._blocking_worker(release, started)

        app_a = _create_app("slot-a")
        app_b = _create_app("slot-b")
        app_c = _create_app("slot-c")
        for app_id in (app_a, app_b, app_c):
            assert _upload(app_id, [("A.cob", b"A")]).status_code == 201

        with patch.object(Service, "_modernize_background", worker):
            first = client.post(f"/applications/{app_a}/modernize")
            assert first.status_code == 202
            assert started.wait(timeout=15), "worker never started"

            second = client.post(f"/applications/{app_b}/modernize")
            assert second.status_code == 429
            assert "Concurrent job limit" in second.json()["detail"]

            release.set()
            # Slot must come back once the worker returns.
            deadline = time.monotonic() + 15
            while app_mod._service._active_jobs > 0:
                assert time.monotonic() < deadline, "slot never released"
                time.sleep(0.05)

            third = client.post(f"/applications/{app_c}/modernize")
            assert third.status_code == 202

    def test_slot_released_when_worker_raises(self, monkeypatch):
        import api.app as app_mod

        monkeypatch.setenv("CONTROL_PLANE_MAX_CONCURRENT_JOBS", "1")
        app_id = _create_app("exploding-worker")
        assert _upload(app_id, [("A.cob", b"A")]).status_code == 201

        def explode(self_svc, app_id_arg, run_id, *args, **kwargs):
            # Real workers fail the run before propagating; emulate that so
            # the slot-release guarantee is tested against a terminal run.
            run = self_svc._store.get_run(run_id)
            self_svc._finish_failed(run, "worker crashed")
            raise RuntimeError("worker crashed")

        # Capture the dying worker's exception instead of letting pytest's
        # thread plugin warn about it — and assert the crash really happened.
        crashes: list[BaseException] = []
        original_hook = threading.excepthook

        def _capture(args):
            if args.exc_value is not None:
                crashes.append(args.exc_value)

        threading.excepthook = _capture
        try:
            with patch.object(Service, "_modernize_background", explode):
                resp = client.post(f"/applications/{app_id}/modernize")
                assert resp.status_code == 202
                deadline = time.monotonic() + 15
                while app_mod._service._active_jobs > 0:
                    assert time.monotonic() < deadline, "slot leaked on crash"
                    time.sleep(0.05)
                while not crashes:
                    assert time.monotonic() < deadline, "worker crash unseen"
                    time.sleep(0.05)
        finally:
            threading.excepthook = original_hook

        assert any(
            isinstance(exc, RuntimeError) and "worker crashed" in str(exc)
            for exc in crashes
        )

        # The run itself failed closed into a terminal state.
        run_id = client.get(f"/applications/{app_id}/runs").json()[0]["id"]
        deadline = time.monotonic() + 15
        stage = ""
        while stage not in ("COMPLETED", "FAILED"):
            stage = client.get(f"/runs/{run_id}").json()["stage"]
            assert time.monotonic() < deadline, f"run stuck in {stage!r}"
            time.sleep(0.05)
        assert stage == "FAILED"


# ---------------------------------------------------------------------------
# Every previously unguarded endpoint answers 404 for unknown ids
# ---------------------------------------------------------------------------


class TestUnknownResourcesAre404:
    def test_unknown_run_endpoints(self):
        checks = [
            ("GET", "/runs/run-ghost"),
            ("GET", "/runs/run-ghost/detail"),
            ("GET", "/runs/run-ghost/artifacts"),
            ("GET", "/runs/run-ghost/verdict"),
            ("GET", "/runs/run-ghost/report"),
            ("GET", "/runs/run-ghost/download"),
            ("POST", "/runs/run-ghost/validate"),
        ]
        for method, path in checks:
            resp = client.request(method, path)
            assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
            assert "Traceback" not in resp.text

    def test_unknown_application_endpoints(self):
        checks = [
            ("GET", "/applications/app-ghost"),
            ("GET", "/applications/app-ghost/runs"),
            ("GET", "/applications/app-ghost/discovery"),
            ("POST", "/applications/app-ghost/modernize"),
        ]
        for method, path in checks:
            resp = client.request(method, path)
            assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"

        upload = _upload("app-ghost", [("A.cob", b"A")])
        assert upload.status_code == 404

    def test_download_without_generated_artifact_is_404(self):
        app_id = _create_app("no-artifact")
        _upload(app_id, [("A.cob", b"A")])
        with patch.object(Service, "_modernize_background", lambda *a, **k: None):
            run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 404
        assert "No generated Java application" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Client-safe error bodies
# ---------------------------------------------------------------------------


class TestErrorBodiesAreClientSafe:
    def test_404_detail_is_short_and_generic(self):
        resp = client.get("/runs/run-ghost")

        detail = resp.json()["detail"]
        assert len(detail) <= 500
        assert "Traceback" not in detail
        assert "site-packages" not in detail
        assert "\\" not in detail  # no filesystem paths

    def test_400_upload_detail_has_no_paths(self):
        app_id = _create_app("detail-safety")

        resp = _upload(app_id, [("../x.cob", b"X")])

        detail = resp.json()["detail"]
        assert len(detail) <= 500
        assert "Traceback" not in detail
        assert str(Path(__file__).parent) not in detail
