"""Application Blueprint (ADR-0014): one content-addressed description of the whole estate, derived from the discovery artefacts.

A pure function of the (already scrubbed) discovery report, the stamped graph document and the bytes of the other artefacts: it adds no
fact that is absent from them, reads no file, uses no clock and names no absolute path.  Bulky artefacts are referenced by ``sha256`` and
size, not copied; bounded lists carry a ``*_total`` so a cut is never silent.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import __version__
from .graph import canonical_bytes
from .kg_export import FORMATS

__all__ = ["BLUEPRINT_SCHEMA", "BLUEPRINT_ARTEFACTS", "build_blueprint", "blueprint_id_of", "verify_blueprint"]

BLUEPRINT_SCHEMA = "systemaops.application-blueprint/1.0"
#: Artefacts the blueprint references (the blueprint itself is excluded: it cannot hash itself).
BLUEPRINT_ARTEFACTS = ("report", "graph", "inventory", "unresolved", "compatibility", "applications", "readiness", "summary")
MAX_BLOCKING_REFERENCES = 200
_VSAM_KIND = "vsam-cluster"
_PROGRAM_KEYS = ("name", "file", "line", "kind", "source_format", "calls", "copybooks", "db2_tables", "cics", "mq", "ims")


def blueprint_id_of(body: Mapping[str, Any]) -> str:
    """Content address of a blueprint body (the document without its own ``blueprint_id``)."""
    return hashlib.sha256(canonical_bytes(dict(body))).hexdigest()


def verify_blueprint(document: Mapping[str, Any]) -> bool:
    """True when the document's ``blueprint_id`` is the hash of everything else in it."""
    claimed = document.get("blueprint_id")
    if not isinstance(claimed, str):
        return False
    return claimed == blueprint_id_of({k: v for k, v in document.items() if k != "blueprint_id"})


def _count(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(v) for v in values).items()))


