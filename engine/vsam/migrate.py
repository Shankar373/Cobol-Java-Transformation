"""Layout-driven dataset migration with an independent reconciliation report.

COBOL record layout + data file -> field-aware conversion -> rejected-record ledger -> KSDS load
order -> independent reconciliation -> a machine-readable report.  It composes
``engine.vsam.layout``, ``engine.vsam.convert`` and ``engine.vsam.reconcile``; nothing here
parses COBOL or runs a program.

States: ``RECONCILED`` (everything checked - the only success), ``RECONCILED_PARTIAL`` (checks
that could not be made, so not a success), ``FAILED`` (an independent check disagreed),
``REFUSED`` (the pipeline will not convert this input, named in ``failures``; nothing was
converted) and ``INTERRUPTED`` (stopped early on request; ``checkpoint.resume_point`` says where
to resume).  Scope, stated rather than hidden: ASCII to EBCDIC cp037 only; fixed-length records
only; KSDS, ESDS (arrival order, no RBA addressing) and sequential datasets; alternate indexes
are not rebuilt or checked (``unsupported_semantics``); no IBM runtime has produced or read
either side.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from engine.vsam.convert import (
    FieldKind, FieldSpec, check_record, convert_dataset, convert_record, sort_for_ksds,
)
from engine.vsam.layout import RecordLayout
from engine.vsam.model import DatasetDefinition, Encoding, Organization, RecordFormat
from engine.vsam.reconcile import RejectedRecord, reconcile_migration, split_records

SCHEMA = "systemaops.migration_report"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MigrationReport:
    state: str
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    source: dict = field(default_factory=dict)
    destination: dict = field(default_factory=dict)
    layout: dict = field(default_factory=dict)
    record_format: str = "FIXED"
    source_encoding: str = ""
    destination_encoding: str = ""
    source_record_count: int = 0
    destination_record_count: int = 0
    converted_record_count: int = 0
    rejected: tuple[tuple[int, str], ...] = ()
    duplicate_key_count: int = 0
    source_sha256: str = ""
    destination_sha256: str = ""
    checkpoint: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.state == "RECONCILED"

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "state": self.state, "success": self.success,
            "source": self.source, "destination": self.destination, "layout": self.layout,
            "record_format": self.record_format,
            "source_encoding": self.source_encoding, "destination_encoding": self.destination_encoding,
            "source_record_count": self.source_record_count,
            "destination_record_count": self.destination_record_count,
            "converted_record_count": self.converted_record_count,
            "rejected_record_count": len(self.rejected), "duplicate_key_count": self.duplicate_key_count,
            "rejected": [{"record_number": n, "reason": r} for n, r in self.rejected],
            "source_sha256": self.source_sha256, "destination_sha256": self.destination_sha256,
            "checkpoint": self.checkpoint,
            "failures": list(self.failures), "warnings": list(self.warnings),
            "unsupported_semantics": list(self.unsupported_semantics),
        }


def _layout_block(layout: RecordLayout) -> dict:
    return {"identity": layout.identity, "record_name": layout.record_name, "record_length": layout.record_length,
            "binary_width_model": layout.binary_width_model,
            "overlay_selection": [list(p) for p in layout.overlay_selection],
            "diagnostics": [{"code": d.code, "path": d.path, "message": d.message} for d in layout.diagnostics]}


def _dataset_block(definition: DatasetDefinition, data: bytes) -> dict:
    return {"name": definition.name, "organization": definition.organization.value,
            "record_length": definition.record_length, "encoding": definition.encoding.value,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _destination_definition(source: DatasetDefinition, encoding: Encoding) -> DatasetDefinition:
    return DatasetDefinition(
        name=f"{source.name}.migrated", organization=source.organization, record_format=RecordFormat.FIXED,
        record_length=source.record_length, encoding=encoding, primary_key=source.primary_key,
        alternate_keys=source.alternate_keys, access_modes=source.access_modes)


def _scope_failures(source: DatasetDefinition, layout: RecordLayout, encoding: Encoding) -> list[str]:
    failures: list[str] = []
    if source.record_format is not RecordFormat.FIXED:
        failures.append("variable-length datasets are not migrated: record descriptor words are not converted")
    if source.organization is Organization.RRDS:
        failures.append("RRDS migration is not modelled: relative slots and their reuse are not represented")
    if source.encoding is not Encoding.ASCII or encoding is not Encoding.EBCDIC_CP037:
        failures.append(f"only an ASCII source migrated to EBCDIC_CP037 is supported "
                        f"(ASCII source required, got {source.encoding.value} -> {encoding.value})")
    failures += [f"invalid source definition: {p}" for p in source.validate()]
    if not layout.supported:
        failures.append("the record layout is not supported: " + "; ".join(
            f"{d.code} at {d.path or layout.record_name}" for d in layout.diagnostics))
        return failures
    if source.record_length != layout.record_length:
        failures.append(f"dataset record length {source.record_length} does not equal the layout's "
                        f"{layout.record_length} ({layout.record_name})")
        return failures
    key = source.primary_key
    if key is not None:
        for spec in layout.field_specs():
            if spec.offset < key.offset + key.length and key.offset < spec.offset + spec.length:
                wants_display = key.kind.value == "CHARACTER"
                if wants_display != (spec.kind is FieldKind.DISPLAY):
                    failures.append(f"the {key.kind.value.lower()} primary key (offset {key.offset}, length "
                                    f"{key.length}) overlaps the {spec.kind.value} field {spec.name}")
    return failures


def _translator(specs: tuple[FieldSpec, ...], source: Encoding, destination: Encoding):
    return lambda record: convert_record(record, specs, source, destination)


def _checkpoint(output: bytes, resume_point: int, resumed_from: int) -> dict:
    return {"identity": hashlib.sha256(output).hexdigest(), "resume_point": resume_point,
            "resumed_from": resumed_from}


def _caveats(source: DatasetDefinition) -> tuple[tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    unsupported: list[str] = []
    if source.organization is Organization.ESDS:
        warnings.append("ESDS: records migrated in entry order; RBA addressing is not modelled")
    if source.alternate_keys:
        unsupported.append(f"{len(source.alternate_keys)} alternate index(es) are not rebuilt or checked")
    return tuple(warnings), tuple(unsupported)


def _reconciled_report(source: DatasetDefinition, source_data: bytes, layout: RecordLayout,
                       encoding: Encoding, destination_data: bytes,
                       rejected: tuple[RejectedRecord, ...], *, resumed_from: int = 0,
                       total_read: int | None = None) -> MigrationReport:
    specs = layout.field_specs()
    destination = _destination_definition(source, encoding)
    recon = reconcile_migration(
        source, source_data, destination, destination_data, rejected,
        translate=_translator(specs, source.encoding, encoding),
        validate_record=lambda record: check_record(record, specs))
    warnings, unsupported = _caveats(source)
    return MigrationReport(
        state=recon.status, failures=recon.failures, warnings=warnings + recon.warnings,
        unsupported_semantics=unsupported,
        source=_dataset_block(source, source_data), destination=_dataset_block(destination, destination_data),
        layout=_layout_block(layout), source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_record_count=recon.source_record_count, destination_record_count=recon.destination_record_count,
        converted_record_count=recon.destination_record_count,
        rejected=tuple((r.record_number, r.reason) for r in sorted(rejected, key=lambda r: r.record_number)),
        duplicate_key_count=recon.duplicate_key_count,
        source_sha256=recon.source_sha256, destination_sha256=recon.destination_sha256,
        checkpoint=_checkpoint(destination_data, total_read if total_read is not None else recon.source_record_count,
                               resumed_from))


def reconcile_destination(source: DatasetDefinition, source_data: bytes, layout: RecordLayout,
                          encoding: Encoding, destination_data: bytes,
                          rejected: tuple[RejectedRecord, ...] = ()) -> MigrationReport:
    """Independently reconcile an existing destination file against its source (no conversion)."""
    failures = _scope_failures(source, layout, encoding)
    if failures:
        return _refused(source, source_data, layout, encoding, failures)
    return _reconciled_report(source, source_data, layout, encoding, destination_data, rejected)


def _refused(source: DatasetDefinition, data: bytes, layout: RecordLayout, encoding: Encoding,
             failures: list[str]) -> MigrationReport:
    return MigrationReport(
        state="REFUSED", failures=tuple(failures), source=_dataset_block(source, data),
        layout=_layout_block(layout), source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_sha256=hashlib.sha256(data).hexdigest())


def migrate_dataset(source: DatasetDefinition, data: bytes, layout: RecordLayout, destination_encoding: Encoding,
                    *, partial_output: bytes = b"", resume_after: int = 0,
                    stop_after: int | None = None) -> tuple[bytes, MigrationReport]:
    """Migrate ``data``; returns ``(destination bytes, report)``.

    Nothing is converted when the input is outside the stated scope (``REFUSED``, empty bytes).
    ``stop_after`` ends the run early (``INTERRUPTED``, the converted prefix is returned and
    ``checkpoint.resume_point`` says where to resume); ``partial_output`` / ``resume_after`` resume
    it and are refused when the partial output is not exactly the conversion of the first records.
    """
    failures = _scope_failures(source, layout, destination_encoding)
    records, structural = split_records(data, source) if not failures else ([], [])
    failures += structural
    if failures:
        return b"", _refused(source, data, layout, destination_encoding, failures)
    specs = layout.field_specs()
    try:
        converted = convert_dataset(source, data, specs, destination_encoding, partial_output=partial_output,
                                    resume_after=resume_after, stop_after=stop_after)
    except ValueError as exc:
        return b"", _refused(source, data, layout, destination_encoding, [str(exc)])

    if converted.records_read < len(records):
        warnings, unsupported = _caveats(source)
        return converted.output, MigrationReport(
            state="INTERRUPTED", warnings=warnings, unsupported_semantics=unsupported,
            source=_dataset_block(source, data), layout=_layout_block(layout),
            source_encoding=source.encoding.value, destination_encoding=destination_encoding.value,
            source_record_count=len(records), converted_record_count=len(converted.output) // source.record_length,
            rejected=tuple((r.record_number, r.reason) for r in converted.rejected),
            source_sha256=hashlib.sha256(data).hexdigest(),
            checkpoint=_checkpoint(converted.output, converted.records_read, resume_after))

    rejected = list(converted.rejected)
    output = converted.output
    key = source.primary_key
    if source.organization is Organization.KSDS and key is not None:
        rejected_numbers = {r.record_number for r in rejected}
        kept = [n for n in range(1, len(records) + 1) if n not in rejected_numbers]
        pieces = [output[i:i + source.record_length] for i in range(0, len(output), source.record_length)]
        seen: set[bytes] = set()
        survivors: list[bytes] = []
        for number, piece in zip(kept, pieces):
            stored_key = piece[key.offset:key.offset + key.length]
            if stored_key in seen:
                rejected.append(RejectedRecord(number, "duplicate primary key (first occurrence kept)"))
            else:
                seen.add(stored_key)
                survivors.append(piece)
        output = sort_for_ksds(b"".join(survivors), source.record_length, key.offset, key.length)
    report = _reconciled_report(source, data, layout, destination_encoding, output, tuple(rejected),
                                resumed_from=resume_after, total_read=converted.records_read)
    return output, report
