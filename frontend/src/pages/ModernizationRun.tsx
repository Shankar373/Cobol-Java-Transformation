import React, { useEffect, useState, useCallback, useRef } from 'react';
import { tokens } from '../theme/tokens';
import {
  PageContainer,
  SectionCard,
  Badge,
  Button,
  VerdictDisplay,
  ValidationScope,
  LoadingSpinner,
  Header,
  HeaderMetaItem,
  PipelineStepper,
  StatCard,
  CopyButton,
  IntegratedProof,
} from '../components';
import {
  IconCode,
  IconDatabase,
  IconFileText,
  IconLayers,
  IconPackage,
  IconShieldCheck,
  IconTimer,
} from '../components/icons';
import {
  RunResponse,
  VerdictResponse,
  DiscoveryResult,
  ArtifactMetadata,
  RunDetailResponse,
  ModernizationReportResponse,
  IntegratedProofResponse,
  getRun,
  getRunDetail,
  getVerdict,
  getDiscovery,
  getArtifacts,
  getReport,
  downloadGenerated,
  getIntegratedProof,
} from '../api/client';
import {
  RUN_STAGES,
  isTerminalStage,
  type IngestSummary,
} from '../api/stages';

interface ModernizationRunProps {
  runId: string;
  applicationId: string;
  /** Completed ingestion summary from POST /applications/{id}/ingest. */
  ingest?: IngestSummary | null;
  /** Poll cadence in ms. Production default is 1500; tests may shorten it. */
  pollIntervalMs?: number;
  /** Optional navigation (breadcrumb back-link). */
  onNavigate?: (page: string, id?: string) => void;
}

const POLL_INTERVAL_MS = 1500;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;
/** Informational only: runs older than this without a terminal stage are
 *  flagged as long-running. No polling behavior changes. */
const LONG_RUN_MS = 10 * 60 * 1000;

// ---------------------------------------------------------------------------
// Report payload shapes (GET /runs/{id}/report → report.pipeline_report.*)
// ---------------------------------------------------------------------------

interface CapabilityComponent {
  component_id?: string;
  component_type?: string;
  level?: string;
  reason?: string;
}

interface CapabilityReport {
  overall_level?: string;
  supported?: number;
  partial?: number;
  unsupported?: number;
  unavailable?: number;
  components?: CapabilityComponent[];
}

interface PlanComponent {
  component_id?: string;
  action?: string;
  transformer?: string;
  reason?: string;
}

interface PlanReport {
  total_programs?: number;
  transformable_programs?: number;
  skipped_programs?: number;
  components?: PlanComponent[];
  assembly?: { output_type?: string; base_package?: string; application_name?: string };
}

interface PipelineReport {
  capability?: CapabilityReport;
  plan?: PlanReport;
  assembly?: { project_dir?: string; entrypoint?: string };
  limitations?: string[];
  recommendations?: string[];
}

