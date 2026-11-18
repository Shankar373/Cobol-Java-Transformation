"""Resolve every scanner reference against the estate and build the traceable dependency graph.

Resolution is name-based and deterministic.  A reference is *resolved* when its target exists in the upload,
*external* when the platform (not the customer) provides it, *ambiguous* when several upload artefacts qualify, and
*unresolved* otherwise, with a reason and a ``blocking`` flag.  Nothing is dropped: a reference that cannot be
resolved becomes an edge to an absent node.

DD binding follows the JCL: a COBOL ``SELECT ... ASSIGN TO DDNAME`` is tied to the dataset of the matching ``DD`` in
every step that runs the program (directly, or through a procedure with job-level overrides).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from posixpath import dirname

from .findings import Fact, Ref
from .graph import DependencyGraph, Edge, Node
from .inventory import FileRecord
from .jcl_utils import SYSTEM_PROGRAMS

__all__ = ["build_graph", "GraphBuild", "Estate"]

PLATFORM_COPYBOOK_PREFIXES = ("DFH", "CMQ", "SQL", "DLI", "IKJ", "IGZ", "CEE", "DSN", "AIB", "UIB")
PLATFORM_PROC_PREFIXES = ("IGYW", "IGYC", "IGYR", "DFHYI", "DFHEI", "DSNH", "ELAX", "IEWL", "CEEW", "CBLW", "ASMA", "EDC")
_FALLBACK = "#FALLBACK"
_PROGRAM_KINDS = frozenset({"PROGRAM-ID", "CLASS-ID", "INTERFACE-ID", "FUNCTION-ID"})


@dataclass
class _Step:
    program: str = ""
    proc: str = ""
    label: str = ""
    file: str = ""
    line: int = 0
    dds: dict[str, list[Ref]] = field(default_factory=dict)


@dataclass
class Estate:
    """Name indexes over the scanned artefacts."""

    programs: dict[str, list[tuple[str, int, str]]] = field(default_factory=dict)
    copybooks: dict[str, list[str]] = field(default_factory=dict)
    procs: dict[str, list[str]] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    jobs: dict[str, str] = field(default_factory=dict)
    tables: dict[str, list[str]] = field(default_factory=dict)
    mapsets: dict[str, str] = field(default_factory=dict)
    clusters: dict[str, tuple[str, int]] = field(default_factory=dict)
    queues: dict[str, str] = field(default_factory=dict)
    transactions: dict[str, str] = field(default_factory=dict)
    cics_files: dict[str, str] = field(default_factory=dict)
    load_modules: dict[str, str] = field(default_factory=dict)
    files: dict[str, FileRecord] = field(default_factory=dict)
    by_basename: dict[str, list[str]] = field(default_factory=dict)
    directories: set[str] = field(default_factory=set)
    steps: dict[tuple[str, str], list[_Step]] = field(default_factory=dict)


@dataclass
class GraphBuild:
    graph: DependencyGraph
    estate: Estate
    #: ``program name -> [(job/proc label, ddname, dataset)]`` for the report.
    bindings: list[dict[str, object]] = field(default_factory=list)


def _add(index: dict[str, list], key: str, value: object) -> None:
    items = index.setdefault(key.upper(), [])
    if value not in items:
        items.append(value)


def _index(records: list[FileRecord]) -> Estate:
    est = Estate()
    for record in sorted(records, key=lambda r: r.path):
        est.files[record.path] = record
        _add(est.by_basename, record.path.rsplit("/", 1)[-1].lower(), record.path)
        parts = record.path.split("/")[:-1]
        est.directories.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        stem = record.stem.upper()
        if record.cls == "copybook":
            _add(est.copybooks, stem, record.path)
            _add(est.copybooks, record.path.rsplit("/", 1)[-1], record.path)
        if record.cls in ("jcl-job", "jcl-proc"):
            _add(est.members, stem, record.path)
        if record.cls == "jcl-proc":
            _add(est.procs, stem, record.path)
        scan = record.scan
        if scan is None:
            continue
        for fact in scan.facts:
            _index_fact(est, record, fact)
        for ref in scan.refs:
            _index_ref(est, record, ref)
    for record in records:
        if record.cls == "cobol":
            for key in (record.stem.upper(),):
                _add(est.copybooks, key + _FALLBACK, record.path)
    return est


def _index_fact(est: Estate, record: FileRecord, fact: Fact) -> None:
    info = dict(fact.detail)
    if fact.category == "program-id":
        kind = info.get("kind", "")
        if kind in _PROGRAM_KINDS or kind.endswith(("-entry", "-member")):
            _add(est.programs, fact.name, (record.path, fact.line, kind + (":nested" if info.get("nested") == "yes" else "")))
            if info.get("external_name"):
                _add(est.programs, info["external_name"], (record.path, fact.line, "external-name"))
    elif fact.category == "entry-point":
        _add(est.programs, fact.name, (record.path, fact.line, "ENTRY"))
    elif fact.category == "jcl-proc":
        _add(est.procs, fact.name, record.path)
    elif fact.category == "jcl-job":
        est.jobs.setdefault(fact.name.upper(), record.path)
    elif fact.category == "bms-mapset":
        est.mapsets.setdefault(fact.name.upper(), record.path)
    elif fact.category == "load-module":
        est.load_modules.setdefault(fact.name.upper(), record.path)


def _index_ref(est: Estate, record: FileRecord, ref: Ref) -> None:
    if ref.relation == "defines-table":
        _add(est.tables, ref.target, record.path)
    elif ref.relation == "defines-dataset" and ref.target_kind in ("vsam-cluster", "dataset"):
        est.clusters.setdefault(ref.target.upper(), (record.path, ref.line))
    elif ref.relation == "defines-queue":
        est.queues.setdefault(ref.target.upper(), record.path)
    elif ref.relation == "defines-resource":
        index = {"transaction": est.transactions, "cics-file": est.cics_files}.get(ref.target_kind)
        if index is not None:
            index.setdefault(ref.target.upper(), record.path)


def _scope(owner: str) -> tuple[str, str, str]:
    """``(kind, name, step)`` of a scanner owner such as ``job:PAY/STEP1`` or ``program:X``."""
    kind, _, rest = owner.partition(":")
    name, _, step = rest.partition("/")
    return kind, name, step


def _owner_node(owner: str, record: FileRecord) -> str:
    kind, name, _ = _scope(owner)
    if not name or kind == "file":
        return f"file:{record.path}"
    return f"{kind}:{name}"


def _steps(est: Estate, records: list[FileRecord]) -> None:
    for record in records:
        if record.scan is None or record.cls not in ("jcl-job", "jcl-proc"):
            continue
        current: dict[tuple[str, str, str], _Step] = {}
        for ref in sorted(record.scan.refs):
            kind, name, step = _scope(ref.owner)
            if kind not in ("job", "proc") or not step:
                continue
            key = (kind, name, step)
            entry = current.setdefault(key, _Step(label=f"{kind}:{name}/{step}", file=record.path))
            info = dict(ref.detail)
            if ref.relation == "executes" and ref.target_kind == "program" and not entry.program and not info.get("via"):
                entry.program, entry.file, entry.line = ref.target, record.path, ref.line
            elif ref.relation == "executes" and ref.target_kind == "proc":
                entry.proc, entry.file, entry.line = ref.target, record.path, ref.line
            elif ref.relation == "executes" and info.get("via") in ("DSN", "DFSRRC00"):
                entry.program = entry.program or ref.target
            elif info.get("dd"):
                entry.dds.setdefault(info["dd"], []).append(ref)
        for (kind, name, _), entry in sorted(current.items()):
            est.steps.setdefault((kind, name), []).append(entry)


def _effective_runs(est: Estate) -> dict[str, list[_Step]]:
    """``program -> steps that run it``, expanding procedures with the job step's DD overrides."""
    runs: dict[str, list[_Step]] = {}
    referenced = {step.proc.upper() for (kind, _), steps in est.steps.items() if kind == "job" for step in steps if step.proc}
    for (kind, name), steps in sorted(est.steps.items()):
        for step in steps:
            if step.program:
                # A procedure step runs through the job step that invokes it (with that job's overrides); a procedure no
                # uploaded job invokes is the only place its DDs are visible, so it is bound as a template.
                if kind == "job" or name.upper() not in referenced:
                    runs.setdefault(step.program.upper(), []).append(step)
            elif step.proc:
                for proc_step in est.steps.get(("proc", step.proc.upper()), []):
                    if not proc_step.program:
                        continue
                    merged = _Step(program=proc_step.program, label=f"{step.label}>{proc_step.label.split('/')[-1]}",
                                   file=proc_step.file, line=proc_step.line, dds={k: list(v) for k, v in proc_step.dds.items()})
                    for ddname, refs in step.dds.items():
                        override_to = {dict(r.detail).get("override", "") for r in refs}
                        if proc_step.label.split("/")[-1] in override_to:
                            merged.dds[ddname] = list(refs)
                    runs.setdefault(proc_step.program.upper(), []).append(merged)
    return runs


