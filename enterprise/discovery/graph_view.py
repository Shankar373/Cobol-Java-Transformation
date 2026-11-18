"""The estate view of the discovery graph: the one adapter between ``enterprise.discovery`` and ``engine.estate``.

Discovery is the single producer of the structural graph (programs, copybooks, jobs, steps, datasets, tables, calls,
COPY, DD bindings).  ``engine.estate.model`` keeps its own small ``Node``/``Edge``/``Estate`` shapes (the decomposition
planner and the API consume them), and this module fills them **only from a graph document**; the engine adds one
thing, the ``proof_state`` (PROVEN / PARTIAL / BLOCKED / UNPROVEN) with a sentence of evidence, decided here from the
graph's own resolution and nothing else.  No source text is read in :func:`estate_from_graph`.

Proof-state rules (the same vocabulary the engine always used, now derived from graph facts):

* ``copies`` / ``calls`` resolved to an artefact in the upload -> PROVEN; unresolved or ambiguous -> BLOCKED (the
  target would be an external node, never dropped); resolved only against the platform (``external``) or through a
  dynamic target -> UNPROVEN / PARTIAL, never promoted;
* ``contains`` job -> step -> PROVEN (JCL structure); ``executes`` a program in the upload -> PROVEN, a native utility
  (IEFBR14, IEBGENER, IDCAMS) -> PARTIAL, anything else -> BLOCKED; a step that runs an unexpanded procedure -> UNPROVEN;
* ``uses-dataset`` from a step -> PARTIAL (catalogued from JCL); a program's DD binding -> PROVEN when the graph bound
  the ddname to a step's DD, BLOCKED when it did not, UNPROVEN when the program names its file itself;
* DB2 / MQ / IMS / CICS references -> a state supplied by the caller (``subsystem_states``, from the ledger) or, with
  none, BLOCKED for MQ / IMS / CICS (no product lane) and UNPROVEN for DB2 (seen, not classified).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from engine.estate.model import (
    BLOCKED, PARTIAL, PROOF_STATES, PROVEN, SIMULATORS, UNPROVEN, UTILITIES, Edge, Estate, Node,
)

from .classify import classify
from .discover import scan_file
from .findings import FileScan, ScanProblem
from .graph import DependencyGraph
from .hashing import sha256_bytes
from .inventory import FileRecord
from .limits import DEFAULT_LIMITS
from .resolve import build_graph
from .textio import decode_source

__all__ = ["estate_from_graph", "graph_from_directory", "estate_from_directory", "SubsystemKey"]

#: ``(program, estate node kind, bare name)`` -> ``(proof_state, reason)``; the optional ledger overlay.
SubsystemKey = tuple[str, str, str]

_GDG_RELATIVE_MEMBER = re.compile(r"^(?:\+\d+|-\d+|0)$")
_DB2_RELATIONS = frozenset({"accesses-table", "sql-reads", "sql-writes", "uses-db2"})
_MQ_RELATIONS = frozenset({"uses-mq", "uses-queue", "mq-put", "mq-get"})
_IMS_RELATIONS = frozenset({"uses-ims", "ims-call"})
_CICS_RELATIONS = frozenset({"cics-link", "cics-xctl", "cics-load", "cics-op", "uses-cics-file", "uses-map",
                             "starts-transaction"})
_BINDING_RELATIONS = frozenset({"uses-dataset", "assigns-file", "reads-file", "writes-file", "rewrites-file"})
_DATASET_KINDS = frozenset({"dataset", "vsam-cluster", "sysout", "dummy", "instream", "uss-path"})
_SUBSYSTEM_KINDS = {"table": ("DB2_TABLE", "USES_DB2"), "mq-queue": ("MQ_QUEUE", "USES_MQ"),
                    "ims-segment": ("IMS_SEGMENT", "USES_IMS"), "ims-interface": ("IMS_SEGMENT", "USES_IMS"),
                    "ims-psb": ("IMS_SEGMENT", "USES_IMS"), "cics-file": ("CICS_RESOURCE", "USES_CICS"),
                    "cics-queue": ("CICS_RESOURCE", "USES_CICS"), "transaction": ("CICS_RESOURCE", "USES_CICS"),
                    "bms-mapset": ("CICS_RESOURCE", "USES_CICS"), "bms-map": ("CICS_RESOURCE", "USES_CICS")}
_DEFAULT_SUBSYSTEM_STATE = {"DB2_TABLE": UNPROVEN, "MQ_QUEUE": BLOCKED, "IMS_SEGMENT": BLOCKED,
                            "CICS_RESOURCE": BLOCKED}


def _name(node_id: str) -> str:
    return node_id.split(":", 1)[1] if ":" in node_id else node_id


def _kind(node_id: str) -> str:
    return node_id.split(":", 1)[0]


class _View:
    """Accumulates estate nodes/edges; one (source, target, relation) keeps its strongest proof state, deterministically."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}

    def node(self, kind: str, name: str, *, external: bool = False) -> str:
        node_id = f"{kind}:{name}"
        self.nodes.setdefault(node_id, Node(node_id, kind, name, external))
        return node_id

    def edge(self, source: str, target: str, relation: str, state: str, evidence: str) -> None:
        key = (source, target, relation)
        existing = self.edges.get(key)
        rank = PROOF_STATES.index(state)
        # strongest state wins; on a tie the smaller evidence text does, so the result never depends on edge order
        if existing is None or (rank, evidence) < (PROOF_STATES.index(existing.proof_state), existing.evidence):
            self.edges[key] = Edge(source, target, relation, state, evidence)


