"""B4: an application can be created from a pinned Git commit; ZIP and Git applications yield the same blueprint shape."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import _svc
from api.service import Service
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.errors import IngestionError
from tests.discovery import test_readiness_gating as gating
from tests.discovery.test_readiness_gating import COMPLETE, ingest, modernize, new_app
from tests.discovery.helpers import write_tree

api = gating.api  # the application fixture is shared with the gating tests
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
URL = "https://example.invalid/org/payroll.git"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = write_tree(tmp_path / "repo", COMPLETE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root, _git(root, "rev-parse", "HEAD")


@pytest.fixture()
def local_git(repo, monkeypatch):
    """The service's Git seam points at a local repository (the API itself only accepts https URLs)."""
    root, _ = repo

    def discover_local(self, url: str, ref: str | None):
        from api.discovery_routes import get_service

        service = get_service()
        return discover(DiscoveryRequest("git", str(root), ref=ref), service.store, limits=service.limits)

    monkeypatch.setattr(Service, "_discover_git", discover_local)


def ingest_git(client: TestClient, app_id: str, url: str = URL, ref: str | None = "main"):
    return client.post(f"/applications/{app_id}/ingest/git", json={"url": url, "ref": ref})


def test_git_ingest_creates_a_pinned_ready_application(api: TestClient, repo, local_git) -> None:
    _, commit = repo
    app_id = new_app(api, "git-app")
    response = ingest_git(api, app_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["detected_name"] == "payroll" and body["source_file_count"] == len(COMPLETE)
    assert body["readiness"]["status"] == "READY" and set(body["top_level_entries"]) == {"src", "cpy", "jcl"}
    pin = _svc()._store.get_pin(_svc().get_application(app_id).cobol_source_path)
    assert pin["origin_kind"] == "git" and pin["origin_ref"] == commit and re.fullmatch(r"[0-9a-f]{40}", commit)
    assert pin["origin_checkpoint_id"].startswith("CP-") and pin["origin_checkpoint_id"] != pin["checkpoint_id"]
    assert api.get(f"/applications/{app_id}/blueprint").json()["blueprint_id"] == pin["blueprint_id"]
    assert modernize(api, app_id).status_code == 202


def test_git_and_zip_applications_have_the_same_blueprint_shape(api: TestClient, local_git) -> None:
    git_app, zip_app = new_app(api, "git-shape"), new_app(api, "zip-shape")
    assert ingest_git(api, git_app).status_code == 201 and ingest(api, zip_app, COMPLETE).status_code == 201
    from_git, from_zip = (api.get(f"/applications/{a}/blueprint").json() for a in (git_app, zip_app))
    assert from_git["estate"] == from_zip["estate"] and from_git["programs"] == from_zip["programs"]
    assert [a["id"] for a in from_git["applications"]] == [a["id"] for a in from_zip["applications"]]
    assert from_git["identity"]["source_digest"] == from_zip["identity"]["source_digest"]


def test_the_materialized_git_workspace_still_fails_closed_on_edit(api: TestClient, local_git) -> None:
    app_id = new_app(api, "git-edit")
    assert ingest_git(api, app_id).status_code == 201
    (Path(_svc().get_application(app_id).cobol_source_path) / "src/SUB.cbl").write_text("x\n", encoding="utf-8")
    assert modernize(api, app_id).status_code == 409


def test_only_https_urls_are_accepted(api: TestClient) -> None:
    app_id = new_app(api, "git-scheme")
    for url in ("http://example.invalid/r.git", "file:///etc", "ssh://git@example.invalid/r.git", "/local/path"):
        assert ingest_git(api, app_id, url).status_code in (400, 422), url


def test_a_refused_git_source_is_a_400_and_leaves_the_previous_source(api: TestClient, monkeypatch) -> None:
    app_id = new_app(api, "git-refused")
    ingest(api, app_id, COMPLETE)
    before = _svc().get_application(app_id).cobol_source_path

    def refuse(self, url, ref):
        raise IngestionError("submodules are not supported", code="SUBMODULE_REFUSED")

    monkeypatch.setattr(Service, "_discover_git", refuse)
    response = ingest_git(api, app_id)
    assert response.status_code == 400 and "submodules" in response.json()["detail"]
    assert _svc().get_application(app_id).cobol_source_path == before
