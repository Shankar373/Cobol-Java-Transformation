"""FastAPI control-plane application.

Endpoints:
  POST   /applications                           — register an application
  GET    /applications                           — list applications
  GET    /applications/{id}                      — application detail
  GET    /applications/{id}/runs                 — list runs for an application
  POST   /applications/{id}/upload               — upload COBOL source files
  POST   /applications/{id}/candidate            — upload Java candidate files
  POST   /applications/{id}/ingest               — ingest ZIP archive
  GET    /applications/{id}/discovery             — discovery results
  POST   /applications/{id}/modernize            — trigger transform + validate
  GET    /runs/{id}                              — run status
  GET    /runs/{id}/detail                       — run detail (state + provenance)
  GET    /runs/{id}/artifacts                    — artifact metadata
  POST   /runs/{id}/validate                     — re-run validation (async)
  GET    /runs/{id}/verdict                      — verdict
  GET    /runs/{id}/download                     — download generated ZIP
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse

from api.models import (
    ApplicationCreate,
    ApplicationResponse,
    ArtifactsResponse,
    ArtifactMetadata,
    ModernizeOptions,
    ModernizeResponse,
    ModernizationReportResponse,
    RunDetailResponse,
    RunResponse,
    RunStage,
    UploadResponse,
    ValidateResponse,
    VerdictResponse,
    ComparisonDetail,
    IngestResponse,
    DiscoveryResponse,
)
from api.service import Service, ServiceError
from api.ingestion import IngestionError
from api.store import ApplicationRecord, Store

# ---------------------------------------------------------------------------
# Singletons (MVP — module-level, no DI framework)
# ---------------------------------------------------------------------------

_DEF_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DEF_DB_PATH = str(_DEF_DB_DIR / "control-plane.db")


def _store_path() -> str:
    """Resolve the SQLite path for the control plane.

    ``CONTROL_PLANE_DB`` overrides the default file location; ``:memory:``
    selects the historical non-persistent store (used by unit tests).
    """
    return os.environ.get("CONTROL_PLANE_DB", _DEF_DB_PATH)


_store = Store(_store_path())
_service = Service(_store)

app = FastAPI(
    title="COBOL-Java Transformation Control Plane",
    version="0.1.0",
    description="Thin orchestration API over the validation engine.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc() -> Service:
    return _service


def _error(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


def _to_app_response(rec: ApplicationRecord) -> ApplicationResponse:
    """Map an internal record to the API response (provenance preserved)."""
    return ApplicationResponse(
        id=rec.id,
        name=rec.name,
        description=rec.description,
        workload_id=rec.workload_id,
        java_entrypoint=rec.java_entrypoint,
        cobol_source_path=rec.cobol_source_path,
        java_candidate_path=rec.java_candidate_path,
        generated_app_path=rec.generated_app_path,
        generated_entrypoint=rec.generated_entrypoint,
        discovered_program_ids=list(rec.discovered_program_ids),
        generated_program_ids=list(rec.generated_program_ids),
        created_at=rec.created_at,
    )


def _safe_download_stem(name: str, fallback: str) -> str:
    """Sanitise an application name for use as a download filename stem."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")
    return stem or fallback


# ---------------------------------------------------------------------------
# Application endpoints
# ---------------------------------------------------------------------------

@app.post("/applications", response_model=ApplicationResponse, status_code=201)
def create_application(body: ApplicationCreate) -> ApplicationResponse:
    """Register a new COBOL-to-Java application."""
    rec = _svc().create_application(
        name=body.name,
        description=body.description,
        workload_id=body.workload_id,
        java_entrypoint=body.java_entrypoint,
    )
    return _to_app_response(rec)


@app.get("/applications", response_model=list[ApplicationResponse])
def list_applications() -> list[ApplicationResponse]:
    """List all registered applications (persisted, ordered by creation)."""
    return [_to_app_response(rec) for rec in _svc().list_applications()]


@app.get("/applications/{app_id}", response_model=ApplicationResponse)
def get_application(app_id: str) -> ApplicationResponse:
    """Return application detail including generation provenance."""
    try:
        rec = _svc().get_application(app_id)
    except ServiceError as exc:
        raise _error(404, str(exc))
    return _to_app_response(rec)


@app.get("/applications/{app_id}/runs", response_model=list[RunResponse])
def list_application_runs(app_id: str) -> list[RunResponse]:
    """List all runs for an application (persisted, ordered by creation)."""
    try:
        runs = _svc().list_runs(app_id)
    except ServiceError as exc:
        raise _error(404, str(exc))
    return [
        RunResponse(
            id=r.id,
            application_id=r.application_id,
            workload_id=r.workload_id,
            stage=r.stage,
            created_at=r.created_at,
            completed_at=r.completed_at,
            error=r.error,
        )
        for r in runs
    ]


