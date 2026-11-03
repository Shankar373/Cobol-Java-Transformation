"""Phase 10 P2: certification-surface leftovers fail closed.

Red-first evidence: every test in this file fails against unmodified code.

* P2-b  the ``unsupported_dependencies`` payload bucket targeted
        ``ProofState("UNSUPPORTED")`` — no such proof state exists
        (UNSUPPORTED is a *capability level*), so the bucket was
        structurally always empty and could never surface an
        UNSUPPORTED-classified dependency.
* P2-h  ``encode_evidence_manifest`` wrote whatever seal the manifest
        carried without re-checking it against the canonical evidence
        graph, so a mutated manifest encoded to a stale-seal blob that
        only failed at a later decode (fail-closed, but late — §38 wants
        the write boundary to refuse it).
* P2-i  ``get_comparisons`` served comparison evidence with no
        evidence<->verdict pair check (the G-5 remainder after P1-e
        covered ``/artifacts``): a stale verdict surviving a reset could
        sit beside served comparison evidence.

fastapi-dependent: deliberately NOT wired into the dependency-free
capability-truth gate (BL-063/BL-080); runs in the backend job.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.errors import PersistenceCorruptionError
from api.models import RunStage
from api.service import Service
from api.store import Store
from engine.domain.identities import RunId, VerdictState
from tests.common import make_stub_verdict
from tests.integration.test_integrated_proof_api import _fresh_run_record

SQL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCT PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL
             SELECT ACCT_BAL INTO :WS-ACCT
               FROM ACCOUNT
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


class TestUnsupportedBucketIsReal:
    """P2-b: bucket by the capability axis that actually exists."""

    def test_unsupported_capability_entries_reach_the_bucket(self):
        from engine.modernization.capability_analyzer import (
            CapabilityLevel,
            CapabilityReport,
        )
        from engine.modernization.external_dependency_edges import (
            extract_db2_dependency_entries,
        )
        from engine.modernization.integrated_proof import RuntimeLaneEvidence
        from api.service import _proof_payload

        report = SimpleNamespace(
            application_id="app-p2b",
            generation_success=True,
            overall_capability="SUPPORTED",
            capability_report=CapabilityReport(
                application_id="app-p2b",
                components=(),
                overall_level=CapabilityLevel.SUPPORTED,
            ),
        )
        runtime = RuntimeLaneEvidence(
            verdict_state="VERIFIED",
            executed_check_count=4,
            evidence_complete=True,
            evidence_integrity_valid=True,
            oracle_exit_code=0,
            candidate_exit_code=0,
        )
        payload = _proof_payload(
            "wl-p2b",
            report,
            runtime,
            "NOT_PRESENT",
            extra_dependencies=extract_db2_dependency_entries(
                SQL_SOURCE, program_id="SQLPROG"
            ),
        )
        unsupported = payload["unsupported_dependencies"]
        assert unsupported, (
            "P2-b: capability-UNSUPPORTED entries never appear in the"
            " unsupported_dependencies bucket"
        )
        assert all(e["capability_level"] == "UNSUPPORTED" for e in unsupported)
        assert any(e["dependency_id"] == "DB2:TABLE=ACCOUNT" for e in unsupported)

    def test_proven_only_ledger_keeps_the_bucket_empty(self):
        from engine.modernization.capability_analyzer import (
            CapabilityLevel,
            CapabilityReport,
        )
        from engine.modernization.integrated_proof import RuntimeLaneEvidence
        from api.service import _proof_payload

        report = SimpleNamespace(
            application_id="app-p2b-empty",
            generation_success=True,
            overall_capability="SUPPORTED",
            capability_report=CapabilityReport(
                application_id="app-p2b-empty",
                components=(),
                overall_level=CapabilityLevel.SUPPORTED,
            ),
        )
        runtime = RuntimeLaneEvidence(
            verdict_state="VERIFIED",
            executed_check_count=4,
            evidence_complete=True,
            evidence_integrity_valid=True,
            oracle_exit_code=0,
            candidate_exit_code=0,
        )
        payload = _proof_payload("wl-p2b", report, runtime, "NOT_PRESENT")
        assert payload["unsupported_dependencies"] == []


class TestEncodeRefusesStaleSeal:
    """P2-h: the write boundary re-checks the seal (§38, fail early)."""

    @staticmethod
    def _manifest():
        from tests.adversarial.conftest import make_manifest

        return make_manifest()

    def test_unmutated_manifest_still_encodes(self):
        from api.serialization import encode_evidence_manifest

        data = encode_evidence_manifest(self._manifest())
        assert data, "a seal-consistent manifest must still encode"

    def test_mutated_manifest_fails_closed_at_encode(self):
        from api.serialization import encode_evidence_manifest
        from engine.domain.identities import WorkloadId

        manifest = self._manifest()
        # In-place mutation after construction: the seal no longer covers
        # the graph.  Decode would catch it later; encode must refuse now.
        manifest.workload_id = WorkloadId(value="tampered-workload")
        with pytest.raises(PersistenceCorruptionError):
            encode_evidence_manifest(manifest)


class TestComparisonsPairCheck:
    """P2-i (G-5 remainder): comparisons run the pair check too."""

    def test_comparisons_refuse_mismatched_pair_beside_verified_verdict(
        self, fresh_service
    ):
        svc = fresh_service
        app_rec = svc.create_application(
            name="cmp-p2", description="", workload_id="wl-cmp",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        from tests.adversarial.conftest import make_manifest

        run.evidence_manifest = make_manifest(run_id=RunId(value=run.id))
        # VERIFIED verdict whose evidence hash cannot match this manifest —
        # the pair was not produced together (stale verdict after a reset).
        run.verdict = make_stub_verdict(
            run.id, run.workload_id, state=VerdictState.VERIFIED
        )
        svc._store.update_run(run)

        with pytest.raises(PersistenceCorruptionError):
            svc.get_comparisons(run.id)

    def test_comparisons_refuse_hash_mismatched_pair(self, fresh_service):
        svc = fresh_service
        app_rec = svc.create_application(
            name="cmp-p2-mismatch", description="", workload_id="wl-cmp",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        from tests.adversarial.conftest import make_manifest

        run.evidence_manifest = make_manifest(run_id=RunId(value=run.id))
        run.verdict = make_stub_verdict(run.id, run.workload_id)
        svc._store.update_run(run)

        with pytest.raises(PersistenceCorruptionError):
            svc.get_comparisons(run.id)

    def test_comparisons_still_serve_without_a_verdict(self, fresh_service):
        svc = fresh_service
        app_rec = svc.create_application(
            name="cmp-p2-clean", description="", workload_id="wl-cmp",
            java_entrypoint="Main",
        )
        run = svc._store.add_run(_fresh_run_record(svc, app_rec.id))
        from tests.adversarial.conftest import make_manifest

        run.evidence_manifest = make_manifest(run_id=RunId(value=run.id))
        run.stage = RunStage.COMPLETED
        svc._store.update_run(run)

        assert svc.get_comparisons(run.id) == []
