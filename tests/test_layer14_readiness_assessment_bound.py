"""Layer 14 (control plane): bounded readiness assessments (L14-P2) that cannot destroy a source (L14-P3).

D8 (`docs/discovery/LAYER_AUDIT.md`): every *fresh* readiness assessment is a full discovery
pass, and ``readiness_for`` started them with no queue/concurrency bound - ``?refresh=true``
or a changed tree could start an unbounded number of them (ingest, modernize, revalidate and
the readiness endpoints all funnel through the same call).

L14-P3 (found by this audit): ingest assessed readiness *after* pointing the application
record at the new workspace and deleting the previous one, so an assessment failure deleted
the very directory the record then named - the application's source was destroyed.  P2 makes
that failure reachable in production (429), so the ordering must be fixed with it.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import _svc, app
from api.discovery_routes import reset_service_for_tests
from api.errors import BusyError
from api.service import Service
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.model import rmtree_force
from enterprise.discovery.runs import DiscoveryRunService
from tests.discovery.test_compilers_applications import FakeCobc
from tests.discovery.test_readiness_gating import COMPLETE, FAKE, ingest, new_app


@pytest.fixture()
def api(tmp_path: Path, monkeypatch):
    for name in ("CONTROL_PLANE_API_TOKEN", "CONTROL_PLANE_ROLE_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCOVERY_COMPILER_BACKEND", "none")
    monkeypatch.setattr(ToolchainConfig, "from_environment", classmethod(lambda cls: FAKE))
    svc = DiscoveryRunService(tmp_path / "discovery")
    reset_service_for_tests(svc)
    yield TestClient(app)
    svc.shutdown()
    reset_service_for_tests(None)
    rmtree_force(tmp_path / "discovery")


def _ready_record(tag: str) -> dict:
    """A READY-shaped readiness record, as ``assess_workspace`` would return it."""
    return {
        "allowed": True, "applications": [], "blocking_references": [], "blockers": [],
        "checkpoint_id": f"CP-{tag}", "compile_errors": [], "discovery_run_id": f"run-{tag}",
        "gate_status": "COMPLETE", "source_digest": f"digest-{tag}", "status": "READY",
        "toolchain": {"backend": "none", "version": ""}, "unsupported": [], "unsupported_total": 0,
        "unverified": [], "unverified_total": 0,
    }


class _AssessmentHold:
    """Holds one assessment permit: the first ``assess_workspace`` call blocks until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def assess(self, workspace: Path, label: str) -> dict:
        self.calls.append(str(workspace))
        if len(self.calls) == 1:
            self.started.set()
            assert self.release.wait(30), "the held assessment was never released"
        return _ready_record(f"held-{len(self.calls)}")

    def __enter__(self):
        self._patcher = patch("api.readiness.assess_workspace", side_effect=self.assess)
        self._patcher.start()
        return self

    def __exit__(self, *exc_info):
        self._patcher.stop()
        return False


def _hold_one_permit(hold: _AssessmentHold, tree: Path, monkeypatch) -> threading.Thread:
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "H.cob").write_text("       IDENTIFICATION DIVISION.\n", encoding="utf-8")
    monkeypatch.setenv("CONTROL_PLANE_MAX_READINESS_ASSESSMENTS", "1")
    holder = threading.Thread(
        target=lambda: _svc().readiness_for(str(tree), "hold"), daemon=True, name="l14-assessment-hold"
    )
    holder.start()
    assert hold.started.wait(30), "the first assessment did not start"
    return holder


# --- L14-P2: the bound ----------------------------------------------------------------------------


def test_a_fresh_assessment_is_refused_once_the_limit_is_reached(tmp_path: Path, monkeypatch) -> None:
    tree_a = tmp_path / "tree-a"
    tree_b = tmp_path / "tree-b"
    for tree in (tree_a, tree_b):
        tree.mkdir()
        (tree / "A.cob").write_text("       IDENTIFICATION DIVISION.\n", encoding="utf-8")

    hold = _AssessmentHold()
    with hold:
        holder = _hold_one_permit(hold, tree_a, monkeypatch)
        with pytest.raises(BusyError):
            _svc().readiness_for(str(tree_b), "b")
        assert hold.calls == [str(tree_a)], "the refused call must never reach discovery"
        hold.release.set()
        holder.join(30)
        assert not holder.is_alive()

    # The permit is released with the assessment: the next fresh one runs.
    with patch("api.readiness.assess_workspace", side_effect=lambda w, label: _ready_record("free")) as assessed:
        record = _svc().readiness_for(str(tree_b), "b")
    assert record["allowed"] is True
    assessed.assert_called_once()


