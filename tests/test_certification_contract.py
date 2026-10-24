"""Certification contract tests (Phase B).

The certification contract is the artifact set a run is certified
against. The control plane must resolve it explicitly for every
(Re)validation and surface which contract was used:

  * declared fixtures resolve to their declared artifacts;
  * unknown workloads fall back to the explicit default contract;
  * declared workloads that need staged inputs fail closed — never a
    silent degradation to the default contract;
  * invalid workload ids are rejected before any filesystem access;
  * the resolved contract reaches the engine pipeline configuration,
    is recorded on the run, and is reported by the verdict endpoint;
  * a contract that cannot be resolved fails the REQUEST (no run).
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.errors import ServiceError
from api.models import RunStage
from api.service import Service
from api.store import RunRecord, Store
from api.workload_contract import (
    DEFAULT_CONTRACT_ID,
    load_declared_workload,
    resolve_certification_contract,
)
from tests.common import make_stub_verdict

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


def _create_app(name: str, workload_id: str) -> str:
    resp = client.post(
        "/applications", json={"name": name, "workload_id": workload_id}
    )
    assert resp.status_code == 201, resp.text
    app_id = resp.json()["id"]
    upload = client.post(
        f"/applications/{app_id}/upload",
        files=[("files", ("A.cob", io.BytesIO(b"       ID DIVISION.\n"), "text/plain"))],
    )
    assert upload.status_code == 201, upload.text
    return app_id


# ---------------------------------------------------------------------------
# Contract resolution (unit)
# ---------------------------------------------------------------------------


class TestContractResolution:
    def test_unknown_workload_falls_back_to_explicit_default(self):
        contract = resolve_certification_contract(
            "wl-not-a-fixture", description="test"
        )

        assert contract.contract_id == DEFAULT_CONTRACT_ID
        assert contract.contract_source == "default"
        assert contract.artifact_types == ("STDOUT", "EXIT_STATUS")
        assert contract.workload.workload_id == "wl-not-a-fixture"
        assert [a.artifact_type for a in contract.workload.artifacts] == [
            "STDOUT",
            "EXIT_STATUS",
        ]

    def test_undeclared_workload_returns_none_from_loader(self):
        assert load_declared_workload("wl-not-a-fixture") is None

    def test_declared_fixture_resolves_by_exact_id(self):
        contract = resolve_certification_contract("workload-file-write-read")

        assert contract.contract_source == "declared"
        assert contract.contract_id == "declared:workload-file-write-read"
        assert contract.artifact_types == (
            "STDOUT",
            "STDERR",
            "EXIT_STATUS",
            "FIXED_RECORD",
        )
        assert contract.workload.workload_id == "file-write-read"

    def test_declared_fixture_resolves_by_plain_name(self):
        contract = resolve_certification_contract("file-write-read")

        assert contract.contract_source == "declared"
        assert contract.contract_id == "declared:workload-file-write-read"
        assert "FIXED_RECORD" in contract.artifact_types

    def test_declared_workload_with_inputs_fails_closed(self):
        for workload_id in ("workload-claims", "claims"):
            with pytest.raises(ServiceError) as exc:
                resolve_certification_contract(workload_id)
            assert "input file(s)" in str(exc.value)

    @pytest.mark.parametrize(
        "workload_id",
        ["../secrets", "..", "a/b", "a\\b", "workload-x\n", "", " workload"],
    )
    def test_invalid_workload_id_rejected_before_filesystem_access(
        self, workload_id
    ):
        with pytest.raises(ServiceError) as exc:
            load_declared_workload(workload_id)
        assert "not allowed in a fixture reference" in str(exc.value)

    def test_fixture_registry_is_repository_controlled(self):
        # The loader only ever reads fixtures/<id>/workload.py inside the
        # repository — never a path built from unvalidated input.
        from api.workload_contract import FIXTURES_ROOT

        repo_root = Path(__file__).resolve().parent.parent
        assert FIXTURES_ROOT == repo_root / "fixtures"
        assert (FIXTURES_ROOT / "workload-file-write-read" / "workload.py").is_file()


# ---------------------------------------------------------------------------
# Contract reaches the engine configuration (service level)
# ---------------------------------------------------------------------------


class _CapturingPipeline:
    """Fake validation pipeline that records the config it was given."""

    captured: dict = {}

    def __init__(self, config, candidate_adapter=None):
        _CapturingPipeline.captured["config"] = config
        _CapturingPipeline.captured["adapter"] = candidate_adapter

    def run(self, progress=None):
        for phase in (
            "EXECUTING_ORACLE",
            "BUILDING",
            "EXECUTING_GENERATED",
            "COMPARING",
            "VALIDATING_EVIDENCE",
        ):
            if progress is not None:
                progress(phase)
        return SimpleNamespace(evidence_manifest=None, verdict=None)


def _run_modernize_with_fake_engine(app_id: str) -> str:
    """Run modernize end-to-end with generation/validation stubbed.

    The certification-contract resolution inside ``_run_validation`` is
    REAL; only the heavy engine work is replaced.
    """
    _CapturingPipeline.captured = {}
    candidate_dir = Path(__file__).resolve().parent  # any existing dir

    with patch.object(
        Service,
        "_generate_application",
        lambda self, app, run: (candidate_dir, "Main"),
    ), patch(
        "api.service.VerticalSlicePipeline", _CapturingPipeline
    ), patch(
        "engine.candidate.docker_spring_boot_adapter."
        "DockerSpringBootCandidateAdapter",
        return_value=MagicMock(),
    ):
        run_id = client.post(f"/applications/{app_id}/modernize").json()["run_id"]
        deadline = time.monotonic() + 30
        stage = ""
        while stage not in ("COMPLETED", "FAILED"):
            body = client.get(f"/runs/{run_id}").json()
            stage = body["stage"]
            if stage == "FAILED":
                raise AssertionError(f"run failed: {body['error']}")
            assert time.monotonic() < deadline, f"run stuck in {stage!r}"
            time.sleep(0.05)
    return run_id


class TestContractReachesEngine:
    def test_default_contract_drives_pipeline_config(self, _reset_store):
        store = _reset_store
        app_id = _create_app("default-contract", "wl-engine-default")

        run_id = _run_modernize_with_fake_engine(app_id)

        config = _CapturingPipeline.captured["config"]
        assert config.workload.workload_id == "wl-engine-default"
        assert [a.artifact_type for a in config.workload.artifacts] == [
            "STDOUT",
            "EXIT_STATUS",
        ]
        run = store.get_run(run_id)
        assert run.stage == RunStage.COMPLETED
        assert run.certification_contract == DEFAULT_CONTRACT_ID

    def test_declared_contract_drives_pipeline_config(self, _reset_store):
        store = _reset_store
        app_id = _create_app("declared-contract", "file-write-read")

        run_id = _run_modernize_with_fake_engine(app_id)

        config = _CapturingPipeline.captured["config"]
        assert [a.artifact_type for a in config.workload.artifacts] == [
            "STDOUT",
            "STDERR",
            "EXIT_STATUS",
            "FIXED_RECORD",
        ]
        # The declared workload's comparator bindings reach the engine.
        fixed = next(
            a for a in config.workload.artifacts if a.artifact_type == "FIXED_RECORD"
        )
        assert fixed.comparator_id == "fixed-record-exact"
        run = store.get_run(run_id)
        assert run.certification_contract == "declared:workload-file-write-read"

    def test_contract_with_inputs_fails_before_run_creation(self, _reset_store):
        store = _reset_store
        app_id = _create_app("claims-workload", "workload-claims")

        resp = client.post(f"/applications/{app_id}/modernize")

        assert resp.status_code == 400
        assert "input file(s)" in resp.json()["detail"]
        # Fail-fast: no run was created for the rejected certification.
        assert store.list_runs_for_application(app_id) == []
        assert client.get(f"/applications/{app_id}/runs").json() == []


# ---------------------------------------------------------------------------
# Contract is reported by the API
# ---------------------------------------------------------------------------


class TestVerdictReportsContract:
    def _completed_run(
        self, name: str, workload_id: str, contract_id: str | None
    ) -> str:
        resp = client.post(
            "/applications", json={"name": name, "workload_id": workload_id}
        )
        app_id = resp.json()["id"]
        run = RunRecord(
            id=f"run-{name}", application_id=app_id, workload_id=workload_id
        )
        import api.app as app_mod

        store = app_mod._store
        store.add_run(run)
        record = store.get_run(run.id)
        record.stage = RunStage.COMPLETED
        record.completed_at = "2024-01-01T00:00:00+00:00"
        record.certification_contract = contract_id
        record.verdict = make_stub_verdict(run.id, workload_id)
        store.update_run(record)
        return run.id

    def test_declared_contract_surfaces_on_verdict(self):
        run_id = self._completed_run(
            "verdict-declared", "wl-verdict", "declared:workload-file-write-read"
        )

        body = client.get(f"/runs/{run_id}/verdict").json()

        assert body["certification_contract"] == "declared:workload-file-write-read"
        assert body["contract_source"] == "declared"

    def test_default_contract_surfaces_on_verdict(self):
        run_id = self._completed_run(
            "verdict-default", "wl-verdict-default", DEFAULT_CONTRACT_ID
        )

        body = client.get(f"/runs/{run_id}/verdict").json()

        assert body["certification_contract"] == DEFAULT_CONTRACT_ID
        assert body["contract_source"] == "default"

    def test_missing_contract_reports_null(self):
        run_id = self._completed_run("verdict-none", "wl-verdict-none", None)

        body = client.get(f"/runs/{run_id}/verdict").json()

        assert body["certification_contract"] is None
        assert body["contract_source"] is None
