"""Bounded migration of variable-length (IBM RDW) datasets (G-28).

An RDW record is a 4-byte descriptor (2-byte big-endian length *including* the descriptor, two zero bytes)
followed by the payload.  A variable-length dataset can hold several record layouts of different lengths;
nothing in the data says which layout a record has, so the only deterministic rule offered here is the
exact payload length: the layouts must have unique lengths, each record is converted with the layout of its
length, and a record of any other length is rejected by name.  No discriminator is guessed.

Supported: sequential and entry-sequenced (arrival order, no RBA) datasets, ASCII to EBCDIC cp037, layouts
without binary fields, restart with a checked partial output, independent reconciliation.  Refused by name:
KSDS (key extraction across layouts), RRDS, binary fields, a non-variable dataset.  GnuCOBOL's own variable
record header excludes itself from the length, so it is *not* this format and is not read here.
"""
from __future__ import annotations

import hashlib

from engine.vsam.convert import FieldKind, check_record, convert_record
from engine.vsam.layout import RecordLayout
from engine.vsam.migrate import (
    MigrationReport, _caveats, _checkpoint, _dataset_block, _layout_block,
)
from engine.vsam.model import DatasetDefinition, Encoding, Organization, RecordFormat
from engine.vsam.reconcile import RejectedRecord, reconcile_migration, split_records

SELECTION_RULE = "exact payload length; the layouts' lengths must be unique (no discriminator is guessed)"


def _rdw(payload: bytes) -> bytes:
    return (len(payload) + 4).to_bytes(2, "big") + b"\x00\x00" + payload


def _scope_failures(source: DatasetDefinition, layouts: tuple[RecordLayout, ...], encoding: Encoding) -> list[str]:
    failures: list[str] = []
    if source.record_format is not RecordFormat.VARIABLE:
        failures.append("migrate_variable_dataset handles variable-length (RDW) datasets only; this dataset is "
                        "not variable-length - use migrate_dataset")
    if source.organization is Organization.KSDS:
        failures.append("variable-length KSDS migration is not implemented: the key would have to be located "
                        "across several record layouts")
    if source.organization is Organization.RRDS:
        failures.append("RRDS migration is BLOCKED: the unload format needs an IBM VSAM reference that is not available")
    if source.encoding is not Encoding.ASCII or encoding is not Encoding.EBCDIC_CP037:
        failures.append(f"only an ASCII source migrated to EBCDIC_CP037 is supported "
                        f"(ASCII source required, got {source.encoding.value} -> {encoding.value})")
    failures += [f"invalid source definition: {p}" for p in source.validate()]
    if not layouts:
        failures.append("no record layout was given")
    lengths: dict[int, str] = {}
    for layout in layouts:
        if not layout.supported:
            failures.append(f"the layout {layout.record_name} is not supported: "
                            + "; ".join(f"{d.code} at {d.path or layout.record_name}" for d in layout.diagnostics))
            continue
        if any(f.kind is FieldKind.BINARY for f in layout.fields):
            failures.append(f"the layout {layout.record_name} has binary (COMP / COMP-5) fields: variable-length "
                            "migration of binary fields is not implemented (no platform conversion per layout)")
        if layout.record_length > source.record_length:
            failures.append(f"the layout {layout.record_name} ({layout.record_length} bytes) is longer than the "
                            f"dataset's maximum record length {source.record_length}")
        if layout.record_length in lengths:
            failures.append(f"the layouts {lengths[layout.record_length]} and {layout.record_name} have the same "
                            f"length {layout.record_length}: records cannot be told apart without a discriminator")
        else:
            lengths[layout.record_length] = layout.record_name
    return failures


def _converter(layouts: tuple[RecordLayout, ...], source: DatasetDefinition, encoding: Encoding):
    by_length = {layout.record_length: layout for layout in layouts}

    def convert(payload: bytes) -> bytes:
        layout = by_length.get(len(payload))
        if layout is None:
            raise ValueError(f"no record layout has length {len(payload)}")
        specs = layout.field_specs()
        reason = check_record(payload, specs)
        if reason:
            raise ValueError(reason)
        return convert_record(payload, specs, source.encoding, encoding)

    def check(payload: bytes) -> str | None:
        try:
            convert(payload)
        except ValueError as exc:
            return str(exc)
        return None

    return convert, check


def _layout_section(layouts: tuple[RecordLayout, ...]) -> dict:
    return {"record_layouts": [_layout_block(layout) for layout in layouts], "selection_rule": SELECTION_RULE}


def _destination(source: DatasetDefinition, encoding: Encoding) -> DatasetDefinition:
    return DatasetDefinition(name=f"{source.name}.migrated", organization=source.organization,
                             record_format=RecordFormat.VARIABLE, record_length=source.record_length,
                             encoding=encoding)


