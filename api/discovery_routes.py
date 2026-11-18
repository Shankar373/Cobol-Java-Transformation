"""COBOL estate discovery routes.

    POST /discovery/runs/zip        upload a ZIP (multipart) -> 202 run
    POST /discovery/runs/git        remote Git URL + optional branch/tag/commit -> 202 run
    GET  /discovery/runs            recent runs
    GET  /discovery/runs/{id}       state, steps, gate
    GET  /discovery/runs/{id}/{artefact}   report | graph | inventory | unresolved | summary
    POST /discovery/runs/{id}/verify       re-hash the immutable checkpoint
    GET  /discovery/runs/{id}/kg[...]      knowledge graph: snapshot | nodes | node | neighbors | impact | path |
                                            slice | diff | export   (read-only, viewer)

Local directory and ``file://`` inputs are deliberately not accepted here: they would let a caller read the server's
own filesystem.  Authentication and role checks are the control plane's middleware, which covers every path; reads are
``viewer``, submissions and re-verification are ``operator``.  Runs execute on a bounded worker pool and are durable.
The ``/kg`` routes are declared **before** ``/{artefact}`` so the generic artefact matcher can never swallow them.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from api.ingestion import _get_max_zip_archive_bytes, _get_max_zip_compression_ratio, _get_max_zip_entries
from api.ingestion import _get_max_total_extracted_bytes
from api.paths import workspace_root
from enterprise.discovery import kg_export as kg_export_module
from enterprise.discovery import kg_query
from enterprise.discovery.kg_store import KGStore
from enterprise.discovery.limits import DEFAULT_LIMITS, Limits
from enterprise.discovery.runs import ARTEFACTS, DiscoveryRunService, RunNotFound

router = APIRouter()
_CHUNK = 1 << 20
#: Bounds on caller-chosen kg paging/traversal parameters (an out-of-range value is a 422, never a 500).
KG_MAX_LIMIT = 5000
KG_MAX_OFFSET = 10_000_000
KG_MAX_DEPTH = 1000
_service: DiscoveryRunService | None = None


class GitRun(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    ref: str | None = Field(default=None, max_length=256)
    label: str | None = Field(default=None, max_length=80)


def _limits() -> Limits:
    """Discovery limits that follow the control plane's configured ZIP limits (one set of knobs)."""
    return Limits(
        max_entries=_get_max_zip_entries(), max_total_bytes=_get_max_total_extracted_bytes(),
        max_entry_bytes=min(DEFAULT_LIMITS.max_entry_bytes, _get_max_total_extracted_bytes()),
        max_compression_ratio=float(_get_max_zip_compression_ratio()))


def get_service() -> DiscoveryRunService:
    global _service
    if _service is None:
        root = workspace_root()
        base = (root / "discovery") if root else Path(tempfile.mkdtemp(prefix="discovery-runs-"))
        _service = DiscoveryRunService(base, limits=_limits())
    return _service


def reset_service_for_tests(service: DiscoveryRunService | None = None) -> None:
    global _service
    _service = service


def _run_or_404(run_id: str):
    try:
        return get_service().get(run_id)
    except RunNotFound:
        raise HTTPException(404, "Discovery run not found") from None


@router.post("/discovery/runs/zip", status_code=202)
async def submit_zip(request: Request, file: UploadFile = File(...), label: str | None = Form(default=None)) -> dict:
    limit = _get_max_zip_archive_bytes()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit + 1_000_000:
        raise HTTPException(413, f"Archive exceeds the {limit} byte limit")
    service = get_service()
    run_id, target = service.new_upload_path()
    received = 0
    try:
        with target.open("wb") as sink:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                received += len(chunk)
                if received > limit:
                    raise HTTPException(413, f"Archive exceeds the {limit} byte limit")
                sink.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if received == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded archive is empty")
    return service.submit_zip(run_id, target, label or (file.filename or "upload")).as_dict()


@router.post("/discovery/runs/git", status_code=202)
def submit_git(body: GitRun) -> dict:
    url = body.url.strip()
    if not url.lower().startswith("https://"):
        raise HTTPException(400, "Only https:// Git URLs are accepted")
    return get_service().submit_git(url, body.ref, body.label).as_dict()


@router.get("/discovery/runs")
def list_runs() -> dict:
    return {"runs": [record.as_dict() for record in get_service().list()]}


