"""Roadmap unit 19: role-based access control on the control plane's bearer tokens."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import api.app as app_mod
from api import rbac
from api.app import app
from api.service import Service
from api.store import Store

VIEWER = "viewer-token-0123456789abcdef"
OPERATOR = "operator-token-0123456789abcdef"
APPROVER = "approver-token-0123456789abcdef"
ADMIN = "admin-shared-token-0123456789abcdef0123"
ROLE_TOKENS = json.dumps({VIEWER: "viewer", OPERATOR: "operator", APPROVER: "approver"})

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_store():
    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield


@pytest.fixture
def roles(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", ROLE_TOKENS)
    monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)
    monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestPolicy:
    @pytest.mark.parametrize("method,path,role", [
        ("GET", "/applications", "viewer"), ("HEAD", "/runs/r1", "viewer"),
        ("POST", "/applications", "operator"), ("POST", "/applications/a1/ingest", "operator"),
        ("POST", "/runs/r1/validate", "operator"), ("DELETE", "/applications/a1", "operator"),
        ("POST", "/runs/r1/approval", "approver"), ("POST", "/runs/r1/approval/", "approver"),
        ("GET", "/runs/r1/approval", "viewer"),
    ])
    def test_the_least_role_for_each_call(self, method, path, role):
        assert rbac.required_role(method, path) == role

    def test_roles_are_ordered(self):
        assert rbac.allows("approver", "POST", "/runs/r/approval")
        assert rbac.allows("operator", "POST", "/applications")
        assert not rbac.allows("operator", "POST", "/runs/r/approval")
        assert not rbac.allows("viewer", "POST", "/applications")
        assert rbac.allows("viewer", "GET", "/applications")
        assert not rbac.allows("nobody", "GET", "/applications")

    @pytest.mark.parametrize("raw", ["not json", "[]", "{}", '{"short": "viewer"}',
                                     json.dumps({VIEWER: "root"}), json.dumps({VIEWER: 3})])
    def test_invalid_configuration_is_refused(self, raw):
        with pytest.raises(rbac.RoleConfigError):
            rbac.parse_role_tokens(raw)

    def test_unset_means_no_roles(self):
        assert rbac.parse_role_tokens(None) == {} and rbac.parse_role_tokens("  ") == {}

    def test_the_admin_token_is_the_approver(self):
        assert rbac.role_for_token(ADMIN, {VIEWER: "viewer"}, ADMIN) == "approver"
        assert rbac.role_for_token("", {VIEWER: "viewer"}, ADMIN) is None
        assert rbac.role_for_token("wrong", {VIEWER: "viewer"}, None) is None


class TestEnforcement:
    def test_a_viewer_reads_but_cannot_start_work(self, roles):
        assert client.get("/applications", headers=_auth(VIEWER)).status_code == 200
        denied = client.post("/applications", json={ "target_runtime": "spring_boot","name": "x", "workload_id": "w"}, headers=_auth(VIEWER))
        assert denied.status_code == 403 and denied.json() == {"detail": "Forbidden for this role"}

    def test_an_operator_starts_work_but_cannot_approve(self, roles):
        created = client.post("/applications", json={ "target_runtime": "spring_boot","name": "x", "workload_id": "w"}, headers=_auth(OPERATOR))
        assert created.status_code == 201
        denied = client.post("/runs/run-1/approval", json={"state": "APPROVED"}, headers=_auth(OPERATOR))
        assert denied.status_code == 403

    def test_an_approver_passes_the_role_check_on_approval(self, roles):
        # a 404 for the unknown run proves the request got past authorization
        reached = client.post("/runs/run-ghost/approval", json={"state": "APPROVED"}, headers=_auth(APPROVER))
        assert reached.status_code in (404, 400, 422)

    def test_unknown_and_missing_tokens_are_401(self, roles):
        assert client.get("/applications").status_code == 401
        assert client.get("/applications", headers=_auth("not-a-token-0123456789")).status_code == 401

    def test_the_probes_and_preflight_need_no_token(self, roles):
        assert client.get("/health").status_code == 200
        assert client.options("/applications").status_code != 401

    def test_the_legacy_shared_token_is_the_administrator_in_role_mode(self, roles, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", ADMIN)
        assert client.post("/applications", json={ "target_runtime": "spring_boot","name": "y", "workload_id": "w"},
                           headers=_auth(ADMIN)).status_code == 201
        assert client.post("/runs/run-ghost/approval", json={"state": "APPROVED"},
                           headers=_auth(ADMIN)).status_code != 403

    def test_broken_role_configuration_grants_nothing(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", "{broken")
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", ADMIN)
        assert client.get("/applications", headers=_auth(ADMIN)).status_code == 401

    def test_startup_refuses_a_broken_role_configuration(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ROLE_TOKENS", '{"short": "viewer"}')
        with pytest.raises(RuntimeError, match="at least 16 characters"):
            app_mod.verify_production_auth_configuration()

    def test_without_role_tokens_the_behaviour_is_unchanged(self, monkeypatch):
        monkeypatch.delenv("CONTROL_PLANE_ROLE_TOKENS", raising=False)
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", ADMIN)
        assert client.get("/applications", headers=_auth(ADMIN)).status_code == 200
        assert client.get("/applications", headers=_auth(VIEWER)).status_code == 401
        assert client.post("/applications", json={ "target_runtime": "spring_boot","name": "z", "workload_id": "w"},
                           headers=_auth(ADMIN)).status_code == 201
