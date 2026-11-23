"""Files, VSAM, SQL and JCL relationships read from the discovery graph (Layer 5, phase P6).

The graph is the one authority for what a ``SELECT`` is bound to outside the program (logical file -> DD -> dataset ->
VSAM cluster), for which tables a program touches, and for JCL steps and DDs.  This module is the read-only join: it
takes a graph *document* (the dict ``graph_from_directory`` returns, ``graph_id`` in its header), never scans source,
never writes the graph and never invents an edge.  Layer 5 adds what the graph lacks: the program-side declaration
(from the symbol table), the host-variable resolution (P3), and provenance (the graph edge's file, line and column plus
the JCL line that bound the DD).

Facts:

* ``file-binding`` - one per FD of each program (sort descriptions excluded): ``resolved`` to the one dataset or literal
  path it is bound to, ``ambiguous`` when several steps bind different datasets (candidates sorted), ``unresolved`` with the
  graph's own reason (``missing-dd``, ``unbound-ddname``) or ``missing-logical-file`` when the graph has no binding at all,
  ``unsupported(GDG_GENERATION_NOT_RESOLVED)`` for a relative generation (``(+1)``), and the organisation / VSAM-candidate /
  step / JCL provenance as attributes.
* ``sql-table`` - one per table edge the graph has for the program, with the graph's resolution.
* ``jcl-dd-binding`` - one per JCL DD edge (job -> dataset or sysout), with step and DD name.

``proposed_edges`` is a *proposal* (design 6.2, decision D6): the nested ``performs`` / ``goes-to`` / ``reads-item`` /
``writes-item`` relations Layer 5 can state with an exact position.  It does not touch the graph, so ``graph_id`` is
unchanged; an edge needs file, line and column, and a fact without an exact span is counted, not emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from engine.semantic_facts.document import Fact, ProgramFacts
from engine.semantic_facts.references import Resolution, Resolver
from engine.semantic_facts.span import Span
from engine.semantic_facts.symbols import SymbolTable

_FILE_RELATIONS = ("uses-dataset", "assigns-file")
_TABLE_RELATIONS = ("accesses-table", "sql-reads", "sql-writes", "uses-db2")
_HOSTVAR_RELATION = "sql-binds-hostvar"
_GENERATION_MEMBER = ("+", "-")


class GraphView:
    """Read-only indexes over one graph document."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document
        self.graph_id = str((document.get("header") or {}).get("graph_id", ""))
        self.nodes = {str(n["id"]): n for n in document.get("nodes", ())}
        self.edges: tuple[Mapping[str, Any], ...] = tuple(document.get("edges", ()))
        self._by_program: dict[str, list[Mapping[str, Any]]] = {}
        self._job_dd: dict[tuple[str, str], Mapping[str, Any]] = {}
        for edge in self.edges:
            source = str(edge.get("from", ""))
            if source.startswith("program:"):
                self._by_program.setdefault(source.partition(":")[2].upper(), []).append(edge)
            detail = edge.get("detail") or {}
            if source.startswith("job:") and detail.get("dd"):
                self._job_dd[(str(edge.get("file", "")), str(edge.get("line", "")))] = edge

    def has_program(self, name: str) -> bool:
        return f"program:{name.upper()}" in self.nodes or name.upper() in self._by_program

    def file_edges(self, program: str, logical_file: str) -> list[Mapping[str, Any]]:
        return [e for e in self._by_program.get(program.upper(), ())
                if e.get("relation") in _FILE_RELATIONS
                and str((e.get("detail") or {}).get("logical_file", "")).upper() == logical_file.upper()]

    def table_edges(self, program: str) -> list[Mapping[str, Any]]:
        return [e for e in self._by_program.get(program.upper(), ()) if e.get("relation") in _TABLE_RELATIONS]

    def generation_of(self, edge: Mapping[str, Any]) -> str:
        """The relative generation (``+1``, ``-1``, ``0``) of the JCL DD that bound this program edge ("" if none)."""
        detail = edge.get("detail") or {}
        job = self._job_dd.get((str(detail.get("jcl_file", "")), str(detail.get("jcl_line", ""))))
        member = str(((job or {}).get("detail") or {}).get("member", ""))
        return member if (job or {}).get("detail", {}).get("generation") == "gdg" else ""

    def hostvar_edges(self, program: str) -> list[Mapping[str, Any]]:
        return [e for e in self._by_program.get(program.upper(), ()) if e.get("relation") == _HOSTVAR_RELATION]

    def job_dd_edges(self) -> list[Mapping[str, Any]]:
        return sorted(self._job_dd.values(), key=lambda e: (str(e.get("file")), int(e.get("line", 0)), str(e.get("to"))))


