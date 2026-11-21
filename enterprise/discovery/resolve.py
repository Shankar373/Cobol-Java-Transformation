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

from .cobol_structure import scoped_node_id
from .findings import Fact, Ref, detail
from .graph import DependencyGraph, Edge, Node, confidence_for
from .inventory import FileRecord
from .jcl_utils import SYSTEM_PROGRAMS
from .library_order import library_winner as _shared_library_winner

__all__ = ["build_graph", "GraphBuild", "Estate"]

PLATFORM_COPYBOOK_PREFIXES = ("DFH", "CMQ", "SQL", "DLI", "IKJ", "IGZ", "CEE", "DSN", "AIB", "UIB")
PLATFORM_PROC_PREFIXES = ("IGYW", "IGYC", "IGYR", "DFHYI", "DFHEI", "DSNH", "ELAX", "IEWL", "CEEW", "CBLW", "ASMA", "EDC")
_FALLBACK = "#FALLBACK"
_PROGRAM_KINDS = frozenset({"PROGRAM-ID", "CLASS-ID", "INTERFACE-ID", "FUNCTION-ID"})
#: Kinds a ``contains`` reference declares; their node ids are scoped by the declaring owner.
_UNIT_KINDS = ("section", "paragraph", "data-item", "record-layout", "screen-field")


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
    #: Declared units: node id -> the files that declare them (section/paragraph/data item/record/screen field).
    declarations: dict[str, list[str]] = field(default_factory=dict)
    #: File path -> node ids it declares, so a copybook's declarations can be linked to every including program.
    declared_in: dict[str, list[str]] = field(default_factory=dict)
    #: ``SELECT`` logical name -> ``(kind, target, file)`` bindings, used to follow ``READ``/``WRITE`` verbs.
    logical_files: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    #: ``JCLLIB ORDER`` per job/proc name: ``[(position, dataset)]`` as written.
    jcllib: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    #: ``(file, line)`` of a compile command -> ``[(position, include dir)]`` (``-I``) and the sources it builds.
    include_dirs: dict[tuple[str, int], list[tuple[int, str]]] = field(default_factory=dict)
    built_sources: dict[tuple[str, int], list[str]] = field(default_factory=dict)
    #: Basename (lower case) of a COBOL source -> its ordered ``-I`` directories.
    include_order: dict[str, list[str]] = field(default_factory=dict)
    #: Program owner -> ``[(line, name)]`` of its ``FD``/``SD`` entries.
    fds: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    #: ``(owner, line, copybook, replacing_pairs)`` of every ``COPY`` written in a program.
    copy_refs: list[tuple[str, int, str, str]] = field(default_factory=list)
    #: ``(program owner, record name)`` -> the logical file (``SELECT`` name) whose FD describes that record.
    record_files: dict[tuple[str, str], str] = field(default_factory=dict)


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
    _finish_index(est)
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
    elif fact.category == "file-description":
        est.fds.setdefault(fact.owner, []).append((fact.line, fact.name.upper()))
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
    elif ref.relation == "uses-library":
        _index_library(est, record, ref)
    elif ref.relation == "builds" and ref.target_kind == "source-file":
        est.built_sources.setdefault((ref.file, ref.line), []).append(ref.target)
    elif ref.relation == "copies" and ref.owner.startswith("program:"):
        est.copy_refs.append((ref.owner, ref.line, ref.target.upper(), dict(ref.detail).get("replacing_pairs", "")))
    elif ref.relation == "contains" and ref.target_kind in _UNIT_KINDS:
        if ref.target_kind == "record-layout" and dict(ref.detail).get("file"):
            est.record_files[(ref.owner, ref.target.upper())] = dict(ref.detail)["file"].upper()
        node_id = scoped_node_id(ref.owner, ref.target, ref.target_kind)
        paths = est.declarations.setdefault(node_id, [])
        if record.path not in paths:
            paths.append(record.path)
        listed = est.declared_in.setdefault(record.path, [])
        if node_id not in listed:
            listed.append(node_id)
    elif ref.relation == "assigns-file":
        logical = dict(ref.detail).get("logical_file", "")
        if logical:
            target_kind = "external-file" if ref.target_kind == "external-file" else "dd"
            target = ref.target if target_kind == "external-file" else ref.target.upper()
            entries = est.logical_files.setdefault(f"{ref.owner}|{logical.upper()}", [])
            if (target_kind, target, record.path) not in entries:
                entries.append((target_kind, target, record.path))