function readPipelineReport(report: ModernizationReportResponse | null): PipelineReport | null {
  const outer = report?.report as Record<string, unknown> | undefined;
  const inner = outer?.pipeline_report;
  if (!inner || typeof inner !== 'object') return null;
  return inner as PipelineReport;
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

function formatDuration(startIso: string | null, endIso: string | null): string | null {
  if (!startIso || !endIso) return null;
  const ms = Date.parse(endIso) - Date.parse(startIso);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const total = Math.round(ms / 1000);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function sanitizeFilenameStem(name: string, fallback: string): string {
  const stem = (name || '').trim().replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  return stem || fallback;
}

function stageBadgeVariant(stage: string): 'success' | 'error' | 'info' {
  if (stage === 'COMPLETED') return 'success';
  if (stage === 'FAILED') return 'error';
  return 'info';
}

/**
 * FAILED runs carry no stage value in RUN_STAGES — infer how far the
 * pipeline is evidenced as having progressed from real artifacts only.
 */
function failedReachedIndex(
  verdict: VerdictResponse | null,
  artifacts: ArtifactMetadata[] | null,
  report: ModernizationReportResponse | null,
): number {
  if (verdict || (artifacts && artifacts.length > 0)) {
    return RUN_STAGES.indexOf('VALIDATING_EVIDENCE');
  }
  if (readPipelineReport(report)) {
    return RUN_STAGES.indexOf('ASSEMBLY_COMPLETED');
  }
  return -1;
}

export function ModernizationRun({
  runId,
  applicationId,
  ingest,
  pollIntervalMs = POLL_INTERVAL_MS,
  onNavigate,
}: ModernizationRunProps) {
  const [run, setRun] = useState<RunResponse | null>(null);
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [verdict, setVerdict] = useState<VerdictResponse | null>(null);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactMetadata[] | null>(null);
  const [report, setReport] = useState<ModernizationReportResponse | null>(null);
  const [integratedProof, setIntegratedProof] = useState<IntegratedProofResponse | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pollFailures, setPollFailures] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const pollFailuresRef = useRef(0);

  // Opening a run straight from the dashboard passes no application id —
  // fall back to the id the run itself reports once it has loaded.
  const effectiveAppId = applicationId || run?.application_id || '';

  // Discovery is independent of run stage: fetch it as soon as the page
  // loads so programs/dependencies render whenever the API provides them
  // — including on FAILED runs. Never fabricated: panel renders only
  // from a real API response.
  useEffect(() => {
    let mounted = true;
    if (!effectiveAppId) return;
    getDiscovery(effectiveAppId)
      .then((d) => {
        if (mounted) setDiscovery(d);
      })
      .catch(() => {
        // Discovery unavailable (e.g. 404 before ingest completes).
        // The run view stays usable; a later terminal refresh retries.
      });
    return () => {
      mounted = false;
    };
  }, [effectiveAppId, runId]);

  const loadTerminalData = useCallback(async () => {
    const [v, a, d, rd, rpt, ip] = await Promise.all([
      getVerdict(runId).catch(() => null),
      getArtifacts(runId).catch(() => null),
      // Re-attempt discovery at terminal state in case the early fetch
      // raced ingestion.
      effectiveAppId ? getDiscovery(effectiveAppId).catch(() => null) : Promise.resolve(null),
      // Run detail is best-effort enrichment; absence never blocks the view.
      getRunDetail(runId).catch(() => null),
      // Modernization report (capability analysis, transformation plan).
      getReport(runId).catch(() => null),
      // Integrated proof (dependency ledger + central status).
      getIntegratedProof(runId).catch(() => null),
    ]);
    return { v, a, d, rd, rpt, ip };
  }, [runId, effectiveAppId]);

  const hasRunRef = useRef(false);

  const poll = useCallback(async () => {
    const [runData, runDetail] = await Promise.all([
      getRun(runId),
      // Detail enriches the view (app name, messages, generated files);
      // it must never fail the poll when the endpoint is unavailable.
      getRunDetail(runId).catch(() => null),
    ]);
    pollFailuresRef.current = 0;
    hasRunRef.current = true;
    setPollFailures(0);
    setPollError(null);
    setRun(runData);
    if (runDetail) setDetail(runDetail);

    if (isTerminalStage(runData.stage)) {
      try {
        const { v, a, d, rd, rpt, ip } = await loadTerminalData();
        if (v) setVerdict(v);
        // Render artifacts only when the backend actually returns them.
        if (a && a.artifacts.length > 0) setArtifacts(a.artifacts);
        if (d) setDiscovery((prev) => prev ?? d);
        if (rd) setDetail((prev) => prev ?? rd);
        if (rpt) setReport(rpt);
        if (ip) setIntegratedProof(ip);
      } catch {
        // Partial terminal data is acceptable; run state itself is shown.
      }
      return true;
    }
    return false;
  }, [runId, loadTerminalData]);

  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setInterval> | null = null;

    const tick = async () => {
      try {
        const done = await poll();
        if (done && timer) {
          clearInterval(timer);
          timer = null;
        }
      } catch (e) {
        if (!mounted) return;
        pollFailuresRef.current += 1;
        setPollFailures(pollFailuresRef.current);
        const message = e instanceof Error ? e.message : String(e);
        setPollError(message);
        if (!hasRunRef.current) {
          // Nothing loaded yet — surface as a load error with retry.
          setLoadError(message);
        }
      }
    };

    tick();
    timer = setInterval(tick, pollIntervalMs);

    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
    };
  }, [runId, poll, pollIntervalMs]);

  const handleRetryPoll = () => {
    pollFailuresRef.current = 0;
    setPollFailures(0);
    setPollError(null);
    setLoadError(null);
    poll().catch((e) => {
      const message = e instanceof Error ? e.message : String(e);
      pollFailuresRef.current = MAX_CONSECUTIVE_POLL_FAILURES;
      setPollFailures(MAX_CONSECUTIVE_POLL_FAILURES);
      setPollError(message);
      if (!hasRunRef.current) {
        setLoadError(message);
      }
    });
  };

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const blob = await downloadGenerated(runId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${sanitizeFilenameStem(detail?.application_name ?? '', run?.workload_id || 'generated')}-generated.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setPollError(`Download failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDownloading(false);
    }
  };

  const breadcrumb = [
    { label: 'Dashboard', onClick: onNavigate ? () => onNavigate('dashboard') : undefined },
  ];

  if (loadError && !run) {
    return (
      <>
        <Header
          breadcrumb={breadcrumb}
          title="Modernization Run"
          meta={<HeaderMetaItem label="Run ID" value={runId} />}
        />
        <PageContainer title="Run" subtitle={runId}>
          <SectionCard title="Could not load run">
            <p style={{ color: tokens.colors.error, fontSize: tokens.font.sizes.sm }}>
              {loadError}
            </p>
            <p style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
              Run ID: {runId}
            </p>
            <div style={{ marginTop: tokens.spacing.md }}>
              <Button variant="primary" onClick={handleRetryPoll}>
                Retry
              </Button>
            </div>
          </SectionCard>
        </PageContainer>
      </>
    );
  }

  if (!run) {
    return (
      <>
        <Header
          breadcrumb={breadcrumb}
          title="Modernization Run"
          meta={<HeaderMetaItem label="Run ID" value={runId} />}
        />
        <PageContainer title="Loading..." subtitle={runId}>
          <LoadingSpinner />
        </PageContainer>
      </>
    );
  }

  const isTerminal = isTerminalStage(run.stage);
  const showPollWarning = pollFailures >= MAX_CONSECUTIVE_POLL_FAILURES && !isTerminal;
  const createdAtMs = Date.parse(run.created_at);
  const showLongRunNotice =
    !isTerminal && !Number.isNaN(createdAtMs) && Date.now() - createdAtMs > LONG_RUN_MS;
  const appName = detail?.application_name || run.workload_id;
  // Stage messages come straight from GET /runs/{id}/detail; skip entries
  // already rendered by the progress stepper and the error panel.
  const extraStageMessages = (detail?.stage_messages ?? []).filter(
    (m) => m !== run.stage && m !== (run.error ?? '\0'),
  );

  const pipeline = readPipelineReport(report);
  const limitations = [
    ...readStringList(report?.report?.limitations),
    ...readStringList(pipeline?.limitations),
  ];
  const recommendations = [
    ...readStringList(report?.report?.recommendations),
    ...readStringList(pipeline?.recommendations),
  ];
  const capability = pipeline?.capability;
  const plan = pipeline?.plan;

  const generatedFiles = detail?.generated_files ?? [];
  const showGeneratedCard = run.stage === 'COMPLETED' || generatedFiles.length > 0;
  const generationComplete =
    run.stage !== 'FAILED' && RUN_STAGES.indexOf(run.stage) >= RUN_STAGES.indexOf('ASSEMBLY_COMPLETED');

  // Evidence-based ingestion display: a stored summary or a discovery
  // payload both prove ingestion happened — never shown otherwise.
  const ingestionEvidence = ingest ?? (discovery ? {
    applicationId: discovery.application_id,
    sourceFileCount: discovery.source_file_count,
    detectedName: '',
  } : null);

  // Metrics row — every value comes from a real API response.
  const metrics: { icon: React.ReactNode; value: number | string; label: string }[] = [];
  if (discovery) {
    metrics.push({ icon: <IconFileText size={22} />, value: discovery.source_file_count, label: 'Source Files' });
    metrics.push({ icon: <IconCode size={22} />, value: discovery.cobol_programs.length, label: 'COBOL Programs' });
    metrics.push({ icon: <IconLayers size={22} />, value: discovery.copybooks.length, label: 'Copybooks' });
    metrics.push({ icon: <IconLayers size={22} />, value: discovery.jcl_jobs.length, label: 'JCL Jobs' });
  }
  if (verdict) {
    metrics.push({ icon: <IconShieldCheck size={22} />, value: verdict.executed_check_count, label: 'Checks' });
  }
  if (artifacts) {
    metrics.push({ icon: <IconDatabase size={22} />, value: artifacts.length, label: 'Artifacts' });
  }
  if (detail) {
    metrics.push({ icon: <IconPackage size={22} />, value: detail.generated_files.length, label: 'Generated Files' });
  }
  const duration = formatDuration(run.created_at, run.completed_at);
  if (duration) {
    metrics.push({ icon: <IconTimer size={22} />, value: duration, label: 'Duration' });
  }

  return (
    <>
      <Header
        breadcrumb={breadcrumb}
        title={appName}
        meta={
          <>
            <HeaderMetaItem label="Run ID" value={run.id} />
            <HeaderMetaItem label="Application" value={run.application_id} />
            <HeaderMetaItem label="Workload" value={run.workload_id} />
          </>
        }
        right={
          <>
            {verdict && run.stage === 'COMPLETED' && (
              <Badge
                variant={
                  verdict.state === 'VERIFIED'
                    ? 'success'
                    : verdict.state === 'FAILED' || verdict.state === 'ERROR'
                      ? 'error'
                      : 'warning'
                }
                size="sm"
              >
                {verdict.state}
              </Badge>
            )}
            <Badge variant={stageBadgeVariant(run.stage)} size="sm">
              {run.stage}
            </Badge>
          </>
        }
      />
      <PageContainer>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.lg }}>
          {/* Long-running (non-terminal past the soft ceiling) — informational */}
          {showLongRunNotice && (
            <SectionCard title="Still running">
              <p style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
                This run has been in progress for a while. Live status checks
                continue; Docker builds and validations can take several
                minutes. Run ID: {runId}
              </p>
            </SectionCard>
          )}

          {/* Polling interruption — visible, non-blocking, with retry */}
          {showPollWarning && (
            <SectionCard title="Live updates interrupted">
              <p style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
                {pollFailures} consecutive status checks failed
                {pollError ? `: ${pollError}` : ''}. The run may still be
                progressing on the server. Run ID: {runId}
              </p>
              <div style={{ marginTop: tokens.spacing.sm }}>
                <Button variant="secondary" size="sm" onClick={handleRetryPoll}>
                  Retry now
                </Button>
              </div>
            </SectionCard>
          )}

          {/* Source ingestion — completed pre-run step, never a run stage */}
          {ingestionEvidence && (
            <SectionCard title="Source Ingestion" subtitle="Completed before this run started.">
              <div style={{ display: 'flex', gap: tokens.spacing.md, alignItems: 'center', flexWrap: 'wrap' }}>
                <Badge variant="success" size="sm">INGESTED</Badge>
                <span style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
                  {ingestionEvidence.sourceFileCount} source file{ingestionEvidence.sourceFileCount !== 1 ? 's' : ''} ingested
                  {ingestionEvidence.detectedName ? ` \u2022 detected name: ${ingestionEvidence.detectedName}` : ''}
                </span>
              </div>
              {!ingest && (
                <div style={{ marginTop: tokens.spacing.xs, fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                  Summary derived from the stored discovery payload (no ingest summary in this session).
                </div>
              )}
            </SectionCard>
          )}

          {/* Progress — horizontal pipeline in exact backend emission order */}
          <SectionCard title="Progress">
            <PipelineStepper
              stage={run.stage}
              showIngested={!!ingestionEvidence}
              failedReachedIndex={failedReachedIndex(verdict, artifacts, report)}
            />
          </SectionCard>

          {/* Metrics row — real API values only */}
          {metrics.length > 0 && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                gap: tokens.spacing.md,
              }}
            >
              {metrics.map((m) => (
                <StatCard key={m.label} icon={m.icon} value={m.value} label={m.label} />
              ))}
            </div>
          )}

          {/* Error — terminal failure explanation with run context */}
          {typeof run.error === 'string' && run.error.length > 0 && (
            <SectionCard title="Error">
              <p style={{ color: tokens.colors.error, fontSize: tokens.font.sizes.sm, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                {String(run.error)}
              </p>
              <p style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                Stage: {String(run.stage)} {' \u2022 '} Run ID: {String(run.id)}
              </p>
            </SectionCard>
          )}

          {/* Discovery — rendered whenever the API provided it, any stage */}
          {discovery && (
            <SectionCard title="Discovery Results">
              <div style={{ display: 'grid', gap: tokens.spacing.lg }}>
                {/* Edge counts — computed from backend dependency edges */}
                <div style={{ display: 'flex', gap: tokens.spacing.md, flexWrap: 'wrap' }}>
                  <EdgeStat
                    label="CALL Edges"
                    value={discovery.dependency_edges.filter((e) => e.edge_type === 'CALL').length}
                  />
                  <EdgeStat
                    label="COPY Edges"
                    value={discovery.dependency_edges.filter((e) => e.edge_type === 'COPY').length}
                  />
                  <EdgeStat
                    label="File Edges"
                    value={discovery.dependency_edges.filter(
                      (e) => e.edge_type !== 'CALL' && e.edge_type !== 'COPY',
                    ).length}
                  />
                </div>

                {/* Programs */}
                {discovery.cobol_programs.length > 0 && (
                  <div>
                    <div style={subheadingStyle}>COBOL Programs ({discovery.cobol_programs.length})</div>
                    <div style={{ overflowX: 'auto' }}>
                      <table
                        style={{ width: '100%', borderCollapse: 'collapse', fontSize: tokens.font.sizes.sm }}
                        aria-label="Discovered COBOL programs"
                      >
                        <thead>
                          <tr style={{ borderBottom: `2px solid ${tokens.colors.divider}`, textAlign: 'left' }}>
                            <th style={thStyle}>Program</th>
                            <th style={thStyle}>Type</th>
                            <th style={thStyle}>Status</th>
                            <th style={thStyle}>Calls</th>
                            <th style={thStyle}>Files</th>
                          </tr>
                        </thead>
                        <tbody>
                          {discovery.cobol_programs.map((prog) => {
                            // Type is derived from the call graph: a program
                            // with no incoming CALL edge is a main program.
                            const hasIncomingCall = discovery.dependency_edges.some(
                              (e) => e.edge_type === 'CALL' && e.target === prog.program_id,
                            );
                            const type = hasIncomingCall ? 'SUB' : 'MAIN';
                            return (
                              <tr
                                key={prog.program_id}
                                style={{ borderBottom: `1px solid ${tokens.colors.divider}`, verticalAlign: 'top' }}
                              >
                                <td style={tdStyle}>
                                  <div style={{ fontWeight: tokens.font.weights.medium }}>
                                    {prog.program_id}
                                    {prog.entry_points.length > 0 && (
                                      <Badge variant="success" size="sm">ENTRY</Badge>
                                    )}
                                  </div>
                                  <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                                    {prog.source_path}
                                  </div>
                                </td>
                                <td style={tdStyle}>
                                  <span
                                    title={
                                      type === 'MAIN'
                                        ? 'Derived from the call graph: no incoming CALL edge'
                                        : 'Derived from the call graph: has an incoming CALL edge'
                                    }
                                  >
                                    <Badge variant={type === 'MAIN' ? 'info' : 'default'} size="sm">
                                      {type}
                                    </Badge>
                                  </span>
                                </td>
                                <td style={tdStyle}>
                                  <Badge variant="success" size="sm">Discovered</Badge>
                                </td>
                                <td style={{ ...tdStyle, color: tokens.colors.textSecondary }}>
                                  {prog.calls.length > 0
                                    ? prog.calls.map((c) => c.target).join(', ')
                                    : '\u2014'}
                                </td>
                                <td style={{ ...tdStyle, color: tokens.colors.textSecondary }}>
                                  {prog.file_dependencies.length > 0
                                    ? prog.file_dependencies.map((f) => `${f.name} (${f.operation})`).join(', ')
                                    : '\u2014'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Copybooks */}
                {discovery.copybooks.length > 0 && (
                  <div>
                    <div style={subheadingStyle}>Copybooks ({discovery.copybooks.length})</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacing.xs }}>
                      {discovery.copybooks.map((cb) => (
                        <Badge key={cb} variant="default" size="sm">{cb}</Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* JCL Jobs */}
                {discovery.jcl_jobs.length > 0 && (
                  <div>
                    <div style={subheadingStyle}>JCL Jobs ({discovery.jcl_jobs.length})</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs }}>
                      {discovery.jcl_jobs.map((job) => (
                        <div key={job.name} style={itemRowStyle}>
                          <span style={{ fontWeight: tokens.font.weights.medium }}>{job.name}</span>
                          <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                            {job.steps.length} step{job.steps.length !== 1 ? 's' : ''}
                            {job.steps.length > 0 && `: ${job.steps.map((s) => s.program ?? s.procedure ?? s.name).join(', ')}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Dependencies — collapsible */}
                {discovery.dependency_edges.length > 0 && (
                  <details className="collapsible" open>
                    <summary>Dependencies ({discovery.dependency_edges.length})</summary>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs, marginTop: tokens.spacing.sm }}>
                      {discovery.dependency_edges.map((edge, i) => (
                        <div key={i} style={itemRowStyle}>
                          <span style={{ fontWeight: tokens.font.weights.medium }}>{edge.source}</span>
                          <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.sm }}>{' \u2192 '}</span>
                          <span style={{ fontWeight: tokens.font.weights.medium }}>{edge.target}</span>
                          <Badge variant="info" size="sm">{edge.edge_type}</Badge>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </SectionCard>
          )}

          {/* Capability Analysis — from universal pipeline report */}
          {capability && capability.components && capability.components.length > 0 && (
            <SectionCard
              title="Capability Analysis"
              subtitle={
                capability.overall_level
                  ? `${capability.overall_level} \u2022 ${capability.supported ?? 0} supported / ${capability.partial ?? 0} partial / ${capability.unsupported ?? 0} unsupported`
                  : undefined
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm, fontSize: tokens.font.sizes.sm }}>
                {capability.components.map((component, i) => (
                  <div key={component.component_id ?? i} style={itemRowStyle}>
                    <Badge
                      variant={
                        component.level === 'SUPPORTED'
                          ? 'success'
                          : component.level === 'PARTIAL'
                            ? 'warning'
                            : 'error'
                      }
                      size="sm"
                    >
                      {component.level ?? 'UNKNOWN'}
                    </Badge>
                    <span style={{ fontWeight: tokens.font.weights.medium }}>{component.component_id}</span>
                    <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                      {component.component_type}
                    </span>
                    {component.reason && (
                      <span style={{ color: tokens.colors.textMuted }}>{'\u2014'} {component.reason}</span>
                    )}
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {/* Transformation Plan — from universal pipeline report */}
          {plan && plan.components && plan.components.length > 0 && (
            <SectionCard
              title="Transformation Plan"
              subtitle={`${plan.total_programs ?? 0} programs \u2022 ${plan.transformable_programs ?? 0} transformable \u2022 ${plan.skipped_programs ?? 0} skipped`}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm, fontSize: tokens.font.sizes.sm }}>
                {plan.components.map((component, i) => (
                  <div key={component.component_id ?? i} style={itemRowStyle}>
                    <Badge variant={component.action === 'TRANSFORM' ? 'info' : 'default'} size="sm">
                      {component.action ?? 'SKIP'}
                    </Badge>
                    <span style={{ fontWeight: tokens.font.weights.medium }}>{component.component_id}</span>
                    <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                      {component.transformer}
                    </span>
                    {component.reason && (
                      <span style={{ color: tokens.colors.textMuted }}>{'\u2014'} {component.reason}</span>
                    )}
                  </div>
                ))}
                {(plan.assembly || pipeline?.assembly?.entrypoint) && (
                  <div style={{ ...itemRowStyle, background: tokens.colors.primaryLight }}>
                    <span style={{ color: tokens.colors.textMuted }}>Assembly:</span>
                    <span style={{ fontWeight: tokens.font.weights.medium }}>
                      {plan.assembly?.output_type ?? 'SPRING_BOOT'}
                    </span>
                    {plan.assembly?.base_package && (
                      <span style={{ color: tokens.colors.textSecondary }}>{plan.assembly.base_package}</span>
                    )}
                    {pipeline?.assembly?.entrypoint && (
                      <span style={{ color: tokens.colors.textSecondary, fontFamily: 'monospace', fontSize: tokens.font.sizes.xs }}>
                        {pipeline.assembly.entrypoint}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </SectionCard>
          )}

          {/* Generated Java Application */}
          {showGeneratedCard && (
            <SectionCard
              title="Generated Java Application"
              subtitle={generationComplete ? 'Generation Complete' : undefined}
              headerRight={
                run.stage === 'COMPLETED' && generatedFiles.length > 0 ? (
                  <Button variant="gradient" size="md" onClick={handleDownload} disabled={downloading}>
                    {downloading ? 'Downloading...' : 'Download Generated Spring Boot Application'}
                  </Button>
                ) : undefined
              }
            >
              {generatedFiles.length > 0 ? (
                <>
                  <div style={{ overflowX: 'auto' }}>
                    <table
                      style={{ width: '100%', borderCollapse: 'collapse', fontSize: tokens.font.sizes.sm }}
                      aria-label="Generated Java files"
                    >
                      <thead>
                        <tr style={{ borderBottom: `2px solid ${tokens.colors.divider}`, textAlign: 'left' }}>
                          <th style={thStyle}>File Path</th>
                          <th style={{ ...thStyle, width: 90 }}>Size</th>
                          <th style={{ ...thStyle, width: 70 }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {generatedFiles.map((file) => (
                          <tr key={file} style={{ borderBottom: `1px solid ${tokens.colors.divider}` }}>
                            <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: tokens.font.sizes.xs, wordBreak: 'break-all' }}>
                              {file}
                            </td>
                            <td style={{ ...tdStyle, color: tokens.colors.textMuted }}>{'\u2014'}</td>
                            <td style={tdStyle}>
                              <CopyButton value={file} label={`Copy ${file}`} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ marginTop: tokens.spacing.sm, fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                    Per-file sizes are not exposed by the API. The download button serves the complete
                    generated Spring Boot archive.
                  </div>
                </>
              ) : (
                <div style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
                  <p>Generated application files are reported by the assembly stage once available.</p>
                  {run.stage === 'COMPLETED' && (
                    <div style={{ marginTop: tokens.spacing.md }}>
                      <Button variant="gradient" size="lg" onClick={handleDownload} disabled={downloading}>
                        {downloading ? 'Downloading...' : 'Download Generated Spring Boot Application'}
                      </Button>
                    </div>
                  )}
                  <div style={{ marginTop: tokens.spacing.sm, fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                    Behavioral/artifact validation within the declared validation scope.
                  </div>
                </div>
              )}
            </SectionCard>
          )}

          {/* Validation Evidence — all seven states rendered by VerdictDisplay */}
          {verdict && <VerdictDisplay verdict={verdict} />}

          {/* Evidence artifacts — only when the backend returns them */}
          {artifacts && artifacts.length > 0 && (
            <SectionCard title="Evidence Artifacts" count={artifacts.length}>
              <div style={{ overflowX: 'auto' }}>
                <table
                  style={{ width: '100%', borderCollapse: 'collapse', fontSize: tokens.font.sizes.base }}
                  aria-label="Evidence artifact metadata"
                >
                  <thead>
                    <tr style={{ borderBottom: '2px solid ' + tokens.colors.divider, textAlign: 'left' }}>
                      <th style={thStyle}>Artifact</th>
                      <th style={thStyle}>Type</th>
                      <th style={thStyle}>Producer</th>
                      <th style={thStyle}>Size</th>
                      <th style={thStyle}>Content hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {artifacts.map((a) => (
                      <tr key={a.artifact_id} style={{ borderBottom: '1px solid ' + tokens.colors.divider }}>
                        <td style={tdStyle}>{a.logical_name}</td>
                        <td style={tdStyle}>{a.artifact_type}</td>
                        <td style={tdStyle}>
                          <Badge variant={a.producer_role === 'ORACLE' ? 'info' : 'success'} size="sm">
                            {a.producer_role}
                          </Badge>
                        </td>
                        <td style={{ ...tdStyle, color: tokens.colors.textMuted }}>{a.size_bytes} B</td>
                        <td style={{ ...tdStyle, color: tokens.colors.textMuted, fontFamily: 'monospace', fontSize: tokens.font.sizes.xs }}>
                          {a.content_hash.slice(0, 24)}{'\u2026'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          )}

          {/* Integrated Proof — dependency ledger + central status gate */}
          {integratedProof && <IntegratedProof proof={integratedProof} />}

          {/* Validation Scope — verbatim backend scope statement + identity hashes */}
          {verdict && <ValidationScope verdict={verdict} />}

          {/* Limitations & recommendations — collapsible */}
          {(limitations.length > 0 || recommendations.length > 0) && (
            <details className="collapsible" style={{ ...cardStyle, padding: 0 }}>
              <summary style={{ padding: `${tokens.spacing.md} ${tokens.spacing.lg}` }}>
                Limitations ({limitations.length})
              </summary>
              <div style={{ padding: `0 ${tokens.spacing.lg} ${tokens.spacing.lg}` }}>
                {limitations.length > 0 && (
                  <ul style={{ margin: 0, paddingLeft: 20, fontSize: tokens.font.sizes.sm }}>
                    {limitations.map((lim, i) => (
                      <li key={i} style={{ color: tokens.colors.textSecondary, marginBottom: tokens.spacing.xs }}>{lim}</li>
                    ))}
                  </ul>
                )}
                {recommendations.length > 0 && (
                  <>
                    <div style={{ ...subheadingStyle, marginTop: tokens.spacing.md }}>
                      Recommendations ({recommendations.length})
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 20, fontSize: tokens.font.sizes.sm }}>
                      {recommendations.map((rec, i) => (
                        <li key={i} style={{ color: tokens.colors.textSecondary, marginBottom: tokens.spacing.xs }}>{rec}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </details>
          )}

          {/* Run detail — served by GET /runs/{id}/detail when available */}
          {detail !== null && (
            <SectionCard title="Run Details">
              <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs, fontSize: tokens.font.sizes.sm }}>
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Application: </span>
                  <span style={{ fontWeight: tokens.font.weights.medium }}>{String(detail.application_name ?? run.application_id)}</span>
                </div>
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Workload: </span>
                  <span>{String(detail.workload_id)}</span>
                </div>
                {detail.verdict_state && (
                  <div>
                    <span style={{ color: tokens.colors.textMuted }}>Verdict: </span>
                    <Badge variant={detail.verdict_state === 'VERIFIED' ? 'success' : detail.verdict_state === 'FAILED' || detail.verdict_state === 'ERROR' ? 'error' : 'warning'} size="sm">
                      {String(detail.verdict_state)}
                    </Badge>
                  </div>
                )}
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Created: </span>
                  <span>{new Date(detail.created_at).toLocaleString()}</span>
                </div>
                {detail.completed_at && (
                  <div>
                    <span style={{ color: tokens.colors.textMuted }}>Completed: </span>
                    <span>{new Date(detail.completed_at).toLocaleString()}</span>
                  </div>
                )}
                {extraStageMessages.length > 0 && (
                  <div>
                    <div style={{ color: tokens.colors.textMuted }}>Stage messages:</div>
                    <ul style={{ margin: `${tokens.spacing.xs} 0 0`, paddingLeft: 20 }}>
                      {extraStageMessages.map((m, i) => (
                        <li key={i} style={{ color: tokens.colors.textSecondary }}>{String(m)}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </SectionCard>
          )}
        </div>
      </PageContainer>
    </>
  );
}

function EdgeStat({ label, value }: { label: string; value: number }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: `${tokens.spacing.sm} ${tokens.spacing.md}`,
        borderRadius: tokens.radii.sm,
        background: tokens.colors.surfaceAlt,
        border: '1px solid ' + tokens.colors.cardBorder,
        minWidth: 90,
      }}
    >
      <span style={{ fontSize: tokens.font.sizes.xl, fontWeight: tokens.font.weights.bold, color: tokens.colors.primary }}>
        {value}
      </span>
      <span style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted, textAlign: 'center' }}>
        {label}
      </span>
    </div>
  );
}

const subheadingStyle: React.CSSProperties = {
  fontSize: tokens.font.sizes.sm,
  fontWeight: tokens.font.weights.bold,
  color: tokens.colors.primary,
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  marginBottom: tokens.spacing.xs,
};

const itemRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: tokens.spacing.sm,
  padding: '8px 12px',
  borderRadius: tokens.radii.sm,
  background: tokens.colors.surfaceAlt,
  border: '1px solid ' + tokens.colors.cardBorder,
  fontSize: tokens.font.sizes.sm,
  flexWrap: 'wrap',
};

const cardStyle: React.CSSProperties = {
  background: tokens.colors.cardBg,
  borderRadius: tokens.radii.md,
  border: `1px solid ${tokens.colors.cardBorder}`,
  boxShadow: tokens.colors.shadow,
  overflow: 'hidden',
};

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontWeight: tokens.font.weights.semibold,
  color: tokens.colors.textSecondary,
};

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
};