def _edge_text(edge: Mapping[str, Any]) -> str:
    return f"{edge.get('file', '')}:{edge.get('line', '')}"


def _program_target(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], dst: str, edge: Mapping[str, Any],
                    *, step: bool = False) -> tuple[str, str, str]:
    """``(estate target id, proof state, evidence)`` for something a program calls or a job step runs."""
    target, state, evidence = _classify_target(view, graph_nodes, dst, edge)
    if step:
        evidence = {"static call to a program in the upload": "step runs a program in the upload",
                    "called program is not in the upload": "step runs a program that is not in the upload",
                    }.get(evidence, evidence)
    return target, state, evidence


def _classify_target(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], dst: str, edge: Mapping[str, Any],
                     ) -> tuple[str, str, str]:
    kind, name = _kind(dst), _name(dst).upper()
    resolution = str(edge.get("resolution", "resolved"))
    in_upload = graph_nodes.get(dst, {}).get("origin") == "input"
    if kind == "dynamic":
        return view.node("EXTERNAL_PROGRAM", name, external=True), UNPROVEN, \
            "dynamic CALL: the target is a run-time value the graph could not resolve"
    if kind == "utility":
        if name in UTILITIES:
            return view.node("UTILITY", name), PARTIAL, "native utility emulation from documented behaviour; no IBM/JES oracle"
        return view.node("EXTERNAL_PROGRAM", name, external=True), BLOCKED, "step runs a program that is not in the upload"
    if in_upload and resolution in ("resolved", "ambiguous") and kind in ("program", "load-module"):
        if resolution == "ambiguous":
            return view.node("PROGRAM", name), BLOCKED, "ambiguous: more than one program carries this name"
        if edge.get("dynamic"):
            return view.node("PROGRAM", name), PARTIAL, \
                "dynamic CALL followed through a VALUE/MOVE literal to a program in the upload"
        return view.node("PROGRAM", name), PROVEN, "static call to a program in the upload"
    if resolution == "external":
        return view.node("EXTERNAL_PROGRAM", name, external=True), UNPROVEN, \
            "called program is provided by the platform, not by the upload"
    return view.node("EXTERNAL_PROGRAM", name, external=True), BLOCKED, "called program is not in the upload"


