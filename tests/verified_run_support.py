"""Seed a genuine VERIFIED verdict onto a stubbed API run.

APPROVED decisions require a VERIFIED verdict that hash-matches
integrity-valid evidence (``Service.set_run_approval``).  Tests that stub
the modernization worker never produce one, so they attach a verdict
derived through the real validated path — no hand-written VERIFIED state.
"""

from __future__ import annotations

from api.models import RunStage
from api.store import Store
from engine.domain.identities import RunId, VerdictState
from engine.evidence.integrity import (
    EvidenceIntegrityValidator,
    ValidatedEvidenceManifest,
)
from engine.verdict.derivation import derive_verdict_validated
from tests.adversarial.conftest import (
    make_artifact,
    make_artifact_evidence,
    make_comparison,
    make_manifest,
)

_TERMINAL = {RunStage.COMPLETED, RunStage.FAILED}


def seed_verified_verdict(store: Store, run_id: str, *, state=VerdictState.VERIFIED):
    """Attach evidence plus a verdict derived from it to ``run_id``.

    ``state`` other than VERIFIED seeds a mismatching STDOUT comparison so
    the derived verdict is FAILED — still produced by the real derivation.
    """
    engine_run = RunId(value=f"engine-{run_id}")
    matched = state == VerdictState.VERIFIED
    oracle_art = make_artifact("art-oracle-stdout", "STDOUT", "ORACLE", b"out")
    candidate_art = make_artifact(
        "art-candidate-stdout",
        "STDOUT",
        "CANDIDATE",
        b"out" if matched else b"different",
    )
    manifest = make_manifest(
        run_id=engine_run,
        artifacts=(
            make_artifact_evidence(oracle_art, "oracle-exec-1"),
            make_artifact_evidence(candidate_art, "candidate-exec-1"),
        ),
        comparisons=(
            make_comparison(
                engine_run,
                result="MATCH" if matched else "MISMATCH",
                differences=() if matched else ("line 1 differs",),
            ),
        ),
    )
    validated = EvidenceIntegrityValidator().validate(manifest)
    assert isinstance(validated, ValidatedEvidenceManifest), validated
    verdict = derive_verdict_validated(validated)
    assert verdict.state == state, verdict.state

    record = store.get_run(run_id)
    assert record is not None
    if record.stage not in _TERMINAL:
        record.stage = RunStage.COMPLETED
    record.evidence_manifest = manifest
    record.verdict = verdict
    store.update_run(record)
    return record


def seed_verified_api_run(run_id: str, *, state=VerdictState.VERIFIED):
    """``seed_verified_verdict`` against the live ``api.app`` service store."""
    import api.app as app_mod

    return seed_verified_verdict(app_mod._service._store, run_id, state=state)
