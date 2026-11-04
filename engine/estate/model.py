"""Estate model: one dependency graph over the whole application, every edge with a proof state.

Nodes: programs, copybooks, JCL jobs and steps, datasets, DB2 tables, MQ queues, IMS segments and PCBs,
CICS resources.  Edges say how two nodes relate (``CALLS``, ``INCLUDES``, ``RUNS``, ``EXECUTES``,
``USES_DATASET``, ``BINDS``, ``FLOWS_TO``, ``USES_DB2``, ``USES_MQ``, ``USES_IMS``, ``USES_CICS``) and carry

* ``proof_state`` -- ``PROVEN`` (an oracle or an exhaustive structural check supports it), ``PARTIAL``
  (modelled or simulator-grade, not proven against the real system), ``BLOCKED`` (the target is missing
  or its subsystem has no product lane) or ``UNPROVEN`` (seen, not classified);
* ``evidence`` -- one sentence saying why, so a reader can challenge the state.

The model is a pure function of the discovery output (and the DB2/MQ/IMS/CICS ledger entries extracted
from the sources); it reads nothing else and invents no edge.  A reference whose target is not in the
upload is an edge to an *external* node, never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROVEN, PARTIAL, BLOCKED, UNPROVEN = "PROVEN", "PARTIAL", "BLOCKED", "UNPROVEN"
PROOF_STATES = (PROVEN, PARTIAL, BLOCKED, UNPROVEN)
NODE_KINDS = ("PROGRAM", "COPYBOOK", "JOB", "STEP", "DATASET", "DB2_TABLE", "MQ_QUEUE", "IMS_SEGMENT",
              "CICS_RESOURCE", "EXTERNAL_PROGRAM", "UTILITY")

#: Utilities the JCL launcher runs natively (roadmap unit 8); documented behaviour, no IBM/JES oracle.
UTILITIES = frozenset({"IEFBR14", "IEBGENER", "IDCAMS"})

_LEDGER_KINDS = {
    "DB2": ("DB2_TABLE", "USES_DB2"), "MQ": ("MQ_QUEUE", "USES_MQ"), "IMS": ("IMS_SEGMENT", "USES_IMS"),
    "CICS": ("CICS_RESOURCE", "USES_CICS"),
}


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    name: str
    external: bool = False


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    proof_state: str
    evidence: str


@dataclass
class Estate:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def summary(self) -> dict:
        by_kind: dict[str, int] = {}
        for node in self.nodes:
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
        by_state = {state: 0 for state in PROOF_STATES}
        by_relation: dict[str, int] = {}
        for edge in self.edges:
            by_state[edge.proof_state] += 1
            by_relation[edge.relation] = by_relation.get(edge.relation, 0) + 1
        total = len(self.edges)
        return {
            "node_count": len(self.nodes),
            "edge_count": total,
            "nodes_by_kind": dict(sorted(by_kind.items())),
            "edges_by_relation": dict(sorted(by_relation.items())),
            "edges_by_proof_state": by_state,
            # the share of edges an oracle or exhaustive structural check supports -- not a readiness score
            "proven_edge_percent": round(100 * by_state[PROVEN] / total, 1) if total else 0.0,
            "blocked_edges": [f"{e.source} -[{e.relation}]-> {e.target}" for e in self.edges
                              if e.proof_state == BLOCKED],
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
        }


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}

    def node(self, kind: str, name: str, *, external: bool = False) -> str:
        node_id = f"{kind}:{name}"
        self.nodes.setdefault(node_id, Node(node_id, kind, name, external))
        return node_id

    def edge(self, source: str, target: str, relation: str, state: str, evidence: str) -> None:
        # the first evidence wins; a later, stronger state for the same edge replaces a weaker one
        key = (source, target, relation)
        existing = self.edges.get(key)
        if existing is None or PROOF_STATES.index(state) < PROOF_STATES.index(existing.proof_state):
            self.edges[key] = Edge(source, target, relation, state, evidence)


def build_estate(discovery: dict, external: "dict[str, list[dict]] | None" = None) -> Estate:
    """Build the estate from ``DiscoveryResult.to_dict()`` and per-program ledger entries.

    ``external`` maps a program id to its DB2 / MQ / IMS / CICS ledger entries
    (``DependencyLedgerEntry.to_dict()``: ``dependency_id``, ``kind``, ``proof_state``, ``reason``).
    """
    b = _Builder()
    programs = {p["program_id"].upper(): p for p in discovery.get("cobol_programs", [])}
    copybooks = {c.upper() for c in discovery.get("copybooks", [])}

    for program in programs.values():
        pid = b.node("PROGRAM", program["program_id"].upper())
        for name in program.get("copybooks", []):
            cid = b.node("COPYBOOK", name.upper())
            if name.upper() in copybooks:
                b.edge(pid, cid, "INCLUDES", PROVEN, "copybook is in the upload and resolved")
            else:
                b.edge(pid, cid, "INCLUDES", BLOCKED, "copybook is not in the upload")
        for call in program.get("calls", []):
            target = (call.get("target") or "").strip()
            if not target:
                continue
            literal = target.upper()
            if literal in programs:
                b.edge(pid, b.node("PROGRAM", literal), "CALLS", PROVEN, "static call to a program in the upload")
            else:
                b.edge(pid, b.node("EXTERNAL_PROGRAM", literal, external=True), "CALLS", BLOCKED,
                       "called program is not in the upload")

    for job in discovery.get("jcl_jobs", []):
        jid = b.node("JOB", job["name"].upper())
        for step in job.get("steps", []):
            sid = b.node("STEP", f"{job['name'].upper()}.{step['name'].upper()}")
            b.edge(jid, sid, "RUNS", PROVEN, "step belongs to the job (JCL structure)")
            program = (step.get("program") or "").upper()
            if not program:
                b.edge(sid, b.node("EXTERNAL_PROGRAM", step.get("procedure") or "?", external=True), "EXECUTES",
                       UNPROVEN, "step runs a procedure that was not expanded")
            elif program in programs:
                b.edge(sid, b.node("PROGRAM", program), "EXECUTES", PROVEN, "step runs a program in the upload")
            elif program in UTILITIES:
                b.edge(sid, b.node("UTILITY", program), "EXECUTES", PARTIAL,
                       "native utility emulation from documented behaviour; no IBM/JES oracle")
            else:
                b.edge(sid, b.node("EXTERNAL_PROGRAM", program, external=True), "EXECUTES", BLOCKED,
                       "step runs a program that is not in the upload")

    for dataset in discovery.get("dataset_catalog", []):
        did = b.node("DATASET", dataset["dsn"])
        for use in dataset.get("uses", []):
            sid = b.node("STEP", f"{use['job'].upper()}.{use['step'].upper()}")
            relation = "USES_DATASET"
            note = f"DD {use['dd']} role {use.get('role', '?')}"
            if dataset.get("kind") == "GDG_RELATIVE":
                b.edge(sid, did, relation, PARTIAL, note + "; relative generation not resolved to a generation")
            else:
                b.edge(sid, did, relation, PARTIAL, note + "; catalogued from JCL, runs are simulator-grade")

    for binding in discovery.get("dd_bindings", []):
        status = binding.get("status")
        if not binding.get("program") or status in ("UNUSED_DD", None):
            continue
        pid = b.node("PROGRAM", binding["program"].upper())
        if status == "BOUND" and binding.get("dataset"):
            b.edge(pid, b.node("DATASET", binding["dataset"]), "BINDS", PROVEN,
                   f"ddname {binding['ddname']} bound to the step's DD (GnuCOBOL ddname oracle)")
        elif status == "UNBOUND":
            b.edge(pid, b.node("DATASET", f"<unbound:{binding['ddname']}>", external=True), "BINDS", BLOCKED,
                   binding.get("detail", "no DD statement"))
        elif status == "LITERAL_PATH":
            b.edge(pid, b.node("DATASET", f"<path:{binding['file_name']}>", external=True), "BINDS", UNPROVEN,
                   binding.get("detail", "the program names its file itself"))

    for flow in discovery.get("dataset_flows", []):
        b.edge(b.node("STEP", flow["from"].upper()), b.node("STEP", flow["to"].upper()), "FLOWS_TO", PARTIAL,
               f"dataset {flow['dsn']} is produced by one step and consumed by the next")

    for program_id, entries in sorted((external or {}).items()):
        pid = b.node("PROGRAM", program_id.upper())
        for entry in entries:
            kind = str(entry.get("kind", "")).split(".")[-1]
            if kind not in _LEDGER_KINDS:
                continue
            node_kind, relation = _LEDGER_KINDS[kind]
            name = str(entry["dependency_id"]).split(":", 1)[-1]
            state = entry.get("proof_state", UNPROVEN)
            state = str(state).split(".")[-1]
            b.edge(pid, b.node(node_kind, name), relation, state if state in PROOF_STATES else UNPROVEN,
                   entry.get("reason", ""))

    return Estate(
        nodes=sorted(b.nodes.values(), key=lambda n: (n.kind, n.name)),
        edges=sorted(b.edges.values(), key=lambda e: (e.source, e.relation, e.target)),
    )
