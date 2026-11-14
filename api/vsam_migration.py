"""VSAM dataset migration inside the control plane (Stage 1 product workflow).

The caller uploads one dataset for a file the application's COBOL source declares; the record layout, the keys
and the organization come from that application's own discovered FD (COPY inside FD expanded), never from the
request.  The request chooses only what the source cannot say: the encodings, the binary platforms and, for an FD
with several records, which record.  Nothing is guessed: an unknown file, an ambiguous FD, an unsupported layout or
a missing platform is a refusal with named reasons, and a migration is a success only when the independent
reconciliation says RECONCILED.

Artifacts (report and converted dataset) are written under the durable workspace root, one directory per
deterministic migration id (the same application, dataset and options always map to the same id), so a restart
never turns a stored result into something else.  Sizes are bounded by the caller (``CONTROL_PLANE_MAX_FILE_BYTES``, default 10 MB per file, enforced by the route while reading) and by
the hard backstop here (``MAX_DATASET_BYTES``, 50 MB, which an operator-raised route limit cannot exceed).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from api.errors import BusyError
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.ir import FileDefinition, FileOrganization
from engine.vsam.convert import FieldKind
from engine.vsam.layout import RecordLayout, derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.migrate_variable import migrate_variable_dataset
from engine.vsam.model import (
    DatasetDefinition, Encoding, KeyDefinition, KeyKind, Organization, RecordFormat,
)
from engine.vsam.platform import PLATFORMS, BinaryRepresentation

MAX_DATASET_BYTES = 50 * 1024 * 1024
#: Bump when conversion, layout or platform behaviour changes: it is part of every migration id, so a changed engine
#: never answers a request with a result stored by an older one.
ENGINE_VERSION = "vsam-2026-11-signed-zoned"
_ALLOWED_OPTIONS = frozenset({"file", "record", "organization", "record_format", "source_encoding",
                              "destination_encoding", "source_platform", "target_platform"})
#: Stored migrations kept per application (disk growth bound; there is no delete or retention API yet - ADR-0011).
MAX_MIGRATIONS_PER_APP = 200
_ID = re.compile(r"vm-[0-9a-f]{16}")
_APP_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}")
#: Entries kept in a stored report's ``rejected`` list (the exact count is always reported).
MAX_REPORTED_REJECTIONS = 1000
#: Migrations running at once; more are refused as busy instead of queuing unbounded work.
MAX_CONCURRENT = 2
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)


class VsamRequestError(ValueError):
    """A request the migration refuses; the message names the reason (surfaced to the caller)."""


@dataclass(frozen=True)
class _Plan:
    fd: FileDefinition
    definition: DatasetDefinition
    source_layouts: tuple[RecordLayout, ...]
    target_layouts: tuple[RecordLayout, ...]
    variable: bool
    source_platform: BinaryRepresentation | None
    target_platform: BinaryRepresentation | None
    destination_encoding: Encoding


def _enum(kind, value: str, label: str):
    try:
        return kind(value)
    except ValueError:
        raise VsamRequestError(f"{label} {value!r} is not one of {', '.join(m.value for m in kind)}") from None


def _platform(options: dict, key: str) -> BinaryRepresentation | None:
    name = options.get(key)
    if name in (None, ""):
        return None
    if name not in PLATFORMS:
        raise VsamRequestError(f"{key} {name!r} is not one of {', '.join(sorted(PLATFORMS))}")
    return PLATFORMS[name]


def parse_options(raw: str) -> dict:
    try:
        options = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise VsamRequestError("options must be a JSON object") from None
    if not isinstance(options, dict):
        raise VsamRequestError("options must be a JSON object")
    unknown = sorted(set(options) - _ALLOWED_OPTIONS)
    if unknown:
        raise VsamRequestError(f"unknown option(s): {', '.join(unknown)}")
    if not all(isinstance(v, str) for v in options.values()):
        raise VsamRequestError("every option value must be a string")
    if not options.get("file"):
        raise VsamRequestError("option 'file' (the COBOL file name) is required")
    return options


def _find_fd(workspace: Path, name: str) -> FileDefinition:
    application = ApplicationDiscovery().discover(str(workspace))
    errors = [str(e) for e in getattr(application, "discovery_errors", ())]
    if errors:
        raise VsamRequestError(f"application discovery reported {len(errors)} error(s); the file declarations "
                               "cannot be trusted until they are fixed")
    found = [fd for unit in application.programs for fd in unit.program.file_definitions
             if fd.name.upper() == name.upper() and not fd.is_sort_file]
    if not found:
        raise VsamRequestError(f"no file named {name!r} is declared by the application's programs"
                               )
    if len({(fd.name, fd.record_groups, fd.organization, fd.record_key, fd.alternate_keys, fd.access_mode)
            for fd in found}) > 1:
        raise VsamRequestError(f"file {name!r} is declared differently by several programs; not guessing which")
    return found[0]


def _key(layout: RecordLayout, field_name: str, unique: bool, label: str) -> KeyDefinition:
    matches = [f for f in layout.fields if f.path.split(".")[-1].split("(")[0] == field_name]
    if len(matches) != 1:
        raise VsamRequestError(f"{label} {field_name!r} must name exactly one field of record {layout.record_name} "
                               f"({len(matches)} found)")
    field = matches[0]
    kind = KeyKind.CHARACTER if field.kind is FieldKind.DISPLAY else KeyKind.BINARY
    return KeyDefinition(field.offset, field.length, kind=kind, unique=unique)


def _plan(workspace: Path, options: dict) -> _Plan:
    fd = _find_fd(workspace, options["file"])
    compatible = {FileOrganization.INDEXED: ("KSDS",), FileOrganization.SEQUENTIAL: ("SEQUENTIAL", "ESDS"),
                  FileOrganization.RELATIVE: ("RRDS",)}[fd.organization]
    organization = options.get("organization") or compatible[0]
    org = _enum(Organization, organization, "organization")
    if organization not in compatible:
        raise VsamRequestError(f"organization {organization!r} does not fit the {fd.organization.value} file "
                               f"{fd.name} (allowed: {', '.join(compatible)})")
    record_format = _enum(RecordFormat, options.get("record_format") or "FIXED", "record_format")
    source_encoding = _enum(Encoding, options.get("source_encoding") or "", "source_encoding")
    destination = _enum(Encoding, options.get("destination_encoding") or "", "destination_encoding")
    source_platform, target_platform = _platform(options, "source_platform"), _platform(options, "target_platform")
    if (source_platform is None) != (target_platform is None):
        raise VsamRequestError("source_platform and target_platform must be given together")

    def layouts(model) -> tuple[RecordLayout, ...]:
        names = [g.name for g in fd.record_groups]
        if record_format is RecordFormat.VARIABLE:
            return tuple(derive_file_layout(fd, binary_width_model=model, record_name=n) for n in names)
        chosen = options.get("record") or ("" if len(names) <= 1 else None)
        if chosen is None:
            raise VsamRequestError(f"FD {fd.name} has several records ({', '.join(names)}); option 'record' must name one")
        return (derive_file_layout(fd, binary_width_model=model, record_name=chosen),)

    src_model = source_platform.width_model if source_platform else next(iter(PLATFORMS.values())).width_model
    tgt_model = target_platform.width_model if target_platform else src_model
    source_layouts, target_layouts = layouts(src_model), layouts(tgt_model)
    first = source_layouts[0]
    primary = alternates = None
    if record_format is RecordFormat.FIXED and org is Organization.KSDS:
        if fd.record_key is None:
            raise VsamRequestError(f"KSDS file {fd.name} declares no RECORD KEY")
        primary = _key(first, fd.record_key.field_name, True, "RECORD KEY")
        alternates = tuple(_key(first, k.field_name, not k.is_duplicated, "ALTERNATE RECORD KEY")
                           for k in fd.alternate_keys)
    definition = DatasetDefinition(
        name=fd.name, organization=org, record_format=record_format, encoding=source_encoding,
        record_length=max(l.record_length for l in source_layouts), primary_key=primary,
        alternate_keys=alternates or ())
    return _Plan(fd, definition, source_layouts, target_layouts, record_format is RecordFormat.VARIABLE,
                 source_platform, target_platform, destination)


def migration_id(app_id: str, data: bytes, options: dict, plan: _Plan) -> str:
    """Deterministic id: the same application, dataset, options, layouts, platforms and engine give the same id,
    and anything that could change the result gives a different one."""
    identity = json.dumps({
        "app": app_id, "options": options, "engine": ENGINE_VERSION,
        "source_layouts": [layout.identity for layout in plan.source_layouts],
        "target_layouts": [layout.identity for layout in plan.target_layouts],
        "definition": repr(plan.definition),
        "platforms": [plan.source_platform.to_dict() if plan.source_platform else None,
                      plan.target_platform.to_dict() if plan.target_platform else None],
    }, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode() + b"|" + hashlib.sha256(data).digest()).hexdigest()
    return f"vm-{digest[:16]}"


def execute(workspace: Path, app_id: str, data: bytes, options: dict) -> tuple[dict, bytes]:
    """Run one migration; returns ``(report dict, converted bytes)`` (empty bytes unless converted)."""
    if len(data) > MAX_DATASET_BYTES:
        raise VsamRequestError(f"dataset is {len(data)} bytes; the limit is {MAX_DATASET_BYTES}")
    if not _SLOTS.acquire(blocking=False):
        raise BusyError("the migration service is busy; retry later")
    try:
        plan = _plan(workspace, options)
        if plan.variable:
            output, report = migrate_variable_dataset(plan.definition, data, plan.source_layouts,
                                                      plan.destination_encoding)
        else:
            output, report = migrate_dataset(
                plan.definition, data, plan.source_layouts[0], plan.destination_encoding,
                target_layout=plan.target_layouts[0], source_platform=plan.source_platform,
                target_platform=plan.target_platform)
    finally:
        _SLOTS.release()
    body = report.to_dict()
    rejected = body.get("rejected") or []
    body["rejected_truncated"] = len(rejected) > MAX_REPORTED_REJECTIONS
    body["rejected"] = rejected[:MAX_REPORTED_REJECTIONS]
    body.update({"migration_id": migration_id(app_id, data, options, plan), "application_id": app_id,
                 "file": plan.fd.name, "options": dict(options), "success": bool(report.success),
                 "complete": bool(report.success) and body.get("rejected_record_count", 0) == 0,
                 "engine_version": ENGINE_VERSION,
                 "source_layout_sha256": hashlib.sha256(
                     "".join(layout.identity for layout in plan.source_layouts).encode()).hexdigest(),
                 "output_sha256": hashlib.sha256(output).hexdigest(), "output_bytes": len(output)})
    return body, (output if report.success else b"")


def _root() -> Path:
    from api.paths import workspace_root

    root = workspace_root()
    base = (root if root is not None else Path(tempfile.gettempdir())) / "systemaops-vsam"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base


def _dir(app_id: str, mid: str) -> Path:
    if not _ID.fullmatch(mid) or not _APP_ID.fullmatch(app_id) or set(app_id) <= {"."}:
        raise VsamRequestError("invalid migration or application id")
    return _root() / app_id / mid


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)                  # never leave a partial temp file behind (disk full, ...)
        raise


def store(app_id: str, report: dict, output: bytes) -> None:
    target = _dir(app_id, report["migration_id"])
    existing = load_report(app_id, report["migration_id"])
    if existing is not None and existing.get("output_sha256") != report.get("output_sha256"):
        raise VsamRequestError("a stored migration with this id has a different result; it is not overwritten")
    if existing is None and not target.exists() and _stored_count(app_id) >= MAX_MIGRATIONS_PER_APP:
        raise VsamRequestError(f"this application already holds {MAX_MIGRATIONS_PER_APP} stored migrations; "
                               "remove old ones from the workspace volume before running more (no delete API yet)")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_write(target / "output.dat", output)           # the report is written last: it vouches for the output
    _atomic_write(target / "report.json", json.dumps(report, sort_keys=True, indent=2).encode("utf-8"))


def _stored_count(app_id: str) -> int:
    parent = _dir(app_id, "vm-0000000000000000").parent
    return sum(1 for entry in parent.iterdir() if entry.is_dir()) if parent.is_dir() else 0


def load_report(app_id: str, mid: str) -> dict | None:
    """The stored report, or ``None`` when absent *or unreadable*: a torn or corrupt file vouches for nothing, so the
    id is neither served nor wedged - an identical request simply rewrites it."""
    path = _dir(app_id, mid) / "report.json"
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def load_output(app_id: str, mid: str) -> bytes | None:
    """The converted dataset, only when the stored report says it was reconciled and the bytes still match."""
    report = load_report(app_id, mid)
    path = _dir(app_id, mid) / "output.dat"
    if report is None or not report.get("success") or not path.is_file():
        return None
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == report.get("output_sha256") else None
