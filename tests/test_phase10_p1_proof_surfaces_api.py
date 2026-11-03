"""Phase 10 P1-d/P1-e/P1-f: the remaining certification surfaces fail closed.

* P1-d  ``GET /runs/{id}/report`` serves the whole modernization report
        including the embedded ``integrated_proof`` with no consistency
        check — the same class as P0-b, one surface lower.  The report
        surface now runs the pair check and only embeds the run's
        *current* proof (recomputed fail-closed, or absent when nothing
        current exists).
* P1-e  ``GET /runs/{id}/artifacts`` serves evidence-derived content hashes
        with no integrity validation (§38: evidence must be integrity
        validated).  An invalid manifest now fails closed with
        ``PersistenceCorruptionError``.
* P1-f  the ``get_integrated_proof`` fallback recompute dropped
        ``extra_dependencies`` (MQ/IMS/DB2/CICS edges vanished on the
        recompute path while the persist path carried them — one endpoint,
        two ledgers).  Both paths now derive platform edges from the
        application's source.

Red-first evidence: against unmodified code the stale-embedded-proof,
artifacts-tamper and fallback-edges tests fail.

fastapi-dependent: deliberately NOT wired into the dependency-free
capability-truth gate (BL-063/BL-080); runs in the backend job.
"""

from __future__ import annotations

import pytest

from api.errors import PersistenceCorruptionError
from api.models import RunStage
from api.service import Service
from api.store import Store
from engine.domain.identities import RunId
from tests.adversarial.conftest import make_comparison, make_manifest
from tests.integration.test_integrated_proof_api import (
    _fresh_run_record,
    _stored_report,
)
from tests.test_phase10_p0_proof_trust_api import STALE_PROOF

PLATFORM_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLATFORM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCT PIC X(10).
       01  WORK-AREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC MQI
             MQOPEN Q(HANDLES) QUEUE('ORDQ')
           END-EXEC.
           EXEC SQL
             SELECT ACCT_BAL INTO :WS-ACCT
               FROM ACCOUNT
           END-EXEC.
           EXEC CICS
             LINK PROGRAM('SUBPROG') COMMAREA(WORK-AREA)
           END-EXEC.
           STOP RUN.
"""


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


def _seed_run_with_report(svc, report: dict) -> object:
    app_rec = svc.create_application(
        name="proof-p1", description="", workload_id="wl-proof",
        java_entrypoint="Main",
    )
    run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
    run.stage = RunStage.COMPLETED
    run.modernization_report = report
    svc._store.update_run(run)
    return run


class TestReportSurfaceFailsClosed:
    """P1-d: /report must not publish a stale embedded proof."""

    def test_stale_embedded_proof_not_served_in_report(self, fresh_service):
        svc = fresh_service
        report = dict(_stored_report("app-proof"))
        report["integrated_proof"] = dict(STALE_PROOF)
        run = _seed_run_with_report(svc, report)

        # Current generation: the embedded proof is served.
        current = svc.get_run_report(run.id)
        assert current["integrated_proof"]["central_status"] == "VERIFIED"

        svc._store.begin_revalidation(run.id, certification_contract=None)
        served = svc.get_run_report(run.id)
        assert served["pipeline_report"], "the report itself must stay intact"
        embedded = served.get("integrated_proof")
        if embedded is not None:
            assert embedded["central_status"] != "VERIFIED", (
                "P1-d: /report served the previous attempt's VERIFIED proof"
            )
            assert embedded["runtime"]["verdict_state"] != "VERIFIED"
            assert embedded["required_dependencies_proven"] is False

    def test_report_pair_check_runs_before_serving(self, fresh_service):
        svc = fresh_service
        report = dict(_stored_report("app-proof"))
        report["integrated_proof"] = dict(STALE_PROOF)
        run = _seed_run_with_report(svc, report)

        run.evidence_manifest = make_manifest()
        from tests.common import make_stub_verdict

        run.verdict = make_stub_verdict(run.id, run.workload_id)
        svc._store.update_run(run)

        with pytest.raises(PersistenceCorruptionError):
            svc.get_run_report(run.id)


class TestArtifactsFailClosed:
    """P1-e: evidence-derived hashes require a valid evidence manifest."""

    @staticmethod
    def _manifest_with_artifacts(run_id: RunId):
        from tests.adversarial.conftest import (
            make_artifact,
            make_artifact_evidence,
        )

        # Validator-valid shape (probed): every artifact must be covered by
        # at least one comparison, and the comparison must bind the same
        # run as the manifest.
        oracle = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"out")
        candidate = make_artifact("art-candidate-stdout", "STDOUT", "CANDIDATE", b"out")
        return make_manifest(
            run_id=run_id,
            artifacts=(
                make_artifact_evidence(oracle, "oracle-exec-1"),
                make_artifact_evidence(candidate, "candidate-exec-1"),
            ),
            comparisons=(make_comparison(run_id, result="MATCH"),),
        )

    def test_invalid_manifest_fails_artifacts_closed(self, fresh_service):
        svc = fresh_service
        app_rec = svc.create_application(
            name="artifacts-p1", description="", workload_id="wl-art",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        # Seal-consistent but binding-invalid: the comparison references an
        # oracle artifact that is not part of the manifest's evidence, so it
        # decodes fine yet fails integrity/binding validation (§38).
        run.evidence_manifest = make_manifest(
            run_id=RunId(value=run.id),
            comparisons=(
                make_comparison(
                    RunId(value=run.id),
                    result="MATCH",
                    oracle_id="art-not-in-manifest",
                    candidate_id="art-candidate-stdout",
                ),
            ),
        )
        svc._store.update_run(run)

        with pytest.raises(PersistenceCorruptionError):
            svc.get_artifacts(run.id)

    def test_valid_manifest_still_serves_artifacts(self, fresh_service):
        svc = fresh_service
        app_rec = svc.create_application(
            name="artifacts-ok", description="", workload_id="wl-art",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        run.evidence_manifest = self._manifest_with_artifacts(
            RunId(value=run.id)
        )
        svc._store.update_run(run)

        artifacts = svc.get_artifacts(run.id)
        assert artifacts, "a valid manifest must still serve its artifacts"
        assert all(a["content_hash"] for a in artifacts)


class TestFallbackCarriesPlatformEdges:
    """P1-f: the recompute path serves the same ledger as the persist path."""

    def test_fallback_proof_includes_mq_db2_cics_edges(self, fresh_service, tmp_path):
        svc = fresh_service
        (tmp_path / "PLATFORM.cob").write_text(PLATFORM_COBOL, encoding="utf-8")

        app_rec = svc.create_application(
            name="platform-app", description="", workload_id="wl-platform",
            java_entrypoint="Main",
        )
        app_rec.cobol_source_path = str(tmp_path)
        svc._store.update_application(app_rec)

        report = _stored_report(app_rec.id)  # pipeline report, NO persisted proof
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        run.stage = RunStage.COMPLETED
        run.modernization_report = report
        svc._store.update_run(run)

        proof = svc.get_integrated_proof(run.id)["proof"]
        ids = {e["dependency_id"] for e in proof["dependency_ledger"]}
        assert "MQ:QUEUE=ORDQ" in ids, sorted(ids)
        assert "DB2:TABLE=ACCOUNT" in ids, sorted(ids)
        assert "CICS:PROGRAM=SUBPROG" in ids, sorted(ids)
        assert proof["central_status"] != "VERIFIED"
        assert proof["required_dependencies_proven"] is False
