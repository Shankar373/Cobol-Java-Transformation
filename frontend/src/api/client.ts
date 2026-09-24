/**
 * Typed API client for the control-plane backend.
 *
 * All HTTP communication lives here.  Pages/components import this
 * module and call its functions — they never fetch directly.
 *
 * Backend API:
 *   GET    /applications
 *   POST   /applications
 *   GET    /applications/{id}
 *   POST   /applications/{id}/upload
 *   POST   /applications/{id}/candidate (internal/test-only; never used by UI)
 *   POST   /applications/{id}/ingest
 *   GET    /applications/{id}/discovery
 *   POST   /applications/{id}/modernize
 *   GET    /applications/{id}/runs
 *   GET    /runs/{id}
 *   GET    /runs/{id}/detail
 *   GET    /runs/{id}/artifacts
 *   POST   /runs/{id}/validate
 *   GET    /runs/{id}/verdict
 *   GET    /runs/{id}/download         (generated artifact only)
 *   GET    /health
 */

const BASE = '';

// ---------------------------------------------------------------------------
// Types (mirror backend Pydantic models)
// ---------------------------------------------------------------------------

export type RunStage =
  | 'CREATED'
  | 'INGESTING'
  | 'DISCOVERING'
  | 'DISCOVERY_COMPLETED'
  | 'ANALYZING'
  | 'ANALYSIS_COMPLETED'
  | 'PLANNING'
  | 'PLAN_COMPLETED'
  | 'TRANSFORMING'
  | 'GENERATING'
  | 'ASSEMBLING'
  | 'ASSEMBLY_COMPLETED'
  | 'BUILDING'
  | 'EXECUTING_ORACLE'
  | 'EXECUTING_GENERATED'
  | 'COMPARING'
  | 'VALIDATING_EVIDENCE'
  | 'COMPLETED'
  | 'FAILED';

export interface ApplicationCreate {
  name: string;
  description?: string;
  workload_id: string;
  java_entrypoint?: string;
}

export interface ApplicationResponse {
  id: string;
  name: string;
  description: string;
  workload_id: string;
  java_entrypoint: string;
  cobol_source_path: string | null;
  java_candidate_path: string | null;
  generated_app_path: string | null;
  generated_entrypoint: string | null;
  discovered_program_ids: string[];
  generated_program_ids: string[];
  created_at: string;
}

export interface UploadResponse {
  application_id: string;
  files_received: number;
  cobol_source_path: string;
}

export interface IngestResponse {
  application_id: string;
  workspace_path: string;
  source_file_count: number;
  total_size_bytes: number;
  discovery: DiscoveryResult;
  detected_name: string;
  top_level_entries: string[];
}

export interface DiscoveryResult {
  application_id: string;
  cobol_programs: CobolProgram[];
  copybooks: string[];
  jcl_jobs: JclJob[];
  file_dependencies: FileDependency[];
  call_dependencies: CallDependency[];
  dependency_edges: DependencyEdge[];
  source_file_count: number;
  total_size_bytes: number;
}

export interface CobolProgram {
  program_id: string;
  source_path: string;
  file_dependencies: { name: string; operation: string; mode?: string }[];
  calls: { target: string; arguments: string[] }[];
  copybooks: string[];
  entry_points: string[];
}

export interface JclJob {
  name: string;
  steps: { name: string; program: string | null; procedure: string | null }[];
}

export interface FileDependency {
  program_id: string;
  file_name: string;
  operation: string;
}

export interface CallDependency {
  caller: string;
  target: string;
}

export interface DependencyEdge {
  source: string;
  target: string;
  edge_type: string;
}

export interface ModernizeResponse {
  run_id: string;
  application_id: string;
  stage: RunStage;
}

