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

from engine.application_ir.legacy import call_edges
from engine.application_ir.model import ApplicationIR
from engine.application_ir.project import project
from engine.semantic_facts.build import build_semantic_facts
from engine.transformation.ir import CobolApplication, DependencyEdge, normalize_cobol_name


@dataclass(frozen=True)
class CallEdgeSource:
    edges: tuple[DependencyEdge, ...]
    source: str          # "ir" | "discovery"
    reason: str          # "" when the IR was used, else IR_INCOMPLETE | IR_DIVERGES_FROM_DISCOVERY | IR_NOT_SUPPLIED
    detail: str = ""


def ir_for_application(application: CobolApplication) -> ApplicationIR | None:
    """The IR of the texts ``application`` was discovered from, or ``None`` when any unit has no source text."""
    texts: dict[str, str] = {}
    for unit in getattr(application, "programs", ()) or ():
        text, path = getattr(unit, "source_text", ""), getattr(unit, "source_path", "")
        if not isinstance(text, str) or not text or not isinstance(path, str) or not path:
            return None             # a unit that cannot show its source: the IR cannot speak for the application
        texts[path] = text
    if not texts:
        return None
    return project(build_semantic_facts(texts).as_dict())


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
