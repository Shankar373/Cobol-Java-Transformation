"""How downstream consumers take their application-level relationships from the canonical Application IR (Layer 6 migration).

``ir_for_application`` projects the facts of the very source texts a discovered :class:`CobolApplication` was built from.
``canonical_call_edges`` returns the CALL edges a consumer should use: the IR's, unless using them would be unsafe, in which
case the legacy edges are kept and the reason is reported.  Fail-closed rules, all deterministic:

* a unit without source text, or a program the IR does not contain, means the IR cannot speak for the application:
  legacy edges, reason ``IR_INCOMPLETE``;
* the IR is the source, the legacy edges are the cross-check: if the two disagree as multisets of
  ``(source, target, resolution, call_type)`` the legacy edges are kept and the reason is ``IR_DIVERGES_FROM_DISCOVERY`` (a
  consumer surfaces it as an unsupported finding; nothing is silently preferred).

Nothing here parses source itself: the facts come from the Layer 5 builder, which uses the one parser.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from engine.application_ir.legacy import call_edges, copybook_references, file_dependencies
from engine.application_ir.model import ApplicationIR
from engine.application_ir.project import project
from engine.semantic_facts.build import build_semantic_facts
from engine.transformation.copybook_resolver import LibraryOrders
from engine.transformation.ir import CobolApplication, DependencyEdge, normalize_cobol_name


@dataclass(frozen=True)
class CallEdgeSource:
    edges: tuple[DependencyEdge, ...]
    source: str          # "ir" | "discovery"
    reason: str          # "" when the IR was used, else IR_INCOMPLETE | IR_DIVERGES_FROM_DISCOVERY | IR_NOT_SUPPLIED
    detail: str = ""


def ir_for_application(application: CobolApplication, source_root: "str | Path | None" = None,
                       orders: LibraryOrders = ()) -> ApplicationIR | None:
    """The IR of the texts ``application`` was discovered from, or ``None`` when any unit has no source text.

    ``source_root`` (the tree it was discovered from) and ``orders`` (the library orders discovery applied) let the facts
    builder resolve every COPY statement through the one copybook resolver; without a root the COPY relationships are stated
    but unresolved, and the COPY comparison below declines to speak (``IR_INCOMPLETE``)."""
    texts: dict[str, str] = {}
    for unit in getattr(application, "programs", ()) or ():
        text, path = getattr(unit, "source_text", ""), getattr(unit, "source_path", "")
        if not isinstance(text, str) or not text or not isinstance(path, str) or not path:
            return None             # a unit that cannot show its source: the IR cannot speak for the application
        texts[path.replace("\\", "/")] = text     # one spelling of a path (discovery's COPY locations are POSIX)
    if not texts:
        return None
    return project(build_semantic_facts(texts, copy_root=source_root, library_orders=orders).as_dict())


def _key(edge: DependencyEdge) -> tuple[str, str, str, str]:
    return (normalize_cobol_name(edge.source), normalize_cobol_name(edge.target), edge.resolution, edge.call_type)


def _in_discovery_order(derived: tuple[DependencyEdge, ...], legacy: tuple[DependencyEdge, ...]) -> tuple[DependencyEdge, ...]:
    """``derived`` in the order discovery lists the same edges, so a consumer that reports per edge keeps its order.  The two
    are equal as multisets here (checked by the caller); ties keep the IR's own (span) order."""
    rank: dict[tuple[str, str, str, str], list[int]] = {}
    for index, edge in enumerate(legacy):
        rank.setdefault(_key(edge), []).append(index)
    taken: dict[tuple[str, str, str, str], int] = {}
    placed = []
    for edge in derived:
        key = _key(edge)
        used = taken.get(key, 0)
        taken[key] = used + 1
        placed.append((rank[key][used], edge))
    return tuple(edge for _rank, edge in sorted(placed, key=lambda pair: pair[0]))


