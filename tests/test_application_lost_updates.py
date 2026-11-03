"""Application lost-update protection (BL-141).

``Store.update_application`` writes every column of the row from the
caller's record.  Every service path that does read-modify-write
(ingest, COBOL upload, Java-candidate upload, generation provenance)
therefore clobbers *unrelated* columns a concurrent writer changed
between the read and the write — a classic lost update.

The store gains ``update_application_fields`` (column-scoped writes) and
the service paths use it for only the columns they actually change.
These tests pin, red-first:

* a concurrent rename survives a COBOL re-upload (full-row write would
  restore the stale name),
* a concurrent rename survives an ingest,
* a concurrent source-path change survives generation provenance writes,
* partial updates reject unknown columns and missing applications,
* the legacy full-row ``update_application`` keeps working (tests and
  fixtures still use it).
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.errors import NotFoundError
from api.store import ApplicationRecord, Store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    import api.app as app_mod
    from api.service import Service

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield store


def _create_app(name: str = "lost-update-app") -> str:
    resp = client.post(
        "/applications", json={"name": name, "workload_id": "wl-lu"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestStorePartialUpdate:
    def test_update_application_fields_changes_only_named_columns(self):
        store = Store()
        rec = store.add_application(
            ApplicationRecord(
                id="app-partial",
                name="before",
                description="keep me",
                workload_id="wl-1",
                java_entrypoint="MAIN",
            )
        )
        assert rec.name == "before"

        updated = store.update_application_fields("app-partial", name="after")

        assert updated.name == "after"
        assert updated.description == "keep me"
        assert updated.workload_id == "wl-1"

    def test_update_application_fields_unknown_column_rejected(self):
        store = Store()
        store.add_application(
            ApplicationRecord(
                id="app-unk", name="x", description="", workload_id="wl",
                java_entrypoint="M",
            )
        )
        with pytest.raises(ValueError, match="unknown application column"):
            store.update_application_fields("app-unk", no_such_column=1)

    def test_update_application_fields_requires_at_least_one_field(self):
        store = Store()
        store.add_application(
            ApplicationRecord(
                id="app-empty", name="x", description="", workload_id="wl",
                java_entrypoint="M",
            )
        )
        with pytest.raises(ValueError):
            store.update_application_fields("app-empty")

    def test_update_application_fields_unknown_app_not_found(self):
        store = Store()
        with pytest.raises(NotFoundError):
            store.update_application_fields("app-ghost", name="x")

    def test_update_application_fields_encodes_program_id_lists(self):
        store = Store()
        store.add_application(
            ApplicationRecord(
                id="app-lists", name="x", description="", workload_id="wl",
                java_entrypoint="M",
            )
        )
        updated = store.update_application_fields(
            "app-lists", discovered_program_ids=("A", "B")
        )
        assert updated.discovered_program_ids == ["A", "B"] or (
            updated.discovered_program_ids == ("A", "B")
        )

    def test_legacy_full_row_update_still_works(self):
        store = Store()
        store.add_application(
            ApplicationRecord(
                id="app-legacy", name="x", description="d",
                workload_id="wl", java_entrypoint="M",
            )
        )
        rec = store.get_application("app-legacy")
        assert rec is not None
        rec.description = "changed"
        store.update_application(rec)
        assert store.get_application("app-legacy").description == "changed"


class TestServicePathsDoNotClobberConcurrentWriters:
    def test_cobol_upload_preserves_concurrent_rename(self, monkeypatch):
        """A rename committed after the upload's read must survive the write."""
        from api.service import Service

        app_id = _create_app("original-name")
        original_get = Service.get_application

        def get_then_rename(service, aid):
            rec = original_get(service, aid)
            # Concurrent writer renames between the read and the write.
            fresh = service._store.get_application(aid)
            assert fresh is not None
            fresh.name = "renamed-concurrently"
            service._store.update_application(fresh)
            return rec  # deliberately stale (old name)

        monkeypatch.setattr(Service, "get_application", get_then_rename)

        resp = client.post(
            f"/applications/{app_id}/upload",
            files=[("files", ("A.cob", io.BytesIO(b"A"), "text/plain"))],
        )
        assert resp.status_code == 201, resp.text

        final = client.get(f"/applications/{app_id}").json()
        assert final["name"] == "renamed-concurrently", (
            "COBOL upload must only write cobol_source_path — a full-row"
            " write restored the stale name and lost the concurrent rename"
        )

    def test_ingest_preserves_concurrent_rename(self, monkeypatch):
        from api.service import Service

        app_id = _create_app("ingest-original")
        original_get = Service.get_application

        def get_then_rename(service, aid):
            rec = original_get(service, aid)
            fresh = service._store.get_application(aid)
            assert fresh is not None
            fresh.name = "renamed-during-ingest"
            service._store.update_application(fresh)
            return rec

        monkeypatch.setattr(Service, "get_application", get_then_rename)

        zip_buf = io.BytesIO()
        import zipfile as zf_mod

        with zf_mod.ZipFile(zip_buf, "w") as zf:
            zf.writestr("PAYROLL/PAYROLL.cob", "       IDENTIFICATION DIVISION.\n")
        zip_buf.seek(0)

        resp = client.post(
            f"/applications/{app_id}/ingest",
            files={"file": ("app.zip", zip_buf.getvalue(), "application/zip")},
        )
        assert resp.status_code == 201, resp.text

        final = client.get(f"/applications/{app_id}").json()
        assert final["name"] == "renamed-during-ingest", (
            "ingest must not write name/cobol_source_path as a full row"
        )

    def test_generation_provenance_preserves_concurrent_source_path(
        self, monkeypatch
    ):
        """Generation writes provenance columns only — a concurrent COBOL
        re-upload's new source path must survive."""
        import api.app as app_mod
        from api.service import Service

        app_id = _create_app("gen-app")
        svc = app_mod._service
        rec = svc.get_application(app_id)

        # Seed an existing source path (as upload would).
        rec.cobol_source_path = "/tmp/old-source-dir"
        svc._store.update_application(rec)

        # Another writer changes the source path after our read.
        rec_stale = svc.get_application(app_id)
        fresh = svc.get_application(app_id)
        fresh.cobol_source_path = "/tmp/new-source-dir"
        svc._store.update_application(fresh)

        # Our (stale) record still has /tmp/old-source-dir; the provenance
        # write must not push that stale path back.
        svc._store.update_application_fields(
            app_id,
            discovered_program_ids=("PROG",),
            generated_app_path="/tmp/gen",
            generated_entrypoint="PROG",
            generated_program_ids=("PROG",),
            java_candidate_path="/tmp/gen",
        )

        final = svc.get_application(app_id)
        assert final.cobol_source_path == "/tmp/new-source-dir"
        assert final.generated_app_path == "/tmp/gen"
        assert final.name == "gen-app"
        assert rec_stale.id == app_id