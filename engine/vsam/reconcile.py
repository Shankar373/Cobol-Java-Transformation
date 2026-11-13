"""Independent reconciliation of a dataset migration.

A migration is not successful because a target file exists.  Given the source
bytes, the destination bytes and the records the migration rejected on purpose,
this recomputes - without trusting the migrator - every fact an auditor needs:
source and destination identity, record counts, rejected and duplicate-key
counts, the key set, key order, content, data hashes and named failures.

Result states: ``RECONCILED`` (everything checked and consistent),
``RECONCILED_PARTIAL`` (counts and keys consistent, record *content* not
comparable because the encodings differ and no field layout was supplied) and
``FAILED``.  A failed or partial result never reads as success.

Pure and deterministic: bytes in, report out.
"""
from __future__ import annotations

import collections
import hashlib
from dataclasses import dataclass

from engine.vsam.collation import collation_key, is_ascending, key_bytes
from engine.vsam.model import DatasetDefinition, Organization, RecordFormat

RDW_LENGTH = 4


@dataclass(frozen=True)
class RejectedRecord:
    record_number: int  # 1-based position in the source
    reason: str


@dataclass(frozen=True)
class ReconciliationReport:
    status: str
    source: dict
    destination: dict
    source_record_count: int
    destination_record_count: int
    rejected_record_count: int
    duplicate_key_count: int
    source_sha256: str
    destination_sha256: str
    content_compared: bool
    warnings: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def reconciled(self) -> bool:
        return self.status == "RECONCILED"

    def to_dict(self) -> dict:
        return {
            "schema": "systemaops.migration_reconciliation", "schema_version": 1,
            "status": self.status, "source": self.source, "destination": self.destination,
            "source_record_count": self.source_record_count,
            "destination_record_count": self.destination_record_count,
            "rejected_record_count": self.rejected_record_count,
            "duplicate_key_count": self.duplicate_key_count,
            "source_sha256": self.source_sha256, "destination_sha256": self.destination_sha256,
            "content_compared": self.content_compared,
            "warnings": list(self.warnings), "failures": list(self.failures),
        }


def split_records(data: bytes, dataset: DatasetDefinition) -> tuple[list[bytes], list[str]]:
    """Whole records of ``data`` and every structural problem found."""
    problems: list[str] = []
    records: list[bytes] = []
    if dataset.record_format is RecordFormat.FIXED:
        length = dataset.record_length
        whole = len(data) // length if length > 0 else 0
        records = [data[i * length:(i + 1) * length] for i in range(whole)]
        if length > 0 and len(data) % length:
            problems.append(f"{dataset.name}: {len(data) % length} trailing byte(s) do not form a "
                            f"whole {length}-byte record")
        return records, problems
    position = 0
    while position < len(data):
        if position + RDW_LENGTH > len(data):
            problems.append(f"{dataset.name}: truncated record descriptor word at byte {position}")
            break
        total = int.from_bytes(data[position:position + 2], "big")
        if data[position + 2:position + 4] != b"\x00\x00":
            problems.append(f"{dataset.name}: record at byte {position} has a non-zero RDW reserved field")
            break
        if total < RDW_LENGTH or total - RDW_LENGTH > dataset.record_length or position + total > len(data):
            problems.append(f"{dataset.name}: record at byte {position} has an invalid length {total}")
            break
        records.append(data[position + RDW_LENGTH:position + total])
        position += total
    return records, problems