def _index_library(est: Estate, record: FileRecord, ref: Ref) -> None:
    info = dict(ref.detail)
    position = int(info["position"]) if info.get("position", "").isdigit() else 0
    if info.get("purpose") == "procedure-library":
        name = _scope(ref.owner)[1].upper()
        est.jcllib.setdefault(name, []).append((position, ref.target.upper()))
    elif info.get("purpose") == "copybook-path" and ref.clause.endswith(" -I"):
        est.include_dirs.setdefault((ref.file, ref.line), []).append((position, ref.target))


def _pairs(replacing: str) -> list[tuple[str, str]]:
    """``"A BY B; C BY D"`` (the recorded ``replacing_pairs``) -> ``[(A, B), (C, D)]``."""
    out = []
    for pair in replacing.split("; "):
        if " BY " in pair:
            left, _, right = pair.partition(" BY ")
            out.append((left.strip(), right.strip()))
    return out


def _expand_name(name: str, pairs: list[tuple[str, str]]) -> str:
    for left, right in pairs:
        if left and left in name:
            name = name.replace(left, right)
    return name


def _finish_index(est: Estate) -> None:
    """Derived indexes that need every file indexed first: -I order per source, and FD record -> logical file."""
    for key, dirs in est.include_dirs.items():
        ordered = [target for _position, target in sorted(dirs)]
        for source in est.built_sources.get(key, []):
            est.include_order.setdefault(source.replace("\\", "/").rsplit("/", 1)[-1].lower(), ordered)
    for owner, line, copybook, replacing in sorted(est.copy_refs):
        fds = [fd for fd in sorted(est.fds.get(owner, [])) if fd[0] < line]
        if not fds:
            continue
        logical = fds[-1][1]
        pairs = _pairs(replacing)
        for path in est.copybooks.get(copybook, []):
            for node_id in est.declared_in.get(path, []):
                kind, _, rest = node_id.partition(":")
                if kind == "record-layout":
                    record = _expand_name(rest.rpartition("/")[2], pairs)
                    est.record_files.setdefault((owner, record), logical)


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


#: Owner kinds that map onto a graph scope; anything else is estate-wide (``""``).
_SCOPED_OWNERS = frozenset({"program", "job", "proc", "file", "paragraph"})


