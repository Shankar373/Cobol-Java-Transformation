"""COBOL estate discovery routes.

    POST /discovery/runs/zip        upload a ZIP (multipart) -> 202 run
    POST /discovery/runs/git        remote Git URL + optional branch/tag/commit -> 202 run
    GET  /discovery/runs            recent runs
    GET  /discovery/runs/{id}       state, steps, gate
    GET  /discovery/runs/{id}/{artefact}   report | graph | inventory | unresolved | summary
    POST /discovery/runs/{id}/verify       re-hash the immutable checkpoint

Local directory and ``file://`` inputs are deliberately not accepted here: they would let a caller read the server's
own filesystem.  Authentication and role checks are the control plane's middleware, which covers every path; reads are
``viewer``, submissions and re-verification are ``operator``.  Runs execute on a bounded worker pool and are durable.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.ingestion import _get_max_zip_archive_bytes, _get_max_zip_compression_ratio, _get_max_zip_entries
from api.ingestion import _get_max_total_extracted_bytes
from api.paths import workspace_root
from enterprise.discovery.limits import DEFAULT_LIMITS, Limits
from enterprise.discovery.runs import ARTEFACTS, DiscoveryRunService, RunNotFound

router = APIRouter()
_CHUNK = 1 << 20
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


@router.get("/discovery/runs/{run_id}/{artefact}")
def get_artefact(run_id: str, artefact: str) -> FileResponse:
    if artefact not in ARTEFACTS:
        raise HTTPException(404, "Unknown discovery artefact")
    try:
        path, media = get_service().artefact_path(run_id, artefact)
    except RunNotFound:
        raise HTTPException(404, "Discovery run not found or not finished") from None
    return FileResponse(path, media_type=media, filename=os.path.basename(path))
