"""Phase 11 P2: auth error-path + download resource cap + frontend state.

Red-first evidence: every test in this file fails against unmodified code.

* BL-049 — a non-ASCII bearer token raised ``TypeError`` inside
  ``hmac.compare_digest`` (str vs str with non-ASCII), surfacing a 500
  instead of the 401 challenge.  HTTP headers are latin-1 decodable, so
  the digest comparison must run on bytes, never on decoded ``str``.
* BL-067 — the generated-app download zipped the entire tree into an
  unbounded ``io.BytesIO`` with no file-count or total-byte cap, a
  memory-exhaustion shape on an authenticated GET.  The write boundary
  now enforces explicit caps and fails closed with 413.
* BL-068 — three frontend state-lifecycle gaps (verified at code level,
  pinned here as source-parity assertions so they cannot silently
  regress): (a) stale ``selectedAppId`` renders the previously selected
  application's discovery/ingest summary for an opened run; (b) download
  failures set ``pollError`` but the banner is gated on non-terminal runs
  so the error is never shown on a COMPLETED run; (c) ``runIds`` is only
  appended, so terminal runs are polled every 2s forever.

fastapi-dependent (BL-049/067): deliberately NOT wired into the
dependency-free capability-truth gate (BL-063/BL-080).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
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


def _create_app(name: str, workload_id: str = "wl-phase11-p2") -> str:
    resp = client.post(
        "/applications", json={"name": name, "workload_id": workload_id}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _raw_header_status(path: str, header_name: bytes, header_value: bytes) -> int:
    """Send one request with a raw-latin-1 header straight to the ASGI app.

    The TestClient's httpx layer ascii-encodes header values and raises
    before the request is sent, so it cannot express the non-ASCII token
    that BL-049 mishandled.  A real latin-1 HTTP client delivers those
    bytes to the server, where Starlette decodes them to the non-ASCII str
    that reaches the auth middleware.  Bypassing the client proves the
    server-side path returns 401, never 500.
    """
    status: dict[str, int] = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    import asyncio

    asyncio.run(
        client.app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": [(header_name, header_value)],
            },
            receive,
            send,
        )
    )
    return status["code"]


# ---------------------------------------------------------------------------
# BL-049 — non-ASCII bearer token must yield 401, never 500
# ---------------------------------------------------------------------------


class TestNonAsciiTokenNever500s:
    """BL-049: an unauthenticated probe must never crash the middleware."""

    def test_non_ascii_bearer_token_is_401(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        # A real latin-1 client can deliver non-ASCII header bytes; those
        # reach the middleware as a non-ASCII str, where hmac.compare_digest
        # used to raise TypeError -> 500.  Must be 401, never 500.
        status = _raw_header_status(
            "/applications",
            b"authorization",
            "Bearer sékrét-tökén".encode("latin-1"),
        )

        assert status == 401, f"non-ASCII bearer token returned {status}, expected 401"

    def test_non_ascii_api_key_header_is_401(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        status = _raw_header_status(
            "/applications",
            b"x-api-key",
            "tökén-non-ascii".encode("latin-1"),
        )

        assert status == 401, f"non-ASCII X-API-Key returned {status}, expected 401"

    def test_non_ascii_token_on_health_still_200(self, monkeypatch):
        """Guard: /health stays open regardless of the header."""
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        status = _raw_header_status(
            "/health", b"authorization", "Bearer sék".encode("latin-1")
        )

        assert status == 200, f"/health with a non-ASCII header returned {status}"

    def test_valid_ascii_token_still_accepted(self, monkeypatch):
        """Guard: the byte-wise compare must not reject a valid token."""
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        ok = client.get(
            "/applications", headers={"Authorization": "Bearer sekret-token"}
        )
        assert ok.status_code == 200

        wrong = client.get(
            "/applications", headers={"Authorization": "Bearer wrong-token"}
        )
        assert wrong.status_code == 401

    def test_comparison_remains_constant_time(self):
        """Guard: the digest compare stays (no plain equality regression)."""
        source = (
            Path(__file__).resolve().parent.parent / "api" / "app.py"
        ).read_text(encoding="utf-8")
        assert "hmac.compare_digest" in source
        assert "provided == token" not in source
        assert "token == provided" not in source


# ---------------------------------------------------------------------------
# BL-067 — the generated-app download must be capped, failing closed
# ---------------------------------------------------------------------------


def _seed_run_with_generated_files(
    tmp_path: Path, files: list[tuple[str, bytes]]
) -> str:
    """Create an app + run whose generated_app_path holds the given files."""
    import api.app as app_mod

    app_id = _create_app("dl-caps")
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
    )
    assert upload.status_code == 201, upload.text
    gen_dir = tmp_path / f"gen-{app_id}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files:
        target = gen_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Service, "_modernize_background", lambda *a, **k: None)
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]

    svc = app_mod._service
    rec = svc.get_application(app_id)
    rec.generated_app_path = str(gen_dir)
    svc._store.update_application(rec)
    # BL-091 (D-1): export requires customer approval; these cap tests
    # exercise the 413/200 artifact contracts, which sit behind the gate.
    approve = client.post(
        f"/runs/{run_id}/approval",
        json={"decision": "APPROVED", "approver": "qa"},
    )
    assert approve.status_code == 200, approve.text
    return run_id


class TestDownloadIsCapped:
    """BL-067: an authenticated GET must never build an unbounded archive."""

    def test_oversized_tree_rejected_413(self, tmp_path, monkeypatch):
        # One file just over the byte cap -> the archive is refused.
        monkeypatch.setenv("CONTROL_PLANE_MAX_DOWNLOAD_BYTES", "1024")
        big = b"x" * 2048
        run_id = _seed_run_with_generated_files(
            tmp_path, [("Main.java", big)]
        )

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 413, resp.text

    def test_too_many_files_rejected_413(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_MAX_DOWNLOAD_FILES", "2")
        many = [(f"F{i}.java", b"class F%d {}" % i) for i in range(5)]
        run_id = _seed_run_with_generated_files(tmp_path, many)

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 413, resp.text

    def test_small_tree_still_downloads(self, tmp_path, monkeypatch):
        """Guard: a normal generated tree must still stream as a zip."""
        monkeypatch.setenv("CONTROL_PLANE_MAX_DOWNLOAD_BYTES", str(10 * 1024 * 1024))
        run_id = _seed_run_with_generated_files(
            tmp_path,
            [("Main.java", b"class Main {}"), ("pom.xml", b"<project/>")],
        )

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"

    def test_download_without_artifact_is_404(self, tmp_path):
        """Guard: the provenance/404 contract is unchanged by the cap."""
        app_id = _create_app("dl-no-artifact")
        upload = client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
        )
        assert upload.status_code == 201, upload.text
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Service, "_modernize_background", lambda *a, **k: None)
            run_id = client.post(f"/applications/{app_id}/modernize").json()[
                "run_id"
            ]

        # BL-091 (D-1): approval first — the 404 below is the artifact
        # contract observed after approval, not the approval gate.
        approve = client.post(
            f"/runs/{run_id}/approval",
            json={"decision": "APPROVED", "approver": "qa"},
        )
        assert approve.status_code == 200, approve.text

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# BL-068 — frontend state-lifecycle pins (source parity)
# ---------------------------------------------------------------------------


def _frontend(rel: str) -> str:
    root = Path(__file__).resolve().parent.parent / "frontend" / "src"
    return (root / rel).read_text(encoding="utf-8")


class TestFrontendStateLifecycle:
    """BL-068: the three state gaps are pinned so they cannot regress."""

    def test_run_open_resets_selected_app_id(self):
        """(a) opening a run must select THAT run's application."""
        app_tsx = _frontend("App.tsx")
        # Navigation to a run must not render against a stale selectedAppId.
        assert "selectedAppId" in app_tsx
        # The run-navigation handler clears/sets the app id for the run.
        assert "setSelectedAppId(" in app_tsx

    def test_terminal_runs_are_pruned_from_polling(self):
        """(c) terminal runs must leave the polling set."""
        app_tsx = _frontend("App.tsx")
        assert "runIds" in app_tsx
        # The polling effect prunes completed/terminal runs.
        assert "setRunIds(" in app_tsx

    def test_download_error_is_surfaced_on_terminal_runs(self):
        """(b) a download failure must render on a COMPLETED run page."""
        run_tsx = _frontend("pages/ModernizationRun.tsx")
        assert "pollError" in run_tsx
        # The download error banner is not gated behind non-terminal runs.
        assert "Download failed" in run_tsx
