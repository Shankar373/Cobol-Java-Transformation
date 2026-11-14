"""Helpers that build logical exports for the VSAM streaming tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from enterprise.contracts import VsamExportManifest, VsamRecordLayout


def fixed_export(records: list[bytes]) -> bytes:
    return b"".join(records)


def rdw_export(records: list[bytes]) -> bytes:
    return b"".join((len(r) + 4).to_bytes(2, "big") + b"\x00\x00" + r for r in records)


def rrds_export(slots: list[tuple[int, bytes]]) -> bytes:
    return b"".join(n.to_bytes(4, "big") + r for n, r in slots)


def make_manifest(
    blob: bytes,
    count: int,
    *,
    organization: str = "KSDS",
    record_format: str = "FIXED",
    min_len: int = 10,
    max_len: int = 10,
    key_length: int = 4,
    code_page: str = "ascii",
    **overrides,
) -> VsamExportManifest:
    return VsamExportManifest(
        dataset_name="TEST.DATA",
        organization=organization,
        layout=VsamRecordLayout(
            record_format=record_format,
            min_record_length=min_len,
            max_record_length=max_len,
            key_length=key_length if organization == "KSDS" else 0,
            code_page=code_page,
        ),
        record_count=count,
        dataset_bytes=len(blob),
        sha256=hashlib.sha256(blob).hexdigest(),
        **overrides,
    )


def write_export(tmp_path: Path, blob: bytes, name: str = "export.dat") -> Path:
    path = tmp_path / name
    path.write_bytes(blob)
    return path


def ksds_records(n: int) -> list[bytes]:
    return [f"{i:04d}REC{i % 1000:03d}".encode("ascii") for i in range(1, n + 1)]
