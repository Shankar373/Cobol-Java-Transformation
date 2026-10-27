"""P0 evidence-substitution protection (generated-bundle seal).

Pins ``api.artifact_seal`` and its enforcement points.  Before the seal,
``GET /runs/{id}/download`` packaged whatever currently sat under
``generated_app_path``: bytes substituted on disk AFTER the run
completed were served as if they were the verified artifact, and a
customer could APPROVE a bundle that no longer matched what was
validated.  This suite pins the fix:

* the seal (SHA-256 per file, POSIX-relative keys) is computed at
  generation time and persisted on the run record (DB column
  ``runs.generated_seal``, schema migration 6);
* download and APPROVED decisions fail closed (409) on changed bytes,
  added files, removed files, or a missing/malformed seal;
* REJECTED decisions keep working on a broken bundle;
* re-validation clears the seal with the rest of the attempt's evidence;
* ``update_run`` (stale-worker policy) never rewrites the seal;
* the seal round-trips through a file-backed store across restarts.

The trust boundary is the control-plane store itself: an attacker who
can rewrite the SQLite database can rewrite every persisted fact; this
protects the filesystem-substitution case.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.artifact_seal import (
    SEAL_ALGORITHM,
    compute_generated_seal,
    verify_generated_seal,
)
from api.errors import ConflictError, ServiceError
from api.models import RunStage
from api.store import RunRecord, Store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod
    from api.service import Service

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_run_with_bundle(
    files: list[tuple[str, bytes]],
) -> tuple[str, Path]:
    """Upload + stub-modernize + attach a generated bundle, like a real run.

    Returns (run_id, generated_dir).  The bundle is NOT sealed here —
    each test decides whether to seal, so unsealed-run behaviour is
    pinned too.
    """
    import api.app as app_mod
    from api.service import Service

    app_id = client.post(
        "/applications", json={"name": "sub-app", "workload_id": "wl-sub"}
    ).json()["id"]
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
    )
    assert upload.status_code == 201, upload.text

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(Service, "_modernize_background", lambda *a, **k: None)
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]

    svc = app_mod._service
    rec = svc.get_application(app_id)
    target = Path(rec.cobol_source_path or ".").parent / f"{rec.id}-generated"
    target.mkdir(parents=True, exist_ok=True)
    for rel, content in files:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    rec.generated_app_path = str(target)
    svc._store.update_application(rec)
    return run_id, target


def _seal(run_id: str, target: Path) -> None:
    import api.app as app_mod

    app_mod._service._store.set_generated_seal(
        run_id, compute_generated_seal(target)
    )


def _approve(run_id: str):
    return client.post(
        f"/runs/{run_id}/approval",
        json={"decision": "APPROVED", "approver": "qa"},
    )


def _reject(run_id: str):
    return client.post(
        f"/runs/{run_id}/approval",
        json={
            "decision": "REJECTED",
            "approver": "qa",
            "reason": "bundle no longer matches its sealed evidence",
        },
    )


# ---------------------------------------------------------------------------
# Unit contract of the seal itself
# ---------------------------------------------------------------------------


class TestSealUnitContract:
    def test_seal_json_shape(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Main.java").write_text("class Main {}", "utf-8")
        (tmp_path / "pom.xml").write_text("<project/>", "utf-8")

        seal = json.loads(compute_generated_seal(tmp_path))

        assert seal["algorithm"] == SEAL_ALGORITHM
        assert seal["files"] == {
            "pom.xml": hashlib.sha256(b"<project/>").hexdigest(),
            "src/Main.java": hashlib.sha256(b"class Main {}").hexdigest(),
        }
        assert seal["sealed_at"]

    def test_identical_bytes_produce_identical_file_map(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        for d in (a, b):
            d.mkdir()
            (d / "F.cob").write_bytes(b"same")
        seal_a = json.loads(compute_generated_seal(a))
        seal_b = json.loads(compute_generated_seal(b))
        assert seal_a["files"] == seal_b["files"]

    def test_missing_directory_cannot_be_sealed(self, tmp_path):
        with pytest.raises(ServiceError):
            compute_generated_seal(tmp_path / "nope")

    @pytest.mark.parametrize(
        "seal_json",
        [
            pytest.param(None, id="missing"),
            pytest.param("", id="empty"),
            pytest.param("{not json", id="malformed"),
            pytest.param(json.dumps({"algorithm": "md5", "files": {}}),
                         id="wrong-algorithm"),
            pytest.param(json.dumps({"algorithm": SEAL_ALGORITHM,
                                     "files": "nope"}), id="bad-files"),
        ],
    )
    def test_verify_fails_closed_on_bad_seal(self, tmp_path, seal_json):
        (tmp_path / "F.cob").write_bytes(b"x")

        with pytest.raises(ConflictError):
            verify_generated_seal(tmp_path, seal_json)

    def test_verify_accepts_an_untouched_bundle(self, tmp_path):
        (tmp_path / "F.cob").write_bytes(b"original")
        verify_generated_seal(tmp_path, compute_generated_seal(tmp_path))

    @pytest.mark.parametrize(
        "tamper",
        [
            pytest.param("change", id="changed-bytes"),
            pytest.param("add", id="added-file"),
            pytest.param("remove", id="removed-file"),
        ],
    )
    def test_verify_detects_every_difference_kind(self, tmp_path, tamper):
        (tmp_path / "F.cob").write_bytes(b"original")
        seal = compute_generated_seal(tmp_path)

        if tamper == "change":
            (tmp_path / "F.cob").write_bytes(b"substituted")
        elif tamper == "add":
            (tmp_path / "Extra.cob").write_bytes(b"added")
        else:
            (tmp_path / "F.cob").unlink()

        with pytest.raises(ConflictError, match="sealed evidence"):
            verify_generated_seal(tmp_path, seal)

    def test_empty_bundle_seal_does_not_admit_files(self, tmp_path):
        empty_seal = compute_generated_seal(tmp_path)
        (tmp_path / "F.cob").write_bytes(b"appeared")

        with pytest.raises(ConflictError):
            verify_generated_seal(tmp_path, empty_seal)


# ---------------------------------------------------------------------------
# Enforcement through the control plane
# ---------------------------------------------------------------------------


class TestDownloadRefusesSubstitutedBundle:
    def test_untouched_sealed_bundle_downloads(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)

        assert _approve(run_id).status_code == 200
        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert "Main.java" in zf.namelist()

    def test_changed_bytes_after_completion_are_refused(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)
        assert _approve(run_id).status_code == 200

        (target / "Main.java").write_bytes(b"class Main { /* evil */ }")

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 409, resp.text
        assert "sealed evidence" in resp.json()["detail"]

    def test_added_file_after_completion_is_refused(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)
        assert _approve(run_id).status_code == 200

        (target / "Injected.java").write_bytes(b"class Injected {}")

        assert client.get(f"/runs/{run_id}/download").status_code == 409

    def test_removed_file_after_completion_is_refused(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}"), ("pom.xml", b"<project/>")]
        )
        _seal(run_id, target)
        assert _approve(run_id).status_code == 200

        (target / "pom.xml").unlink()

        assert client.get(f"/runs/{run_id}/download").status_code == 409

    def test_unsealed_run_cannot_be_approved_or_exported(self):
        """A run completed before sealing existed fails closed (409).

        The bundle exists on disk but carries no seal — approving bytes
        the control plane cannot verify, or exporting them, must both be
        refused until the run is re-validated.
        """
        run_id, _target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )

        approve = _approve(run_id)
        assert approve.status_code == 409, approve.text
        assert "sealed evidence" in approve.json()["detail"]

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 409, resp.text


class TestApprovalRefusesSubstitutedBundle:
    def test_approving_a_substituted_bundle_is_refused(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)

        (target / "Main.java").write_bytes(b"class Main { /* evil */ }")

        resp = _approve(run_id)

        assert resp.status_code == 409, resp.text
        # And the download gate still holds (state never became APPROVED).
        assert client.get(f"/runs/{run_id}/download").status_code == 409

    def test_rejecting_a_broken_bundle_still_works(self):
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)

        (target / "Main.java").write_bytes(b"tampered")

        resp = _reject(run_id)

        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "REJECTED"

    def test_approving_a_run_without_a_generated_bundle_works(self):
        """Runs with no generated artifact (upload-only) stay approvable."""
        import api.app as app_mod
        from api.service import Service

        app_id = client.post(
            "/applications", json={"name": "no-bundle", "workload_id": "wl"}
        ).json()["id"]
        client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Service, "_modernize_background", lambda *a, **k: None)
            run_id = client.post(
                f"/applications/{app_id}/modernize"
            ).json()["run_id"]

        assert _approve(run_id).status_code == 200


# ---------------------------------------------------------------------------
# Store-level invariants (schema 6, stale-worker policy, reset)
# ---------------------------------------------------------------------------


class TestSealPersistence:
    def test_seal_round_trips_through_a_file_backed_store(self, tmp_path):
        db = tmp_path / "cp.db"
        store = Store(db)
        store.add_run(
            RunRecord(id="run-rt", application_id="app-rt", workload_id="wl")
        )
        store.set_generated_seal("run-rt", '{"algorithm":"sha256","files":{}}')

        restarted = Store(db)

        assert restarted.get_run("run-rt").generated_seal == (
            '{"algorithm":"sha256","files":{}}'
        )

    def test_set_seal_for_unknown_run_is_not_found(self):
        from api.errors import NotFoundError

        store = Store()
        with pytest.raises(NotFoundError):
            store.set_generated_seal("run-ghost", "{}")

    def test_update_run_never_clobbers_the_seal(self):
        """Stale-worker policy: update_run does not write generated_seal."""
        store = Store()
        run = store.add_run(
            RunRecord(id="run-stale", application_id="app-s", workload_id="wl")
        )
        store.set_generated_seal("run-stale", "SEAL-A")

        run.generated_seal = "STALE-WORKER-VALUE"
        run.stage = RunStage.COMPLETED
        store.update_run(run)

        assert store.get_run("run-stale").generated_seal == "SEAL-A"

    def test_revalidation_clears_the_seal_with_the_attempt(self):
        store = Store()
        run = store.add_run(
            RunRecord(id="run-rv", application_id="app-rv", workload_id="wl")
        )
        store.set_generated_seal("run-rv", "SEAL-OLD")
        run.stage = RunStage.COMPLETED
        store.update_run(run)

        reset = store.begin_revalidation("run-rv")

        assert reset.generated_seal is None
        assert store.get_run("run-rv").generated_seal is None


# ---------------------------------------------------------------------------
# Verify-then-package TOCTOU (BL-140): the zip must contain exactly the
# bytes that were verified against the seal — not a second, later read of
# the filesystem that an attacker could swap between the two.
# ---------------------------------------------------------------------------


class TestDownloadServesVerifiedBytes:
    def test_zip_contains_verified_bytes_even_if_disk_swaps_mid_request(
        self, monkeypatch
    ):
        """Simulate a filesystem swap between seal verification and packaging.

        Pre-fix the endpoint verified the seal and then ``ZipFile.write``
        re-read every file from disk — a substitution in that window was
        served as the verified artifact.  Post-fix the bundle is read once,
        verified, and packaged from those same bytes (``ZipFile.write`` is
        never used), so a swap after verification cannot reach the archive.
        """
        run_id, target = _create_run_with_bundle(
            [("Main.java", b"class Main {}")]
        )
        _seal(run_id, target)
        assert _approve(run_id).status_code == 200

        original_write = zipfile.ZipFile.write

        def swapping_write(self, filename, arcname=None, *args, **kwargs):
            # Mutate the file "after verification, before packaging".
            Path(filename).write_bytes(b"class Main { /* swapped */ }")
            return original_write(self, filename, arcname, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "write", swapping_write)

        resp = client.get(f"/runs/{run_id}/download")

        assert resp.status_code == 200, resp.text
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert zf.read("Main.java") == b"class Main {}"

    def test_read_verified_bundle_returns_exact_sealed_bytes(self, tmp_path):
        from api.artifact_seal import read_verified_bundle

        (tmp_path / "Main.java").write_bytes(b"class Main {}")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "Util.java").write_bytes(b"class Util {}")
        seal = compute_generated_seal(tmp_path)

        bundle = read_verified_bundle(tmp_path, seal)

        assert bundle == {
            "Main.java": b"class Main {}",
            "sub/Util.java": b"class Util {}",
        }

    def test_read_verified_bundle_refuses_tampered_bytes(self, tmp_path):
        from api.artifact_seal import read_verified_bundle

        (tmp_path / "Main.java").write_bytes(b"class Main {}")
        seal = compute_generated_seal(tmp_path)
        (tmp_path / "Main.java").write_bytes(b"class Evil {}")

        with pytest.raises(ConflictError):
            read_verified_bundle(tmp_path, seal)

    def test_read_verified_bundle_enforces_caps(self, tmp_path):
        from api.artifact_seal import read_verified_bundle
        from api.errors import PayloadTooLargeError

        (tmp_path / "a.bin").write_bytes(b"x" * 100)
        seal = compute_generated_seal(tmp_path)

        with pytest.raises(PayloadTooLargeError):
            read_verified_bundle(tmp_path, seal, max_files=0)
        with pytest.raises(PayloadTooLargeError):
            read_verified_bundle(tmp_path, seal, max_bytes=10)
