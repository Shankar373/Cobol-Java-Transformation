"""Common test utilities."""

from engine.domain.identities import ContentHash, VerdictState, WorkloadId
from engine.verdict.derivation import Verdict


def make_hash(data: str = "test") -> ContentHash:
    """Create a content hash for testing."""
    return ContentHash.from_string(data)


def make_stub_verdict(
    run_id: str,
    workload_id: str,
    *,
    state: VerdictState = VerdictState.UNPROVEN,
) -> Verdict:
    """Build a real engine ``Verdict`` double for API/persistence tests.

    The control-plane store persists verdicts as schema-validated JSON, so
    test doubles must be genuine ``Verdict`` instances — any other object is
    rejected at persist time (fail closed). ``run_id`` keeps the historical
    ``engine-`` prefix so ``engine_run_id`` response behaviour stays covered.
    """
    return Verdict(
        state=state,
        workload_id=WorkloadId(workload_id),
        run_id=f"engine-{run_id}",
        source_hash="sha256:" + "a" * 64,
        candidate_hash="sha256:" + "b" * 64,
        oracle_id="stub-oracle",
        oracle_digest="sha256:" + "c" * 64,
        executed_check_count=0,
        skipped_count=0,
        unavailable_count=0,
        supported_scope_statement="stub scope",
        evidence_manifest_hash="sha256:" + "d" * 64,
        derivation_timestamp="2024-01-01T00:00:00+00:00",
        differences=(),
    )
