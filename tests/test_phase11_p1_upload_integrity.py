"""Phase 11 P1: upload-integrity defects BL-047 + BL-048.

Red-first evidence: the BL-047/BL-048 tests in this file fail against
unmodified code; the guard/contract tests document behavior that must
not regress.

* BL-047 — duplicate upload filenames silently collapse in the API
  ingestion dict (``api/app.py``): two parts carrying the same filename
  overwrite one dict key, so one file is never written and the service's
  documented collision detector can never fire (``files_received``
  undercounts what the client actually sent).
* BL-048 — the upload endpoints delete the previous source directory
  *before* the new upload is validated and written (``api/service.py``):
  a re-upload rejected for traversal/collision/disk error leaves the
  record pointing at a deleted directory and the previous good source
  gone (data loss on the error path).

fastapi-dependent: deliberately NOT wired into the dependency-free
capability-truth gate (BL-063/BL-080); runs in the backend job.
"""

from __future__ import annotations

import io
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


def _create_app(name: str, workload_id: str = "wl-phase11-p1") -> str:
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


def _source_files(app_id: str) -> list[str]:
    """Relative paths of every file currently on disk for this app."""
    base = client.get(f"/applications/{app_id}").json()["cobol_source_path"]
    if base is None or not Path(base).exists():
        return []
    root = Path(base)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# BL-047 — duplicate filenames must not silently collapse
# ---------------------------------------------------------------------------


class TestDuplicateFilenamesRejected:
    """BL-047: an accepted upload must never silently lose a file."""

    def test_duplicate_filename_fails_closed(self):
        app_id = _create_app("dup-name")

        resp = _upload(app_id, [("A.cob", b"FIRST"), ("A.cob", b"SECOND")])

        # The dict keyed by filename previously let the second part
        # overwrite the first, returning 201 with one file on disk and
        # a files_received that undercounted the request.
        assert resp.status_code == 400, resp.text
        assert "duplicate" in resp.json()["detail"].lower()

    def test_duplicate_filename_writes_nothing(self):
        app_id = _create_app("dup-name-no-write")

        resp = _upload(app_id, [("A.cob", b"FIRST"), ("A.cob", b"SECOND")])

        assert resp.status_code == 400, resp.text
        # Fail closed: a rejected upload must not leave a partial tree
        # that a downstream transformation could run on.
        assert _source_files(app_id) == []
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] is None

    def test_duplicate_across_nested_paths_rejected(self):
        """Same basename in two folders is legal; same *name* is not."""
        app_id = _create_app("dup-nested")

        resp = _upload(
            app_id, [("src/A.cob", b"ONE"), ("src/A.cob", b"TWO")]
        )

        assert resp.status_code == 400, resp.text

    def test_distinct_names_still_accepted(self):
        """Guard: the fix must not reject a legitimate multi-file upload."""
        app_id = _create_app("distinct-names")

        resp = _upload(app_id, [("A.cob", b"AAA"), ("B.cob", b"BBB")])

        assert resp.status_code == 201, resp.text
        assert sorted(_source_files(app_id)) == ["A.cob", "B.cob"]


# ---------------------------------------------------------------------------
# BL-048 — a rejected re-upload must preserve the previous source
# ---------------------------------------------------------------------------


class TestRejectedReuploadPreservesPreviousSource:
    """BL-048: cleanup must be ordered after a successful write, never before."""

    @staticmethod
    def _seed_good_source(app_id: str) -> Path:
        resp = _upload(app_id, [("GOOD.cob", b"       IDENTIFICATION DIVISION.")])
        assert resp.status_code == 201, resp.text
        base = resp.json()["cobol_source_path"]
        assert base and Path(base).exists()
        return Path(base)

    def test_traversal_reupload_preserves_previous_source(self):
        app_id = _create_app("reupload-traversal")
        before = self._seed_good_source(app_id)
        assert _source_files(app_id) == ["GOOD.cob"]

        resp = _upload(app_id, [("../evil.cob", b"EVIL")])

        assert resp.status_code == 400, resp.text
        # The record must still point at the ORIGINAL directory...
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] == str(before)
        # ...and that directory must still hold the previous good source.
        assert before.exists(), "previous source dir was deleted by a rejected re-upload"
        assert _source_files(app_id) == ["GOOD.cob"]

    def test_collision_reupload_preserves_previous_source(self):
        app_id = _create_app("reupload-collision")
        before = self._seed_good_source(app_id)

        # src/A.cob and src\\A.cob resolve to the same path -> collision
        # is raised by the service's validator, after cleanup used to run.
        resp = _upload(
            app_id, [("src/A.cob", b"ONE"), ("src\\A.cob", b"TWO")]
        )

        assert resp.status_code == 400, resp.text
        assert client.get(f"/applications/{app_id}").json()[
            "cobol_source_path"
        ] == str(before)
        assert before.exists()
        assert _source_files(app_id) == ["GOOD.cob"]

    def test_successful_reupload_still_replaces_source(self):
        """Guard: a valid re-upload must still swap in the new tree."""
        app_id = _create_app("reupload-success")
        old = self._seed_good_source(app_id)

        resp = _upload(app_id, [("NEW.cob", b"       PROGRAM-ID. NEW.")])

        assert resp.status_code == 201, resp.text
        new = Path(resp.json()["cobol_source_path"])
        assert new != old, "a successful re-upload must use a fresh directory"
        assert not old.exists(), "the replaced source directory should be cleaned up"
        assert _source_files(app_id) == ["NEW.cob"]

    def test_java_candidate_reupload_preserves_previous(self):
        """BL-048 applies to the candidate endpoint too."""
        app_id = _create_app("reupload-candidate")
        good = client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("Main.java", io.BytesIO(b"class Main {}"), "text/plain"))],
        )
        assert good.status_code == 201, good.text
        before = good.json()["cobol_source_path"]
        assert before and Path(before).exists()

        bad = client.post(
            f"/applications/{app_id}/candidate",
            files=[("files", ("../evil.java", io.BytesIO(b"EVIL"), "text/plain"))],
        )

        assert bad.status_code == 400, bad.text
        assert client.get(f"/applications/{app_id}").json()[
            "java_candidate_path"
        ] == before
        assert Path(before).exists(), "previous candidate dir was deleted by a rejected re-upload"
