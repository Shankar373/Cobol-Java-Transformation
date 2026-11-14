"""Versioned, immutable data contracts shared by API, workers and storage.

Every contract carries ``schema_version`` so stored documents can be migrated.
Contracts are metadata only: large objects are referenced through
``ObjectRef`` and never embedded.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise.jobs import JobState

SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "enterprise-1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_sha256(value: str) -> str:
    if not _SHA256.match(value):
        raise ValueError("expected a lowercase hex SHA-256")
    return value


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str = SCHEMA_VERSION


class ObjectRef(Contract):
    """Pointer to an immutable object in object storage."""

    key: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str
    version: str = ""

    _v = field_validator("sha256")(_check_sha256)


class SourceFileEntry(Contract):
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str
    file_type: str = "unknown"

    _v = field_validator("sha256")(_check_sha256)


class IgnoredFile(Contract):
    path: str
    reason: str


class SourceFileManifest(Contract):
    manifest_id: str
    files: tuple[SourceFileEntry, ...] = ()
    ignored: tuple[IgnoredFile, ...] = ()


class SourceSnapshot(Contract):
    snapshot_id: str
    application_id: str
    source_type: Literal["github", "zip"]
    repository: str = ""
    requested_ref: str = ""
    resolved_commit: str = ""
    manifest: SourceFileManifest
    archive: ObjectRef | None = None
    acquired_at: datetime = Field(default_factory=utcnow)


class JobError(Contract):
    category: Literal[
        "quota", "validation", "security", "transient", "storage", "internal", "unsupported"
    ]
    message: str
    retryable: bool = False


class IngestionJob(Contract):
    job_id: str
    application_id: str
    idempotency_key: str = Field(min_length=1)
    source_type: Literal["github", "zip"]
    state: JobState = JobState.CREATED
    snapshot_id: str = ""
    engine_version: str = ENGINE_VERSION
    attempts: int = Field(default=0, ge=0)
    error: JobError | None = None
    correlation_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ApplicationInventory(Contract):
    snapshot_id: str
    application_id: str
    programs: tuple[str, ...] = ()
    copybooks: tuple[str, ...] = ()
    other_files: tuple[str, ...] = ()
    discovery_state: Literal["pending", "complete", "failed"] = "pending"


class ApplicationDiscovery(Contract):
    snapshot_id: str
    entry_programs: tuple[str, ...] = ()
    calls: tuple[tuple[str, str], ...] = ()
    copy_edges: tuple[tuple[str, str], ...] = ()
    file_definitions: tuple[str, ...] = ()
    vsam_datasets: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()


class DatasetManifest(Contract):
    dataset_name: str
    object: ObjectRef
    record_count: int = Field(ge=0)


class VsamRecordLayout(Contract):
    record_format: Literal["FIXED", "VARIABLE_RDW"]
    min_record_length: int = Field(ge=1)
    max_record_length: int = Field(ge=1)
    key_offset: int = Field(default=0, ge=0)
    key_length: int = Field(default=0, ge=0)
    code_page: str = "cp037"


class VsamExportManifest(Contract):
    dataset_name: str = Field(min_length=1)
    organization: Literal["KSDS", "ESDS", "RRDS"]
    layout: VsamRecordLayout
    duplicate_keys: Literal["REJECT", "ALLOW"] = "REJECT"
    alternate_keys: tuple[tuple[int, int], ...] = ()
    record_count: int = Field(ge=0)
    dataset_bytes: int = Field(ge=0)
    sha256: str
    export_platform: str = "unspecified"
    export_tool: str = "unspecified"
    export_tool_version: str = "unspecified"
    provenance: str = ""

    _v = field_validator("sha256")(_check_sha256)


class MigrationCheckpoint(Contract):
    job_id: str
    input_key: str
    input_version: str
    input_sha256: str
    input_offset: int = Field(ge=0)
    output_offset: int = Field(ge=0)
    records_processed: int = Field(ge=0)
    last_key_hex: str = ""
    layout_digest: str
    options_digest: str
    engine_version: str = ENGINE_VERSION
    running_sha256_state: str = ""


class MigrationJob(Contract):
    job_id: str
    application_id: str
    idempotency_key: str = Field(min_length=1)
    manifest: VsamExportManifest
    input: ObjectRef
    state: JobState = JobState.CREATED
    bytes_processed: int = Field(default=0, ge=0)
    records_processed: int = Field(default=0, ge=0)
    output: ObjectRef | None = None
    error: JobError | None = None
    engine_version: str = ENGINE_VERSION


class ArtifactObject(Contract):
    artifact_id: str
    job_id: str
    kind: Literal["converted_dataset", "java_artifact", "validation_report", "manifest"]
    object: ObjectRef
    published: bool = False


class ValidationEvidence(Contract):
    job_id: str
    source_sha256: str
    engine_version: str = ENGINE_VERSION
    runtime: str = ""
    commands: tuple[str, ...] = ()
    comparison: Literal["match", "mismatch", "not_run"] = "not_run"
    oracle: Literal["gnucobol", "independent_fixture", "none"] = "none"
    details: str = ""


class CertificationResult(Contract):
    commit_sha: str
    workflow: str
    run_id: str = ""
    required_jobs: tuple[str, ...] = ()
    passed_jobs: tuple[str, ...] = ()
    skipped_jobs: tuple[str, ...] = ()

    @property
    def certified(self) -> bool:
        return (
            bool(self.run_id)
            and not self.skipped_jobs
            and set(self.required_jobs) <= set(self.passed_jobs)
        )