@app.post("/applications/{app_id}/upload", response_model=UploadResponse, status_code=201)
async def upload_cobol_source(app_id: str, files: list[UploadFile] = File(...)) -> UploadResponse:
    """Upload COBOL source files for an application."""
    try:
        file_contents: dict[str, bytes] = {}
        for f in files:
            content = await f.read()
            name = f.filename or f"file_{len(file_contents)}"
            file_contents[name] = content

        _app, count = _svc().upload_cobol_source(app_id, file_contents)
    except ServiceError as exc:
        raise _error(404, str(exc))

    return UploadResponse(
        application_id=_app.id,
        files_received=count,
        cobol_source_path=_app.cobol_source_path or "",
    )


@app.post("/applications/{app_id}/candidate", response_model=UploadResponse, status_code=201)
async def upload_java_candidate(app_id: str, files: list[UploadFile] = File(...)) -> UploadResponse:
    """Upload Java candidate files for an application."""
    try:
        file_contents: dict[str, bytes] = {}
        for f in files:
            content = await f.read()
            name = f.filename or f"file_{len(file_contents)}"
            file_contents[name] = content

        _app, count = _svc().upload_java_candidate(app_id, file_contents)
    except ServiceError as exc:
        raise _error(404, str(exc))

    return UploadResponse(
        application_id=_app.id,
        files_received=count,
        cobol_source_path=_app.java_candidate_path or "",
    )


@app.post("/applications/{app_id}/modernize", response_model=ModernizeResponse, status_code=202)
def modernize_application(
    app_id: str, options: ModernizeOptions | None = None
) -> ModernizeResponse:
    """Trigger transformation + validation pipeline for an application.

    The normal workflow transforms the DISCOVERED application structure and
    validates the GENERATED artifact. The optional body flag is internal/
    test-only and never sent by the UI.
    """
    try:
        run = _svc().modernize(
            app_id,
            use_uploaded_candidate=(
                options.use_uploaded_candidate if options else False
            ),
        )
    except ServiceError as exc:
        raise _error(400, str(exc))

    return ModernizeResponse(
        run_id=run.id,
        application_id=run.application_id,
        stage=run.stage,
    )


@app.post("/applications/{app_id}/ingest", response_model=IngestResponse, status_code=201)
async def ingest_application(app_id: str, file: UploadFile = File(...)) -> IngestResponse:
    """Ingest a ZIP archive containing legacy application source.

    Extracts the archive, runs application discovery, detects the project
    name, and returns structured results about the discovered source tree.
    """
    content = await file.read()
    zip_filename = file.filename or "upload.zip"
    try:
        discovery = _svc().ingest_application(app_id, content, zip_filename)
    except (ServiceError, IngestionError) as exc:
        raise _error(400, str(exc))

    app = _svc().get_application(app_id)
    return IngestResponse(
        application_id=app_id,
        workspace_path=app.cobol_source_path or "",
        source_file_count=discovery["source_file_count"],
        total_size_bytes=discovery["total_size_bytes"],
        discovery=discovery,
        detected_name=discovery.get("detected_name", ""),
        top_level_entries=discovery.get("top_level_entries", []),
    )


@app.get("/applications/{app_id}/discovery", response_model=DiscoveryResponse)
def get_application_discovery(app_id: str) -> DiscoveryResponse:
    """Return discovery results for an application."""
    app = _svc().get_application(app_id)
    if app.cobol_source_path is None:
        raise _error(404, "No source has been ingested for this application")

    from api.ingestion import discover_application
    discovery = discover_application(Path(app.cobol_source_path), app_id)

    return DiscoveryResponse(
        application_id=app_id,
        cobol_programs=discovery.cobol_programs,
        copybooks=discovery.copybooks,
        jcl_jobs=discovery.jcl_jobs,
        file_dependencies=discovery.file_dependencies,
        call_dependencies=discovery.call_dependencies,
        dependency_edges=discovery.dependency_edges,
        source_file_count=discovery.source_file_count,
        total_size_bytes=discovery.total_size_bytes,
        discovery_success=discovery.discovery_success,
        discovery_errors=discovery.discovery_errors,
    )


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    """Get run status and summary."""
    try:
        run = _svc().get_run(run_id)
    except ServiceError as exc:
        raise _error(404, str(exc))

    return RunResponse(
        id=run.id,
        application_id=run.application_id,
        workload_id=run.workload_id,
        stage=run.stage,
        created_at=run.created_at,
        completed_at=run.completed_at,
        error=run.error,
    )


