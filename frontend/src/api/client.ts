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
 *   GET    /runs/{id}/approval      (the customer's approval record)
 *   POST   /runs/{id}/approval      (record APPROVED/REJECTED decision)
 *   GET    /runs/{id}/download         (generated artifact only; 409 until APPROVED)
 *   GET    /health
 */

const BASE = '';

// ---------------------------------------------------------------------------
// Bearer-token auth (production CONTROL_PLANE_API_TOKEN integration)
//
// The backend middleware (api/app.py) requires `Authorization: Bearer
// <token>` on every route except /health when CONTROL_PLANE_API_TOKEN is
// set; without a browser-side entry point the SPA received 401 on every
// call in that configuration.  The token is resolved in priority order:
//
//   1. localStorage override (`systemaops.apiToken`) — runtime
//      configuration without a rebuild (set/clear via setApiToken);
//   2. build-time env `VITE_CONTROL_PLANE_API_TOKEN` — baked in by the
//      deployment's frontend build;
//   3. none → auth is off (the documented dev default) and requests are
//      byte-identical to the pre-auth client (no Authorization header,
//      GET init stays `undefined`).
//
// The token is a deployment-level shared secret; it is never logged and
// is only ever sent to the same-origin backend (BASE === '').
// ---------------------------------------------------------------------------

const TOKEN_STORAGE_KEY = 'systemaops.apiToken';

type MaybeEnvImportMeta = ImportMeta & {
  env?: Record<string, string | undefined>;
};

/** Current bearer token, or null when auth is off. */
export function getApiToken(): string | null {
  try {
    const stored = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) return stored;
  } catch {
    // Storage unavailable (private mode, disabled) — fall through to env.
  }
  const env = (import.meta as MaybeEnvImportMeta).env;
  const fromEnv = env?.['VITE_CONTROL_PLANE_API_TOKEN'];
  return fromEnv ? fromEnv : null;
}

/** Set (token string) or clear (null) the runtime token override. */
export function setApiToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } else {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
}

/** Attach the Authorization header when a token is configured. */
function withAuth(init?: RequestInit): RequestInit | undefined {
  const token = getApiToken();
  if (!token) return init;
  const headers = new Headers(init?.headers);
  if (!headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return { ...init, headers };
}

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
  /**
   * Whether discovery finished without any stage failing.  The API always
   * sends this (it is computed server-side from `discovery_errors`), and the
   * UI needs it: without it, a discovery that partially failed looked
   * identical to one that fully succeeded.
   */
  discovery_success: boolean;
  /** One entry per stage that failed; a non-empty list means the flag above is false. */
  discovery_errors: DiscoveryIssue[];
}

/** One discovery-stage failure, as produced by `api/ingestion.py`. */
export interface DiscoveryIssue {
  stage: string;
  message: string;
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
  /**
   * Persisted verdict state (VERIFIED/FAILED/UNPROVEN/...), or null when no
   * verdict was produced.  Served fail-closed: only when the verdict
   * hash-matches its evidence manifest.  The dashboard's "Verified" stat
   * must count this field — never the run stage.
   */
  verdict_state?: string | null;
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

// ---------------------------------------------------------------------------
// Customer approval
// ---------------------------------------------------------------------------

/** Current per-run approval state. PENDING until an explicit decision. */
export type ApprovalState = 'PENDING' | 'APPROVED' | 'REJECTED';

/** Decisions accepted by the approval endpoint (PENDING is never one). */
export type ApprovalDecisionValue = 'APPROVED' | 'REJECTED';

export interface RunApprovalResponse {
  run_id: string;
  state: ApprovalState;
  approver: string | null;
  reason: string | null;
  decided_at: string | null;
}

export interface ApprovalDecisionInput {
  decision: ApprovalDecisionValue;
  approver: string;
  reason?: string;
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

/**
 * Turn the API's `detail` field into a message a person can actually read.
 *
 * `detail` is not one shape: it is a plain string for errors the API authors
 * wrote by hand, an ARRAY of Pydantic error objects when request validation
 * fails (HTTP 422), and sometimes a single object for structured rejections.
 * Displaying the raw envelope directly put `[object Object]` on the screen,
 * which tells the customer nothing.  Each of these shapes is flattened
 * deliberately so no part of the message is dropped or mangled.
 */
export function detailToMessage(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => detailToMessage(item))
      .filter((part) => part.length > 0);
    return parts.length > 0 ? parts.join('; ') : JSON.stringify(detail);
  }
  if (detail !== null && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    // Pydantic puts the actual sentence in `msg`, and `loc` tells us which
    // field was wrong.  Leading with the field name keeps the message precise
    // without us having to invent any wording of our own.
    const msg = typeof record.msg === 'string' ? record.msg : null;
    if (msg !== null) {
      const loc = Array.isArray(record.loc)
        ? record.loc.map(String).join('.')
        : '';
      return loc ? `${loc}: ${msg}` : msg;
    }
    const parts = Object.entries(record).map(([key, value]) =>
      `${key}: ${typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}`,
    );
    return parts.length > 0 ? parts.join('; ') : JSON.stringify(detail);
  }
  return detail === null || detail === undefined
    ? ''
    : String(detail);
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, withAuth(init));
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail !== undefined ? detailToMessage(body.detail) : JSON.stringify(body);
      if (!msg) {
        msg = JSON.stringify(body);
      }
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