def canonical_call_edges(application: CobolApplication, ir: ApplicationIR | None) -> CallEdgeSource:
    legacy = tuple(e for e in application.edges if e.edge_type == "CALL")
    if ir is None:
        return CallEdgeSource(legacy, "discovery", "IR_NOT_SUPPLIED")
    known = {normalize_cobol_name(p.name) for p in ir.programs}
    missing = sorted(u.program_id for u in application.programs if normalize_cobol_name(u.program_id) not in known)
    if missing:
        return CallEdgeSource(legacy, "discovery", "IR_INCOMPLETE", ",".join(missing))
    derived = call_edges(ir)
    if Counter(map(_key, derived)) != Counter(map(_key, legacy)):
        return CallEdgeSource(legacy, "discovery", "IR_DIVERGES_FROM_DISCOVERY",
                              f"ir={len(derived)} discovery={len(legacy)}")
    return CallEdgeSource(_in_discovery_order(derived, legacy), "ir", "")


def with_canonical_call_edges(application: CobolApplication, resolved: CallEdgeSource) -> CobolApplication:
    """``application`` with its CALL edges replaced by ``resolved.edges`` (other edge types untouched, order kept)."""
    others = tuple(e for e in application.edges if e.edge_type != "CALL")
    return dataclasses.replace(application, edges=others + resolved.edges)


# ----- entry points (M2) ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class EntrySource:
    by_program: tuple[tuple[str, tuple[str, ...]], ...]    # (program_id, entry points) for every unit, discovery's spelling
    source: str          # "ir" when the IR confirmed discovery's entry points for every unit, else "discovery"
    reason: str          # "" | IR_NOT_SUPPLIED | IR_INCOMPLETE | IR_DIVERGES_FROM_DISCOVERY
    detail: str = ""


def canonical_entry_points(application: CobolApplication, ir: ApplicationIR | None) -> EntrySource:
    """Entry points per unit, *verified* against the IR's ``entry`` declarations.

    The IR names an entry in upper case; discovery keeps the spelling it read.  The value a consumer receives is discovery's
    spelling (existing behaviour, generated names depend on it) and it is returned only after the IR confirms the same set of
    names for every unit: any difference keeps discovery's tuple and is reported as ``IR_DIVERGES_FROM_DISCOVERY``.
    """
    legacy = tuple((u.program_id, tuple(u.entry_points)) for u in application.programs)
    if ir is None:
        return EntrySource(legacy, "discovery", "IR_NOT_SUPPLIED")
    by_name = {normalize_cobol_name(p.name): p for p in ir.programs}
    names = {d.decl_id: d.name for d in ir.declarations if d.kind == "entry"}
    differing = []
    for unit in application.programs:
        program = by_name.get(normalize_cobol_name(unit.program_id))
        if program is None:
            return EntrySource(legacy, "discovery", "IR_INCOMPLETE", unit.program_id)
        confirmed = sorted(names[e] for e in program.entries)
        if confirmed != sorted(normalize_cobol_name(e.strip("'\"")) for e in unit.entry_points):
            differing.append(unit.program_id)
    if differing:
        return EntrySource(legacy, "discovery", "IR_DIVERGES_FROM_DISCOVERY", ",".join(sorted(differing)))
    return EntrySource(legacy, "ir", "")


def with_canonical_entry_points(application: CobolApplication, resolved: EntrySource) -> CobolApplication:
    """``application`` carrying ``resolved``'s entry points (identical values; the point is that they are IR-verified)."""
    mapping = dict(resolved.by_program)
    units = tuple(dataclasses.replace(u, entry_points=mapping.get(u.program_id, u.entry_points)) for u in application.programs)
    return dataclasses.replace(application, programs=units)


@dataclass(frozen=True)
class CanonicalApplication:
    """The application after the IR has been consulted, and what the consultation found."""

    application: CobolApplication
    checks: tuple[tuple[str, str, str, str], ...]     # (what, source, reason, detail) per relationship kind

    @property
    def divergences(self) -> tuple[str, ...]:
        """Relationship kinds on which the IR and discovery disagree (the consumer reports them UNSUPPORTED)."""
        return tuple(f"{what} ({detail})" for what, _source, reason, detail in self.checks
                     if reason == "IR_DIVERGES_FROM_DISCOVERY")