class _Builder:
    def __init__(self, est: Estate) -> None:
        self.est = est
        self.graph = DependencyGraph()
        self.bindings: list[dict[str, object]] = []

    # -- nodes ---------------------------------------------------------------------------------------------------
    def node(self, node_id: str, kind: str, origin: str = "input", path: str = "") -> str:
        record = self.est.files.get(path)
        self.graph.add_node(Node(node_id, kind, path, record.sha256 if record else "", origin))
        return node_id

    def edge(self, src: str, dst: str, ref: Ref, resolution: str = "resolved", reason: str = "",
             candidates: tuple[str, ...] = (), extra: tuple[tuple[str, str], ...] = (), relation: str = "") -> None:
        info = tuple(sorted(set(ref.detail) | set(extra)))
        self.graph.add_edge(Edge(src, dst, relation or ref.relation, ref.clause, ref.file, ref.line, ref.column, resolution,
                                 reason, ref.dynamic, ref.variable, candidates, info))

    # -- per-kind resolution ----------------------------------------------------------------------------------
    def ref(self, record: FileRecord, ref: Ref) -> None:
        src = self.node(_owner_node(ref.owner, record), _scope(ref.owner)[0] if _scope(ref.owner)[1] else "file",
                        "input", record.path if _scope(ref.owner)[0] in ("program", "file") else "")
        if ref.dynamic and not ref.target:
            dst = self.node(f"dynamic:{ref.variable or 'unknown'}", "dynamic", "absent")
            self.edge(src, dst, ref, "unresolved", "dynamic-target")
            return
        handler = getattr(self, "_" + ref.target_kind.replace("-", "_"), None)
        if handler is not None:
            handler(src, ref)
        else:
            self._generic(src, ref)

    def _generic(self, src: str, ref: Ref) -> None:
        dst = self.node(f"{ref.target_kind}:{ref.target}", ref.target_kind, "catalog")
        self.edge(src, dst, ref, "external")

    def _program(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        found = self.est.programs.get(name, [])
        real = [f for f in found if not f[2].endswith(":nested")] or found
        paths = sorted({f[0] for f in real})
        if not paths and name in self.est.load_modules:
            dst = self.node(f"load-module:{name}", "load-module", "input", self.est.load_modules[name])
            self.edge(src, dst, ref)
            return
        if not paths:
            stems = [p for p in self.est.files if self.est.files[p].stem.upper() == name
                     and self.est.files[p].cls in ("cobol", "assembler", "pli", "rexx", "clist")]
            if stems:
                dst = self.node(f"program:{name}", "program", "input", sorted(stems)[0])
                self.edge(src, dst, ref, extra=(("matched_by", "file-name"),))
                return
        if not paths:
            if name in SYSTEM_PROGRAMS or name.startswith(("IGY", "CEE", "DFH", "DSN", "CSQ", "IEW", "ICE", "DFS")):
                dst = self.node(f"utility:{name}", "utility", "platform")
                self.edge(src, dst, ref, "external")
                return
            dst = self.node(f"program:{name}", "program", "absent")
            self.edge(src, dst, ref, "unresolved", "missing-program")
            return
        dst = self.node(f"program:{name}", "program", "input", paths[0])
        if len(paths) > 1:
            self.edge(src, dst, ref, "ambiguous", candidates=tuple(paths))
        else:
            self.edge(src, dst, ref)

    def _copybook(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        candidates = list(self.est.copybooks.get(name, []))
        if not candidates:
            candidates = list(self.est.copybooks.get(name.rsplit(".", 1)[0], [])) if "." in name else []
        extra: tuple[tuple[str, str], ...] = ()
        if not candidates:
            fallback = self.est.copybooks.get(name + _FALLBACK, [])
            if fallback:
                candidates, extra = list(fallback), (("matched_by", "program-file-used-as-copybook"),)
        if ref.qualifier and len(candidates) > 1:
            preferred = [c for c in candidates if ref.qualifier.lower() in c.lower().split("/")]
            candidates = preferred or candidates
        if not candidates:
            if name.startswith(PLATFORM_COPYBOOK_PREFIXES):
                dst = self.node(f"copybook:{name}", "copybook", "platform")
                self.edge(src, dst, ref, "external")
                return
            dst = self.node(f"copybook:{name}", "copybook", "absent")
            self.edge(src, dst, ref, "unresolved", "missing-copybook")
            return
        # Prefer the copybook nearest the referencing file, then the shortest path, then the first alphabetically.
        here = ref.file
        candidates = sorted(set(candidates), key=lambda c: (0 if dirname(c) == dirname(here) else 1, len(c), c))
        dst = self.node(f"copybook:{name}", "copybook", "input", candidates[0])
        if len(candidates) > 1 and not (dirname(candidates[0]) == dirname(here)
                                         and dirname(candidates[1]) != dirname(here)):
            self.edge(src, dst, ref, "ambiguous", candidates=tuple(candidates), extra=extra)
        else:
            self.edge(src, dst, ref, extra=extra)

    def _proc(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        paths = sorted(set(self.est.procs.get(name, [])))
        if paths:
            dst = self.node(f"proc:{name}", "proc", "input", paths[0])
            self.edge(src, dst, ref, "ambiguous" if len(paths) > 1 else "resolved",
                      candidates=tuple(paths) if len(paths) > 1 else ())
        elif name.startswith(PLATFORM_PROC_PREFIXES):
            self.edge(src, self.node(f"proc:{name}", "proc", "platform"), ref, "external")
        else:
            self.edge(src, self.node(f"proc:{name}", "proc", "absent"), ref, "unresolved", "missing-procedure")

    def _jcl_member(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        paths = sorted(set(self.est.members.get(name, [])))
        if paths:
            self.edge(src, self.node(f"jcl-member:{name}", "jcl-member", "input", paths[0]), ref,
                      "ambiguous" if len(paths) > 1 else "resolved", candidates=tuple(paths) if len(paths) > 1 else ())
        else:
            self.edge(src, self.node(f"jcl-member:{name}", "jcl-member", "absent"), ref, "unresolved", "missing-include")

    def _table(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        paths = self.est.tables.get(name) or self.est.tables.get(name.rsplit(".", 1)[-1], [])
        if not paths:
            unqualified = [p for key, vals in self.est.tables.items() if key.rsplit(".", 1)[-1] == name.rsplit(".", 1)[-1]
                           for p in vals]
            paths = unqualified
        if paths:
            self.edge(src, self.node(f"table:{name}", "table", "input", sorted(set(paths))[0]), ref)
        else:
            self.edge(src, self.node(f"table:{name}", "table", "catalog"), ref, "unresolved", "external-table")

    def _dd(self, src: str, ref: Ref) -> None:
        if ref.relation == "assigns-file":
            return  # bound against JCL in a separate pass
        kind, name, step = _scope(ref.owner)
        steps = [s for s in self.est.steps.get((kind, name), []) if s.label.endswith("/" + step)]
        dds = steps[0].dds.get(ref.target.upper(), []) if steps else []
        if dds:
            first = dds[0]
            self.edge(src, self._dataset_node(first.target, first.target_kind), ref, extra=(("via_dd", ref.target.upper()),))
        else:
            self.edge(src, self.node(f"dd:{ref.target.upper()}", "dd", "absent"), ref, "unresolved", "missing-dd")

    def _dataset_node(self, dsn: str, kind: str = "dataset") -> str:
        defined = self.est.clusters.get(dsn.upper())
        if defined:
            return self.node(f"vsam-cluster:{dsn.upper()}", "vsam-cluster", "input", defined[0])
        prefix = kind if kind in ("uss-path", "sysout", "dummy", "instream") else "dataset"
        return self.node(f"{prefix}:{dsn}", kind, "catalog")

    def _dataset(self, src: str, ref: Ref) -> None:
        self.edge(src, self._dataset_node(ref.target.upper(), "dataset"), ref)

    def _vsam_cluster(self, src: str, ref: Ref) -> None:
        self.edge(src, self.node(f"vsam-cluster:{ref.target.upper()}", "vsam-cluster", "input",
                                 self.est.clusters.get(ref.target.upper(), ("", 0))[0]), ref)

    def _uss_path(self, src: str, ref: Ref) -> None:
        self.edge(src, self.node(f"uss-path:{ref.target}", "uss-path", "catalog"), ref, "external")

    def _external_file(self, src: str, ref: Ref) -> None:
        self.edge(src, self.node(f"external-file:{ref.target}", "external-file", "catalog"), ref, "external")

    def _directory(self, src: str, ref: Ref) -> None:
        target = ref.target.replace("\\", "/").strip("/")
        match = [d for d in self.est.directories if d == target or d.endswith("/" + target.lstrip("./")) or target in ("", ".")]
        if match:
            self.edge(src, self.node(f"directory:{sorted(match)[0]}", "directory", "input"), ref)
        else:
            self.edge(src, self.node(f"directory:{ref.target}", "directory", "absent"), ref, "unresolved",
                      "library-not-in-estate")

    def _source_member(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        paths = [p for p, r in self.est.files.items() if r.stem.upper() == name and r.cls in ("cobol", "copybook", "pli",
                                                                                              "assembler")]
        found = self.est.programs.get(name)
        if paths or found:
            path = sorted(paths)[0] if paths else (found or [("", 0, "")])[0][0]
            self.edge(src, self.node(f"program:{name}", "program", "input", path), ref)
        else:
            self.edge(src, self.node(f"source-member:{name}", "source-member", "absent"), ref, "unresolved", "missing-source")

    def _source_file(self, src: str, ref: Ref) -> None:
        base = ref.target.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if "$" in ref.target or "{" in ref.target:
            self.edge(src, self.node(f"dynamic:{ref.target}", "dynamic", "absent"), ref, "unresolved", "dynamic-target")
            return
        paths = sorted(self.est.by_basename.get(base.upper(), []))
        wanted = ref.target.replace("\\", "/").lstrip("./")
        narrowed = [p for p in paths if p.endswith(wanted)] or paths
        if narrowed:
            self.edge(src, self.node(f"file:{narrowed[0]}", "file", "input", narrowed[0]), ref,
                      "ambiguous" if len(narrowed) > 1 else "resolved",
                      candidates=tuple(narrowed) if len(narrowed) > 1 else ())
        else:
            self.edge(src, self.node(f"source-file:{ref.target}", "source-file", "absent"), ref, "unresolved", "missing-source")

    def _bms_mapset(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        if ref.relation == "defines-resource":
            self.edge(src, self.node(f"bms-mapset:{name}", "bms-mapset", "input", ref.file), ref)
        elif name in self.est.mapsets:
            self.edge(src, self.node(f"bms-mapset:{name}", "bms-mapset", "input", self.est.mapsets[name]), ref)
        else:
            self.edge(src, self.node(f"bms-mapset:{name}", "bms-mapset", "absent"), ref, "unresolved", "missing-mapset")

    def _bms_map(self, src: str, ref: Ref) -> None:
        if ref.relation == "defines-resource":
            self.edge(src, self.node(f"bms-map:{ref.target.upper()}", "bms-map", "input", ref.file), ref)
        else:
            self._bms_mapset(src, ref)

    def _transaction(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        if name in self.est.transactions:
            self.edge(src, self.node(f"transaction:{name}", "transaction", "input", self.est.transactions[name]), ref)
        elif ref.relation == "defines-resource":
            self.edge(src, self.node(f"transaction:{name}", "transaction", "input", ref.file), ref)
        else:
            self.edge(src, self.node(f"transaction:{name}", "transaction", "catalog"), ref, "unresolved",
                      "undefined-transaction")

    def _cics_file(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        path = self.est.cics_files.get(name, ref.file if ref.relation == "defines-resource" else "")
        self.edge(src, self.node(f"cics-file:{name}", "cics-file", "input" if path else "catalog", path), ref,
                  "resolved" if path else "external")

    def _mq_queue(self, src: str, ref: Ref) -> None:
        name = ref.target.upper()
        path = self.est.queues.get(name, "")
        self.edge(src, self.node(f"mq-queue:{name}", "mq-queue", "input" if path else "catalog", path), ref,
                  "resolved" if path else "external")

    def _utility(self, src: str, ref: Ref) -> None:
        self.edge(src, self.node(f"utility:{ref.target.upper()}", "utility", "platform"), ref, "external")

    def _runtime(self, src: str, ref: Ref) -> None:
        self.edge(src, self.node(f"runtime:{ref.target.upper()}", "runtime", "platform"), ref, "external")


def build_graph(records: list[FileRecord]) -> GraphBuild:
    """Build the dependency graph for scanned ``records`` (any order; the result is canonical)."""
    est = _index(records)
    _steps(est, records)
    builder = _Builder(est)
    for record in sorted(records, key=lambda r: r.path):
        builder.node(f"file:{record.path}", "file", "input", record.path)
        if record.scan is None:
            continue
        _definition_edges(builder, record)
        for ref in record.scan.refs:
            builder.ref(record, ref)
    _bind_dd_names(builder, records, _effective_runs(est))
    return GraphBuild(builder.graph, est, builder.bindings)


_DEFINING_FACTS = {"program-id": "program", "jcl-job": "job", "jcl-proc": "proc", "bms-mapset": "bms-mapset"}


def _definition_edges(builder: _Builder, record: FileRecord) -> None:
    assert record.scan is not None
    for fact in record.scan.facts:
        kind = _DEFINING_FACTS.get(fact.category)
        if kind is None:
            continue
        info = dict(fact.detail)
        if fact.category == "program-id" and info.get("kind") not in _PROGRAM_KINDS and not str(info.get("kind", "")).endswith(
                ("-entry", "-member")):
            continue
        src = builder.node(f"file:{record.path}", "file", "input", record.path)
        dst = builder.node(f"{kind}:{fact.name.upper()}", kind, "input", record.path)
        builder.graph.add_edge(Edge(src, dst, "defines", "definition", record.path, fact.line, max(fact.column, 1),
                                    detail=fact.detail))


def _bind_dd_names(builder: _Builder, records: list[FileRecord], runs: dict[str, list[_Step]]) -> None:
    est = builder.est
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for ref in record.scan.refs:
            if ref.relation != "assigns-file" or ref.target_kind != "dd":
                continue
            kind, program, _ = _scope(ref.owner)
            src = builder.node(f"program:{program}", "program", "input", record.path) if program else \
                builder.node(f"file:{record.path}", "file", "input", record.path)
            ddname = ref.target.upper()
            steps = runs.get(program.upper(), []) if program else []
            if not steps:
                builder.edge(src, builder.node(f"dd:{ddname}", "dd", "absent"), ref, "unresolved", "unbound-ddname")
                continue
            for step in steps:
                dds = step.dds.get(ddname, [])
                if not dds:
                    builder.edge(src, builder.node(f"dd:{ddname}", "dd", "absent"), ref, "unresolved", "missing-dd",
                                 extra=(("job_step", step.label),))
                    continue
                for dd in dds:
                    info = dict(dd.detail)
                    dsn = dd.target if dd.target else ""
                    if not dsn:
                        builder.edge(src, builder.node(f"dynamic:{dd.variable}", "dynamic", "absent"), ref, "unresolved",
                                     "dynamic-target", extra=(("job_step", step.label), ("ddname", ddname)))
                        continue
                    dst = builder._dataset_node(dsn, dd.target_kind)
                    vsam = dsn.upper() in est.clusters or info.get("amp") == "vsam-hint"
                    builder.edge(src, dst, ref, extra=(("ddname", ddname), ("job_step", step.label), ("jcl_file", dd.file),
                                                       ("jcl_line", str(dd.line)), ("disp", info.get("disp", "")),
                                                       ("vsam", "yes" if vsam else "")), relation="uses-dataset")
                    builder.bindings.append({"program": program.upper(), "ddname": ddname, "dataset": dsn.upper(),
                                             "step": step.label, "cobol_file": ref.file, "cobol_line": ref.line,
                                             "jcl_file": dd.file, "jcl_line": dd.line, "vsam": bool(vsam),
                                             "organization": dict(ref.detail).get("organization", "")})