/** Current approval record for a run (PENDING until a decision). */
export async function getRunApproval(runId: string): Promise<RunApprovalResponse> {
  return request<RunApprovalResponse>(`/runs/${runId}/approval`);
}

/**
 * Record the customer's explicit decision.
 *
 * The backend enforces the scope: rejection requires a reason, approval
 * reason is optional, a later decision supersedes the earlier one, and
 * export/download answers 409 until the run is APPROVED.
 */
export async function setRunApproval(
  runId: string,
  input: ApprovalDecisionInput,
): Promise<RunApprovalResponse> {
  return request<RunApprovalResponse>(`/runs/${runId}/approval`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
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

/**
 * Build a warning message for a discovery that did not finish cleanly, or
 * return null when the discovery is complete.
 *
 * The server tells us directly via `discovery_success`, but not every payload
 * carries it (older responses, truncated bodies), so a non-empty error list is
 * used as a fallback signal.  A completed discovery must return null — we must
 * never invent a warning where none was reported — while a partial one must
 * never be presented as complete.
 */
export function discoveryIssuesMessage(
  discovery: DiscoveryResult,
): string | null {
  const errors = discovery.discovery_errors ?? [];

  if (discovery.discovery_success) {
    // The flag says success but errors were still reported.  That is a server
    // contradiction, and hiding it would risk losing a real problem, so we
    // show the errors rather than take the flag at its word.
    return errors.length > 0 ? formatDiscoveryErrors(errors) : null;
  }

  if (errors.length > 0) {
    return formatDiscoveryErrors(errors);
  }

  // Incomplete with no detail: say so plainly instead of guessing a cause.
  return 'Discovery incomplete: the run did not finish cleanly (no further detail was reported).';
}

function formatDiscoveryErrors(errors: DiscoveryIssue[]): string {
  const detail = errors
    .map((error) => `${error.stage}: ${error.message}`)
    .join('; ');
  return `Discovery incomplete — ${errors.length} stage(s) reported problems: ${detail}`;
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

export interface DependencyLedgerEntry {
  dependency_id: string;
  kind: string;
  visible: boolean;
  capability_level: string;
  proof_state: string;
  required: boolean;
  reason: string;
}

export interface IntegratedProofResult {
  workload_id: string;
  application_id: string;
  central_status: string;
  blocking_reasons: string[];
  generation_success: boolean;
  overall_capability: string;
  jcl_status: string;
  runtime: Record<string, unknown>;
  dependency_ledger: DependencyLedgerEntry[];
  required_dependencies: DependencyLedgerEntry[];
  unproven_dependencies: DependencyLedgerEntry[];
  runtime_verdict_is_verified: boolean;
}

export interface IntegratedProofResponse {
  run_id: string;
  application_id: string;
  proof: IntegratedProofResult;
  verdict_state: string;
  evidence_status: string;
  runtime_proof_status: string;
  reasons_for_not_verified: string[];
  proven_dependencies: DependencyLedgerEntry[];
  unproven_dependencies: DependencyLedgerEntry[];
  blocked_dependencies: DependencyLedgerEntry[];
  unsupported_dependencies: DependencyLedgerEntry[];
  evidence_complete: boolean;
  evidence_integrity_valid: boolean;
  required_dependencies_proven: boolean;
  overall_verification: string;
}

// ---------------------------------------------------------------------------
// Integrated Proof
// ---------------------------------------------------------------------------

export async function getIntegratedProof(
  runId: string,
): Promise<IntegratedProofResponse> {
  return request<IntegratedProofResponse>(`/runs/${runId}/integrated-proof`);
}

// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------

export async function downloadGenerated(runId: string): Promise<Blob> {
  // Call-shape parity with the pre-auth client: without a token the fetch
  // receives no init argument at all (pinned by api-client tests).
  const authed = withAuth();
  const res = authed
    ? await fetch(`${BASE}/runs/${runId}/download`, authed)
    : await fetch(`${BASE}/runs/${runId}/download`);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail !== undefined ? detailToMessage(body.detail) : JSON.stringify(body);
      if (!msg) {
        msg = JSON.stringify(body);
      }
    } catch {
      // ignore
    }
    throw new ApiError(res.status, msg);
  }
  return res.blob();
}