def _copybook_owner(graph_nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """``file:<path>`` -> ``copybook:<NAME>``: a copybook's own COPY statements are recorded against its file node."""
    by_path = {str(n.get("path")): nid for nid, n in graph_nodes.items()
               if _kind(nid) == "copybook" and n.get("origin") == "input" and n.get("path")}
    return {nid: by_path[str(n["path"])] for nid, n in graph_nodes.items()
            if _kind(nid) == "file" and str(n.get("path")) in by_path}


def _copybook(view: _View, edge: Mapping[str, Any], owners: Mapping[str, str]) -> None:
    origin = owners.get(str(edge["from"]), str(edge["from"]))
    src_kind = _kind(origin)
    if src_kind not in ("program", "copybook"):
        return
    source = view.node("PROGRAM" if src_kind == "program" else "COPYBOOK", _name(origin).upper())
    target = view.node("COPYBOOK", _name(edge["to"]).upper())
    resolution = str(edge.get("resolution", "resolved"))
    if resolution == "resolved":
        view.edge(source, target, "INCLUDES", PROVEN, "copybook is in the upload and resolved")
    elif resolution == "external":
        view.edge(source, target, "INCLUDES", UNPROVEN, "copybook is provided by the platform, not by the upload")
    elif resolution == "ambiguous":
        candidates = ", ".join(str(c) for c in edge.get("candidates", ()))
        view.edge(source, target, "INCLUDES", BLOCKED, f"ambiguous: {candidates}" if candidates else "ambiguous")
    else:
        view.edge(source, target, "INCLUDES", BLOCKED, "copybook is not in the upload")


def _job_steps(view: _View, edges: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """RUNS edges for every job step; returns ``label -> contains-edge`` so EXECUTES can find unexpanded procedures."""
    steps: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if edge["relation"] != "contains" or _kind(edge["from"]) != "job" or _kind(edge["to"]) != "step":
            continue
        job, step = _name(edge["from"]).upper(), _name(edge["to"]).rsplit("/", 1)[-1].upper()
        job_id = view.node("JOB", job)
        step_id = view.node("STEP", f"{job}.{step}")
        view.edge(job_id, step_id, "RUNS", PROVEN, "step belongs to the job (JCL structure)")
        steps[step_id] = dict(edge)
    return steps


def _executes(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]],
              steps: Mapping[str, Mapping[str, Any]]) -> None:
    executed: set[str] = set()
    for edge in edges:
        if edge["relation"] != "executes" or _kind(edge["from"]) != "job":
            continue
        step = str(dict(edge.get("detail", {})).get("step", "")).upper()
        if not step:
            continue
        step_id = view.node("STEP", f"{_name(edge['from']).upper()}.{step}")
        executed.add(step_id)
        if _kind(edge["to"]) == "proc":
            _executes_proc(view, graph_nodes, edges, step_id, edge)
            continue
        target, state, evidence = _program_target(view, graph_nodes, edge["to"], edge, step=True)
        view.edge(step_id, target, "EXECUTES", state, evidence)
    for step_id, contained in steps.items():
        info = dict(contained.get("detail", {}))
        if step_id not in executed and info.get("proc") and not info.get("program"):
            view.edge(step_id, view.node("EXTERNAL_PROGRAM", str(info["proc"]).upper(), external=True), "EXECUTES",
                      UNPROVEN, "step runs a procedure that was not expanded")


def _executes_proc(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]],
                   step_id: str, edge: Mapping[str, Any]) -> None:
    """A step that runs a procedure: follow the procedure's own ``executes`` edges when the graph expanded it."""
    proc = str(edge["to"])
    name = _name(proc).upper()
    inner = [e for e in edges if e["relation"] == "executes" and e["from"] == proc]
    if edge.get("resolution") != "resolved" or not inner:
        reason = ("procedure is not in the upload" if edge.get("resolution") != "resolved"
                  else "procedure is in the upload but runs no program the graph could read")
        view.edge(step_id, view.node("EXTERNAL_PROGRAM", name, external=True), "EXECUTES",
                  BLOCKED if edge.get("resolution") != "resolved" else UNPROVEN, f"step runs a procedure: {reason}")
        return
    for body in inner:
        target, state, evidence = _program_target(view, graph_nodes, body["to"], body, step=True)
        view.edge(step_id, target, "EXECUTES", state, f"via procedure {name}: {evidence}")


