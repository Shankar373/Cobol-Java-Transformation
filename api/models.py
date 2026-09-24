"""Pydantic request/response models for the control-plane API.

Models mirror engine domain objects but are serialisation-boundary types.
No engine logic lives here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RunStage(str, Enum):
    """Explicit run lifecycle stages.

    Lifecycle:
      CREATED → DISCOVERING → DISCOVERY_COMPLETED → ANALYZING →
      ANALYSIS_COMPLETED → PLANNING → PLAN_COMPLETED → TRANSFORMING →
      GENERATING → ASSEMBLING → ASSEMBLY_COMPLETED → EXECUTING_ORACLE →
      BUILDING → EXECUTING_GENERATED → COMPARING → VALIDATING_EVIDENCE →
      COMPLETED / FAILED
    """
    CREATED = "CREATED"
    INGESTING = "INGESTING"
    DISCOVERING = "DISCOVERING"
    DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
    ANALYZING = "ANALYZING"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    PLANNING = "PLANNING"
    PLAN_COMPLETED = "PLAN_COMPLETED"
    TRANSFORMING = "TRANSFORMING"
    GENERATING = "GENERATING"
    ASSEMBLING = "ASSEMBLING"
    ASSEMBLY_COMPLETED = "ASSEMBLY_COMPLETED"
    BUILDING = "BUILDING"
    EXECUTING_ORACLE = "EXECUTING_ORACLE"
    EXECUTING_GENERATED = "EXECUTING_GENERATED"
    COMPARING = "COMPARING"
    VALIDATING_EVIDENCE = "VALIDATING_EVIDENCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class ApplicationCreate(BaseModel):
    """Request to register a new application."""
    name: str = Field(..., min_length=1, max_length=256)
    description: str = ""
    workload_id: str = Field(..., min_length=1, max_length=256)
    java_entrypoint: str = Field(default="Main", min_length=1)


class ApplicationResponse(BaseModel):
    """Application metadata."""
    id: str
    name: str
    description: str
    workload_id: str
    java_entrypoint: str
    cobol_source_path: str | None = None
    java_candidate_path: str | None = None
    generated_app_path: str | None = None
    generated_entrypoint: str | None = None
    discovered_program_ids: list[str] = Field(default_factory=list)
    generated_program_ids: list[str] = Field(default_factory=list)
    created_at: str


class UploadResponse(BaseModel):
    """Response after uploading COBOL source files."""
    application_id: str
    files_received: int
    cobol_source_path: str


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class RunResponse(BaseModel):
    """Run summary."""
    id: str
    application_id: str
    workload_id: str
    stage: RunStage
    created_at: str
    completed_at: str | None = None
    error: str | None = None


class ArtifactMetadata(BaseModel):
    """Metadata for a single captured artifact."""
    artifact_id: str
    artifact_type: str
    logical_name: str
    producer_role: str
    content_hash: str
    size_bytes: int
    record_count: int | None = None


class ArtifactsResponse(BaseModel):
    """Artifact metadata for a run."""
    run_id: str
    artifacts: list[ArtifactMetadata]


class ModernizeResponse(BaseModel):
    """Response after triggering modernization."""
    run_id: str
    application_id: str
    stage: RunStage


class ModernizeOptions(BaseModel):
    """Optional flags for the modernize endpoint.

    Internal/test-only: ``use_uploaded_candidate`` is NOT part of the normal
    workflow and is never sent by the UI. It exists so integration tests can
    validate a pre-built/uploaded candidate against the engine. The default
    (False) always transforms the DISCOVERED application structure and
    validates the GENERATED artifact.
    """
    use_uploaded_candidate: bool = False


class ValidateResponse(BaseModel):
    """Response after (re-)validation."""
    run_id: str
    stage: RunStage


class ComparisonDetail(BaseModel):
    """Single comparison result."""
    comparison_id: str
    comparator_id: str
    comparator_version: str = ""
    artifact_type: str
    result: str
    differences: list[str]


class VerdictResponse(BaseModel):
    """Verdict for a run.

    ``run_id`` is the API run-record ID (stable for polling correlation).
    ``engine_run_id`` carries the engine pipeline's internal run ID when it
    differs; it is informational only.
    """
    run_id: str
    engine_run_id: str | None = None
    state: str
    workload_id: str
    source_hash: str
    candidate_hash: str | None
    oracle_id: str
    oracle_digest: str
    executed_check_count: int
    skipped_count: int
    unavailable_count: int
    supported_scope_statement: str
    evidence_manifest_hash: str
    derivation_timestamp: str
    differences: list[str]
    comparisons: list[ComparisonDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """Request to ingest a legacy application source."""
    git_url: str | None = None


class IngestResponse(BaseModel):
    """Response after ingestion + discovery."""
    application_id: str
    workspace_path: str
    source_file_count: int
    total_size_bytes: int
    discovery: dict
    detected_name: str = ""
    top_level_entries: list[str] = Field(default_factory=list)


class DiscoveryResponse(BaseModel):
    """Discovery results for an application."""
    application_id: str
    cobol_programs: list[dict]
    copybooks: list[str]
    jcl_jobs: list[dict]
    file_dependencies: list[dict]
    call_dependencies: list[dict]
    dependency_edges: list[dict]
    source_file_count: int
    total_size_bytes: int
    discovery_success: bool = True
    discovery_errors: list[dict] = Field(default_factory=list)


class RunDetailResponse(BaseModel):
    """Detailed run response including discovery + stage messages."""
    id: str
    application_id: str
    application_name: str | None = None
    workload_id: str
    stage: RunStage
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    verdict_state: str | None = None
    discovery: dict | None = None
    stage_messages: list[str] = Field(default_factory=list)
    generated_files: list[str] = Field(default_factory=list)


class ModernizationReportResponse(BaseModel):
    """Full modernization report for a run.

    Contains discovery, capability analysis, transformation plan,
    transformation results, assembly results, limitations, and
    recommendations. Never fabricated — only returned when the
    universal pipeline produced a report.
    """
    run_id: str
    application_id: str
    report: dict