export interface RunResponse {
  id: string;
  application_id: string;
  workload_id: string;
  stage: RunStage;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface ArtifactMetadata {
  artifact_id: string;
  artifact_type: string;
  logical_name: string;
  producer_role: string;
  content_hash: string;
  size_bytes: number;
  record_count: number | null;
}

export interface ArtifactsResponse {
  run_id: string;
  artifacts: ArtifactMetadata[];
}

export interface ValidateResponse {
  run_id: string;
  stage: RunStage;
}

export interface ComparisonDetail {
  comparison_id: string;
  comparator_id: string;
  comparator_version?: string;
  artifact_type: string;
  result: string;
  differences: string[];
}

export interface VerdictResponse {
  run_id: string;
  engine_run_id?: string | null;
  state: string;
  workload_id: string;
  source_hash: string;
  candidate_hash: string | null;
  oracle_id: string;
  oracle_digest: string;
  executed_check_count: number;
  skipped_count: number;
  unavailable_count: number;
  supported_scope_statement: string;
  evidence_manifest_hash: string;
  derivation_timestamp: string;
  differences: string[];
  comparisons: ComparisonDetail[];
}

export interface HealthResponse {
  status: string;
}

export interface RunDetailResponse {
  id: string;
  application_id: string;
  application_name: string | null;
  workload_id: string;
  stage: RunStage;
  created_at: string;
  completed_at: string | null;
  error: string | null;
  verdict_state: string | null;
  discovery: Record<string, unknown> | null;
  stage_messages: string[];
  generated_files: string[];
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function createApplication(
  data: ApplicationCreate,
): Promise<ApplicationResponse> {
  return request<ApplicationResponse>('/applications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function uploadFiles(
  appId: string,
  files: File[],
): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', f);
  }
  return request<UploadResponse>(`/applications/${appId}/upload`, {
    method: 'POST',
    body: form,
  });
}

export async function uploadCandidate(
  appId: string,
  files: File[],
): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append('files', f);
  }
  return request<UploadResponse>(`/applications/${appId}/candidate`, {
    method: 'POST',
    body: form,
  });
}

export async function modernize(
  appId: string,
): Promise<ModernizeResponse> {
  return request<ModernizeResponse>(`/applications/${appId}/modernize`, {
    method: 'POST',
  });
}

export async function getRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/runs/${runId}`);
}

/** GET /runs/{id}/detail — run state plus provenance (best-effort fields). */
export async function getRunDetail(runId: string): Promise<RunDetailResponse> {
  return request<RunDetailResponse>(`/runs/${runId}/detail`);
}

export async function getArtifacts(
  runId: string,
): Promise<ArtifactsResponse> {
  return request<ArtifactsResponse>(`/runs/${runId}/artifacts`);
}

export async function validateRun(runId: string): Promise<ValidateResponse> {
  return request<ValidateResponse>(`/runs/${runId}/validate`, {
    method: 'POST',
  });
}

export async function getVerdict(runId: string): Promise<VerdictResponse> {
  return request<VerdictResponse>(`/runs/${runId}/verdict`);
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

// ---------------------------------------------------------------------------
// Application history (persistent backend contract).
//
// The backend is authoritative: the UI consumes these endpoints directly
// with no local persistence. Callers keep session state only as a
// fallback and surface it explicitly when the server is unreachable.
// ---------------------------------------------------------------------------

/** GET /applications — full application history (persistent backend). */
export async function listApplications(): Promise<ApplicationResponse[]> {
  return request<ApplicationResponse[]>('/applications');
}

/** GET /applications/{id} — single application record. */
export async function getApplication(
  appId: string,
): Promise<ApplicationResponse> {
  return request<ApplicationResponse>(`/applications/${appId}`);
}

/** GET /applications/{id}/runs — run history for an application. */
export async function listApplicationRuns(
  appId: string,
): Promise<RunResponse[]> {
  return request<RunResponse[]>(`/applications/${appId}/runs`);
}

// ---------------------------------------------------------------------------
// Ingestion
// ---------------------------------------------------------------------------

export async function ingestApplication(
  appId: string,
  file: File,
): Promise<IngestResponse> {
  const form = new FormData();
  form.append('file', file);
  return request<IngestResponse>(`/applications/${appId}/ingest`, {
    method: 'POST',
    body: form,
  });
}

export async function getDiscovery(
  appId: string,
): Promise<DiscoveryResult> {
  return request<DiscoveryResult>(`/applications/${appId}/discovery`);
}

// ---------------------------------------------------------------------------
// Modernization Report
// ---------------------------------------------------------------------------

export interface ModernizationReportResponse {
  run_id: string;
  application_id: string;
  report: Record<string, unknown>;
}

export async function getReport(
  runId: string,
): Promise<ModernizationReportResponse> {
  return request<ModernizationReportResponse>(`/runs/${runId}/report`);
}

// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------

export async function downloadGenerated(runId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/runs/${runId}/download`);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new ApiError(res.status, msg);
  }
  return res.blob();
}