def _datasets(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]]) -> None:
    uses: dict[str, list[tuple[int, str, str]]] = {}  # dsn id -> [(line, step id, disposition)]
    for edge in edges:
        relation, src, dst = edge["relation"], edge["from"], edge["to"]
        info = dict(edge.get("detail", {}))
        if (relation in ("uses-dataset", "creates-dataset") and _kind(src) == "job"
                and _kind(dst) in _DATASET_KINDS and info.get("step")):
            step_id = view.node("STEP", f"{_name(src).upper()}.{str(info['step']).upper()}")
            member = str(info.get("member", ""))
            relative = info.get("generation") == "gdg" and bool(_GDG_RELATIVE_MEMBER.match(member))
            dsn = f"{_name(dst)}({member})" if relative else _name(dst)
            note = f"DD {info.get('dd', '?')} disposition {info.get('disp') or '?'}"
            ds_id = view.node("DATASET", dsn)
            if relative:
                view.edge(step_id, ds_id, "USES_DATASET", PARTIAL, note + "; relative generation not resolved to a generation")
            else:
                view.edge(step_id, ds_id, "USES_DATASET", PARTIAL, note + "; catalogued from JCL, runs are simulator-grade")
            uses.setdefault(ds_id, []).append((int(edge.get("line", 0)), step_id, str(info.get("disp", "")).upper()))
        elif relation in _BINDING_RELATIONS and _kind(src) == "program":
            _binding(view, edge)
    for ds_id, rows in uses.items():
        producer = next(((line, step) for line, step, disp in sorted(rows) if disp.startswith(("NEW", "MOD"))), None)
        if producer is None:
            continue
        for line, step, _ in sorted(rows):
            if step != producer[1] and line > producer[0] and step.split(".")[0] == producer[1].split(".")[0]:
                view.edge(producer[1], step, "FLOWS_TO", PARTIAL,
                          f"dataset {_name(ds_id)} is produced by one step and consumed by a later one")


def _binding(view: _View, edge: Mapping[str, Any]) -> None:
    program = view.node("PROGRAM", _name(edge["from"]).upper())
    dst, resolution = str(edge["to"]), str(edge.get("resolution", "resolved"))
    kind, name = _kind(dst), _name(dst)
    info = dict(edge.get("detail", {}))
    ddname = info.get("ddname") or name
    if resolution == "resolved" and kind in _DATASET_KINDS:
        view.edge(program, view.node("DATASET", name), "BINDS", PROVEN,
                  f"ddname {ddname} bound to the step's DD ({_edge_text(edge)})")
    elif kind == "dd":
        view.edge(program, view.node("DATASET", f"<unbound:{name}>", external=True), "BINDS", BLOCKED,
                  f"no DD statement named {name} in the step that runs the program")
    elif kind == "external-file":
        view.edge(program, view.node("DATASET", f"<path:{name}>", external=True), "BINDS", UNPROVEN,
                  "the program names its file itself")
    elif kind == "dynamic":
        view.edge(program, view.node("DATASET", f"<dynamic:{name}>", external=True), "BINDS", UNPROVEN,
                  "the DD target is a run-time value")


def _subsystems(view: _View, graph_nodes: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]],
                states: Mapping[SubsystemKey, tuple[str, str]]) -> None:
    for edge in edges:
        relation, src, dst = edge["relation"], edge["from"], edge["to"]
        if _kind(src) != "program":
            continue
        spec = _SUBSYSTEM_KINDS.get(_kind(dst))
        if spec is None or relation not in (_DB2_RELATIONS | _MQ_RELATIONS | _IMS_RELATIONS | _CICS_RELATIONS):
            continue
        node_kind, estate_relation = spec
        program = _name(src).upper()
        name = _name(dst).upper()
        state, reason = states.get((program, node_kind, name.split("=")[-1]),
                                   (_DEFAULT_SUBSYSTEM_STATE[node_kind],
                                    f"referenced in {_edge_text(edge)}; no product lane has classified it"))
        if node_kind in SIMULATORS:
            reason = (f"{reason} A simulator ({SIMULATORS[node_kind]}, SIMULATOR_VERIFIED library) specifies this "
                      "subsystem; generated code does not call it and no IBM runtime was run.").strip()
        view.edge(view.node("PROGRAM", program), view.node(node_kind, name), estate_relation,
                  state if state in PROOF_STATES else UNPROVEN, reason)