def test_a_stored_readiness_record_never_consumes_an_assessment_permit(api: TestClient, tmp_path: Path, monkeypatch) -> None:
    """The bound applies to fresh assessments only; a cached read is free (the common polling path)."""
    app_id = new_app(api, "l14-permit-cached")
    assert ingest(api, app_id, COMPLETE).status_code == 201

    hold = _AssessmentHold()
    with hold:
        holder = _hold_one_permit(hold, tmp_path / "unrelated", monkeypatch)
        body = api.get(f"/applications/{app_id}/readiness")
        assert body.status_code == 200 and body.json()["status"] == "READY"
        hold.release.set()
        holder.join(30)
        assert not holder.is_alive()


def test_the_readiness_refresh_endpoint_returns_429_while_the_limit_is_reached(api: TestClient, tmp_path: Path, monkeypatch) -> None:
    app_id = new_app(api, "l14-permit-refresh")
    assert ingest(api, app_id, COMPLETE).status_code == 201

    hold = _AssessmentHold()
    with hold:
        holder = _hold_one_permit(hold, tmp_path / "unrelated", monkeypatch)
        refused = api.post(f"/applications/{app_id}/readiness/refresh")
        assert refused.status_code == 429
        assert "readiness assessment limit" in refused.json()["detail"]
        hold.release.set()
        holder.join(30)
        assert not holder.is_alive()

    # The permit is released: the same refresh succeeds again.
    again = api.post(f"/applications/{app_id}/readiness/refresh")
    assert again.status_code == 200 and again.json()["status"] == "READY"


# --- L14-P3: a failed assessment never destroys the source ---------------------------------------


def test_a_failed_readiness_assessment_during_ingest_leaves_the_previous_source_intact(api: TestClient) -> None:
    app_id = new_app(api, "l14-ingest-fail")
    assert ingest(api, app_id, COMPLETE).status_code == 201
    svc = _svc()
    first_source = Path(svc.get_application(app_id).cobol_source_path)
    assert first_source.is_dir()

    # The assessment cannot be served (production trigger: the P2 429).
    with patch.object(
        Service, "readiness_for", side_effect=BusyError("Concurrent readiness assessment limit reached (1)")
    ):
        second = ingest(api, app_id, {**COMPLETE, "src/EXTRA.cbl": "       IDENTIFICATION DIVISION.\n"})
    assert second.status_code == 429

    record = svc.get_application(app_id)
    assert record.cobol_source_path == str(first_source), "the record was pointed at a workspace that no longer exists"
    assert first_source.is_dir(), "the application's source was destroyed by the failed assessment"


def test_ingest_is_refused_while_the_assessment_limit_is_reached_and_keeps_its_source(api: TestClient, tmp_path: Path, monkeypatch) -> None:
    """End to end: the production trigger (P2) reaches ingest and the source survives it (P3)."""
    app_id = new_app(api, "l14-ingest-bound")
    assert ingest(api, app_id, COMPLETE).status_code == 201
    svc = _svc()
    source = Path(svc.get_application(app_id).cobol_source_path)

    hold = _AssessmentHold()
    with hold:
        holder = _hold_one_permit(hold, tmp_path / "unrelated", monkeypatch)
        refused = ingest(api, app_id, {**COMPLETE, "src/EXTRA.cbl": "       IDENTIFICATION DIVISION.\n"})
        assert refused.status_code == 429
        assert "readiness assessment limit" in refused.json()["detail"]
        hold.release.set()
        holder.join(30)
        assert not holder.is_alive()

    record = svc.get_application(app_id)
    assert record.cobol_source_path == str(source) and source.is_dir()

    # After the release the same ingest succeeds: no permit leaked.
    accepted = ingest(api, app_id, {**COMPLETE, "src/EXTRA2.cbl": "       IDENTIFICATION DIVISION.\n"})
    assert accepted.status_code == 201