def _unit_check(application: CobolApplication, ir: ApplicationIR | None, what: str, attr: str,
                derived: dict[str, tuple], key) -> tuple[str, str, str, str]:
    """Compare, unit by unit, discovery's ``attr`` with the IR-derived values (as multisets of ``key``)."""
    if ir is None:
        return what, "discovery", "IR_NOT_SUPPLIED", ""
    known = {normalize_cobol_name(p.name) for p in ir.programs}
    missing = sorted(u.program_id for u in application.programs if normalize_cobol_name(u.program_id) not in known)
    if missing:
        return what, "discovery", "IR_INCOMPLETE", ",".join(missing)
    differing: list[str] = []
    superset: list[str] = []
    for u in application.programs:
        old, new = Counter(map(key, getattr(u, attr))), Counter(map(key, derived.get(u.source_path.replace("\\", "/"), ())))
        if old == new:
            continue
        # discovery found MORE than the IR (its text scan also reads words inside EXEC CICS blocks, for example): keeping the
        # larger set is the fail-closed direction and is not a disagreement; anything the IR has that discovery lacks, or any
        # different value, is
        (superset if not (new - old) and (old - new) else differing).append(u.program_id)
    if differing:
        return what, "discovery", "IR_DIVERGES_FROM_DISCOVERY", ",".join(sorted(differing))
    if superset:
        return what, "discovery", "DISCOVERY_SUPERSET", ",".join(sorted(superset))
    return what, "ir", "", ""


def _copy_key(ref) -> tuple[str, str, str, str]:
    return (ref.copybook_name.upper(), ref.location, ref.resolution, ref.resolved_path)


def _file_key(dep) -> tuple[str, str, str, str]:
    return (dep.operation, dep.file_name.upper(), dep.mode.upper(), dep.ownership_note)


def canonicalize(application: CobolApplication, ir: ApplicationIR | None,
                 source_root: "str | Path | None" = None) -> CanonicalApplication:
    """Consult the IR for every application-level relationship consumers read.

    CALL edges come from the IR (discovery is the cross-check).  Entry points, COPY references and FILE dependencies are
    *verified* against the IR: the values consumers receive are discovery's (their spelling and ownership notes are existing
    behaviour) and are delivered with the IR's confirmation recorded in ``checks``; any disagreement keeps discovery's values
    and is a divergence.  COPY is compared only when the IR was built with the tree's root (it resolves the COPY statements
    through the one resolver); without it the check declines (``IR_INCOMPLETE``).
    """
    calls = canonical_call_edges(application, ir)
    entries = canonical_entry_points(application, ir)
    result = with_canonical_entry_points(with_canonical_call_edges(application, calls), entries)
    # the IR resolved its COPY sites only if it was built with the tree's root; a site it left ``unsupported`` cannot be compared
    copy_resolved = (ir is not None and source_root is not None
                     and not any(e.kind == "copy-site" and e.resolution.state == "unsupported" for e in ir.edges))
    copies = (_unit_check(application, ir, "COPY references", "copybooks",
                          copybook_references(ir, str(source_root)), _copy_key)
              if copy_resolved and ir is not None else ("COPY references", "discovery", "IR_INCOMPLETE", "no source root"))
    files = _unit_check(application, ir, "FILE dependencies", "file_dependencies",
                        file_dependencies(ir) if ir is not None else {}, _file_key)
    checks = (("CALL edges", calls.source, calls.reason, calls.detail),
              ("entry points", entries.source, entries.reason, entries.detail), copies, files)
    return CanonicalApplication(result, checks)


def canonical_application(application: CobolApplication, ir: ApplicationIR | None,
                          source_root: "str | Path | None" = None) -> CobolApplication:
    """``application`` with its relationships taken from the IR where it can speak (identical values otherwise)."""
    if ir is None:
        return application
    return canonicalize(application, ir, source_root).application
