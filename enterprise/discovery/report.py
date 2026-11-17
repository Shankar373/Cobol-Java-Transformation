"""Discovery report: deterministic, source-traceable JSON plus the completeness gate and a human summary.

The report is a pure function of the checkpoint contents (and the limits in force): no clock, no absolute path, no
randomness, so the same upload always yields byte-identical artefacts.  The completeness gate says, with its checks
and evidence, whether discovery is complete enough to start modernizing; it never opens that gate on its own.
"""

from __future__ import annotations

from collections import Counter

from .graph import BLOCKING_REASONS, DependencyGraph, Edge
from .inventory import DirectoryEntry, FileRecord
from .resolve import GraphBuild
from .runtime_deps import dialect_report, runtime_dependencies

__all__ = ["REPORT_SCHEMA", "build_report", "completeness", "render_summary", "LIMITATIONS"]

REPORT_SCHEMA = "systemaops.discovery-report/1.0"

LIMITATIONS = (
    "Discovery is lexical: it reads COBOL, JCL, BMS, SQL and build text with exact positions but does not compile, "
    "execute or fully parse the programs.",
    "COPY ... REPLACING, nested copybook expansion and conditional compilation are recorded but not expanded, so "
    "statements that exist only after expansion are not seen.",
    "Names built at run time cannot be resolved statically; they are reported as dynamic targets, with candidate values "
    "taken from VALUE clauses and MOVE literals in the same program.",
    "Dialects are indicative evidence from source signals, not a compiler verdict.",
    "Datasets, DB2 tables, MQ queues, IMS PSBs and CICS resources are linked by name; their definitions are present only "
    "when the upload contains the DDL, IDCAMS, MQSC or CSD source.",
    "JCL procedures and symbols are expanded only from the same upload; cataloged procedures that are not uploaded are "
    "reported as missing, and DD overrides are honoured for the common step.dd form.",
    "Archives nested inside the upload are inventoried but not expanded.",
    "No LLM and no network access are used anywhere in discovery (apart from an explicit remote Git fetch).",
)

_SCAN_ERROR_CODES = frozenset({
    "NO_PROGRAM_ID", "PROGRAM_ID_MISSING_NAME", "EXEC_NOT_CLOSED", "UNTERMINATED_LITERAL", "JCL_NO_STATEMENTS",
    "END_PROGRAM_MISMATCH", "PROGRAM_NOT_CLOSED", "BMS_NO_MAPSET", "SCANNER_FAILED",
})


def _node_summaries(graph: DependencyGraph, kinds: set[str], relations: set[str] | None = None) -> list[dict[str, object]]:
    by_node: dict[str, list[Edge]] = {}
    for edge in graph.edges():
        node = graph.nodes.get(edge.dst)
        if node is None or node.kind not in kinds or (relations and edge.relation not in relations):
            continue
        by_node.setdefault(edge.dst, []).append(edge)
    out = []
    for node_id in sorted(by_node):
        node = graph.nodes[node_id]
        out.append({
            **node.as_dict(),
            "referenced_by": [{"clause": e.clause, "file": e.file, "from": e.src, "line": e.line, "relation": e.relation,
                               "resolution": e.resolution, **({"detail": dict(e.detail)} if e.detail else {})}
                              for e in by_node[node_id]],
        })
    return out


def _programs(records: list[FileRecord], graph: DependencyGraph) -> list[dict[str, object]]:
    out = []
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for fact in record.scan.facts:
            info = dict(fact.detail)
            if fact.category != "program-id" or info.get("kind") not in ("PROGRAM-ID", "CLASS-ID", "FUNCTION-ID",
                                                                         "INTERFACE-ID"):
                continue
            owner = f"program:{fact.name}"
            refs = [r for r in record.scan.refs if r.owner == owner]
            files = [dict(f.detail) | {"logical_file": f.name, "line": f.line} for f in record.scan.facts
                     if f.category == "file-select" and f.owner == owner]
            out.append({
                "calls": sorted({(r.target or f"<dynamic:{r.variable}>") for r in refs if r.relation == "calls"}),
                "cics": sorted({f"{r.relation}:{r.target}" for r in refs if r.relation.startswith(("cics-", "uses-map",
                                                                                                 "starts-", "uses-cics"))}),
                "copybooks": sorted({r.target for r in refs if r.relation == "copies"}),
                "db2_tables": sorted({r.target for r in refs if r.relation == "accesses-table" and r.target}),
                "file": record.path, "files": files, "ims": sorted({r.target for r in refs if r.relation == "uses-ims"}),
                "kind": info.get("kind", ""), "line": fact.line, "mq": sorted({r.target for r in refs
                                                                               if r.relation in ("uses-mq", "uses-queue")}),
                "name": fact.name, "nested": info.get("nested") == "yes", "source_format": record.source_format,
            })
    return sorted(out, key=lambda p: (str(p["name"]), str(p["file"]), int(p["line"])))  # type: ignore[call-overload]


