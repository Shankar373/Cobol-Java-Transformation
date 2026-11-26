"""Discovery-backed readiness of an application's source tree, shared by every downstream modernization entry point.

``assess_workspace`` runs the complete discovery workflow (immutable checkpoint, inventory, dependency graph, open-source compiler
check) over a source directory and returns a small readiness record.  ``Service`` stores one record per source tree and re-uses it
until the tree changes (a cheap size/mtime fingerprint), so modernize and revalidate consult the same evidence that the ingest screen
showed.  A tree that cannot be assessed (limits, unreadable files) is ``BLOCKED`` with the reason, never silently ready.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.errors import IngestionError
from enterprise.discovery.readiness import describe_blockers

logger = logging.getLogger(__name__)

#: Public keys of a readiness record (the API never returns local paths).
PUBLIC_KEYS = ("status", "allowed", "blockers", "blocking_references", "unsupported_total", "unsupported", "compile_errors",
               "unverified_total", "unverified", "applications", "checkpoint_id", "source_digest", "blueprint_id", "discovery_run_id", "gate_status", "toolchain")


#: Bump when the readiness policy changes: stored records of an older policy are re-assessed.
POLICY_VERSION = "6"  # 6: and blueprint_id; 3: records carry library_orders and dialect_profiles for the engine bridge; 4: and graph_id; 5: and graph_artifact
_CHUNK = 1 << 20


def is_transient(record: dict[str, Any]) -> bool:
    """An unexpected discovery failure: never cached, so the next request assesses again."""
    return any(b.get("id") == "discovery-failed:INTERNAL_ERROR" for b in record.get("blockers", []))


def _tree_lines(workspace: Path) -> list[str]:
    """One line per file (relative path and content SHA-256), in a stable order."""
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            content = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(_CHUNK), b""):
                        content.update(chunk)
            except OSError:
                content.update(b"unreadable")
            lines.append(f"{path.relative_to(workspace).as_posix()}\0{content.hexdigest()}\n")
    return lines


def content_digest(workspace: Path) -> str:
    """SHA-256 of the tree's paths and file contents alone (no policy or toolchain input): what an ingested source is pinned to."""
    digest = hashlib.sha256()
    for line in _tree_lines(workspace):
        digest.update(line.encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def fingerprint(workspace: Path) -> str:
    """Change detector for a source tree: relative path and SHA-256 of the *content* of every file, the assessing toolchain setting and the
    policy version. Content, not size/mtime: an edit that keeps both (or restores the mtime) still invalidates a stored READY."""
    from enterprise.discovery.compilers import ToolchainConfig

    config = ToolchainConfig.from_environment()
    digest = hashlib.sha256(f"policy={POLICY_VERSION}\0backend={config.backend}\0image={config.image}\n".encode())
    for dirpath, dirnames, filenames in os.walk(workspace):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            content = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(_CHUNK), b""):
                        content.update(chunk)
            except OSError:
                content.update(b"unreadable")
            digest.update(f"{path.relative_to(workspace).as_posix()}\0{content.hexdigest()}\n".encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def blocked_record(code: str, message: str) -> dict[str, Any]:
    """A readiness record for a tree discovery could not assess."""
    return {"allowed": False, "applications": [], "blocking_references": [], "blockers": [{"detail": message[:200], "id": f"discovery-failed:{code}"}],
            "checkpoint_id": "", "compile_errors": [], "discovery_run_id": "", "gate_status": "INCOMPLETE", "source_digest": "",
            "status": "BLOCKED", "toolchain": {}, "unsupported": [], "unsupported_total": 0, "unverified": [], "unverified_total": 0}


def assess_workspace(workspace: Path, label: str) -> dict[str, Any]:
    """Run discovery over ``workspace`` and return its readiness record (``BLOCKED`` when discovery itself is refused)."""
    from api.discovery_routes import get_service, seal_key_problem

    problem = seal_key_problem()
    if problem:
        return blocked_record("STORE_KEY_REQUIRED", problem)
    service = get_service()
    try:
        result = discover(DiscoveryRequest("directory", str(workspace), label=label[:80]), service.store, limits=service.limits)
    except IngestionError as exc:
        logger.warning("readiness assessment refused (%s)", exc.code)
        return blocked_record(exc.code, exc.message)
    except Exception:  # noqa: BLE001 - an assessment failure must block, and must not leak internals
        logger.exception("readiness assessment failed")
        return blocked_record("INTERNAL_ERROR", "discovery failed unexpectedly")
    readiness = result.report["readiness"]
    run = service.register_result(result, kind="directory", label=label)
    tools = result.report["compatibility"]["backend"]
    record = {key: readiness.get(key) for key in ("status", "allowed", "blockers", "blocking_references", "unsupported_total", "unsupported",
                                                  "compile_errors", "unverified_total", "unverified", "applications")}
    record.update(checkpoint_id=result.checkpoint.checkpoint_id, source_digest=result.checkpoint.source_digest,
                  discovery_run_id=run.run_id, gate_status=result.report["completeness"]["status"],
                  toolchain={"backend": tools["kind"], "version": tools.get("version", "")})
    record.update(library_orders=library_orders_record(result.library_orders),
                  dialect_profiles=profile_pairs(result.report),
                  blueprint_id=result.blueprint_id,
                  graph_id=str(result.report.get("dependency_graph", {}).get("graph_id", "")),
                  graph_artifact=str(result.outdir / result.outputs["graph"]) if result.outputs.get("graph") else "")
    return record


def library_orders_record(orders: dict[str, tuple[tuple[str, ...], ...]]) -> dict[str, list[list[str]]]:
    """Discovery's per-program library orders as JSON-safe plain data (sorted by program)."""
    return {program: [list(order) for order in orders[program]] for program in sorted(orders)}


def profile_pairs(report: dict[str, Any]) -> list[list[str]]:
    """``[[file, profile_id], ...]`` sorted by file, read straight from the discovery report's DialectProfiles
    (``report['dialects']['profiles']``): the dialect/format authority is discovery, nothing is re-derived here."""
    profiles = report.get("dialects", {}).get("profiles", [])
    return sorted([str(p["file"]), str(p["profile_id"])] for p in profiles if p.get("profile_id"))


def engine_wiring(record: dict[str, Any]) -> tuple[tuple[tuple[str, tuple[tuple[str, ...], ...]], ...], tuple[tuple[str, str], ...]]:
    """``(library_orders, dialect_profiles)`` of a readiness record as the immutable plain-data tuples the engine
    configs take; both empty for a record without them (older or blocked records never invent facts)."""
    orders = record.get("library_orders") or {}
    library_orders = tuple((str(program), tuple(tuple(str(name) for name in order) for order in value))
                           for program, value in sorted(orders.items()))
    profiles = tuple(sorted((str(pair[0]), str(pair[1])) for pair in record.get("dialect_profiles") or ()))
    return library_orders, profiles


#: Bounds on the Layer 5 facts build inside a run (a tree over either is not read: no claim is made, never a partial one).
SEMANTIC_MAX_FILES = 2000
SEMANTIC_MAX_BYTES = 4_000_000


JCL_SUFFIXES = (".jcl", ".job", ".proc", ".prc", ".jclproc")


def _graph_artifact_is_genuine(candidate: dict[str, Any], graph_id: str) -> bool:
    """The artefact's nodes and edges hash to the record's ``graph_id`` (its header string alone is not trusted)."""
    from enterprise.discovery.graph import graph_id_of

    try:
        recomputed = graph_id_of(list(candidate.get("nodes", [])), list(candidate.get("edges", [])))
    except (TypeError, ValueError):
        return False
    return recomputed == graph_id == str((candidate.get("header") or {}).get("graph_id", ""))


def semantic_document(source: str, record: dict[str, Any]):
    """The Layer 5 facts document built from ``source``'s COBOL program texts under the record's checkpoint, source digest,
    graph id and dialect profiles, or ``None`` (no claim) when there is nothing to read, a file is not valid UTF-8, or the
    tree exceeds the bounds above.

    For a directory, the discovery graph artefact the readiness assessment wrote (``record["graph_artifact"]``) is read and,
    when its ``header.graph_id`` is the record's, the file, SQL and JCL facts are read from it (``header.graph_bound``); a
    missing, unreadable or foreign graph is not used.
    """
    from pathlib import Path

    from engine.semantic_facts.build import COBOL_SUFFIXES, build_semantic_facts

    root = Path(source)
    if root.is_file():
        files, base = [root], root.parent
    elif root.is_dir():
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in COBOL_SUFFIXES)
        base = root
    else:
        return None
    if not files or len(files) > SEMANTIC_MAX_FILES:
        return None
    texts: dict[str, str] = {}
    total = 0
    for path in files:
        try:
            raw = path.read_bytes()
            total += len(raw)
            if total > SEMANTIC_MAX_BYTES:
                return None
            texts[path.relative_to(base).as_posix()] = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    profiles = engine_wiring(record)[1]
    graph_id = dict(graph_lineage(record)).get("graph_id", "")
    graph = None
    jcl: dict[str, str] = {}
    artifact = str(record.get("graph_artifact") or "")
    if root.is_dir() and graph_id and artifact:
        import json

        try:
            candidate = json.loads(Path(artifact).read_text(encoding="utf-8"))
        except (OSError, ValueError):  # a graph artefact that is gone or unreadable is simply not used
            candidate = None
        if isinstance(candidate, dict) and _graph_artifact_is_genuine(candidate, graph_id):
            graph = candidate
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in JCL_SUFFIXES and path.stat().st_size <= SEMANTIC_MAX_BYTES:
                    try:
                        jcl[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
    return build_semantic_facts(
        texts, checkpoint_id=str(record.get("checkpoint_id", "")), source_digest=str(record.get("source_digest", "")),
        graph_id=graph_id, profile_ids=profiles, graph=graph, jcl_sources=jcl)


def _semantic_pairs(document: Any, record: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    from engine.evidence.integrity import profiles_digest

    profiles = engine_wiring(record)[1]
    graph_id = dict(graph_lineage(record)).get("graph_id", "")
    return tuple(sorted((
        ("facts_digest", document.facts_digest), ("graph_id", graph_id),
        ("profiles_digest", profiles_digest(profiles)), ("semantic_id", document.semantic_id))))


def semantic_lineage(source: str, record: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """``semantic_facts`` pairs for the evidence manifest (see :func:`semantic_document`); ``()`` when no document."""
    document = semantic_document(source, record)
    return () if document is None else _semantic_pairs(document, record)


def document_lineage(source: str, record: dict[str, Any]) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """``(semantic_facts pairs, application_ir pairs)`` from ONE facts document: the Application IR is its projection, so
    the two are recorded together or not at all.  ``((), ())`` when there is no document."""
    from engine.application_ir.project import ir_id_of, project

    document = semantic_document(source, record)
    if document is None:
        return (), ()
    ir = project(document.as_dict())
    return _semantic_pairs(document, record), tuple(sorted((("ir_id", ir_id_of(ir)), ("semantic_id", document.semantic_id))))


def graph_lineage(record: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """``(("graph_id", id),)`` of the discovery graph the readiness gate assessed, or ``()`` for a record without one.

    This is the lineage the sealed evidence manifest can honestly state today: the run generated from the source
    tree whose discovery produced that graph (same content-addressed source).  It is *not* the traceability overlay
    (generated class -> graph node), which needs the graph file and fails a run closed; the overlay id stays absent.
    """
    graph_id = str(record.get("graph_id") or "")
    return (("graph_id", graph_id),) if graph_id else ()


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in PUBLIC_KEYS}


def refusal_message(record: dict[str, Any]) -> str:
    return "Modernization is blocked until discovery is complete: " + describe_blockers(record)
