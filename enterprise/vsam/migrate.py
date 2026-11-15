"""Single-pass streaming migration of a VSAM logical export.

KSDS -> ``<path>.idx`` image, fixed ESDS -> record-sequential file (records
back to back), variable ESDS -> line-sequential file, RRDS -> ``<path>.rel``
image: the exact images the generated Java runtime
(``CobolFileIo``) reads. Memory is bounded by the read chunk and one record.
Output is written to ``<out>.part`` and published atomically only after the
record count, byte count and SHA-256 all match the manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from enterprise.contracts import ENGINE_VERSION, MigrationCheckpoint, VsamExportManifest, VsamRecordLayout
from enterprise.quotas import VsamQuotas
from enterprise.vsam.errors import MigrationInterrupted, VsamRefusal
from enterprise.vsam.reader import iter_frames

# Single-byte code pages only: one byte is one key character.
SUPPORTED_CODE_PAGES = frozenset({"ascii", "latin-1", "cp037", "cp500", "cp1047", "cp1140"})
# Control characters cannot be carried by the line-oriented runtime images.
_UNREPRESENTABLE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")
_SEP = "\u0001"
MAX_ALTERNATE_KEYS = 3  # what the generated runtime registers (CobolFileIo.altKey)


@dataclass(frozen=True)
class MigrationResult:
    records: int
    input_bytes: int
    output_bytes: int
    input_sha256: str
    output_sha256: str
    resumed_from_records: int = 0


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def validate_manifest(manifest: VsamExportManifest, quotas: VsamQuotas) -> None:
    layout = manifest.layout
    if manifest.alternate_keys and (manifest.organization != "KSDS" or layout.record_format != "FIXED"):
        raise VsamRefusal("ALTERNATE_KEY_UNSUPPORTED", "alternate keys are supported for fixed-length KSDS only")
    if layout.code_page.lower() not in SUPPORTED_CODE_PAGES:
        raise VsamRefusal("CODE_PAGE_UNSUPPORTED", f"code page {layout.code_page!r}")
    if manifest.dataset_bytes > quotas.dataset_bytes:
        raise VsamRefusal("DATASET_TOO_LARGE", f"{manifest.dataset_bytes} bytes")
    if layout.max_record_length > quotas.record_bytes:
        raise VsamRefusal("RECORD_TOO_LARGE", f"{layout.max_record_length} bytes")
    if layout.min_record_length > layout.max_record_length:
        raise VsamRefusal("INVALID_LAYOUT", "minimum record length exceeds maximum")
    if layout.record_format == "FIXED" and layout.min_record_length != layout.max_record_length:
        raise VsamRefusal("INVALID_LAYOUT", "FIXED records need equal minimum and maximum length")
    if manifest.organization == "KSDS":
        if layout.key_length < 1:
            raise VsamRefusal("INVALID_LAYOUT", "KSDS needs a key length")
        if layout.key_offset != 0:
            raise VsamRefusal("KEY_OFFSET_UNSUPPORTED", "only keys at offset 0 are supported")
        if layout.key_length > layout.min_record_length:
            raise VsamRefusal("INVALID_LAYOUT", "key longer than the shortest record")
        if manifest.duplicate_keys != "REJECT":
            raise VsamRefusal("DUPLICATE_KEYS_UNSUPPORTED", "KSDS duplicate primary keys")
        _validate_alternate_keys(manifest)
    if manifest.organization == "RRDS" and layout.record_format != "FIXED":
        raise VsamRefusal("INVALID_LAYOUT", "RRDS exports must be FIXED")


def _validate_alternate_keys(manifest: VsamExportManifest) -> None:
    layout = manifest.layout
    if len(manifest.alternate_keys) > MAX_ALTERNATE_KEYS:
        raise VsamRefusal("ALTERNATE_KEY_UNSUPPORTED", f"at most {MAX_ALTERNATE_KEYS} alternate keys")
    for offset, length, _duplicates in manifest.alternate_keys:
        if length < 1 or offset + length > layout.min_record_length:
            raise VsamRefusal("INVALID_LAYOUT", f"alternate key {offset}+{length} is outside the shortest record")
        if (offset, length) == (layout.key_offset, layout.key_length):
            raise VsamRefusal("INVALID_LAYOUT", "an alternate key may not be the primary key")


def _seed_unique_alternates(
    src: Path,
    layout: VsamRecordLayout,
    specs: tuple[tuple[int, int, bool], ...],
    upto: int,
    chunk: int,
    limit: int,
) -> list[set[bytes]]:
    """Alternate-key values of the records before ``upto`` (resume): the output has them, the checkpoint does not."""
    seen: list[set[bytes]] = [set() for _ in specs]
    if all(duplicates for _o, _l, duplicates in specs):
        return seen
    with src.open("rb") as fin:
        for frame in iter_frames(fin, layout, relative=False, chunk=chunk, start_offset=0):
            if frame.end > upto:
                break
            _check_alternates(frame.data, frame.offset, specs, seen, limit)
    return seen


def _check_alternates(
    data: bytes,
    offset: int,
    specs: tuple[tuple[int, int, bool], ...],
    seen: list[set[bytes]],
    limit: int,
) -> None:
    """Refuse the value GnuCOBOL answers with status 22 when the file is loaded: a repeated UNIQUE alternate key."""
    for index, (start, length, duplicates) in enumerate(specs):
        if duplicates:
            continue
        value = data[start:start + length]
        if value in seen[index]:
            raise VsamRefusal("ALTERNATE_KEY_DUPLICATE", f"offset {offset}: alternate key {index + 1} repeats a value")
        if len(seen[index]) >= limit:
            raise VsamRefusal(
                "ALTERNATE_CHECK_TOO_LARGE",
                f"more than {limit} records with a unique alternate key cannot be checked in bounded memory",
            )
        seen[index].add(value)


def _decode(raw: bytes, codec: str, offset: int) -> str:
    try:
        text = raw.decode(codec)
    except UnicodeDecodeError as exc:
        raise VsamRefusal("UNDECODABLE_RECORD", f"offset {offset}: {exc.reason}") from None
    if _UNREPRESENTABLE.search(text) or _SEP in text:
        raise VsamRefusal(
            "UNREPRESENTABLE_RECORD",
            f"offset {offset}: binary or control bytes cannot be carried as text",
        )
    return text


def _prefix_digest(path: Path, length: int, chunk: int) -> str:
    h = hashlib.sha256()
    left = length
    with path.open("rb") as f:
        while left > 0:
            block = f.read(min(chunk, left))
            if not block:
                break
            h.update(block)
            left -= len(block)
    return h.hexdigest()


def _write_checkpoint(path: Path, ckpt: MigrationCheckpoint) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(ckpt.model_dump_json(), encoding="utf-8")
    os.replace(tmp, path)


def migrate_export(
    src: Path,
    manifest: VsamExportManifest,
    out: Path,
    *,
    quotas: VsamQuotas | None = None,
    checkpoint_every: int | None = None,
    stop_after_records: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> MigrationResult:
    """Migrate ``src`` to ``out``. ``stop_after_records`` simulates interruption.

    ``cancel_check`` is polled at every checkpoint; when it returns true the run stops with
    :class:`MigrationInterrupted`, keeping the partial output and checkpoint so another worker can resume.
    """
    quotas = quotas or VsamQuotas()
    every = checkpoint_every or quotas.checkpoint_interval_records
    validate_manifest(manifest, quotas)
    layout = manifest.layout
    codec = layout.code_page.lower()
    size = src.stat().st_size
    if size != manifest.dataset_bytes:
        raise VsamRefusal("SIZE_MISMATCH", f"file has {size} bytes, manifest says {manifest.dataset_bytes}")

    part = out.with_name(out.name + ".part")
    ckpt_path = out.with_name(out.name + ".ckpt")
    layout_digest = _digest(layout.model_dump(), manifest.organization)
    options_digest = _digest(codec, manifest.duplicate_keys, quotas.stream_buffer_bytes, manifest.alternate_keys)
    chunk = quotas.stream_buffer_bytes

    in_hash = hashlib.sha256()
    out_hash = hashlib.sha256()
    records = 0
    in_offset = 0
    last_key = b""
    resumed = 0
    out.parent.mkdir(parents=True, exist_ok=True)

    if ckpt_path.exists() and part.exists():
        ckpt = MigrationCheckpoint.model_validate_json(ckpt_path.read_text(encoding="utf-8"))
        compatible = (
            ckpt.input_key == src.name
            and ckpt.input_version == str(size)
            and ckpt.input_sha256 == manifest.sha256
            and ckpt.layout_digest == layout_digest
            and ckpt.options_digest == options_digest
            and ckpt.engine_version == ENGINE_VERSION
        )
        if not compatible or _prefix_digest(src, ckpt.input_offset, chunk) != ckpt.running_sha256_state:
            raise VsamRefusal(
                "RESUME_REJECTED",
                "checkpoint does not match the current source, layout, options or engine",
            )
        if part.stat().st_size < ckpt.output_offset:
            raise VsamRefusal("RESUME_REJECTED", "partial output is shorter than the checkpoint")
        with part.open("r+b") as f:
            f.truncate(ckpt.output_offset)
        for block in _iter_file(src, ckpt.input_offset, chunk):
            in_hash.update(block)
        for block in _iter_file(part, ckpt.output_offset, chunk):
            out_hash.update(block)
        records = resumed = ckpt.records_processed
        in_offset = ckpt.input_offset
        last_key = bytes.fromhex(ckpt.last_key_hex)
        out_mode = "ab"
    else:
        out_mode = "wb"

    relative = manifest.organization == "RRDS"
    key_len = layout.key_length if manifest.organization == "KSDS" else 0
    alternates = manifest.alternate_keys
    seen = (_seed_unique_alternates(src, layout, alternates, in_offset, chunk, quotas.alternate_unique_check_records)
            if alternates and resumed else [set() for _ in alternates])
    try:
        with src.open("rb") as fin, part.open(out_mode) as fout:
            fin.seek(in_offset)
            if out_mode == "wb":
                header = ""
                if manifest.organization == "KSDS":
                    header = f"K{key_len}\n"
                elif relative:
                    header = "R\n"
                if header:
                    data = header.encode("utf-8")
                    fout.write(data)
                    out_hash.update(data)
            out_offset = fout.tell()
            for frame in iter_frames(fin, layout, relative=relative, chunk=chunk, start_offset=in_offset):
                text = _decode(frame.data, codec, frame.offset)
                if manifest.organization == "KSDS":
                    key = frame.data[:key_len]
                    if last_key:
                        if key == last_key:
                            raise VsamRefusal("DUPLICATE_KEY", f"offset {frame.offset}")
                        if key < last_key:
                            raise VsamRefusal("KEYS_OUT_OF_ORDER", f"offset {frame.offset}")
                        if key.decode(codec) <= last_key.decode(codec):
                            raise VsamRefusal(
                                "COLLATION_MISMATCH",
                                f"offset {frame.offset}: key order differs after decoding to text",
                            )
                    last_key = key
                    _check_alternates(frame.data, frame.offset, alternates, seen, quotas.alternate_unique_check_records)
                    # a file with alternate keys keeps each record's write sequence in front of its data
                    prefix = f"{records + 1:016x}" * len(alternates)
                    line = f"{text[:key_len]}{_SEP}{prefix}{text[key_len:]}\n"
                elif relative:
                    previous = int.from_bytes(last_key, "big") if last_key else 0
                    if frame.rrn <= previous:
                        raise VsamRefusal("RRN_OUT_OF_ORDER", f"RRN {frame.rrn} at offset {frame.offset}")
                    last_key = frame.rrn.to_bytes(4, "big")
                    line = f"{frame.rrn}{_SEP}{text}\n"
                elif layout.record_format == "FIXED":
                    line = text  # record-sequential image: no terminator
                else:
                    line = f"{text}\n"  # variable-length: line-sequential image
                encoded = line.encode("utf-8")
                fout.write(encoded)
                out_hash.update(encoded)
                in_hash.update(frame.raw)
                out_offset += len(encoded)
                in_offset = frame.end
                records += 1
                if records % every == 0:
                    fout.flush()
                    os.fsync(fout.fileno())
                    _write_checkpoint(
                        ckpt_path,
                        MigrationCheckpoint(
                            job_id=src.name,
                            input_key=src.name,
                            input_version=str(size),
                            input_sha256=manifest.sha256,
                            input_offset=in_offset,
                            output_offset=out_offset,
                            records_processed=records,
                            last_key_hex=last_key.hex(),
                            layout_digest=layout_digest,
                            options_digest=options_digest,
                            running_sha256_state=in_hash.copy().hexdigest(),
                        ),
                    )
                    if cancel_check is not None and cancel_check():
                        raise MigrationInterrupted(f"stopped at record {records}")
                if stop_after_records is not None and records >= stop_after_records:
                    fout.flush()
                    os.fsync(fout.fileno())
                    raise KeyboardInterrupt("simulated interruption")
            fout.flush()
            os.fsync(fout.fileno())
    except VsamRefusal:
        part.unlink(missing_ok=True)
        ckpt_path.unlink(missing_ok=True)
        raise

    if records != manifest.record_count:
        _discard(part, ckpt_path)
        raise VsamRefusal("RECORD_COUNT_MISMATCH", f"{records} records, manifest says {manifest.record_count}")
    if in_offset != manifest.dataset_bytes:
        _discard(part, ckpt_path)
        raise VsamRefusal("SIZE_MISMATCH", f"consumed {in_offset} of {manifest.dataset_bytes} bytes")
    if in_hash.hexdigest() != manifest.sha256:
        _discard(part, ckpt_path)
        raise VsamRefusal("CHECKSUM_MISMATCH", "input SHA-256 does not match the manifest")

    os.replace(part, out)
    ckpt_path.unlink(missing_ok=True)
    return MigrationResult(
        records=records,
        input_bytes=in_offset,
        output_bytes=out.stat().st_size,
        input_sha256=in_hash.hexdigest(),
        output_sha256=out_hash.hexdigest(),
        resumed_from_records=resumed,
    )


def _discard(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def _iter_file(path: Path, length: int, chunk: int):
    left = length
    with path.open("rb") as f:
        while left > 0:
            block = f.read(min(chunk, left))
            if not block:
                return
            left -= len(block)
            yield block