def _jcl(records: list[FileRecord]) -> dict[str, list[dict[str, object]]]:
    jobs: list[dict[str, object]] = []
    procs: list[dict[str, object]] = []
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None or record.cls not in ("jcl-job", "jcl-proc"):
            continue
        steps = [{"line": f.line, "name": f.name, **dict(f.detail)} for f in record.scan.facts if f.category == "jcl-step"]
        for fact in record.scan.facts:
            if fact.category == "jcl-job":
                jobs.append({"file": record.path, "line": fact.line, "name": fact.name,
                             "steps": [s for s in steps if s["line"] >= fact.line]})  # type: ignore[operator]
            elif fact.category == "jcl-proc":
                procs.append({"file": record.path, "line": fact.line, "name": fact.name, "steps": steps})
        if record.cls == "jcl-proc" and not any(f.category == "jcl-proc" for f in record.scan.facts):
            procs.append({"file": record.path, "line": 1, "name": record.stem.upper(), "steps": steps})
    return {"jobs": jobs, "procedures": procs}


def _vsam(records: list[FileRecord], build: GraphBuild) -> dict[str, object]:
    clusters = []
    selects = []
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for fact in record.scan.facts:
            info = dict(fact.detail)
            if fact.category == "vsam-cluster":
                clusters.append({"file": record.path, "line": fact.line, "name": fact.name, **info})
            elif fact.category == "file-select":
                selects.append({"file": record.path, "line": fact.line, "program": fact.owner.removeprefix("program:"),
                                "logical_file": fact.name, **info})
    return {"cobol_file_selects": selects, "defined_clusters": clusters,
            "dd_bindings": sorted(build.bindings, key=lambda b: (str(b["program"]), str(b["ddname"]), str(b["step"]),
                                                                 str(b["dataset"])))}


def _build(records: list[FileRecord]) -> dict[str, list[dict[str, object]]]:
    sections: dict[str, list[dict[str, object]]] = {"compile_and_link_steps": [], "invocations": [], "targets": [],
                                                    "runtime_settings": []}
    names = {"compile-step": "compile_and_link_steps", "link-step": "compile_and_link_steps",
             "build-invocation": "invocations", "build-target": "targets", "runtime-setting": "runtime_settings"}
    for record in sorted(records, key=lambda r: r.path):
        if record.scan is None:
            continue
        for fact in record.scan.facts:
            if fact.category in names:
                sections[names[fact.category]].append({"category": fact.category, "file": record.path, "line": fact.line,
                                                       "name": fact.name, **dict(fact.detail)})
    return sections


def completeness(records: list[FileRecord], graph: DependencyGraph, *, checkpoint_ok: bool, expected_files: int,
                 diagnostics_dropped: int = 0) -> dict[str, object]:
    """The gate: ``INCOMPLETE`` (blockers), ``COMPLETE_WITH_OPEN_ITEMS`` or ``COMPLETE``; never a guess."""
    problems = [(r.path, p) for r in records if r.scan for p in r.scan.problems]
    errors = [(path, p) for path, p in problems if p.code in _SCAN_ERROR_CODES]
    not_scanned = [r for r in records if r.blocker and r.cls != "binary"]
    unresolved = graph.unresolved()
    blocking = [e for e in unresolved if e.reason in BLOCKING_REASONS]
    archives = [r.path for r in records if r.cls == "archive"]
    unknown = [r.path for r in records if r.cls == "unknown"]
    low_confidence = [r.path for r in records if r.encoding_confidence == "low" and r.cls in ("cobol", "copybook", "jcl-job",
                                                                                              "jcl-proc")]
    checks = [
        _check("checkpoint-verified", checkpoint_ok, "the preserved source re-hashes to the recorded digest"),
        _check("every-file-inventoried", len(records) == expected_files, f"{len(records)} of {expected_files} files"),
        _check("every-source-file-scanned", not not_scanned, f"{len(not_scanned)} file(s) not scanned"),
        _check("no-scanner-errors", not errors, f"{len(errors)} scanner error(s)"),
        _check("no-blocking-unresolved-references", not blocking, f"{len(blocking)} blocking unresolved reference(s)"),
        _check("no-unexpanded-archives", not archives, f"{len(archives)} nested archive(s) not expanded"),
    ]
    blockers = [c["id"] for c in checks if not c["passed"]]
    open_items = [
        {"count": len([e for e in unresolved if e.reason not in BLOCKING_REASONS]), "id": "non-blocking-unresolved",
         "detail": "references to catalog objects or dynamic targets the upload cannot resolve"},
        {"count": len(graph.ambiguous()), "id": "ambiguous-references", "detail": "references with several candidates"},
        {"count": len(unknown), "id": "unclassified-files", "detail": "files no rule classified"},
        {"count": len(low_confidence), "id": "low-confidence-encoding", "detail": "source decoded by a fallback code page"},
        {"count": len([p for _, p in problems if p.code not in _SCAN_ERROR_CODES]), "id": "scanner-warnings",
         "detail": "constructs the scanners did not recognise"},
        {"count": diagnostics_dropped, "id": "diagnostics-truncated", "detail": "diagnostics suppressed by the cap"},
    ]
    open_items = [item for item in open_items if item["count"]]
    status = "INCOMPLETE" if blockers else ("COMPLETE_WITH_OPEN_ITEMS" if open_items else "COMPLETE")
    return {
        "blockers": blockers, "blocking_references": [e.as_dict() for e in blocking[:200]], "checks": checks,
        "open_items": open_items,
        "ready_for_transformation": not blockers,
        "status": status,
    }


