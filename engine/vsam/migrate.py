"""Layout-driven dataset migration with an independent reconciliation report.

COBOL record layout + data file -> field-aware conversion -> rejected-record ledger -> KSDS load
order -> independent reconciliation -> a machine-readable report.  It composes
``engine.vsam.layout``, ``engine.vsam.convert``, ``engine.vsam.platform`` and
``engine.vsam.reconcile``; nothing here parses COBOL or runs a program.

States: ``RECONCILED`` (everything checked - the only success), ``RECONCILED_PARTIAL`` (checks
that could not be made, so not a success), ``FAILED`` (an independent check disagreed),
``REFUSED`` (the pipeline will not convert this input, named in ``failures``; nothing was
converted) and ``INTERRUPTED`` (stopped early on request; ``checkpoint.resume_point`` says where
to resume).

Binary fields (COMP / COMP-5) are never copied as if portable (G-27): the migration requires an
explicit ``source_platform``, ``target_platform`` and ``target_layout`` (each layout derived for its
platform's width model) and converts every binary field's width and byte order, rejecting a record
whose value does not fit.  A layout with no binary field needs none of the three.

Scope, stated rather than hidden: ASCII<->EBCDIC cp037 in either direction; fixed-length records only; KSDS, ESDS
(arrival order, no RBA addressing) and sequential datasets; alternate indexes are not rebuilt or
checked (``unsupported_semantics``); no IBM runtime has produced or read either side.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

from engine.vsam.convert import (
    FieldKind, check_record, convert_dataset, convert_record, sort_for_ksds,
)
from engine.vsam.layout import RecordLayout
from engine.vsam.model import DatasetDefinition, Encoding, KeyDefinition, Organization, RecordFormat
from engine.vsam.platform import BinaryRepresentation, check_layout_pair, convert_record_between
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
    target_layout: dict = field(default_factory=dict)
    source_platform: dict = field(default_factory=dict)
    target_platform: dict = field(default_factory=dict)
    binary_conversions: tuple[dict, ...] = ()
    alternate_indexes: tuple[dict, ...] = ()
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
            "target_layout": self.target_layout,
            "source_platform": self.source_platform, "target_platform": self.target_platform,
            "binary_conversions": list(self.binary_conversions),
            "alternate_indexes": list(self.alternate_indexes),
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


def _layout_block(layout: RecordLayout | None) -> dict:
    if layout is None:
        return {}
    return {"identity": layout.identity, "record_name": layout.record_name, "record_length": layout.record_length,
            "binary_width_model": layout.binary_width_model,
            "overlay_selection": [list(p) for p in layout.overlay_selection],
            "diagnostics": [{"code": d.code, "path": d.path, "message": d.message} for d in layout.diagnostics]}


def _dataset_block(definition: DatasetDefinition, data: bytes) -> dict:
    return {"name": definition.name, "organization": definition.organization.value,
            "record_length": definition.record_length, "encoding": definition.encoding.value,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@dataclass(frozen=True)
class _Plan:
    """Everything the conversion needs, decided once and refused up front when it cannot be."""
    source_layout: RecordLayout
    target_layout: RecordLayout
    source_platform: BinaryRepresentation | None
    target_platform: BinaryRepresentation | None
    binary: bool
    destination: DatasetDefinition
    failures: tuple[str, ...]


def _has_binary(layout: RecordLayout) -> bool:
    return any(f.kind is FieldKind.BINARY for f in layout.fields)


def _mapped_key(key: KeyDefinition, source: RecordLayout, target: RecordLayout, label: str,
                failures: list[str]) -> KeyDefinition:
    """The key at its position in the target layout; every field it touches must move the same way."""
    shifts = {dst.offset - src.offset
              for src, dst in zip(source.fields, target.fields)
              if src.offset < key.offset + key.length and key.offset < src.offset + src.length}
    if len(shifts) != 1:
        failures.append(f"the {label} (offset {key.offset}, length {key.length}) spans fields that move "
                        "differently in the target layout")
        return key
    return replace(key, offset=key.offset + shifts.pop())


def _binary_key_failures(layout: RecordLayout, target: RecordLayout, source_platform: BinaryRepresentation,
                         target_platform: BinaryRepresentation, primary: KeyDefinition | None,
                         alternates: tuple[KeyDefinition, ...]) -> list[str]:
    """A key over a binary field whose width or byte order changes between the platforms would not hold the
    source key's bytes (or sort order) afterwards: refused rather than re-keyed by guesswork.  When the field
    is represented identically on both platforms the key is unaffected."""
    def order(plat: BinaryRepresentation, usage: str):
        return plat.comp5_byte_order if usage == "COMP-5" else plat.comp_byte_order

    changed = {s.path for s, t in zip(layout.fields, target.fields)
               if s.kind is FieldKind.BINARY and (s.length != t.length
                                                  or order(source_platform, s.usage) is not order(target_platform, s.usage))}
    keys = ([("primary key", primary)] if primary is not None else []) + [
        (f"alternate key {i}", k) for i, k in enumerate(alternates, start=1)]
    return [f"the {label} (offset {k.offset}, length {k.length}) overlaps the binary field {spec.name}: a key "
            "over a binary field cannot be migrated between platforms (width and byte order change)"
            for label, k in keys for spec in layout.field_specs()
            if spec.name in changed and spec.offset < k.offset + k.length and k.offset < spec.offset + spec.length]


def _plan(source: DatasetDefinition, layout: RecordLayout, encoding: Encoding, target_layout: RecordLayout | None,
          source_platform: BinaryRepresentation | None, target_platform: BinaryRepresentation | None,
          require_rba_preserved: bool = False) -> _Plan:
    failures: list[str] = []
    if source.record_format is not RecordFormat.FIXED:
        failures.append("variable-length datasets are not migrated: record descriptor words are not converted")
    if source.organization is Organization.RRDS:
        failures.append("RRDS migration is BLOCKED: the unload format (slot numbering, empty slots, slot reuse) "
                        "needs an IBM VSAM reference that is not available, so relative-slot semantics cannot be "
                        "preserved or verified")
    if source.organization is Organization.ESDS and require_rba_preserved:
        failures.append("ESDS relative byte addresses (RBA) cannot be preserved: records are migrated in entry "
                        "order and the RBAs of the target are not the source's; a migration that depends on RBA "
                        "identity is refused")
    if {source.encoding, encoding} != {Encoding.ASCII, Encoding.EBCDIC_CP037}:
        failures.append(f"only ASCII<->EBCDIC_CP037 migration is supported, in either direction "
                        f"(got {source.encoding.value} -> {encoding.value})")
    failures += [f"invalid source definition: {p}" for p in source.validate()]
    binary = layout.supported and _has_binary(layout)
    target = target_layout if target_layout is not None else layout
    if not layout.supported:
        failures.append("the record layout is not supported: " + "; ".join(
            f"{d.code} at {d.path or layout.record_name}" for d in layout.diagnostics))
    elif source.record_length != layout.record_length:
        failures.append(f"dataset record length {source.record_length} does not equal the layout's "
                        f"{layout.record_length} ({layout.record_name})")
    elif binary:
        missing = [name for name, value in (("source_platform", source_platform), ("target_platform", target_platform),
                                            ("target_layout", target_layout)) if value is None]
        if missing:
            failures.append("binary (COMP / COMP-5) fields cannot be copied as portable bytes: an explicit "
                            "source_platform, target_platform and target_layout are required; "
                            f"missing: {', '.join(missing)}")
        else:
            failures += check_layout_pair(layout, target, source_platform, target_platform)  # type: ignore[arg-type]
    elif target_layout is not None and target_layout is not layout and (
            target_layout.record_length != layout.record_length or target_layout.fields != layout.fields):
        failures.append("a target layout that differs from the source layout is only accepted for binary "
                        "layouts (with explicit platforms): without binary fields the record is copied "
                        "field by field and cannot change shape")

    mapped_key, mapped_alt = source.primary_key, source.alternate_keys
    if not failures:
        key = source.primary_key
        keys = ([("primary key", key)] if key is not None else []) + [
            (f"alternate key {i}", k) for i, k in enumerate(source.alternate_keys, start=1)]
        for label, candidate in keys:
            for spec in layout.field_specs():
                if spec.offset < candidate.offset + candidate.length and candidate.offset < spec.offset + spec.length:
                    if (candidate.kind.value == "CHARACTER") != (spec.kind is FieldKind.DISPLAY):
                        failures.append(f"the {candidate.kind.value.lower()} {label} (offset {candidate.offset}, "
                                        f"length {candidate.length}) overlaps the {spec.kind.value} field {spec.name}: "
                                        "the declared key kind does not match the field it covers")
        if binary and not failures:
            failures += _binary_key_failures(layout, target, source_platform, target_platform,  # type: ignore[arg-type]
                                             source.primary_key, source.alternate_keys)
        if not failures:
            mapped: list[str] = []
            if key is not None:
                mapped_key = _mapped_key(key, layout, target, "primary key", mapped)
            mapped_alt = tuple(_mapped_key(k, layout, target, f"alternate key {i}", mapped)
                               for i, k in enumerate(source.alternate_keys, start=1))
            failures += mapped
    destination = DatasetDefinition(
        name=f"{source.name}.migrated", organization=source.organization, record_format=RecordFormat.FIXED,
        record_length=target.record_length if layout.supported else source.record_length, encoding=encoding,
        primary_key=mapped_key, alternate_keys=mapped_alt, access_modes=source.access_modes)
    return _Plan(layout, target, source_platform, target_platform, binary, destination, tuple(failures))


def _converters(plan: _Plan, source: DatasetDefinition, encoding: Encoding):
    """``(convert, check)`` for one record, field-wise or between platforms."""
    specs = plan.source_layout.field_specs()
    if plan.binary:
        def convert(record: bytes) -> bytes:
            return convert_record_between(record, plan.source_layout, plan.target_layout,
                                          plan.source_platform, plan.target_platform,  # type: ignore[arg-type]
                                          source.encoding, encoding)

        def check(record: bytes) -> str | None:
            try:
                convert(record)
            except ValueError as exc:
                return str(exc)
            return None
        return convert, check
    return ((lambda record: convert_record(record, specs, source.encoding, encoding)),
            (lambda record: check_record(record, specs)))


def _binary_decisions(plan: _Plan) -> tuple[dict, ...]:
    if not plan.binary or plan.source_platform is None or plan.target_platform is None:
        return ()
    sp, tp = plan.source_platform, plan.target_platform
    return tuple(
        {"path": s.path, "usage": s.usage,
         "source": {"byte_order": (sp.comp5_byte_order if s.usage == "COMP-5" else sp.comp_byte_order).value,
                    "bytes": s.length},
         "target": {"byte_order": (tp.comp5_byte_order if s.usage == "COMP-5" else tp.comp_byte_order).value,
                    "bytes": t.length}}
        for s, t in zip(plan.source_layout.fields, plan.target_layout.fields) if s.kind is FieldKind.BINARY)


def _caveats(source: DatasetDefinition) -> tuple[tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    unsupported: list[str] = []
    if source.organization is Organization.ESDS:
        warnings.append("ESDS: records migrated in entry order; RBA addressing is not modelled")
    if source.alternate_keys:
        unsupported.append(f"{len(source.alternate_keys)} alternate index(es) are not built (the uniqueness and "
                           "duplicates of each key are validated and reported, the index structure is not created)")
    return tuple(warnings), tuple(unsupported)


def _identity_blocks(plan: _Plan) -> dict:
    return {"layout": _layout_block(plan.source_layout), "target_layout": _layout_block(plan.target_layout),
            "source_platform": plan.source_platform.to_dict() if plan.source_platform else {},
            "target_platform": plan.target_platform.to_dict() if plan.target_platform else {},
            "binary_conversions": _binary_decisions(plan)}


def _checkpoint(output: bytes, resume_point: int, resumed_from: int) -> dict:
    return {"identity": hashlib.sha256(output).hexdigest(), "resume_point": resume_point,
            "resumed_from": resumed_from}


def _refused(source: DatasetDefinition, data: bytes, plan: _Plan, encoding: Encoding,
             failures: list[str] | tuple[str, ...]) -> MigrationReport:
    return MigrationReport(
        state="REFUSED", failures=tuple(failures), source=_dataset_block(source, data),
        layout=_layout_block(plan.source_layout),
        target_layout=_layout_block(plan.target_layout) if plan.target_layout is not plan.source_layout else {},
        source_platform=plan.source_platform.to_dict() if plan.source_platform else {},
        target_platform=plan.target_platform.to_dict() if plan.target_platform else {},
        source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_sha256=hashlib.sha256(data).hexdigest())


def _reconciled_report(source: DatasetDefinition, source_data: bytes, plan: _Plan, encoding: Encoding,
                       destination_data: bytes, rejected: tuple[RejectedRecord, ...], *, resumed_from: int = 0,
                       total_read: int | None = None) -> MigrationReport:
    convert, check = _converters(plan, source, encoding)
    recon = reconcile_migration(source, source_data, plan.destination, destination_data, rejected,
                                translate=convert, validate_record=check)
    warnings, unsupported = _caveats(source)
    destination_records, _ = split_records(destination_data, plan.destination)
    indexes = tuple(
        {"index": i, "offset": k.offset, "length": k.length, "unique": k.unique,
         "distinct_keys": len({r[k.offset:k.offset + k.length] for r in destination_records}),
         "duplicate_records": len(destination_records) - len({r[k.offset:k.offset + k.length]
                                                              for r in destination_records}),
         "records": len(destination_records)}
        for i, k in enumerate(plan.destination.alternate_keys, start=1))
    return MigrationReport(
        state=recon.status, failures=recon.failures, warnings=warnings + recon.warnings,
        unsupported_semantics=unsupported,
        source=_dataset_block(source, source_data),
        destination=_dataset_block(plan.destination, destination_data),
        source_encoding=source.encoding.value, destination_encoding=encoding.value,
        source_record_count=recon.source_record_count, destination_record_count=recon.destination_record_count,
        converted_record_count=recon.destination_record_count,
        rejected=tuple((r.record_number, r.reason) for r in sorted(rejected, key=lambda r: r.record_number)),
        duplicate_key_count=recon.duplicate_key_count,
        source_sha256=recon.source_sha256, destination_sha256=recon.destination_sha256,
        checkpoint=_checkpoint(destination_data, total_read if total_read is not None else recon.source_record_count,
                               resumed_from),
        alternate_indexes=indexes,
        **_identity_blocks(plan))


def reconcile_destination(source: DatasetDefinition, source_data: bytes, layout: RecordLayout,
                          encoding: Encoding, destination_data: bytes,
                          rejected: tuple[RejectedRecord, ...] = (), *, target_layout: RecordLayout | None = None,
                          source_platform: BinaryRepresentation | None = None,
                          target_platform: BinaryRepresentation | None = None) -> MigrationReport:
    """Independently reconcile an existing destination file against its source (no conversion)."""
    plan = _plan(source, layout, encoding, target_layout, source_platform, target_platform)
    if plan.failures:
        return _refused(source, source_data, plan, encoding, plan.failures)
    return _reconciled_report(source, source_data, plan, encoding, destination_data, rejected)


def migrate_dataset(source: DatasetDefinition, data: bytes, layout: RecordLayout, destination_encoding: Encoding,
                    *, target_layout: RecordLayout | None = None, source_platform: BinaryRepresentation | None = None,
                    target_platform: BinaryRepresentation | None = None, partial_output: bytes = b"",
                    resume_after: int = 0, stop_after: int | None = None,
                    require_rba_preserved: bool = False) -> tuple[bytes, MigrationReport]:
    """Migrate ``data``; returns ``(destination bytes, report)``.

    Nothing is converted when the input is outside the stated scope (``REFUSED``, empty bytes).
    Binary fields need ``source_platform``, ``target_platform`` and ``target_layout``.  ``stop_after``
    ends the run early (``INTERRUPTED``, the converted prefix is returned and ``checkpoint.resume_point``
    says where to resume); ``partial_output`` / ``resume_after`` resume it and are refused when the
    partial output is not exactly the conversion of the first records.
    """
    plan = _plan(source, layout, destination_encoding, target_layout, source_platform, target_platform,
                 require_rba_preserved)
    failures = list(plan.failures)
    records, structural = split_records(data, source) if not failures else ([], [])
    failures += structural
    if failures:
        return b"", _refused(source, data, plan, destination_encoding, failures)
    specs = plan.source_layout.field_specs()
    convert, _ = _converters(plan, source, destination_encoding)
    target_length = plan.destination.record_length
    try:
        converted = convert_dataset(source, data, specs, destination_encoding, partial_output=partial_output,
                                    resume_after=resume_after, stop_after=stop_after,
                                    convert=convert if plan.binary else None)
    except ValueError as exc:
        return b"", _refused(source, data, plan, destination_encoding, [str(exc)])

    if converted.records_read < len(records):
        warnings, unsupported = _caveats(source)
        return converted.output, MigrationReport(
            state="INTERRUPTED", warnings=warnings, unsupported_semantics=unsupported,
            source=_dataset_block(source, data),
            source_encoding=source.encoding.value, destination_encoding=destination_encoding.value,
            source_record_count=len(records), converted_record_count=len(converted.output) // target_length,
            rejected=tuple((r.record_number, r.reason) for r in converted.rejected),
            source_sha256=hashlib.sha256(data).hexdigest(),
            checkpoint=_checkpoint(converted.output, converted.records_read, resume_after),
            **_identity_blocks(plan))

    rejected = list(converted.rejected)
    output = converted.output
    key = plan.destination.primary_key
    unique_alternates = [(i, k) for i, k in enumerate(plan.destination.alternate_keys, start=1) if k.unique]
    if source.organization in (Organization.KSDS, Organization.ESDS) and (key is not None or unique_alternates):
        rejected_numbers = {r.record_number for r in rejected}
        kept = [n for n in range(1, len(records) + 1) if n not in rejected_numbers]
        pieces = [output[i:i + target_length] for i in range(0, len(output), target_length)]
        survivors: list[tuple[int, bytes]] = list(zip(kept, pieces))
        if source.organization is Organization.KSDS and key is not None:
            seen: set[bytes] = set()
            unique: list[tuple[int, bytes]] = []
            for number, piece in survivors:
                stored_key = piece[key.offset:key.offset + key.length]
                if stored_key in seen:
                    rejected.append(RejectedRecord(number, "duplicate primary key (first occurrence kept)"))
                else:
                    seen.add(stored_key)
                    unique.append((number, piece))
            survivors = unique
        for index, akey in unique_alternates:
            held: set[bytes] = set()
            unique = []
            for number, piece in survivors:
                stored = piece[akey.offset:akey.offset + akey.length]
                if stored in held:
                    rejected.append(RejectedRecord(number, f"duplicate unique alternate key {index} (first occurrence kept)"))
                else:
                    held.add(stored)
                    unique.append((number, piece))
            survivors = unique
        output = b"".join(piece for _, piece in survivors)
        if source.organization is Organization.KSDS and key is not None:
            output = sort_for_ksds(output, target_length, key.offset, key.length)
    report = _reconciled_report(source, data, plan, destination_encoding, output, tuple(rejected),
                                resumed_from=resume_after, total_read=converted.records_read)
    return output, report