def estate_from_graph(document: "Mapping[str, Any] | DependencyGraph",
                      *, subsystem_states: Mapping[SubsystemKey, tuple[str, str]] | None = None) -> Estate:
    """The estate (engine shapes + proof states) of a discovery graph document.

    Pure: reads only ``document`` (a ``DependencyGraph.to_dict()`` result or a ``DependencyGraph``) and the optional
    ``subsystem_states`` overlay; the output is sorted exactly like ``engine.estate.model.build_estate`` so the two
    are interchangeable for the decomposition planner.
    """
    doc = document.to_dict() if isinstance(document, DependencyGraph) else document
    graph_nodes = {str(n["id"]): n for n in doc.get("nodes", ())}
    edges = [dict(e) for e in doc.get("edges", ())]
    view = _View()
    for node_id, node in graph_nodes.items():
        kind, name = _kind(node_id), _name(node_id).upper()
        if node.get("origin") != "input":
            continue
        if kind == "program":
            view.node("PROGRAM", name)
        elif kind == "copybook":
            view.node("COPYBOOK", name)
        elif kind == "job":
            view.node("JOB", name)
    owners = _copybook_owner(graph_nodes)
    for edge in edges:
        if edge["relation"] == "copies":
            _copybook(view, edge, owners)
        elif edge["relation"] == "calls" and _kind(edge["from"]) == "program":
            target, state, evidence = _program_target(view, graph_nodes, edge["to"], edge)
            view.edge(view.node("PROGRAM", _name(edge["from"]).upper()), target, "CALLS", state, evidence)
    steps = _job_steps(view, edges)
    _executes(view, graph_nodes, edges, steps)
    _datasets(view, graph_nodes, edges)
    _subsystems(view, graph_nodes, edges, subsystem_states or {})
    return Estate(
        nodes=sorted(view.nodes.values(), key=lambda n: (n.kind, n.name)),
        edges=sorted(view.edges.values(), key=lambda e: (e.source, e.relation, e.target)),
    )


def _read_records(root: Path) -> tuple[list[FileRecord], list[ScanProblem]]:
    """Scan every readable file under ``root`` with the discovery scanners (no checkpoint, nothing written)."""
    records: list[FileRecord] = []
    problems: list[ScanProblem] = []
    base = root.resolve()
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        rel = relative.as_posix()
        try:
            if path.stat().st_size > DEFAULT_LIMITS.max_source_bytes:
                problems.append(ScanProblem(rel, 1, "FILE_TOO_LARGE", "larger than max_source_bytes; not scanned"))
                continue
            data = path.read_bytes()
        except OSError as exc:
            problems.append(ScanProblem(rel, 1, "FILE_UNREADABLE", type(exc).__name__))
            continue
        decoded = decode_source(data)
        guess = classify(rel, None if decoded.binary else decoded.text, binary=decoded.binary)
        record = FileRecord(path=rel, sha256=sha256_bytes(data), size=len(data))
        record.cls, record.evidence = guess.cls, guess.evidence
        if not decoded.binary:
            try:
                scan: FileScan | None = scan_file(rel, guess.cls, decoded.text)
            except Exception as exc:  # noqa: BLE001 - a scanner defect is a finding, never a silent skip
                scan = FileScan(path=rel, problems=[ScanProblem(rel, 1, "SCANNER_FAILED",
                                                                f"{type(exc).__name__} while scanning as {guess.cls}")])
            if scan is not None:
                record.scan, record.source_format, record.line_count = scan, scan.source_format, scan.line_count
                problems.extend(scan.problems)
        records.append(record)
    return records, problems


def graph_from_directory(root: "Path | str") -> tuple[dict[str, Any], list[ScanProblem]]:
    """The discovery graph document of a directory plus the scanner problems met on the way."""
    records, problems = _read_records(Path(root))
    return build_graph(records).graph.to_dict(), sorted(problems)


def estate_from_directory(root: "Path | str",
                          *, subsystem_states: Mapping[SubsystemKey, tuple[str, str]] | None = None,
                          ) -> tuple[Estate, dict[str, Any], list[ScanProblem]]:
    """``(estate, graph document, scanner problems)`` for a directory - discovery's own pipeline, then the view."""
    document, problems = graph_from_directory(root)
    return estate_from_graph(document, subsystem_states=subsystem_states), document, problems