@router.get("/discovery/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _run_or_404(run_id).as_dict()


@router.post("/discovery/runs/{run_id}/verify")
def verify_run(run_id: str) -> dict:
    try:
        return get_service().verify(run_id)
    except RunNotFound:
        raise HTTPException(404, "Discovery run not found or not finished") from None


@router.get("/discovery/runs/{run_id}/source")
def get_source(run_id: str, path: str, line: int = 1, context: int = 12) -> dict:
    """Lines of one inventoried source file around ``line``, read from the immutable checkpoint (never from a client-chosen path)."""
    try:
        return get_service().source_excerpt(run_id, path, line, context)
    except RunNotFound:
        raise HTTPException(404, "Discovery run, file or line not found") from None


@router.get("/discovery/runs/{run_id}/kg")
def kg_snapshot(run_id: str) -> dict:
    """Snapshot identity and row counts — metadata only, the stored document is never read."""
    store, graph_id = _kg_snapshot(run_id)
    meta = next((row for row in store.list_snapshots() if row["graph_id"] == graph_id), None)
    if meta is None:  # pragma: no cover - the snapshot is written with the run
        raise HTTPException(404, "Knowledge graph snapshot not found")
    return {**meta, "counts": store.counts(graph_id)}


@router.get("/discovery/runs/{run_id}/kg/nodes")
def kg_nodes(run_id: str, kind: str | None = None, limit: int = Query(500, ge=0, le=KG_MAX_LIMIT),
             offset: int = Query(0, ge=0, le=KG_MAX_OFFSET)) -> dict:
    """Node rows from the index, filtered and paged in SQL (never by loading the document)."""
    store, graph_id = _kg_snapshot(run_id)
    try:
        rows = store.nodes(graph_id, kind=kind, limit=limit, offset=offset)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {"graph_id": graph_id, "count": len(rows), "nodes": rows}


@router.get("/discovery/runs/{run_id}/kg/node")
def kg_node(run_id: str, id: str) -> dict:
    """One node with the edges that touch it, both read from the row tables."""
    store, graph_id = _kg_snapshot(run_id)
    found = [row for row in store.nodes(graph_id, kind=None, limit=None) if row["id"] == id]
    if not found:
        raise HTTPException(404, "No such node in this snapshot")
    return {
        "graph_id": graph_id, "node": found[0],
        "outgoing": store.edges(graph_id, src=id, limit=None),
        "incoming": store.edges(graph_id, dst=id, limit=None),
    }


@router.get("/discovery/runs/{run_id}/kg/neighbors")
def kg_neighbors(run_id: str, node: str, direction: str = "both", relation: str | None = None,
                 limit: int = Query(500, ge=0, le=KG_MAX_LIMIT)) -> dict:
    """Adjacent node ids, one hop, answered from ``kg_edge`` alone (no document is loaded)."""
    store, graph_id = _kg_snapshot(run_id)
    if direction not in ("out", "in", "both"):
        raise HTTPException(400, f"unknown direction {direction!r}")
    if not node:
        raise HTTPException(400, "node is required")
    try:
        rows = store.edges(graph_id, relation=relation, limit=None)
    except TypeError as exc:
        raise HTTPException(400, str(exc)) from None
    found: set[str] = set()
    for row in rows:
        if direction in ("out", "both") and row["src"] == node:
            found.add(row["dst"])
        if direction in ("in", "both") and row["dst"] == node:
            found.add(row["src"])
    ordered = sorted(found)
    return {"graph_id": graph_id, "node": node, "direction": direction, "count": len(ordered[:limit]),
            "neighbors": ordered[:limit]}


@router.get("/discovery/runs/{run_id}/kg/impact")
def kg_impact(run_id: str, node: str, direction: str = "in",
              depth: int | None = Query(None, ge=0, le=KG_MAX_DEPTH)) -> dict:
    """Transitive impact of ``node`` (upstream by default): the set a change to it would reach."""
    if not node:
        raise HTTPException(400, "node is required")
    document = _kg_document(run_id)
    try:
        found = kg_query.impact(document, node, direction=direction, depth=depth)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {"graph_id": document["header"]["graph_id"], "node": node, "direction": direction, "depth": depth,
            "count": len(found), "impact": sorted(found)}


@router.get("/discovery/runs/{run_id}/kg/path")
def kg_path(run_id: str, src: str, dst: str, direction: str = "both") -> dict:
    """A shortest path between two nodes, or an empty list when none exists."""
    if not src or not dst:
        raise HTTPException(400, "src and dst are required")
    document = _kg_document(run_id)
    try:
        walk = kg_query.path(document, src, dst, direction=direction)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    return {"graph_id": document["header"]["graph_id"], "src": src, "dst": dst, "direction": direction,
            "found": bool(walk), "path": walk}


@router.get("/discovery/runs/{run_id}/kg/slice")
def kg_slice(run_id: str, node: str, depth: int | None = Query(None, ge=0, le=KG_MAX_DEPTH)) -> dict:
    """The subgraph around ``node``, with its own ``graph_id`` and this snapshot as its parent."""
    if not node:
        raise HTTPException(400, "node is required")
    document = _kg_document(run_id)
    try:
        return kg_query.slice(document, node, depth=depth)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/discovery/runs/{run_id}/kg/diff")
def kg_diff(run_id: str, against: str | None = None) -> dict:
    """Added/removed/changed nodes and edges going from ``against`` to this snapshot (empty for identical input)."""
    store, graph_id = _kg_snapshot(run_id)
    if not against:
        against = _previous_snapshot(store, graph_id)
        if against is None:
            raise HTTPException(400, "there is no earlier snapshot to compare against")
    try:
        other = store.load(against)
    except KeyError:
        raise HTTPException(404, "The comparison snapshot is not stored") from None
    result = kg_query.diff(other, _kg_document(run_id))
    return {"graph_id": graph_id, "against": against,
            "nodes": {bucket: sorted(values) for bucket, values in result["nodes"].items()},
            "edges": {bucket: sorted(values) for bucket, values in result["edges"].items()}}


@router.get("/discovery/runs/{run_id}/kg/export")
def kg_export(run_id: str, format: str = "json") -> Response:
    """The snapshot in ``json``, ``dot``, ``graphml`` or ``csv``; an unknown format is a 400, never a guess."""
    if format not in kg_export_module.FORMATS:
        raise HTTPException(400, f"unknown export format {format!r}")
    document = _kg_document(run_id)
    media, filename = _EXPORT_FILES[format]
    return Response(content=kg_export_module.export(document, format), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


_EXPORT_FILES: dict[str, tuple[str, str]] = {
    "json": ("application/json", "knowledge-graph.json"),
    "dot": ("text/vnd.graphviz", "knowledge-graph.dot"),
    "graphml": ("application/xml", "knowledge-graph.graphml"),
    "csv": ("text/csv", "knowledge-graph.csv"),
}


def _kg_snapshot(run_id: str) -> tuple[KGStore, str]:
    """The run's stored snapshot; materialised from the checkpoint artefact for a run stored before Layer 3."""
    service = get_service()
    record = _run_or_404(run_id)
    if record.state != "succeeded":
        raise HTTPException(404, "Discovery run not found or not finished")
    graph_id = str(record.summary.get("graph_id", ""))
    if graph_id:
        try:
            service.kg.counts(graph_id)
            return service.kg, graph_id
        except KeyError:
            pass
    path, _media = service.artefact_path(run_id, "graph")
    return service.kg, service.kg.save(json.loads(path.read_text(encoding="utf-8")))


def _kg_document(run_id: str) -> dict:
    store, graph_id = _kg_snapshot(run_id)
    return store.load(graph_id)


def _previous_snapshot(store: KGStore, graph_id: str) -> str | None:
    """The snapshot stored immediately before ``graph_id`` (newest first), or ``None``."""
    seen = False
    for row in store.list_snapshots():
        if row["graph_id"] == graph_id:
            seen = True
            continue
        if seen:
            return row["graph_id"]
    return None


@router.get("/discovery/runs/{run_id}/{artefact}")
def get_artefact(run_id: str, artefact: str) -> FileResponse:
    if artefact not in ARTEFACTS:
        raise HTTPException(404, "Unknown discovery artefact")
    try:
        path, media = get_service().artefact_path(run_id, artefact)
    except RunNotFound:
        raise HTTPException(404, "Discovery run not found or not finished") from None
    return FileResponse(path, media_type=media, filename=os.path.basename(path))