def _identity(dataset: DatasetDefinition, data: bytes) -> dict:
    return {"name": dataset.name, "organization": dataset.organization.value,
            "record_format": dataset.record_format.value, "record_length": dataset.record_length,
            "encoding": dataset.encoding.value, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def reconcile_migration(source: DatasetDefinition, source_data: bytes,
                        destination: DatasetDefinition, destination_data: bytes,
                        rejected: tuple[RejectedRecord, ...] = ()) -> ReconciliationReport:
    failures: list[str] = []
    warnings: list[str] = []
    failures += [f"invalid source definition: {p}" for p in source.validate()]
    failures += [f"invalid destination definition: {p}" for p in destination.validate()]
    src, src_problems = split_records(source_data, source)
    dst, dst_problems = split_records(destination_data, destination)
    failures += src_problems + dst_problems

    rejected_numbers = collections.Counter(r.record_number for r in rejected)
    for number, times in sorted(rejected_numbers.items()):
        if number < 1 or number > len(src):
            failures.append(f"rejected record {number} does not exist in the source ({len(src)} records)")
        elif times > 1:
            failures.append(f"source record {number} is listed as rejected {times} times")
    valid_rejected = {n for n in rejected_numbers if 1 <= n <= len(src)}
    kept = [(i + 1, record) for i, record in enumerate(src) if (i + 1) not in valid_rejected]

    if len(dst) != len(kept):
        failures.append(f"destination holds {len(dst)} record(s); source {len(src)} minus "
                        f"{len(valid_rejected)} rejected = {len(kept)} expected")

    duplicate_keys = 0
    justified_rejections: set[int] = set()
    keys_checked = False
    key = source.primary_key
    dkey = destination.primary_key
    if key is None or dkey is None:
        warnings.append("no primary key on source or destination: key set and key order were not checked")
    else:
        keys_checked = True
        seen_any: dict[bytes, int] = {}
        seen_kept: dict[bytes, int] = {}
        for number, record in enumerate(src, start=1):
            k = key_bytes(record, key)
            if k in seen_any:
                duplicate_keys += 1
                if number in valid_rejected:
                    justified_rejections.add(number)  # a repeated key is provably a reason to reject
            seen_any.setdefault(k, number)
            if number not in valid_rejected:
                if k in seen_kept:
                    failures.append(f"source record {number} repeats the primary key of record {seen_kept[k]} "
                                    "and was not rejected")
                seen_kept.setdefault(k, number)
        try:
            expected = collections.Counter(
                collation_key(key_bytes(r, key), key, source.encoding, destination.encoding) for _, r in kept)
        except (UnicodeDecodeError, UnicodeEncodeError) as exc:
            failures.append(f"a source key has no counterpart in {destination.encoding.value}: {exc.reason}")
            expected = collections.Counter()
            keys_checked = False
        actual_keys = [key_bytes(r, dkey) for r in dst]
        actual = collections.Counter(actual_keys)
        if keys_checked:
            missing = sum((expected - actual).values())
            unexpected = sum((actual - expected).values())
            if missing:
                failures.append(f"{missing} source key(s) are missing from the destination")
            if unexpected:
                failures.append(f"{unexpected} destination key(s) have no source record")
        if dkey.unique and any(n > 1 for n in actual.values()):
            failures.append(f"destination has {sum(n - 1 for n in actual.values() if n > 1)} duplicate "
                            "primary key(s) in a unique-key dataset")
        if destination.organization is Organization.KSDS:
            try:
                ordered = is_ascending(
                    [collation_key(k, dkey, destination.encoding, destination.encoding) for k in actual_keys])
            except (UnicodeDecodeError, UnicodeEncodeError) as exc:
                ordered = False
                failures.append(f"a destination key cannot be ordered in {destination.encoding.value}: {exc.reason}")
            else:
                if not ordered:
                    failures.append(f"destination records are not in {destination.encoding.value} key order")

    content_compared = source.encoding is destination.encoding and \
        source.record_format is destination.record_format and source.record_length == destination.record_length
    if content_compared:
        kept_records = [record for _, record in kept]
        if destination.organization is Organization.KSDS:
            # a KSDS is reordered by key; its order was checked above
            same_content = collections.Counter(kept_records) == collections.Counter(dst)
        else:
            # sequential and entry-sequenced datasets keep arrival order
            same_content = kept_records == dst
            if not same_content and collections.Counter(kept_records) == collections.Counter(dst):
                failures.append("destination records are the source records in a different order")
                same_content = True
        if not same_content:
            failures.append("destination record content differs from the source records")
    else:
        warnings.append("record content was not compared: encoding or record format differs and no field "
                        "layout was supplied to translate it")
    if valid_rejected:
        warnings.append(f"{len(valid_rejected)} source record(s) were rejected on purpose "
                        f"({'; '.join(sorted({r.reason for r in rejected})[:3])})")
    unverified = sorted(valid_rejected - justified_rejections)
    if unverified:
        warnings.append(f"{len(unverified)} rejected record(s) were not independently justified "
                        f"(first: record {unverified[0]}); only a repeated primary key is verified here")

    fully_checked = content_compared and keys_checked and not unverified
    status = "FAILED" if failures else ("RECONCILED" if fully_checked else "RECONCILED_PARTIAL")
    return ReconciliationReport(
        status=status, source=_identity(source, source_data), destination=_identity(destination, destination_data),
        source_record_count=len(src), destination_record_count=len(dst),
        rejected_record_count=len(valid_rejected), duplicate_key_count=duplicate_keys,
        source_sha256=hashlib.sha256(source_data).hexdigest(),
        destination_sha256=hashlib.sha256(destination_data).hexdigest(),
        content_compared=content_compared, warnings=tuple(warnings), failures=tuple(failures))
