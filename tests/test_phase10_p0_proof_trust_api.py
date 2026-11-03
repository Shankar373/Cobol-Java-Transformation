"""Phase 10 P0-b/P0-c: the integrated-proof certification surface must fail closed.

Covers, at the service/API layer:

* P0-b  a persisted proof may only be served while it is bound to the run's
        current ``validation_generation`` and a consistent evidence<->verdict
        pair.  After ``begin_revalidation`` (which clears evidence + verdict
        and bumps the generation but keeps ``report_blob``), the previous
        attempt's VERIFIED claims must not be served while ``GET /verdict``
        answers 404 for the same run.
* P0-b  ``_persist_integrated_proof`` stamps the generation into the payload
        (the durable form of the binding; backlog item F-7 is discharged by
        this fix, not double-fixed later).
* P0-c  ``_proof_payload`` must not report vacuous
        ``required_dependencies_proven`` / central ``VERIFIED`` for an empty
        dependency ledger.

Red-first evidence (unmodified code): the stale-proof, pair-check,
generation-stamp and empty-ledger tests below all fail.

fastapi-dependent: deliberately NOT wired into the dependency-free
capability-truth gate (BL-063/BL-080 precedent — API tests stay out of it);
it runs in the backend job with the full requirements stack.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.errors import NotFoundError, PersistenceCorruptionError
from api.models import RunStage
from api.service import Service
from api.store import Store
from engine.modernization.integrated_proof import RuntimeLaneEvidence
from tests.common import make_stub_verdict
from tests.integration.test_integrated_proof_api import (
    _await_terminal,
    _fresh_run_record,
    _mock_generate,
    _mock_validation,
    _seed_proof_run,
    _stored_report,
    client,
)

# Prior-attempt proof claiming full certification (probe P0-b shape).
STALE_PROOF = {
    "workload_id": "wl-proof",
    "application_id": "proof-test",
    "central_status": "VERIFIED",
    "blocking_reasons": [],
    "reasons_for_not_verified": [],
    "generation_success": True,
    "overall_capability": "SUPPORTED",
    "jcl_status": "NOT_PRESENT",
    "runtime": {
        "verdict_state": "VERIFIED",
        "executed_check_count": 4,
        "evidence_complete": True,
        "evidence_integrity_valid": True,
        "oracle_exit_code": 0,
        "candidate_exit_code": 0,
        "artifact_results": [],
    },
    "dependency_ledger": [
        {"dependency_id": "PROGRAM:HELLO", "kind": "PROGRAM", "visible": True,
         "capability_level": "SUPPORTED", "proof_state": "PROVEN",
         "required": True, "reason": ""},
    ],
    "required_dependencies": [
        {"dependency_id": "PROGRAM:HELLO", "kind": "PROGRAM", "visible": True,
         "capability_level": "SUPPORTED", "proof_state": "PROVEN",
         "required": True, "reason": ""},
    ],
    "runtime_verdict_is_verified": True,
    "proven_dependencies": [],
    "unproven_dependencies": [],
    "blocked_dependencies": [],
    "unsupported_dependencies": [],
    "evidence_complete": True,
    "evidence_integrity_valid": True,
    "required_dependencies_proven": True,
    "overall_verification": "VERIFIED",
}

PERFECT_RUNTIME = RuntimeLaneEvidence(
    verdict_state="VERIFIED",
    executed_check_count=4,
    evidence_complete=True,
    evidence_integrity_valid=True,
    oracle_exit_code=0,
    candidate_exit_code=0,
)


@pytest.fixture
def fresh_service():
    """Fresh Service with an isolated in-memory store (app globals rewired)."""
    import api.app as app_mod
    import api.service as svc_mod

    store = Store()
    svc = Service(store)
    app_mod._store = store
    app_mod._service = svc
    svc_mod._store = store
    svc_mod._service = svc
    return svc


def _seed_run_with_report(svc, report: dict, *, terminal: bool = True) -> tuple:
    """Create app + run whose modernization_report is ``report``."""
    app_rec = svc.create_application(
        name="proof-p0", description="", workload_id="wl-proof",
        java_entrypoint="Main",
    )
    run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
    if terminal:
        run.stage = RunStage.COMPLETED
    run.modernization_report = report
    svc._store.update_run(run)
    return app_rec, run


def _assert_not_certifying(proof: dict) -> None:
    """A served proof may never claim certification during these scenarios."""
    assert proof["central_status"] != "VERIFIED", (
        "stale proof served with central VERIFIED"
    )
    assert proof["runtime"]["verdict_state"] != "VERIFIED", (
        "stale proof served with runtime VERIFIED"
    )
    assert proof["runtime_verdict_is_verified"] is False
    assert proof["required_dependencies_proven"] is False
    assert proof["overall_verification"] != "VERIFIED"


def _get_proof_or_none(svc, run_id: str) -> dict | None:
    """get_integrated_proof, accepting a fail-closed 404 as 'not served'."""
    try:
        return svc.get_integrated_proof(run_id)
    except NotFoundError:
        return None


class TestStaleProofFailsClosed:
    """P0-b: the proof surface must not outlive its validation attempt."""

    def test_unstamped_proof_not_served_after_revalidation(self, fresh_service):
        svc = fresh_service
        report = dict(_stored_report("app-proof"))
        report["integrated_proof"] = dict(STALE_PROOF)
        _app, run = _seed_run_with_report(svc, report)

        # Generation 0 / legacy unstamped proof: served as the current proof.
        first = svc.get_integrated_proof(run.id)
        assert first["proof"]["central_status"] == "VERIFIED"

        # Reset for a new attempt: evidence + verdict cleared, generation
        # bumped, report_blob (and its embedded proof) intentionally kept.
        svc._store.begin_revalidation(run.id, certification_contract=None)
        refreshed = svc.get_run(run.id)
        assert refreshed.validation_generation == 1
        assert refreshed.verdict is None
        assert refreshed.evidence_manifest is None

        out = _get_proof_or_none(svc, run.id)
        if out is None:
            return  # fail-closed 404 is acceptable
        _assert_not_certifying(out["proof"])

    def test_stamped_proof_not_served_after_revalidation(self, fresh_service):
        svc = fresh_service
        report = dict(_stored_report("app-proof"))
        stamped = dict(STALE_PROOF)
        stamped["validation_generation"] = 0
        report["integrated_proof"] = stamped
        _app, run = _seed_run_with_report(svc, report)

        first = svc.get_integrated_proof(run.id)
        assert first["proof"]["central_status"] == "VERIFIED"

        svc._store.begin_revalidation(run.id, certification_contract=None)
        out = _get_proof_or_none(svc, run.id)
        if out is None:
            return
        _assert_not_certifying(out["proof"])

    def test_broken_evidence_verdict_pair_blocks_proof(self, fresh_service):
        """The pair check runs before any proof is served (P0-b / F-3)."""
        from tests.adversarial.conftest import make_manifest

        svc = fresh_service
        report = dict(_stored_report("app-proof"))
        report["integrated_proof"] = dict(STALE_PROOF)
        _app, run = _seed_run_with_report(svc, report)

        # Present-but-inconsistent pair: verdict's evidence hash does not
        # hash-match the stored manifest (same shape as the store's own
        # cross-check pins in tests/test_persistence_integrity.py).
        run.evidence_manifest = make_manifest()
        run.verdict = make_stub_verdict(run.id, run.workload_id)
        svc._store.update_run(run)

        with pytest.raises(PersistenceCorruptionError):
            svc.get_integrated_proof(run.id)

    def test_persist_integrated_proof_stamps_validation_generation(self, fresh_service):
        """The write path stamps the generation the proof was produced under."""
        svc = fresh_service
        _app, run = _seed_run_with_report(svc, dict(_stored_report("app-proof")))
        result = SimpleNamespace(
            evidence_manifest=None,
            verdict=None,
            oracle_exit_code=None,
            candidate_exit_code=None,
            comparison_evidence=(),
        )
        app_rec = svc.get_application(run.application_id)
        svc._persist_integrated_proof(app_rec, run, result)
        svc._store.update_run(run)

        proof = svc.get_run(run.id).modernization_report["integrated_proof"]
        assert proof["validation_generation"] == run.validation_generation
        # Persisted against no runtime evidence: never claims certification.
        assert proof["central_status"] != "VERIFIED"
        assert proof["runtime"]["verdict_state"] != "VERIFIED"

        # The stamped proof dies with its generation on revalidation.
        svc._store.begin_revalidation(run.id, certification_contract=None)
        out = _get_proof_or_none(svc, run.id)
        if out is None:
            return
        _assert_not_certifying(out["proof"])


class TestEmptyLedgerPayloadFailsClosed:
    """P0-c: vacuous truth in the proof payload."""

    def test_empty_ledger_payload_never_verifies(self):
        from api.service import _proof_payload, _report_facade

        report = _stored_report("app-empty")
        report["pipeline_report"]["capability"]["components"] = []
        facade = _report_facade(report)
        assert facade is not None, "test setup: facade must exist"

        payload = _proof_payload(
            "wl-proof", facade, PERFECT_RUNTIME, "NOT_PRESENT"
        )
        assert payload["dependency_ledger"] == [], payload["dependency_ledger"]
        assert payload["central_status"] != "VERIFIED", (
            "P0-c: empty ledger payload certified central VERIFIED"
        )
        assert payload["overall_verification"] != "VERIFIED"
        assert payload["required_dependencies_proven"] is False, (
            "P0-c: required_dependencies_proven was vacuously true"
        )
        assert payload["blocking_reasons"], "the fail-closed must be explained"


class TestIntegratedProofEndpointFailClosed:
    """P0-b at the HTTP certification surface (probe P0-b shape)."""

    @patch.object(Service, "_generate_application", _mock_generate)
    @patch.object(Service, "_run_validation", _mock_validation)
    def test_endpoint_stops_serving_stale_verified_after_revalidation(
        self, fresh_service
    ):
        svc, run_id = _seed_proof_run()
        _await_terminal(run_id)

        # Baseline: the persisted proof is served while the attempt is current.
        before = client.get(f"/runs/{run_id}/integrated-proof")
        assert before.status_code == 200

        svc._store.begin_revalidation(run_id, certification_contract=None)
        assert client.get(f"/runs/{run_id}/verdict").status_code == 404

        resp = client.get(f"/runs/{run_id}/integrated-proof")
        if resp.status_code == 200:
            proof = resp.json()["proof"]
            _assert_not_certifying(proof)
        else:
            assert resp.status_code in (404, 500, 503), resp.text