def _owner_scope(owner: str) -> str:
    """Scope of an edge: a reference written inside a JCL step is scoped to that step, otherwise to its owner."""
    kind, _name, step = _scope(owner)
    if step and kind in ("job", "proc"):
        return "step"
    return kind if kind in _SCOPED_OWNERS else ""


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
        #: ``program -> steps that run it`` with procedures expanded; computed once in :func:`build_graph`.
        self.runs: dict[str, list[_Step]] = {}
        #: Copybook nodes whose path was fixed by a library order (so a later heuristic pick cannot move it).
        self._ordered_nodes: set[str] = set()

    # -- nodes ---------------------------------------------------------------------------------------------------
    def node(self, node_id: str, kind: str, origin: str = "input", path: str = "") -> str:
        record = self.est.files.get(path)
        self.graph.add_node(Node(node_id, kind, path, record.sha256 if record else "", origin))
        return node_id

    def edge(self, src: str, dst: str, ref: Ref, resolution: str = "resolved", reason: str = "",
             candidates: tuple[str, ...] = (), extra: tuple[tuple[str, str], ...] = (), relation: str = "",
             rule: str = "", confidence: str = "", mode: str = "", scope: str = "") -> None:
        """Append a validated edge.  ``rule``/``confidence`` default from the relation and the resolution; ``mode``
        comes from the scanner's reference and ``scope`` from the owner of the reference (a step-scoped JCL reference
        is scoped to that step)."""
        info = tuple(sorted(set(ref.detail) | set(extra)))
        relation = relation or ref.relation
        if not rule:
            rule = f"definition-{relation}"
        if not confidence:
            confidence = confidence_for(resolution)
        if not mode:
            mode = ref.mode
        if not scope:
            scope = _owner_scope(ref.owner)
        self.graph.add_edge(Edge(src, dst, relation, ref.clause, ref.file, ref.line, ref.column, resolution,
                                 reason, ref.dynamic, ref.variable, candidates, info,
                                 rule=rule, confidence=confidence, mode=mode, scope=scope))

    # -- per-kind resolution ----------------------------------------------------------------------------------
    def ref(self, record: FileRecord, ref: Ref) -> None:
        if ref.relation == "copies" and record.cls == "copybook" and _scope(ref.owner)[0] == "file":
            # A nested COPY belongs to the copybook that writes it, so impact of the inner copybook reaches the
            # programs that copy the outer one.
            src = self.node(f"copybook:{record.stem.upper()}", "copybook", "input", record.path)
        else:
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

    def _declared(self, src: str, ref: Ref, kind: str) -> None:
        """A section/paragraph/data item resolves against what the estate actually declares, scoped by owner.

        Two programs that both have a ``MAIN-PARA`` declare two different nodes, so a control-flow edge can never
        silently land on another program's paragraph.
        """
        node_id = scoped_node_id(ref.owner, ref.target, kind)
        paths = sorted(set(self.est.declarations.get(node_id, [])))
        if paths:
            dst = self.node(node_id, kind, "input", paths[0])
            self.edge(src, dst, ref, "ambiguous" if len(paths) > 1 else "resolved",
                      candidates=tuple(paths) if len(paths) > 1 else ())
            return
        reason = "missing-paragraph" if kind in ("section", "paragraph") else "missing-data-item"
        self.edge(src, self.node(node_id, kind, "absent"), ref, "unresolved", reason)

    def _paragraph(self, src: str, ref: Ref) -> None:
        self._declared(src, ref, "paragraph")

    def _section(self, src: str, ref: Ref) -> None:
        self._declared(src, ref, "section")

    def _data_item(self, src: str, ref: Ref) -> None:
        self._declared(src, ref, "data-item")

    def _record_layout(self, src: str, ref: Ref) -> None:
        self._declared(src, ref, "record-layout")

    def _screen_field(self, src: str, ref: Ref) -> None:
        self._declared(src, ref, "screen-field")

    def _bind_dd(self, src: str, ref: Ref, ddname: str, program: str, relation: str = "",
                 collect: bool = False) -> None:
        """Bind a DD name to the dataset(s) of every step that runs ``program`` (procedures already expanded).

        Used both by ``SELECT ... ASSIGN`` (``collect`` records the binding for the report) and by a file verb that
        follows its ``SELECT`` to the same ``DD``.
        """
        steps = self.runs.get(program.upper(), []) if program else []
        if not steps:
            self.edge(src, self.node(f"dd:{ddname}", "dd", "absent"), ref, "unresolved", "unbound-ddname")
            return
        for step in steps:
            dds = step.dds.get(ddname, [])
            if not dds:
                self.edge(src, self.node(f"dd:{ddname}", "dd", "absent"), ref, "unresolved", "missing-dd",
                          extra=(("job_step", step.label),))
                continue
            for dd in dds:
                info = dict(dd.detail)
                dsn = dd.target if dd.target else ""
                if not dsn:
                    self.edge(src, self.node(f"dynamic:{dd.variable}", "dynamic", "absent"), ref, "unresolved",
                              "dynamic-target", extra=(("job_step", step.label), ("ddname", ddname)))
                    continue
                dst = self._dataset_node(dsn, dd.target_kind)
                vsam = dsn.upper() in self.est.clusters or info.get("amp") == "vsam-hint"
                self.edge(src, dst, ref,
                          extra=(("ddname", ddname), ("job_step", step.label), ("jcl_file", dd.file),
                                 ("jcl_line", str(dd.line)), ("disp", info.get("disp", "")),
                                 ("vsam", "yes" if vsam else "")), relation=relation)
                if collect:
                    self.bindings.append({"program": program.upper(), "ddname": ddname, "dataset": dsn.upper(),
                                          "step": step.label, "cobol_file": ref.file, "cobol_line": ref.line,
                                          "jcl_file": dd.file, "jcl_line": dd.line, "vsam": bool(vsam),
                                          "organization": dict(ref.detail).get("organization", "")})

    def _logical_file(self, src: str, ref: Ref) -> None:
        """``READ``/``WRITE``/``REWRITE <logical file>``: follow the ``SELECT`` the program declared for that name
        to its ``DD`` and on to the dataset, exactly as ``SELECT ... ASSIGN`` is bound."""
        logical = ref.target.upper()
        entries = sorted(set(self.est.logical_files.get(f"{ref.owner}|{logical}", [])))
        if not entries:
            # ``WRITE``/``REWRITE`` name the FD *record*; follow it to the file whose FD describes it.
            logical = self.est.record_files.get((ref.owner, logical), logical)
            entries = sorted(set(self.est.logical_files.get(f"{ref.owner}|{logical}", [])))
        if not entries:
            self.edge(src, self.node(f"logical-file:{ref.target.upper()}", "logical-file", "absent"), ref,
                      "unresolved", "missing-logical-file")
            return
        target_kind, target, _path = entries[0]
        if target_kind == "external-file":
            self.edge(src, self.node(f"external-file:{target}", "external-file", "catalog"), ref, "external")
            return
        self._bind_dd(src, ref, target, _scope(ref.owner)[1])

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
        here = ref.file
        winner = self._library_winner(ref, sorted(set(candidates))) if len(set(candidates)) > 1 else ""
        if winner:
            # The library concatenation decides: first library holding the member wins, the rest stay candidates.
            self._ordered_copybook_node(name, winner)
            self.edge(src, f"copybook:{name}", ref, candidates=tuple(sorted(set(candidates))),
                      extra=extra, rule="copy-library-order", confidence="derived")
            return
        # Prefer the copybook nearest the referencing file, then the shortest path, then the first alphabetically.
        candidates = sorted(set(candidates), key=lambda c: (0 if dirname(c) == dirname(here) else 1, len(c), c))
        dst = self.node(f"copybook:{name}", "copybook", "input", candidates[0])
        if len(candidates) > 1 and not (dirname(candidates[0]) == dirname(here)
                                         and dirname(candidates[1]) != dirname(here)):
            self.edge(src, dst, ref, "ambiguous", candidates=tuple(candidates), extra=extra)
        else:
            self.edge(src, dst, ref, extra=extra)

    def _ordered_copybook_node(self, name: str, path: str) -> None:
        """Create the ``copybook:NAME`` node at the library-order winner; an order-decided path beats a heuristic one."""
        node_id = f"copybook:{name}"
        if node_id in self._ordered_nodes:
            return
        self._ordered_nodes.add(node_id)
        record = self.est.files.get(path)
        self.graph.nodes[node_id] = Node(node_id, "copybook", path, record.sha256 if record else "", "input")

    def _library_orders(self, ref: Ref) -> list[list[str]]:
        """Library concatenations that apply to the program writing ``ref``: one per step that runs it (its ``SYSLIB``
        DD, else the job's ``JCLLIB ORDER``), or the compile command's ``-I`` order when no JCL runs it."""
        program = _scope(ref.owner)[1].upper()
        orders: list[list[str]] = []
        for step in self.runs.get(program, []):
            syslib = [dd.target.upper() for dd in step.dds.get("SYSLIB", []) if dd.target]
            job = step.label.split(":", 1)[-1].split("/", 1)[0].upper()
            jcllib = [target for _position, target in sorted(self.est.jcllib.get(job, []))]
            if syslib or jcllib:
                orders.append(syslib or jcllib)
        if not orders:
            include = self.est.include_order.get(ref.file.rsplit("/", 1)[-1].lower())
            if include:
                orders.append(list(include))
        return orders

    def _library_winner(self, ref: Ref, candidates: list[str]) -> str:
        """The candidate every applicable library order agrees on, or ``""`` when no order decides."""
        return _shared_library_winner(candidates, self._library_orders(ref))

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
    builder.runs = _effective_runs(est)
    for record in sorted(records, key=lambda r: r.path):
        builder.node(f"file:{record.path}", "file", "input", record.path)
        if record.scan is None:
            continue
        _definition_edges(builder, record)
        for ref in record.scan.refs:
            builder.ref(record, ref)
    _step_nodes(builder, est)
    _link_copybook_declarations(builder, est)
    _bind_dd_names(builder, records)
    return GraphBuild(builder.graph, est, builder.bindings)