def _edge_span(edge: Mapping[str, Any], file: str | None = None) -> Span | None:
    if not edge.get("file") or not edge.get("line"):
        return None
    return Span(file or str(edge["file"]), int(edge["line"]), int(edge.get("column") or 0), basis="token",
                exact=bool(edge.get("column")), note="" if edge.get("column") else "SPAN_COLUMN_NOT_IN_GRAPH")


def _provenance(edge: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    detail = edge.get("detail") or {}
    pairs = {
        "ddname": detail.get("ddname", ""), "dataset": str(edge.get("to", "")), "disp": detail.get("disp", ""),
        "job_step": detail.get("job_step", ""), "jcl_file": detail.get("jcl_file", ""),
        "jcl_line": detail.get("jcl_line", ""), "organization": detail.get("organization", ""),
        "vsam_candidate": detail.get("vsam_candidate", ""), "graph_edge_line": str(edge.get("line", "")),
    }
    return tuple(sorted((k, str(v)) for k, v in pairs.items() if str(v)))


@dataclass
class ExternalFacts:
    facts: dict[str, list[Fact]]
    unsupported: dict[str, list[tuple[str, str]]]
    programs: list[ProgramFacts]        # synthetic per-JCL-file holders for facts that belong to no COBOL file

    def add(self, file: str, fact: Fact) -> None:
        self.facts.setdefault(file, []).append(fact)
        if fact.resolution.state == "unsupported":
            self.unsupported.setdefault(file, []).append((fact.resolution.reason, fact.subject))


def _scope_program(symbols: SymbolTable) -> str:
    return symbols.scopes[0].scope_id.partition(":")[2].partition("@")[0] if symbols.scopes else ""


def build_external_facts(programs: Sequence[ProgramFacts], graph: GraphView) -> ExternalFacts:
    out = ExternalFacts({}, {}, [])
    for program in programs:
        if program.program is None or not program.symbols.scopes:
            continue
        name = _scope_program(program.symbols)
        for decl in program.symbols.declarations:
            if decl.kind == "file" and dict(decl.attributes).get("sort_file") != "true":
                out.add(program.file, _file_binding(program, decl.decl_id, decl.name,
                                                    dict(decl.attributes).get("assign_kind", ""), name, graph))
        for edge in graph.table_edges(name):
            out.add(program.file, _sql_table(program, name, edge))
        resolver = Resolver(program.symbols)
        for edge in graph.hostvar_edges(name):
            out.add(program.file, _sql_host_var(program, name, edge, resolver))
    holders: dict[str, list[Fact]] = {}
    for edge in graph.job_dd_edges():
        fact = _jcl_dd(edge)
        holders.setdefault(str(edge.get("file")), []).append(fact)
    for file, facts in sorted(holders.items()):
        out.programs.append(ProgramFacts(file, SymbolTable(file, (), ()), _empty_references(), tuple(facts), ()))
    return out


def _empty_references():
    from engine.semantic_facts.references import ReferenceTable

    return ReferenceTable((), (), ())


def _file_binding(program: ProgramFacts, decl_id: str, file_name: str, assign_kind: str, program_name: str,
                  graph: GraphView) -> Fact:
    edges = graph.file_edges(program_name, file_name)
    base = (("assign_kind", assign_kind), ("file", file_name), ("program", program_name))
    datasets = [e for e in edges if e.get("relation") == "uses-dataset"]
    generations = sorted({g for g in (graph.generation_of(e) for e in datasets) if g})
    if generations:
        return Fact("file-binding", decl_id, None,
                    Resolution("unsupported", reason="GDG_GENERATION_NOT_RESOLVED", rule="l5.file-binding"),
                    "l5.file-binding", tuple(sorted(base + (("generation", ",".join(generations)),)
                                                    + _provenance(datasets[0]))))
    if datasets:
        targets = sorted({str(e.get("to")) for e in datasets})
        provenance = _provenance(datasets[0]) if len(targets) == 1 else (("datasets", ",".join(targets)),)
        span = _edge_span(datasets[0], program.file) if len(targets) == 1 else None
        if len(targets) == 1:
            res = Resolution("resolved", (targets[0],), rule="l5.file-binding")
        else:
            res = Resolution("ambiguous", tuple(targets), confidence="heuristic", rule="l5.file-binding")
        kind = graph.nodes.get(targets[0], {}).get("kind", "")
        return Fact("file-binding", decl_id, span, res, "l5.file-binding",
                    tuple(sorted(base + provenance + ((("dataset_kind", str(kind)),) if kind else ()))))
    for edge in edges:
        if edge.get("relation") == "assigns-file":
            if edge.get("resolution") == "unresolved":
                reason = str(edge.get("reason") or "unbound-ddname")
                reason = reason if reason in ("missing-dd", "unbound-ddname") else "unbound-ddname"
                res = Resolution("unresolved", reason=reason, confidence="unresolved", rule="l5.file-binding")
            else:
                res = Resolution("resolved", (str(edge.get("to")),), rule="l5.file-binding")
            return Fact("file-binding", decl_id, _edge_span(edge, program.file), res, "l5.file-binding",
                        tuple(sorted(base + _provenance(edge))))
    return Fact("file-binding", decl_id, None,
                Resolution("unresolved", reason="missing-logical-file", confidence="unresolved", rule="l5.file-binding"),
                "l5.file-binding", base)


def _sql_table(program: ProgramFacts, program_name: str, edge: Mapping[str, Any]) -> Fact:
    target = str(edge.get("to"))
    if edge.get("resolution") == "unresolved":
        res = Resolution("unresolved", reason="external-table", confidence="unresolved", rule="l5.sql-table")
    else:
        res = Resolution("resolved", (target,), rule="l5.sql-table")
    subject = f"sql:{program_name}:{target}:{edge.get('relation')}:{edge.get('line')}"
    return Fact("sql-table", subject, _edge_span(edge, program.file), res, "l5.sql-table",
                tuple(sorted((("relation", str(edge.get("relation"))), ("table", target),
                              ("program", program_name), ("mode", str(edge.get("mode", "")))))))


def _sql_host_var(program: ProgramFacts, program_name: str, edge: Mapping[str, Any], resolver: Resolver) -> Fact:
    """A host variable of an EXEC SQL block, resolved against the program's own declarations.

    The graph names the variable (``data-item:PROG/NAME``) but cannot always find its declaration (it resolves by name
    inside one program scan); Layer 5 has the symbol table, so the fact carries *its* resolution and the graph's edge
    as provenance.
    """
    name = str(edge.get("to")).partition("/")[2]
    resolution, _decl = resolver.data(name, ())
    subject = f"sqlvar:{program_name}:{name}:{edge.get('line')}:{edge.get('column')}"
    return Fact("sql-host-var", subject, _edge_span(edge, program.file), resolution,
                resolution.rule or "l5.sql-host-var",
                tuple(sorted((("name", name), ("program", program_name), ("graph_resolution", str(edge.get("resolution"))),
                              ("graph_reason", str(edge.get("reason", "")))))))


def _jcl_dd(edge: Mapping[str, Any]) -> Fact:
    detail = edge.get("detail") or {}
    target = str(edge.get("to"))
    subject = f"jcl:{str(edge.get('from')).partition(':')[2]}/{detail.get('step', '')}/{detail.get('dd', '')}"
    res = Resolution("resolved", (target,), rule="l5.jcl-dd",
                     confidence="certain" if edge.get("resolution") == "resolved" else "derived")
    attributes = {"dd": detail.get("dd", ""), "disp": detail.get("disp", ""), "step": detail.get("step", ""),
                  "relation": str(edge.get("relation")), "resolution": str(edge.get("resolution")),
                  "generation": detail.get("generation", ""), "member": detail.get("member", "")}
    return Fact("jcl-dd-binding", subject, _edge_span(edge), res, "l5.jcl-dd",
                tuple(sorted((k, str(v)) for k, v in attributes.items() if str(v))))


def jcl_flavour_facts(jcl_sources: Mapping[str, str]) -> list[Fact]:
    """A ``refusal`` for every JCL text that is not z/OS JCL (VSE or unknown): never read as z/OS."""
    from enterprise.discovery.source_policy import jcl_flavour

    facts = []
    for path, text in sorted(jcl_sources.items()):
        flavour = jcl_flavour(text)
        if flavour != "ZOS":
            facts.append(Fact("refusal", f"jcl:{path}", None,
                              Resolution("unsupported", reason="JCL_FLAVOUR_UNSUPPORTED", rule="l5.diagnostic"),
                              "l5.diagnostic", (("flavour", flavour), ("path", path))))
    return facts


# ----- the proposal --------------------------------------------------------------------------------------------

_PROPOSED = {"perform": "performs", "goto": "goes-to", "read": "reads-item", "write": "writes-item",
             "modify": "writes-item"}


def proposed_edges(programs: Iterable[ProgramFacts], graph: GraphView | None = None) -> dict[str, Any]:
    """Edges Layer 5 could add to the graph with an exact position, and how many facts it could not place.

    ``edges``: ``{from, to, relation, file, line, column, mode, rule}`` where ``from`` is the paragraph node containing the
    statement and ``to`` the paragraph / data-item node of a resolved reference whose graph node is not collapsed.
    ``rule`` is ``l5-proposed``, which is not in ``graph.RESOLVER_RULES``: emitting these is decision D6, so nothing here
    can be turned into a graph ``Edge`` by accident.  ``already_in_graph`` counts proposals the graph already has.
    """
    edges: list[dict[str, Any]] = []
    unplaced = 0
    present = 0
    existing = {(str(e.get("from")), str(e.get("to")), str(e.get("relation"))) for e in (graph.edges if graph else ())}
    for program in sorted(programs, key=lambda p: p.file):
        if not program.symbols.scopes:
            continue
        scope = program.symbols.scopes[0].scope_id
        by_id = program.symbols.by_id()
        paragraph_of = {r.stmt_id: r.paragraph for r in program.references.statements}
        for ref in program.references.references:
            relation = _PROPOSED.get(ref.access)
            if relation is None or ref.resolution.state != "resolved" or ref.kind in ("file", "host-var"):
                continue
            decl = by_id.get(ref.resolution.candidates[0])
            if decl is None or not decl.graph_node_id or decl.graph_node_collapsed:
                continue
            paragraph = paragraph_of.get(ref.owner_stmt, "")
            if ref.span is None or not ref.span.exact or not paragraph:
                unplaced += 1
                continue
            source = f"paragraph:{scope.partition(':')[2].partition('@')[0]}/{paragraph}"
            edge = {"from": source, "to": decl.graph_node_id, "relation": relation, "file": ref.span.file,
                    "line": ref.span.line, "column": ref.span.column, "rule": "l5-proposed"}
            present += (source, decl.graph_node_id, relation) in existing
            edges.append(edge)
    edges.sort(key=lambda e: (e["file"], e["line"], e["column"], e["relation"], e["to"]))
    return {"edges": edges, "unplaced": unplaced, "already_in_graph": present}