def _resource_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Node summaries without their evidence lists: id, kind, origin and how many references point at the node."""
    return [{"id": r["id"], "kind": r["kind"], "origin": r["origin"], "references": len(r.get("referenced_by", ()))} for r in rows]


def _artefact_refs(texts: Mapping[str, str], files: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    refs = {}
    for name in BLUEPRINT_ARTEFACTS:
        data = texts[name].encode("utf-8")
        refs[name] = {"bytes": len(data), "file": files[name], "sha256": hashlib.sha256(data).hexdigest()}
    return refs


def _unresolved(edges: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unresolved = [e for e in edges if e.get("resolution") == "unresolved"]
    blocking = sorted((e for e in unresolved if e.get("blocking")), key=lambda e: (e["file"], e["line"], e["to"], e["from"]))
    return {
        "ambiguous": sum(1 for e in edges if e.get("resolution") == "ambiguous"),
        "blocking": len(blocking),
        "blocking_references": [{"file": e["file"], "from": e["from"], "line": e["line"], "reason": e.get("reason", ""), "to": e["to"]}
                                for e in blocking[:MAX_BLOCKING_REFERENCES]],
        "blocking_total": len(blocking),
        "by_reason": _count(e.get("reason", "") for e in unresolved),
        "non_blocking": len(unresolved) - len(blocking),
        "total": len(unresolved),
    }


def _application_rows(report: Mapping[str, Any], edges: Sequence[Mapping[str, Any]], kinds: Mapping[str, str]) -> list[dict[str, Any]]:
    by_file: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in edges:
        by_file[str(edge["file"])].append(edge)
    rows = []
    for app in report["applications"]["applications"]:
        own = [e for f in app["files"] for e in by_file.get(f, ())]
        resources = app["resources"]
        rows.append({
            "architecture": {"dependency_kinds": _count(kinds.get(str(e["to"]), "unknown") for e in own), "edges": len(own),
                             "relations": _count(e["relation"] for e in own)},
            "blocking_unresolved": app["blocking_unresolved"], "compile_errors": app["compile_errors"],
            "compiler_verdicts": app["compiler_verdicts"], "copybooks": app["copybooks"], "entry_points": app["entry_points"],
            "files": len(app["files"]), "id": app["id"], "jobs": app["jobs"], "name": app["name"], "programs": app["programs"],
            "readiness": app["readiness"], "resource_kinds": _count(r["kind"] for r in resources), "resources": resources,
            "unresolved_total": app["unresolved_total"], "unsupported_features": app["unsupported_features"],
            "unverified": app["unverified"],
        })
    return rows


def _program_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    profiles = {str(p["file"]): str(p["profile_id"]) for p in report.get("dialects", {}).get("profiles", []) if p.get("profile_id")}
    return [{**{k: p.get(k, "" if k in ("name", "file", "kind", "source_format") else []) for k in _PROGRAM_KEYS},
             "logical_files": sorted({str(f.get("logical_file", "")) for f in p.get("files", [])}),
             "profile_id": profiles.get(str(p["file"]), "")} for p in report["programs"]]


def build_blueprint(report: Mapping[str, Any], graph_document: Mapping[str, Any], texts: Mapping[str, str],
                    files: Mapping[str, str]) -> dict[str, Any]:
    """The blueprint of one discovery.

    ``texts`` maps every name in :data:`BLUEPRINT_ARTEFACTS` to the exact text written for it and ``files`` to its file name; ``report`` is
    the scrubbed report and ``graph_document`` the scrubbed, id-stamped graph, so every digest below names bytes that exist on disk.
    """
    nodes, edges = list(graph_document["nodes"]), list(graph_document["edges"])
    kinds = {str(n["id"]): str(n["kind"]) for n in nodes}
    graph_id = str(graph_document["header"]["graph_id"])
    provenance, checkpoint = report["provenance"], report["checkpoint"]
    summary = report["summary"]
    datasets = report["datasets"]
    db2 = report["db2"]
    cics = report["cics"]
    stats = {k: v for k, v in report["dependency_graph"].items() if k != "graph_id"}
    body: dict[str, Any] = {
        "applications": _application_rows(report, edges, kinds),
        "architecture": {"export_formats": list(FORMATS), "graph_id": graph_id, "node_kinds": _count(kinds.values()),
                         "relations": _count(e["relation"] for e in edges), "stats": stats},
        "artefacts": _artefact_refs(texts, files),
        "build": {"compile_and_link_steps": report["build"]["compile_and_link_steps"], "invocations": report["build"]["invocations"],
                  "runtime_dependencies": report["runtime_dependencies"], "runtime_settings": report["build"]["runtime_settings"],
                  "targets": report["build"]["targets"], "toolchain_required": report["toolchain"]["required"]},
        "completeness": report["completeness"],
        "entry_points": report["applications"]["entry_points"],
        "estate": {"bytes": summary["bytes"], "directories": summary["directories"], "files": summary["files"],
                   "files_by_class": summary["files_by_class"], "scanned": summary["scanned"],
                   "source_formats": summary["source_formats"]},
        "identity": {"checkpoint_id": checkpoint["checkpoint_id"], "graph_id": graph_id, "source_digest": checkpoint["source_digest"],
                     "source": {k: provenance.get(k, "") for k in ("kind", "origin", "ref", "commit", "tree_id", "archive_sha256")}},
        "integrations": {"cics": _resource_rows(cics), "ims": _resource_rows(report["ims"]), "mq": _resource_rows(report["mq"]),
                         "utilities": _resource_rows(report["utilities"])},
        "limitations": report["limitations"],
        "programs": _program_rows(report),
        "readiness": report["readiness"],
        "relationships": report["applications"]["relationships"],
        "resources": {"datasets": _resource_rows([d for d in datasets if d["kind"] != _VSAM_KIND]),
                      "db2": {"plans": _resource_rows(db2["plans"]), "stored_procedures": _resource_rows(db2["stored_procedures"]),
                              "tables": _resource_rows(db2["tables"])},
                      "vsam": _resource_rows([d for d in datasets if d["kind"] == _VSAM_KIND])},
        "schema_version": BLUEPRINT_SCHEMA,
        "tool": {"name": "systemaops-discovery", "version": __version__},
        "unresolved": _unresolved(edges),
    }
    return {**body, "blueprint_id": blueprint_id_of(body)}
