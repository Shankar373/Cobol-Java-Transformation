"""Entry points, application boundaries and cross-application relationships, derived only from the dependency graph.

An *application* is a connected set of programs, jobs, procedures, transactions and map sets that execute, call or start one another.
Two applications are *related* when they share a resource (dataset, VSAM cluster, Db2 table, queue, IMS PSB, CICS file, copybook): the
coupling that matters when one is modernized and the other is not.  Nothing here is guessed; every member and every shared resource
traces to graph edges, which trace to source lines.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .graph import BLOCKING_REASONS, DependencyGraph, Edge
from .inventory import FileRecord

__all__ = ["build_applications", "ENTRY_KINDS"]

#: Closed set of entry-point kinds.
ENTRY_KINDS = ("batch-job-step", "ims-region-program", "cics-transaction-program", "called-subprogram", "unreferenced-program")
_COUPLING_RELATIONS = frozenset({"calls", "cics-link", "cics-xctl", "cics-load", "executes", "includes", "starts-transaction", "uses-map"})
_MEMBER_KINDS = frozenset({"program", "job", "proc", "jcl-member", "transaction", "bms-mapset", "load-module"})
_SHARED_KINDS = frozenset({"dataset", "vsam-cluster", "table", "mq-queue", "cics-file", "ims-psb", "copybook", "ims-segment", "db2-plan"})
_SKIP_SHARED_DATASETS = frozenset({"sysout", "dummy", "instream"})


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


def _name(node_id: str) -> str:
    return node_id.split(":", 1)[-1]


def _entry_points(graph: DependencyGraph) -> list[dict[str, Any]]:
    incoming: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for edge in graph.edges():
        node = graph.nodes.get(edge.dst)
        if node is None or node.kind != "program" or node.origin != "input":
            continue
        info = dict(edge.detail)
        if edge.relation == "executes" and edge.clause.startswith("IMS region") or info.get("via") == "DFSRRC00":
            incoming[edge.dst]["ims-region-program"].add(edge.src)
        elif edge.relation == "executes" and edge.clause == "CICS TRANSACTION PROGRAM":
            incoming[edge.dst]["cics-transaction-program"].add(edge.src)
        elif edge.relation == "executes":
            incoming[edge.dst]["batch-job-step"].add(edge.src)
        elif edge.relation in ("calls", "cics-link", "cics-xctl", "cics-load"):
            if edge.src != edge.dst:
                incoming[edge.dst]["called-subprogram"].add(edge.src)
    out = []
    for node_id in sorted(n for n, node in graph.nodes.items() if node.kind == "program" and node.origin == "input"):
        node = graph.nodes[node_id]
        kinds = incoming.get(node_id, {})
        row_kinds = sorted(k for k in kinds if k != "called-subprogram") or (["called-subprogram"] if "called-subprogram" in kinds else
                                                                              ["unreferenced-program"])
        out.append({"invoked_by": sorted({s for k in kinds.values() for s in k}), "kinds": row_kinds,
                    "called_by_programs": sorted(kinds.get("called-subprogram", set())), "file": node.path, "program": _name(node_id)})
    return out


def build_applications(records: Sequence[FileRecord], graph: DependencyGraph,
                       compatibility: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Entry points, applications and their relationships; ``compatibility`` adds per-application compiler verdicts."""
    entries = _entry_points(graph)
    cobol_paths = {r.path for r in records if r.cls == "cobol"}
    union = _Union()
    members: set[str] = set()
    for edge in graph.edges():
        if edge.relation not in _COUPLING_RELATIONS or edge.resolution not in ("resolved", "ambiguous"):
            continue
        a, b = graph.nodes.get(edge.src), graph.nodes.get(edge.dst)
        if a is None or b is None or a.kind not in _MEMBER_KINDS or b.kind not in _MEMBER_KINDS or b.origin != "input":
            continue
        union.union(edge.src, edge.dst)
        members.update((edge.src, edge.dst))
    for node_id, node in graph.nodes.items():  # a lone program or job is still an application
        if node.kind in ("program", "job") and node.origin == "input" and (node.kind == "job" or cobol_paths is None or node.path in cobol_paths):
            members.add(node_id)
            union.find(node_id)
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in sorted(members):
        if graph.nodes[node_id].origin == "input":
            groups[union.find(node_id)].append(node_id)

    files_of = {nid: graph.nodes[nid].path for nid in members if graph.nodes[nid].path}
    verdicts = {p["file"]: p for p in (compatibility or {}).get("programs", [])}
    edges_by_file: dict[str, list[Edge]] = defaultdict(list)
    for edge in graph.edges():
        edges_by_file[edge.file].append(edge)

    applications: list[dict[str, Any]] = []
    owner: dict[str, str] = {}
    for _, nodes in sorted(groups.items()):
        app_files = sorted({files_of[n] for n in nodes if n in files_of})
        app_id = "APP-" + hashlib.sha256("\n".join(nodes).encode("utf-8")).hexdigest()[:8]
        for node_id in nodes:
            owner[node_id] = app_id
        resources: dict[str, dict[str, Any]] = {}
        copybooks: set[str] = set()
        unresolved: list[Edge] = []
        for path in app_files:
            for edge in edges_by_file.get(path, []):
                dst = graph.nodes.get(edge.dst)
                if edge.resolution == "unresolved":
                    unresolved.append(edge)
                if dst is None:
                    continue
                if dst.kind == "copybook" and edge.relation == "copies":
                    copybooks.add(edge.dst)
                if dst.kind in _SHARED_KINDS and dst.kind != "copybook" and edge.dst.split(":", 1)[0] not in _SKIP_SHARED_DATASETS:
                    entry = resources.setdefault(edge.dst, {"id": edge.dst, "kind": dst.kind, "origin": dst.origin, "uses": 0})
                    entry["uses"] += 1
        programs = sorted(_name(n) for n in nodes if graph.nodes[n].kind == "program")
        jobs = sorted(_name(n) for n in nodes if graph.nodes[n].kind == "job")
        app_entries = [e for e in entries if f"program:{e['program']}" in nodes and "called-subprogram" not in e["kinds"]]
        compile_rows = [verdicts[f] for f in app_files if f in verdicts]
        features = sorted({f["feature"] for row in compile_rows for f in row["unsupported_features"]})
        blocking = [e for e in unresolved if e.reason in BLOCKING_REASONS]
        compile_errors = sorted(r["file"] for r in compile_rows if r["verdict"] == "COMPILE_ERRORS")
        status = "BLOCKED" if blocking else ("NOT_SUPPORTED" if features or compile_errors else "READY")
        applications.append({
            "blocking_unresolved": [{"file": e.file, "line": e.line, "reason": e.reason, "to": e.dst} for e in blocking[:50]],
            "compile_errors": compile_errors,
            "compiler_verdicts": _count(r["verdict"] for r in compile_rows),
            "copybooks": sorted(_name(c) for c in copybooks), "entry_points": app_entries, "files": app_files, "id": app_id,
            "jobs": jobs, "members": sorted(nodes),
            "name": _app_name(jobs, programs, app_entries, app_id), "programs": programs,
            "readiness": status, "resources": sorted(resources.values(), key=lambda r: str(r["id"])),
            "unresolved_total": len(unresolved), "unsupported_features": features,
        })
    applications.sort(key=lambda a: (a["name"], a["id"]))
    return {"applications": applications, "entry_points": entries, "relationships": _relationships(applications)}