def _refused(source: DatasetDefinition, data: bytes, layouts: tuple[RecordLayout, ...], encoding: Encoding,
             failures: list[str]) -> MigrationReport:
    return MigrationReport(
        state="REFUSED", failures=tuple(failures), source=_dataset_block(source, data), layout=_layout_section(layouts),
        record_format="VARIABLE", source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_sha256=hashlib.sha256(data).hexdigest())


def _report(source: DatasetDefinition, data: bytes, layouts: tuple[RecordLayout, ...], encoding: Encoding,
            destination_data: bytes, rejected: tuple[RejectedRecord, ...], *, resumed_from: int = 0,
            total_read: int | None = None) -> MigrationReport:
    convert, check = _converter(layouts, source, encoding)
    destination = _destination(source, encoding)
    recon = reconcile_migration(source, data, destination, destination_data, rejected,
                                translate=convert, validate_record=check)
    warnings, unsupported = _caveats(source)
    return MigrationReport(
        state=recon.status, failures=recon.failures, warnings=warnings + recon.warnings,
        unsupported_semantics=unsupported, source=_dataset_block(source, data),
        destination=_dataset_block(destination, destination_data), layout=_layout_section(layouts),
        record_format="VARIABLE", source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_record_count=recon.source_record_count, destination_record_count=recon.destination_record_count,
        converted_record_count=recon.destination_record_count,
        rejected=tuple((r.record_number, r.reason) for r in sorted(rejected, key=lambda r: r.record_number)),
        duplicate_key_count=recon.duplicate_key_count, source_sha256=recon.source_sha256,
        destination_sha256=recon.destination_sha256,
        checkpoint=_checkpoint(destination_data, total_read if total_read is not None else recon.source_record_count,
                               resumed_from))


def reconcile_variable_destination(source: DatasetDefinition, source_data: bytes, layouts: tuple[RecordLayout, ...],
                                   encoding: Encoding, destination_data: bytes,
                                   rejected: tuple[RejectedRecord, ...] = ()) -> MigrationReport:
    """Independently reconcile an existing variable-length destination against its source."""
    failures = _scope_failures(source, layouts, encoding)
    if failures:
        return _refused(source, source_data, layouts, encoding, failures)
    return _report(source, source_data, layouts, encoding, destination_data, rejected)


def migrate_variable_dataset(source: DatasetDefinition, data: bytes, layouts: tuple[RecordLayout, ...],
                             destination_encoding: Encoding, *, partial_output: bytes = b"",
                             resume_after: int = 0,
                             stop_after: int | None = None) -> tuple[bytes, MigrationReport]:
    """Migrate an RDW dataset; returns ``(destination bytes, report)`` (empty bytes when refused)."""
    failures = _scope_failures(source, layouts, destination_encoding)
    records, structural = split_records(data, source) if not failures else ([], [])
    failures += structural
    if not failures and (resume_after < 0 or resume_after > len(records)):
        failures.append(f"cannot resume after record {resume_after} of {len(records)}")
    if not failures and not resume_after and partial_output:
        failures.append("partial output supplied without a resume point")
    if failures:
        return b"", _refused(source, data, layouts, destination_encoding, failures)

    convert, check = _converter(layouts, source, destination_encoding)
    rejected: list[RejectedRecord] = []
    expected_prefix = bytearray()
    for number, payload in enumerate(records[:resume_after], start=1):
        reason = check(payload)
        if reason:
            rejected.append(RejectedRecord(number, reason))
        else:
            expected_prefix += _rdw(convert(payload))
    if resume_after and bytes(expected_prefix) != partial_output:
        return b"", _refused(source, data, layouts, destination_encoding, [
            f"the partial output does not match the first {resume_after} source record(s); refusing to continue "
            "a torn or altered output"])

    output = bytearray(partial_output)
    end = len(records) if stop_after is None else min(stop_after, len(records))
    for number in range(resume_after + 1, end + 1):
        payload = records[number - 1]
        reason = check(payload)
        if reason:
            rejected.append(RejectedRecord(number, reason))
        else:
            output += _rdw(convert(payload))
    done = max(end, resume_after)
    if done < len(records):
        warnings, unsupported = _caveats(source)
        return bytes(output), MigrationReport(
            state="INTERRUPTED", warnings=warnings, unsupported_semantics=unsupported,
            source=_dataset_block(source, data), layout=_layout_section(layouts), record_format="VARIABLE",
            source_encoding=source.encoding.value, destination_encoding=destination_encoding.value,
            source_record_count=len(records),
            converted_record_count=len(split_records(bytes(output), _destination(source, destination_encoding))[0]),
            rejected=tuple((r.record_number, r.reason) for r in rejected),
            source_sha256=hashlib.sha256(data).hexdigest(),
            checkpoint=_checkpoint(bytes(output), done, resume_after))
    return bytes(output), _report(source, data, layouts, destination_encoding, bytes(output), tuple(rejected),
                                  resumed_from=resume_after, total_read=done)
