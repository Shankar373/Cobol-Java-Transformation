import pytest
from pydantic import ValidationError

from enterprise.contracts import (
    CertificationResult,
    IngestionJob,
    VsamExportManifest,
    VsamRecordLayout,
)
from enterprise.jobs import (
    TERMINAL_STATES,
    CompletionEvidence,
    IncompleteEvidence,
    InvalidTransition,
    JobState,
    can_transition,
    next_state,
)
from enterprise.quotas import (
    IngestionQuotas,
    QuotaExceeded,
    load_ingestion_quotas,
    validate_multipart_plan,
)

SHA = "a" * 64
MIB = 1024 * 1024


def test_success_requires_publishing_state():
    full = CompletionEvidence(True, True, True, True)
    with pytest.raises(InvalidTransition):
        next_state(JobState.RUNNING, JobState.SUCCEEDED, full)


def test_success_requires_complete_evidence():
    partial = CompletionEvidence(True, True, False, False)
    with pytest.raises(IncompleteEvidence) as exc:
        next_state(JobState.PUBLISHING, JobState.SUCCEEDED, partial)
    assert "checksum_verified" in str(exc.value) and "published" in str(exc.value)


def test_success_with_full_evidence():
    full = CompletionEvidence(True, True, True, True)
    assert next_state(JobState.PUBLISHING, JobState.SUCCEEDED, full) is JobState.SUCCEEDED


def test_terminal_states_have_no_exits():
    for state in TERMINAL_STATES:
        assert not any(can_transition(state, t) for t in JobState)


def test_retry_loop_allowed():
    assert can_transition(JobState.RUNNING, JobState.RETRYING)
    assert can_transition(JobState.RETRYING, JobState.QUEUED)


def test_multipart_plan_counts_parts():
    assert validate_multipart_plan(100 * MIB, 10 * MIB, IngestionQuotas()) == 10


@pytest.mark.parametrize(
    "total,part",
    [(10 * 1024**4, 256 * MIB), (1024**3, 1024), (1024**3, 512 * MIB)],
)
def test_multipart_plan_rejects_bad_sizes(total, part):
    with pytest.raises(QuotaExceeded):
        validate_multipart_plan(total, part, IngestionQuotas())


def test_multipart_part_count_limit():
    quotas = IngestionQuotas(multipart_max_parts=3)
    with pytest.raises(QuotaExceeded) as exc:
        validate_multipart_plan(100 * MIB, 5 * MIB, quotas)
    assert exc.value.limit == "multipart_max_parts"


def test_quota_env_override(monkeypatch):
    monkeypatch.setenv("SYSTEMAOPS_INGEST_ZIP_BYTES", "1234")
    assert load_ingestion_quotas().zip_bytes == 1234
    monkeypatch.setenv("SYSTEMAOPS_INGEST_ZIP_BYTES", "-5")
    assert load_ingestion_quotas().zip_bytes == IngestionQuotas().zip_bytes


def _manifest(**overrides):
    base = dict(
        dataset_name="CUST.KSDS",
        organization="KSDS",
        layout=VsamRecordLayout(
            record_format="FIXED", min_record_length=80, max_record_length=80, key_length=8
        ),
        record_count=1,
        dataset_bytes=80,
        sha256=SHA,
    )
    base.update(overrides)
    return VsamExportManifest(**base)


def test_manifest_is_versioned_and_validates_checksum():
    assert _manifest().schema_version == "1.0"
    with pytest.raises(ValidationError):
        _manifest(sha256="XYZ")


def test_manifest_rejects_unknown_fields_and_is_immutable():
    with pytest.raises(ValidationError):
        _manifest(surprise=1)
    with pytest.raises(ValidationError):
        _manifest().record_count = 5


def test_job_defaults_and_idempotency_key_required():
    job = IngestionJob(job_id="j", application_id="a", idempotency_key="k", source_type="zip")
    assert job.state is JobState.CREATED and job.attempts == 0
    with pytest.raises(ValidationError):
        IngestionJob(job_id="j", application_id="a", idempotency_key="", source_type="zip")


def test_certification_requires_run_and_no_skips():
    base = dict(commit_sha="x", workflow="w", required_jobs=("a", "b"))
    assert not CertificationResult(**base, passed_jobs=("a", "b")).certified
    assert not CertificationResult(**base, run_id="1", passed_jobs=("a",)).certified
    skipped = CertificationResult(**base, run_id="1", passed_jobs=("a", "b"), skipped_jobs=("c",))
    assert not skipped.certified
    assert CertificationResult(**base, run_id="1", passed_jobs=("a", "b")).certified