def _step_nodes(builder: _Builder, est: Estate) -> None:
    """Every JCL step becomes a node contained by the job or procedure that declares it, at its own source line."""
    for (kind, name), steps in sorted(est.steps.items()):
        owner = builder.node(f"{kind}:{name}", kind, "input")
        for step in sorted(steps, key=lambda s: s.label):
            dst = builder.node(f"step:{step.label}", "step", "input", step.file)
            builder.graph.add_edge(Edge(owner, dst, "contains", "JCL STEP", step.file, step.line, 1,
                                        detail=detail(label=step.label, program=step.program, proc=step.proc),
                                        rule="definition-contains", confidence="certain", scope=kind))


def _link_copybook_declarations(builder: _Builder, est: Estate) -> None:
    """A program that copies a copybook also contains everything that copybook declares (criterion 5).

    The link is evidence-backed: the edge is stamped with the ``COPY`` statement's own file, line and column, and
    with the ``REPLACING`` clause written there.  ``REPLACING`` pairs are *recorded*, not applied to the copybook's
    own declarations; a name a pair renames is additionally linked under its expanded form, because that is the name
    the including program actually sees.
    """
    for edge in list(builder.graph.edges()):
        if edge.relation != "copies" or not edge.src.startswith("program:") or not edge.dst.startswith("copybook:"):
            continue
        node = builder.graph.nodes.get(edge.dst)
        if node is None or not node.path:
            continue
        info = dict(edge.detail)
        rule = "copy-replacing" if info.get("replacing") == "yes" else "copy-no-replacing"
        pairs = [tuple(part.strip() for part in pair.split(" BY ")) for pair in info.get("replacing_pairs", "").split("; ")
                 if " BY " in pair]
        for node_id in est.declared_in.get(node.path, []):
            kind, _, rest = node_id.partition(":")
            if kind not in _UNIT_KINDS:
                continue
            name = rest.rpartition("/")[2]
            builder.graph.add_edge(Edge(edge.src, node_id, "contains", "COPY", edge.file, edge.line, edge.column,
                                        detail=detail(copybook=edge.dst.split(":", 1)[1],
                                                      replacing_pairs=info.get("replacing_pairs", "")),
                                        rule=rule, confidence="certain", scope="program"))
            for left, right in pairs:
                if left and left in name and name.replace(left, right) != name:
                    expanded = name.replace(left, right)
                    builder.graph.add_edge(Edge(edge.src, f"{kind}:{edge.src.split(':', 1)[1]}/{expanded}", "contains",
                                                "COPY REPLACING", edge.file, edge.line, edge.column,
                                                detail=detail(copybook=edge.dst.split(":", 1)[1],
                                                              replacing_pair=f"{left} BY {right}",
                                                              source_name=name),
                                                rule="copy-replacing", confidence="derived", scope="program"))


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
                                    detail=fact.detail, rule="definition-defines", confidence="certain",
                                    scope="file"))


def _bind_dd_names(builder: _Builder, records: list[FileRecord]) -> None:
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for ref in record.scan.refs:
            if ref.relation != "assigns-file" or ref.target_kind != "dd":
                continue
            _kind, program, _step = _scope(ref.owner)
            src = builder.node(f"program:{program}", "program", "input", record.path) if program else \
                builder.node(f"file:{record.path}", "file", "input", record.path)
            builder._bind_dd(src, ref, ref.target.upper(), program, relation="uses-dataset", collect=True)
