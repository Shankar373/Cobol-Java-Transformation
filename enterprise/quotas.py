"""Per-workflow quotas. Every limit is configurable through the environment.

One global request limit is deliberately not used: GitHub transfer, multipart
ZIP upload, discovery and VSAM streaming have different cost profiles. The
default sizes are conservative engineering values, not approved production
quotas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import cast

from api.limits import env_int_limit

_LOG = logging.getLogger(__name__)
MIB = 1024 * 1024
GIB = 1024 * MIB


class QuotaExceeded(Exception):
    """A configured limit was exceeded; the work must be refused."""

    def __init__(self, limit: str, value: int, maximum: int) -> None:
        super().__init__(f"{limit}: {value} exceeds the limit of {maximum}")
        self.limit = limit
        self.value = value
        self.maximum = maximum


@dataclass(frozen=True)
class IngestionQuotas:
    zip_bytes: int = 5 * GIB
    extracted_bytes: int = 20 * GIB
    archive_entries: int = 200_000
    compression_ratio: int = 100
    repo_transfer_bytes: int = 2 * GIB
    repo_file_count: int = 200_000
    file_bytes: int = 256 * MIB
    multipart_part_min_bytes: int = 5 * MIB
    multipart_part_max_bytes: int = 256 * MIB
    multipart_max_parts: int = 10_000
    upload_session_ttl_seconds: int = 24 * 3600
    git_timeout_seconds: int = 600


@dataclass(frozen=True)
class VsamQuotas:
    dataset_bytes: int = 20 * GIB
    record_bytes: int = 32_767
    stream_buffer_bytes: int = 1 * MIB
    checkpoint_interval_records: int = 100_000


@dataclass(frozen=True)
class WorkerQuotas:
    concurrency: int = 4
    job_timeout_seconds: int = 4 * 3600
    lease_seconds: int = 300
    max_retries: int = 3
    storage_retention_days: int = 30


def _from_env(cls, prefix: str):
    values = {
        f.name: env_int_limit(f"SYSTEMAOPS_{prefix}_{f.name.upper()}", cast(int, f.default), _LOG)
        for f in fields(cls)
    }
    return cls(**values)


def load_ingestion_quotas() -> IngestionQuotas:
    return _from_env(IngestionQuotas, "INGEST")


def load_vsam_quotas() -> VsamQuotas:
    return _from_env(VsamQuotas, "VSAM")


def load_worker_quotas() -> WorkerQuotas:
    return _from_env(WorkerQuotas, "WORKER")


def enforce(limit: str, value: int, maximum: int) -> None:
    if value > maximum:
        raise QuotaExceeded(limit, value, maximum)


def validate_multipart_plan(
    total_bytes: int, part_bytes: int, quotas: IngestionQuotas
) -> int:
    """Return the part count for an upload, or raise QuotaExceeded."""
    enforce("zip_bytes", total_bytes, quotas.zip_bytes)
    if part_bytes < quotas.multipart_part_min_bytes:
        raise QuotaExceeded(
            "multipart_part_min_bytes", part_bytes, quotas.multipart_part_min_bytes
        )
    enforce("multipart_part_max_bytes", part_bytes, quotas.multipart_part_max_bytes)
    parts = -(-total_bytes // part_bytes)
    enforce("multipart_max_parts", parts, quotas.multipart_max_parts)
    return parts