@app.get("/runs/{run_id}/detail", response_model=RunDetailResponse)
def get_run_detail(run_id: str) -> RunDetailResponse:
    """Get coherent run detail: state, app identity, discovery, files, verdict."""
    try:
        detail = _svc().get_run_detail(run_id)
    except ServiceError as exc:
        raise _error(404, str(exc))

    return RunDetailResponse(
        id=detail["id"],
        application_id=detail["application_id"],
        application_name=detail["application_name"],
        workload_id=detail["workload_id"],
        stage=detail["stage"],
        created_at=detail["created_at"],
        completed_at=detail["completed_at"],
        error=detail["error"],
        verdict_state=detail["verdict_state"],
        discovery=detail["discovery"],
        stage_messages=detail["stage_messages"],
        generated_files=detail["generated_files"],
    )


@app.get("/runs/{run_id}/artifacts", response_model=ArtifactsResponse)
def get_run_artifacts(run_id: str) -> ArtifactsResponse:
    """Get artifact metadata for a run."""
    try:
        artifacts = _svc().get_artifacts(run_id)
    except ServiceError as exc:
        raise _error(404, str(exc))

    return ArtifactsResponse(
        run_id=run_id,
        artifacts=[ArtifactMetadata(**a) for a in artifacts],
    )


@app.post("/runs/{run_id}/validate", response_model=ValidateResponse, status_code=202)
def validate_run(run_id: str) -> ValidateResponse:
    """Re-run validation on an existing run (asynchronous).

    Explicit behavior: mirrors modernize — the run resets to CREATED and a
    background thread re-executes validation of the GENERATED artifact.
    Poll GET /runs/{id} until a terminal stage.
    """
    try:
        run = _svc().revalidate(run_id)
    except ServiceError as exc:
        raise _error(400, str(exc))

    return ValidateResponse(run_id=run.id, stage=run.stage)


@app.get("/runs/{run_id}/verdict", response_model=VerdictResponse)
def get_run_verdict(run_id: str) -> VerdictResponse:
    """Get the verdict for a run."""
    try:
        v = _svc().get_verdict(run_id)
        comparisons_raw = _svc().get_comparisons(run_id)
    except ServiceError as exc:
        raise _error(404, str(exc))

    comparisons = [ComparisonDetail(**c) for c in comparisons_raw]

    return VerdictResponse(
        run_id=v["run_id"],
        engine_run_id=v.get("engine_run_id"),
        state=v["state"],
        workload_id=v["workload_id"],
        source_hash=v["source_hash"],
        candidate_hash=v.get("candidate_hash"),
        oracle_id=v["oracle_id"],
        oracle_digest=v["oracle_digest"],
        executed_check_count=v["executed_check_count"],
        skipped_count=v["skipped_count"],
        unavailable_count=v["unavailable_count"],
        supported_scope_statement=v["supported_scope_statement"],
        evidence_manifest_hash=v["evidence_manifest_hash"],
        derivation_timestamp=v["derivation_timestamp"],
        differences=v.get("differences", []),
        comparisons=comparisons,
    )


@app.get("/runs/{run_id}/report", response_model=ModernizationReportResponse)
def get_run_report(run_id: str) -> ModernizationReportResponse:
    """Get the full modernization report for a run.

    Contains capability analysis, transformation plan, limitations,
    and recommendations produced by the universal pipeline. Only
    returned when the pipeline ran — never fabricated.
    """
    try:
        report = _svc().get_run_report(run_id)
    except ServiceError as exc:
        raise _error(404, str(exc))

    run = _svc().get_run(run_id)
    return ModernizationReportResponse(
        run_id=run_id,
        application_id=run.application_id,
        report=report,
    )


@app.get("/runs/{run_id}/download")
def download_generated(run_id: str) -> StreamingResponse:
    """Download the GENERATED Java application as a ZIP archive.

    Provenance guarantee: packages generated_app_path ONLY — the artifact
    produced by ApplicationGenerator during modernization. An uploaded
    candidate is never served here; runs without a generated artifact
    return 404.
    """
    run = _svc().get_run(run_id)
    app = _svc().get_application(run.application_id)

    java_dir = app.generated_app_path
    if java_dir is None or not Path(java_dir).exists():
        raise _error(404, "No generated Java application available for this run")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in Path(java_dir).rglob("*"):
            if f.is_file():
                arcname = f.relative_to(java_dir)
                zf.write(f, arcname)

    buf.seek(0)
    # Stable product filename derived from the application name (not the
    # workload id, which collides across applications reusing a workload).
    filename = f"{_safe_download_stem(app.name, run.id)}-generated.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
