"""Layer 4 (P1): ``DialectProfile`` — one frozen, deterministic dialect/reference-format record per file.

The profile is produced **here and nowhere else** (integration contract 3 in
``docs/architecture/LAYER_MODEL.md``): it is fed from ``runtime_deps.dialect_report`` (the dialect
evidence), the single reference-format reader recorded on the scan (``cobol_text.read_source`` via
``FileScan.source_format``/``format_switches``) and ``compilers.std_for_dialect``.  Nothing here
re-detects a dialect or a reference format from raw bytes — it only records what those authorities
already concluded.

Determinism: a pure function of the scan findings; canonical JSON with sorted keys and fixed
separators; ``profile_id`` is the sha256 of that JSON **without** the id itself, so the same source
bytes always yield the same id regardless of file order, and any byte change changes the id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .compilers import std_for_dialect
from .findings import FileScan
from .inventory import FileRecord
from .runtime_deps import dialect_report

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .resolve import GraphBuild

__all__ = ["PROFILE_SCHEMA", "ORACLE_TOOL", "DialectProfile", "build_profiles", "canonical_json"]

PROFILE_SCHEMA = "systemaops.dialect-profile/1.0"
#: The oracle the platform pins (layer 11); recorded on every profile so the identity travels with the record.
ORACLE_TOOL = "gnucobol-3.1.2"
#: The only two confidence values; a dialect is never claimed as certain.
CONFIDENCE_VALUES = ("indicative", "undetermined")
#: Honest, shared basis string for every profile (the report repeats it verbatim).
BASIS = ("indicative: derived from source signals; only the customer's compiler can confirm a dialect")
#: Reference formats a profile may record.
REFERENCE_FORMATS = ("fixed", "free", "mixed", "variable")
#: Directive states a profile may record (P3 adds ``evaluated`` for the computable ``>>IF`` subset).
DIRECTIVE_STATES = ("none", "evaluated", "unevaluated")

#: Construct names this file requires that the engine frontend refuses before parsing (P4 refusals).
UNSUPPORTED_OO = "OO_COBOL_UNSUPPORTED"
UNSUPPORTED_SCREEN = "SCREEN_SECTION_UNSUPPORTED"
UNSUPPORTED_VARIABLE = "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED"
UNSUPPORTED_CONDITIONAL = "CONDITIONAL_COMPILATION_UNEVALUATED"

#: Directive prefixes that mean conditional compilation is present: the fail-closed fallback when a
#: scan carries no reader verdict (the reader itself evaluates the subset and reports the verdict).
_CONDITIONAL_PREFIXES = (">>IF", ">>DEFINE", ">>CALL", ">>EVALUATE", ">>ELSE", ">>END-IF", ">>WHEN")
#: ``program-id`` fact kinds that mean object-oriented COBOL.
_OO_KINDS = ("CLASS-ID", "INTERFACE-ID", "FACTORY", "OBJECT", "METHOD-ID")


@dataclass(frozen=True)
class DialectProfile:
    """The frozen per-file dialect record.  ``profile_id`` covers every other field."""

    file: str
    source_digest: str           #: sha256 of the file's exact bytes (immutable identity, layer model contract 2)
    dialect: str                 #: primary dialect from ``dialect_report`` or ``"undetermined"``
    confidence: str              #: ``indicative`` | ``undetermined`` (never ``certain``)
    basis: str                   #: the shared honest basis string
    reference_format: str        #: ``fixed`` | ``free`` | ``mixed`` | ``variable``
    format_switches: tuple[tuple[int, str], ...]  #: ``(line, new_format)`` from the single reader
    compiler_options: tuple[str, ...]             #: CBL/PROCESS/``$SET`` options, first-occurrence order
    directive_state: str         #: ``none`` | ``evaluated`` | ``unevaluated``
    directives: tuple[tuple[int, str], ...]        #: ``(line, text)`` for every ``>>``/``$SET`` directive
    library_order: tuple[str, ...]                 #: effective COPY search order for this file
    unsupported: tuple[str, ...]                   #: construct names this file requires and generation refuses
    oracle_tool: str
    oracle_std: str              #: ``-std`` value selected by ``compilers.std_for_dialect``
    oracle_format: str           #: ``-free`` | ``-fixed`` | ``""`` (not attributable: mixed/variable)
    profile_id: str = ""         #: sha256 of :func:`canonical_json` of this record without the id

    def as_dict(self) -> dict[str, object]:
        """The canonical mapping of the profile, ``profile_id`` last (it hashes everything before it)."""
        return {
            "schema": PROFILE_SCHEMA,
            "file": self.file,
            "source_digest": self.source_digest,
            "dialect": self.dialect,
            "confidence": self.confidence,
            "basis": self.basis,
            "reference_format": self.reference_format,
            "format_switches": [list(pair) for pair in self.format_switches],
            "compiler_options": list(self.compiler_options),
            "directive_state": self.directive_state,
            "directives": [list(pair) for pair in self.directives],
            "library_order": list(self.library_order),
            "unsupported": list(self.unsupported),
            "oracle": {"tool": self.oracle_tool, "std": self.oracle_std, "format": self.oracle_format},
            "profile_id": self.profile_id,
        }


def canonical_json(profile: DialectProfile) -> str:
    """Canonical bytes of the profile **without** ``profile_id`` — what ``profile_id`` hashes."""
    payload = {key: value for key, value in profile.as_dict().items() if key != "profile_id"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _with_id(profile: DialectProfile) -> DialectProfile:
    digest = hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()
    return replace(profile, profile_id=digest)


def _library_order(record: FileRecord, build: "GraphBuild | None") -> tuple[str, ...]:
    """The effective COPY search order for this file: its compile command's ``-I`` order, else the estate's
    ``JCLLIB ORDER`` concatenation (job order, position order, deduplicated)."""
    if build is None:
        return ()
    include = build.estate.include_order.get(record.path.rsplit("/", 1)[-1].lower())
    if include:
        return tuple(include)
    order: list[str] = []
    for job in sorted(build.estate.jcllib):
        for _position, target in sorted(build.estate.jcllib[job]):
            if target not in order:
                order.append(target)
    return tuple(order)


def _unsupported(scan: FileScan, reference_format: str, directives: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    names: list[str] = []
    if reference_format == "variable":
        names.append(UNSUPPORTED_VARIABLE)
    if any(fact.category == "program-id" and dict(fact.detail).get("kind") in _OO_KINDS for fact in scan.facts):
        names.append(UNSUPPORTED_OO)
    if any(ref.target_kind == "screen-field" for ref in scan.refs):
        names.append(UNSUPPORTED_SCREEN)
    if _directive_state(scan, directives) == "unevaluated":
        names.append(UNSUPPORTED_CONDITIONAL)
    return tuple(sorted(set(names)))


def _directive_state(scan: FileScan, directives: Sequence[tuple[int, str]]) -> str:
    """``none`` | ``evaluated`` | ``unevaluated`` — the single reader's conditional verdict (criterion 5).

    ``read_source`` evaluates the documented ``>>DEFINE``/``>>IF`` subset and drops the dead branch;
    anything outside it records the first offending line and both branches are kept.  The prefix
    check is the fail-closed fallback for a scan built without a reader verdict.
    """
    if scan.conditional == "unevaluated":
        return "unevaluated"
    if scan.conditional == "evaluated":
        return "evaluated"
    if any(directive.upper().startswith(_CONDITIONAL_PREFIXES) for _line, directive in directives):
        return "unevaluated"
    return "none"


def _compiler_options(scan: FileScan, directives: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    """CBL/PROCESS options plus ``$SET`` directive text, first-occurrence order, deduplicated."""
    options: list[str] = []
    for fact in scan.facts:
        if fact.category == "compiler-option" and fact.name and fact.name not in options:
            options.append(fact.name)
    for _line, directive in directives:
        if directive.upper().startswith("$SET") and directive not in options:
            options.append(directive)
    return tuple(options)


def build_profiles(records: Sequence[FileRecord], *, build: "GraphBuild | None" = None,
                   dialect_report_result: Mapping[str, object] | None = None) -> tuple[DialectProfile, ...]:
    """One :class:`DialectProfile` per COBOL/copybook record, sorted by file path.

    ``dialect_report_result`` may pass the already-computed ``dialect_report(records)`` so the report
    computes the dialect evidence once.  Pure function of the records (and the estate library order):
    the same inputs always yield the same profiles and ids, in any order.
    """
    report = dialect_report_result if dialect_report_result is not None else dialect_report(list(records))
    primary: dict[str, str] = {}
    entries = report.get("files", [])
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        primary[str(entry["file"])] = str(entry["primary"])

    profiles: list[DialectProfile] = []
    for record in sorted(records, key=lambda r: r.path):
        if record.cls not in ("cobol", "copybook") or record.scan is None:
            continue
        scan = record.scan
        dialect = primary.get(record.path, "undetermined")
        reference_format = record.source_format or scan.source_format or "fixed"
        directives = tuple((fact.line, fact.name) for fact in scan.facts if fact.category == "directive")
        conditional = _directive_state(scan, directives)
        oracle_format = "-free" if reference_format == "free" else ("-fixed" if reference_format == "fixed" else "")
        profile = DialectProfile(
            file=record.path,
            source_digest=record.sha256,
            dialect=dialect,
            confidence="undetermined" if dialect == "undetermined" else "indicative",
            basis=BASIS,
            reference_format=reference_format,
            format_switches=tuple(scan.format_switches),
            compiler_options=_compiler_options(scan, directives),
            directive_state=conditional,
            directives=directives,
            library_order=_library_order(record, build),
            unsupported=_unsupported(scan, reference_format, directives),
            oracle_tool=ORACLE_TOOL,
            oracle_std=std_for_dialect(dialect),
            oracle_format=oracle_format,
        )
        profiles.append(_with_id(profile))
    return tuple(profiles)