def _check(check_id: str, passed: bool, detail: str) -> dict[str, object]:
    return {"detail": detail, "id": check_id, "passed": bool(passed)}


def build_report(*, checkpoint: dict[str, object], provenance: dict[str, object], records: list[FileRecord],
                 directories: list[DirectoryEntry], build: GraphBuild, diagnostics: list[dict[str, object]],
                 limits: dict[str, object], checkpoint_ok: bool, tool_version: str) -> dict[str, object]:
    graph = build.graph
    by_class = Counter(r.cls for r in records)
    gate = completeness(records, graph, checkpoint_ok=checkpoint_ok, expected_files=int(checkpoint["file_count"]),  # type: ignore[call-overload]
                        diagnostics_dropped=sum(1 for d in diagnostics if d.get("code") == "DIAGNOSTICS_TRUNCATED"))
    scanner_problems = [{"code": p.code, "file": r.path, "line": p.line, "message": p.message}
                        for r in sorted(records, key=lambda r: r.path) if r.scan for p in r.scan.problems]
    return {
        "build": _build(records),
        "checkpoint": checkpoint,
        "cics": _node_summaries(graph, {"transaction", "cics-file", "bms-mapset", "bms-map", "cics-queue"})
        + _node_summaries(graph, {"program"}, {"cics-link", "cics-xctl", "cics-load"}),
        "completeness": gate,
        "datasets": _node_summaries(graph, {"dataset", "vsam-cluster", "uss-path", "external-file"}),
        "db2": {"plans": _node_summaries(graph, {"db2-plan", "dbrm", "db2-subsystem"}),
                "tables": _node_summaries(graph, {"table"}, {"accesses-table", "defines-table"}),
                "stored_procedures": _node_summaries(graph, {"stored-procedure"})},
        "dependency_graph": graph.stats(),
        "dialects": dialect_report(records),
        "diagnostics": diagnostics,
        "ims": _node_summaries(graph, {"ims-interface", "ims-psb", "ims-segment"}),
        "jcl": _jcl(records),
        "limitations": list(LIMITATIONS),
        "limits": limits,
        "mq": _node_summaries(graph, {"mq-interface", "mq-queue", "mq-object"}),
        "programs": _programs(records, graph),
        "provenance": provenance,
        "runtime_dependencies": runtime_dependencies(records),
        "scanner_problems": scanner_problems,
        "schema_version": REPORT_SCHEMA,
        "summary": {
            "bytes": sum(r.size for r in records), "directories": len(directories), "files": len(records),
            "files_by_class": dict(sorted(by_class.items())),
            "scanned": sum(1 for r in records if r.scan is not None),
            "source_formats": dict(sorted(Counter(r.source_format for r in records if r.source_format).items())),
        },
        "tool": {"name": "systemaops-discovery", "version": tool_version},
        "utilities": _node_summaries(graph, {"utility", "runtime"}),
        "vsam": _vsam(records, build),
    }


def render_summary(report: dict[str, object]) -> str:
    """Deterministic Markdown summary of ``report`` for people (the JSON is the contract)."""
    gate = report["completeness"]
    summary = report["summary"]
    stats = report["dependency_graph"]
    lines = [
        "# Discovery summary", "",
        f"- Checkpoint: `{report['checkpoint']['checkpoint_id']}` (source digest `{report['checkpoint']['source_digest'][:16]}...`)",  # type: ignore[index]
        f"- Files: {summary['files']} in {summary['directories']} directories ({summary['bytes']} bytes)",  # type: ignore[index]
        f"- Gate: **{gate['status']}** (ready for transformation: {'yes' if gate['ready_for_transformation'] else 'no'})",  # type: ignore[index]
        f"- Dependency graph: {stats['nodes']} nodes, {stats['edges']} edges, "  # type: ignore[index]
        f"{stats['blocking_unresolved']} blocking unresolved",  # type: ignore[index]
        "", "## Files by class", "",
    ]
    for cls, count in summary["files_by_class"].items():  # type: ignore[index, union-attr]
        lines.append(f"- {cls}: {count}")
    lines += ["", "## Completeness checks", ""]
    for check in gate["checks"]:  # type: ignore[index, union-attr]
        lines.append(f"- [{'x' if check['passed'] else ' '}] {check['id']}: {check['detail']}")
    if gate["open_items"]:  # type: ignore[index]
        lines += ["", "## Open items", ""]
        lines += [f"- {item['id']}: {item['count']} ({item['detail']})" for item in gate["open_items"]]  # type: ignore[index, union-attr]
    lines += ["", "## Limitations", ""] + [f"- {text}" for text in report["limitations"]]  # type: ignore[union-attr]
    return "\n".join(lines) + "\n"
