"""VSAM logical-export migration routes.

    POST /applications/{app_id}/vsam/migrations   create a job (idempotent)
    PUT  /vsam/migrations/{job_id}/data           stream the export (raw body)
    GET  /vsam/migrations/{job_id}                job state, counts, refusal reason
    GET  /vsam/migrations/{job_id}/download       migrated image, SUCCEEDED jobs only

The export is streamed to disk and migrated by a background worker; the API
never holds a dataset in memory. Authentication is the control plane's
bearer-token middleware, which covers every path here.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.paths import workspace_root
from enterprise.contracts import VsamExportManifest
from enterprise.vsam.errors import VsamRefusal
from enterprise.vsam.jobs import (
    IdempotencyConflict,
    JobNotFound,
    VsamJobService,
    WrongState,
    file_sha256,
    safe_runtime_path,
)

router = APIRouter()
UPLOAD_PATH = re.compile(r"^/vsam/migrations/[0-9a-f]{32}/data$")
_CHUNK = 1 << 20

_service: VsamJobService | None = None
_application_lookup: Callable[[str], object] | None = None


class MigrationCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    runtime_path: str = Field(min_length=1, max_length=100)
    manifest: VsamExportManifest
    # Optional: validate the manifest against the program's SELECT / FD.
    cobol_source: str | None = Field(default=None, max_length=1_048_576)
    cobol_file: str | None = Field(default=None, max_length=64)


def configure(service: VsamJobService | None = None,
              application_lookup: Callable[[str], object] | None = None) -> None:
    global _service, _application_lookup
    if service is not None:
        _service = service
    if application_lookup is not None:
        _application_lookup = application_lookup


def get_service() -> VsamJobService:
    global _service
    if _service is None:
        control_db = os.environ.get("CONTROL_PLANE_DB", "")
        root = workspace_root()
        data_root = (root / "vsam") if root else Path(tempfile.mkdtemp(prefix="vsam-"))
        db = ":memory:" if control_db in ("", ":memory:") else control_db + ".vsam"
        _service = VsamJobService(db, data_root)
        _service.recover_interrupted()
    return _service


def _job_or_404(job_id: str):
    try:
        return get_service().get(job_id)
    except JobNotFound:
        raise HTTPException(404, "Migration job not found") from None


@router.post("/applications/{app_id}/vsam/migrations", status_code=201)
def create_migration(app_id: str, body: MigrationCreate) -> dict:
    if _application_lookup is not None:
        _application_lookup(app_id)  # raises the control plane's 404
    try:
        runtime_path = safe_runtime_path(body.runtime_path)
    except VsamRefusal as refusal:
        raise HTTPException(400, refusal.message) from None
    try:
        view, created = get_service().create(
            app_id, body.idempotency_key, body.manifest, runtime_path, body.cobol_source, body.cobol_file)
    except IdempotencyConflict:
        raise HTTPException(409, "Idempotency key was already used for a different request") from None
    payload = view.as_dict()
    payload["created"] = created
    payload["upload_path"] = f"/vsam/migrations/{view.job_id}/data"
    return payload


@router.put("/vsam/migrations/{job_id}/data", status_code=202)
async def upload_export(job_id: str, request: Request) -> dict:
    service = get_service()
    try:
        manifest = service.accept_upload_slot(job_id)
    except JobNotFound:
        raise HTTPException(404, "Migration job not found") from None
    except WrongState:
        raise HTTPException(409, "Job is not waiting for an upload") from None

    expected = manifest.dataset_bytes
    declared = request.headers.get("content-length", "")
    if not declared.isdigit() or int(declared) != expected:
        service.upload_aborted(job_id)
        raise HTTPException(400, f"Content-Length must equal the manifest dataset_bytes ({expected})")

    received = 0
    try:
        with service.input_path(job_id).open("wb") as sink:
            async for chunk in request.stream():
                received += len(chunk)
                if received > expected:
                    break
                sink.write(chunk)
    except BaseException:
        service.upload_aborted(job_id)
        raise
    if received != expected:
        service.upload_failed(job_id, "UPLOAD_SIZE_MISMATCH",
                              f"received {received} bytes, manifest says {expected}")
        raise HTTPException(400, "Uploaded size does not match the manifest")
    service.upload_complete(job_id)
    return service.get(job_id).as_dict()


@router.get("/vsam/migrations/{job_id}")
def get_migration(job_id: str) -> dict:
    return _job_or_404(job_id).as_dict()


@router.get("/vsam/migrations/{job_id}/download")
def download_migration(job_id: str) -> FileResponse:
    view = _job_or_404(job_id)
    if view.state != "SUCCEEDED":
        raise HTTPException(409, f"Job is {view.state}; only SUCCEEDED jobs have artifacts")
    path = get_service().output_path(job_id)
    if not path.is_file():
        raise HTTPException(404, "Artifact is no longer available")
    if file_sha256(path) != view.output_sha256:
        raise HTTPException(500, "Artifact failed its integrity check and was not served")
    return FileResponse(
        path, media_type="application/octet-stream", filename=view.output_name,
        headers={"X-Content-SHA256": view.output_sha256},
    )
