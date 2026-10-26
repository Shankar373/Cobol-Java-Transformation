"""P0 production authentication fail-closed (CONTROL_PLANE_ENV=production).

Pins the approved hardening plan item 2:

* ``CONTROL_PLANE_ENV=production`` without ``CONTROL_PLANE_API_TOKEN`` fails
  closed — the configuration gate raises at startup and the middleware
  answers 401 for every non-``/health`` request even if the process somehow
  started;
* development mode is preserved exactly (auth stays opt-in when the
  environment is unset/development/test);
* unknown environment values fail closed instead of behaving like dev;
* secrets never appear in logs or error responses;
* CORS stays deny-by-default without ``CONTROL_PLANE_ALLOWED_ORIGINS``;
* the deployment artifacts (compose, env example, start script) actually
  wire the switch, so a production stack cannot drift back to auth-off.

None of these tests weaken the existing bearer-token suite
(`tests/test_api_security.py`); they add the missing environment axis.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import (
    app,
    deployment_environment,
    production_environment_active,
    verify_production_auth_configuration,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset module-level singletons for test isolation."""
    import api.app as app_mod
    from api.service import Service
    from api.store import Store

    store = Store()
    app_mod._store = store
    app_mod._service = Service(store)
    yield store


# ---------------------------------------------------------------------------
# Configuration gate (startup check)
# ---------------------------------------------------------------------------


class TestProductionConfigurationGate:
    def test_production_without_token_refuses_to_start(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="CONTROL_PLANE_API_TOKEN"):
            verify_production_auth_configuration()

    def test_production_with_token_accepted(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        verify_production_auth_configuration()  # must not raise

    @pytest.mark.parametrize("value", ["", "development", "dev", "test"])
    def test_non_production_environments_keep_dev_default(
        self, monkeypatch, value
    ):
        if value:
            monkeypatch.setenv("CONTROL_PLANE_ENV", value)
        else:
            monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)

        verify_production_auth_configuration()  # dev parity: no raise

    @pytest.mark.parametrize("value", ["prod", "staging", "PRODUCTION-1", "yes"])
    def test_unknown_environment_values_fail_closed(self, monkeypatch, value):
        """A typo'd environment must never silently behave like development."""
        monkeypatch.setenv("CONTROL_PLANE_ENV", value)
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="Unknown CONTROL_PLANE_ENV"):
            verify_production_auth_configuration()

    def test_environment_value_is_normalised(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "  Production ")
        assert deployment_environment() == "production"
        assert production_environment_active() is True

    def test_startup_gate_is_invoked_at_import_time(self):
        """The module-level call must exist — a mere definition protects nothing."""
        source = (REPO_ROOT / "api" / "app.py").read_text(encoding="utf-8")
        # One definition + at least one unconditional module-level call.
        assert source.count("verify_production_auth_configuration") >= 2


# ---------------------------------------------------------------------------
# Middleware fail-closed behaviour under production environment
# ---------------------------------------------------------------------------


class TestProductionMiddlewareFailClosed:
    def test_production_without_token_answers_401_on_every_route(
        self, monkeypatch
    ):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)

        for path in ("/applications", "/runs/any", "/health"):
            resp = client.get(path)
            if path == "/health":
                # Probes stay reachable (liveness), everything else fails closed.
                assert resp.status_code == 200, resp.text
            else:
                assert resp.status_code == 401, f"{path}: {resp.status_code}"
                assert resp.headers.get("WWW-Authenticate") == "Bearer"

    def test_production_with_token_still_enforces_bearer_auth(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        assert client.get("/applications").status_code == 401
        ok = client.get(
            "/applications", headers={"Authorization": "Bearer sekret-token"}
        )
        assert ok.status_code == 200

    def test_development_mode_is_unchanged(self, monkeypatch):
        """No env, no token -> served (the pinned dev default)."""
        monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
        monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)

        assert client.get("/health").status_code == 200
        assert client.get("/applications").status_code == 200


# ---------------------------------------------------------------------------
# Secrets never leak
# ---------------------------------------------------------------------------


class TestSecretsNeverLeak:
    def test_authorized_request_never_logs_the_token(self, monkeypatch, caplog):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "super-secret-token-value")

        with caplog.at_level(logging.DEBUG):
            resp = client.get(
                "/applications",
                headers={"Authorization": "Bearer super-secret-token-value"},
            )
        assert resp.status_code == 200
        assert "super-secret-token-value" not in caplog.text, (
            "the bearer token must never appear in application logs"
        )

    def test_unauthorized_response_never_echoes_the_presented_token(
        self, monkeypatch
    ):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "sekret-token")

        resp = client.get(
            "/applications", headers={"Authorization": "Bearer wrong-marker-xyzzy"}
        )

        assert resp.status_code == 401
        assert "wrong-marker-xyzzy" not in resp.text
        assert "sekret-token" not in resp.text


# ---------------------------------------------------------------------------
# CORS deny-by-default
# ---------------------------------------------------------------------------


class TestCorsDenyByDefault:
    def test_cross_origin_request_gets_no_cors_grant(self, monkeypatch):
        monkeypatch.delenv("CONTROL_PLANE_ALLOWED_ORIGINS", raising=False)

        resp = client.get(
            "/health", headers={"Origin": "https://evil.example.com"}
        )

        assert resp.status_code == 200
        assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}

    def test_preflight_without_configuration_is_not_granted(self, monkeypatch):
        monkeypatch.delenv("CONTROL_PLANE_ALLOWED_ORIGINS", raising=False)

        resp = client.options(
            "/applications",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


# ---------------------------------------------------------------------------
# Deployment wiring (the switch must actually be on in production artifacts)
# ---------------------------------------------------------------------------


class TestProductionDeploymentWiring:
    def test_compose_pins_production_environment(self):
        text = (REPO_ROOT / "docker-compose.production.yml").read_text(
            encoding="utf-8"
        )
        assert "CONTROL_PLANE_ENV: production" in text

    def test_env_example_documents_the_switch(self):
        text = (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8")
        assert "CONTROL_PLANE_ENV=production" in text

    def test_start_script_exports_the_switch(self):
        text = (REPO_ROOT / "scripts" / "deploy" / "start-production.sh").read_text(
            encoding="utf-8"
        )
        assert 'CONTROL_PLANE_ENV="${CONTROL_PLANE_ENV:-production}"' in text