def _app_name(jobs: list[str], programs: list[str], entries: list[dict[str, Any]], app_id: str) -> str:
    """Prefer a CICS transaction program (a CSD job only defines resources), then the first job, then the first program."""
    online = sorted(e["program"] for e in entries if "cics-transaction-program" in e["kinds"])
    return (online or jobs or programs or [app_id])[0]


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for value in values:
        out[str(value)] += 1
    return dict(sorted(out.items()))


def _relationships(applications: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Resources and copybooks used by more than one application, with who uses them."""
    users: dict[str, dict[str, Any]] = {}
    for app in applications:
        for resource in app["resources"]:
            entry = users.setdefault(resource["id"], {"id": resource["id"], "kind": resource["kind"], "applications": {}})
            entry["applications"][app["id"]] = resource["uses"]
        for copybook in app["copybooks"]:
            entry = users.setdefault(f"copybook:{copybook}", {"id": f"copybook:{copybook}", "kind": "copybook", "applications": {}})
            entry["applications"][app["id"]] = entry["applications"].get(app["id"], 0) + 1
    names = {a["id"]: a["name"] for a in applications}
    out = []
    for key in sorted(users):
        entry = users[key]
        if len(entry["applications"]) > 1:
            out.append({"applications": [{"id": a, "name": names[a], "uses": n} for a, n in sorted(entry["applications"].items())],
                        "kind": entry["kind"], "resource": entry["id"]})
    return out
