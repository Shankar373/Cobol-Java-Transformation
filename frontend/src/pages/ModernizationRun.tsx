import React, { useEffect, useState, useCallback, useRef } from 'react';
import { tokens } from '../theme/tokens';
import {
  PageContainer,
  SectionCard,
  Badge,
  Button,
  VerdictDisplay,
  LoadingSpinner,
} from '../components';
import {
  RunResponse,
  VerdictResponse,
  DiscoveryResult,
  ArtifactMetadata,
  RunDetailResponse,
  ModernizationReportResponse,
  getRun,
  getRunDetail,
  getVerdict,
  getDiscovery,
  getArtifacts,
  getReport,
  downloadGenerated,
} from '../api/client';
import {
  RUN_STAGES,
  STAGE_LABELS,
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
}

const POLL_INTERVAL_MS = 1500;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;
/** Informational only: runs older than this without a terminal stage are
 *  flagged as long-running. No polling behavior changes. */
const LONG_RUN_MS = 10 * 60 * 1000;

/**
 * User-facing pipeline: one node per original modernization phase.
 * Backend completion markers are authoritative lifecycle states, but they
 * are intentionally collapsed into their parent phase in the UI.
 */
const DISPLAY_PIPELINE: Array<{ key: string; label: string; stages: RunResponse['stage'][] }> = [
  { key: 'CREATED', label: 'Created', stages: ['CREATED'] },
  { key: 'DISCOVERING', label: 'Discovering', stages: ['DISCOVERING', 'DISCOVERY_COMPLETED'] },
  { key: 'ANALYZING', label: 'Analyzing', stages: ['ANALYZING', 'ANALYSIS_COMPLETED'] },
  { key: 'PLANNING', label: 'Planning', stages: ['PLANNING', 'PLAN_COMPLETED'] },
  { key: 'TRANSFORMING', label: 'Transforming', stages: ['TRANSFORMING'] },
  { key: 'GENERATING', label: 'Generating', stages: ['GENERATING'] },
  { key: 'ASSEMBLING', label: 'Assembling', stages: ['ASSEMBLING', 'ASSEMBLY_COMPLETED'] },
  { key: 'EXECUTING_ORACLE', label: 'Executing Oracle', stages: ['EXECUTING_ORACLE'] },
  { key: 'BUILDING', label: 'Building', stages: ['BUILDING'] },
  { key: 'EXECUTING_GENERATED', label: 'Executing Generated', stages: ['EXECUTING_GENERATED'] },
  { key: 'COMPARING', label: 'Comparing', stages: ['COMPARING'] },
  { key: 'VALIDATING_EVIDENCE', label: 'Validating Evidence', stages: ['VALIDATING_EVIDENCE'] },
  { key: 'COMPLETED', label: 'Completed', stages: ['COMPLETED'] },
];

const DISPLAY_COMPLETION_STAGES = new Set<RunResponse['stage']>([
  'DISCOVERY_COMPLETED',
  'ANALYSIS_COMPLETED',
  'PLAN_COMPLETED',
  'ASSEMBLY_COMPLETED',
  'COMPLETED',
]);

function sanitizeFilenameStem(name: string, fallback: string): string {
  const stem = (name || '').trim().replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  return stem || fallback;
}

export function ModernizationRun({ runId, applicationId, ingest, pollIntervalMs = POLL_INTERVAL_MS }: ModernizationRunProps) {
  const [run, setRun] = useState<RunResponse | null>(null);
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [verdict, setVerdict] = useState<VerdictResponse | null>(null);
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactMetadata[] | null>(null);
  const [report, setReport] = useState<ModernizationReportResponse | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pollFailures, setPollFailures] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const pollFailuresRef = useRef(0);

  // Discovery is independent of run stage: fetch it as soon as the page
  // loads so programs/dependencies render whenever the API provides them
  // — including on FAILED runs. Never fabricated: panel renders only
  // from a real API response.
  useEffect(() => {
    let mounted = true;
    if (!applicationId) return;
    getDiscovery(applicationId)
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
  }, [applicationId, runId]);

  const loadTerminalData = useCallback(async () => {
    const [v, a, d, rd, rpt] = await Promise.all([
      getVerdict(runId).catch(() => null),
      getArtifacts(runId).catch(() => null),
      // Re-attempt discovery at terminal state in case the early fetch
      // raced ingestion.
      applicationId ? getDiscovery(applicationId).catch(() => null) : Promise.resolve(null),
      // Run detail is best-effort enrichment; absence never blocks the view.
      getRunDetail(runId).catch(() => null),
      // Modernization report (capability analysis, transformation plan).
      getReport(runId).catch(() => null),
    ]);
    return { v, a, d, rd, rpt };
  }, [runId, applicationId]);

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
        const { v, a, d, rd, rpt } = await loadTerminalData();
        if (v) setVerdict(v);
        // Render artifacts only when the backend actually returns them.
        if (a && a.artifacts.length > 0) setArtifacts(a.artifacts);
        if (d) setDiscovery((prev) => prev ?? d);
        if (rd) setDetail((prev) => prev ?? rd);
        if (rpt) setReport(rpt);
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

  if (loadError && !run) {
    return (
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
    );
  }

  if (!run) {
    return (
      <PageContainer title="Loading..." subtitle={runId}>
        <LoadingSpinner />
      </PageContainer>
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

  const showCapabilityReport = !!report?.report?.capability_report;
  const showTransformationPlan = !!report?.report?.transformation_plan;
  const reportLimitations = report?.report?.limitations;
  const showLimitations = Array.isArray(reportLimitations) && reportLimitations.length > 0;
  const reportRecommendations = report?.report?.recommendations;
  const showRecommendations = Array.isArray(reportRecommendations) && reportRecommendations.length > 0;

  return (
    <PageContainer
      title={appName}
      subtitle={`Run ${run.id} \u2022 Application ${run.application_id}`}
    >
      {/* Long-running (non-terminal past the soft ceiling) — informational */}
      {showLongRunNotice && (
        <>
          <SectionCard title="Still running">
            <p style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
              This run has been in progress for a while. Live status checks
              continue; Docker builds and validations can take several
              minutes. Run ID: {runId}
            </p>
          </SectionCard>
          <div style={{ height: tokens.spacing.md }} />
        </>
      )}
      {/* Polling interruption — visible, non-blocking, with retry */}
      {showPollWarning && (
        <>
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
          <div style={{ height: tokens.spacing.md }} />
        </>
      )}

      {/* Source ingestion — completed pre-run step, never a run stage */}
      {ingest && (
        <>
          <SectionCard title="Source Ingestion">
            <div style={{ display: 'flex', gap: tokens.spacing.md, alignItems: 'center', flexWrap: 'wrap' }}>
              <Badge variant="success" size="sm">COMPLETED</Badge>
              <span style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
                {ingest.sourceFileCount} source file{ingest.sourceFileCount !== 1 ? 's' : ''} ingested
                {ingest.detectedName ? ` \u2022 detected name: ${ingest.detectedName}` : ''}
              </span>
            </div>
            <div style={{ marginTop: tokens.spacing.xs, fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
              Ingestion is a separate step that finished before this run started.
            </div>
          </SectionCard>
          <div style={{ height: tokens.spacing.md }} />
        </>
      )}

      {/* Progress — simplified original modernization phases; backend lifecycle sub-states are collapsed. */}
      <SectionCard title="Progress">
        <div style={pipelineViewportStyle} aria-label="Modernization pipeline">
          <div style={pipelineTrackStyle}>
            {DISPLAY_PIPELINE.map((phase, i) => {
              const currentIndex = DISPLAY_PIPELINE.findIndex((p) => p.stages.includes(run.stage));
              const isTerminalSuccess = run.stage === 'COMPLETED';
              const phaseContainsCurrentStage = phase.stages.includes(run.stage);
              const phaseIsCompletionState = phaseContainsCurrentStage && DISPLAY_COMPLETION_STAGES.has(run.stage);
              const isDone = isTerminalSuccess || currentIndex > i || (currentIndex === i && phaseIsCompletionState);
              const isActive = currentIndex === i && !isDone && !isTerminal;
              const state = isActive ? 'active' : isDone ? 'complete' : 'pending';

              return (
                <React.Fragment key={phase.key}>
                  <div style={pipelineNodeStyle}>
                    <div style={pipelineCircleStyle(state)} aria-current={isActive ? 'step' : undefined}>
                      {isDone ? '✓' : isActive ? '•' : i + 1}
                    </div>
                    <span style={pipelineLabelStyle(state)}>{phase.label}</span>
                    {isActive && (
                      <span style={pipelineActiveStyle} aria-label="In progress">
                        <LoadingSpinner size={12} />
                      </span>
                    )}
                  </div>
                  {i < DISPLAY_PIPELINE.length - 1 && (
                    <div style={pipelineConnectorStyle(isDone)} aria-hidden="true" />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>
        {run.stage === 'FAILED' && (
          <div style={pipelineFailureStyle}>
            <strong>Run failed — see error details below</strong>
            <span>{run.error ? String(run.error) : 'The modernization run stopped before completion.'}</span>
          </div>
        )}
      </SectionCard>

      {/* Error — terminal failure explanation with run context */}
      {typeof run.error === 'string' && run.error.length > 0 && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Error">
            <p style={{ color: tokens.colors.error, fontSize: tokens.font.sizes.sm, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {String(run.error)}
            </p>
            <p style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
              Run ID: {String(run.id)} \u2022 Application: {String(run.application_id)}
            </p>
          </SectionCard>
        </>
      )}

      {/* Run detail — served by GET /runs/{id}/detail when available */}
      {detail !== null && (
        <>
          <div style={{ height: tokens.spacing.md }} />
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
              {detail.generated_files.length > 0 && (
                <div>
                  <div style={{ color: tokens.colors.textMuted }}>
                    Generated files ({detail.generated_files.length}):
                  </div>
                  <ul style={{ margin: `${tokens.spacing.xs} 0 0`, paddingLeft: 20, fontFamily: 'monospace', fontSize: tokens.font.sizes.xs }}>
                    {detail.generated_files.map((f) => (
                      <li key={f} style={{ color: tokens.colors.textSecondary }}>{String(f)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </SectionCard>
        </>
      )}

      {/* Discovery — rendered whenever the API provided it, any stage */}
      {discovery && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Discovery Results">
            <div style={{ display: 'grid', gap: tokens.spacing.lg }}>
              {/* Summary stats — counts only what the backend returned */}
              <div style={{ display: 'flex', gap: tokens.spacing.md, flexWrap: 'wrap' }}>
                <StatBadge label="Source Files" value={discovery.source_file_count} />
                <StatBadge label="COBOL Programs" value={discovery.cobol_programs.length} />
                <StatBadge label="Copybooks" value={discovery.copybooks.length} />
                <StatBadge label="JCL Jobs" value={discovery.jcl_jobs.length} />
                <StatBadge
                  label="CALL Edges"
                  value={discovery.dependency_edges.filter((e) => e.edge_type === 'CALL').length}
                />
                <StatBadge
                  label="COPY Edges"
                  value={discovery.dependency_edges.filter((e) => e.edge_type === 'COPY').length}
                />
              </div>

              {/* Programs */}
              {discovery.cobol_programs.length > 0 && (
                <div>
                  <div style={subheadingStyle}>COBOL Programs</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs }}>
                    {discovery.cobol_programs.map((prog) => (
                      <div key={prog.program_id} style={itemRowStyle}>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: tokens.font.weights.medium }}>{prog.program_id}</div>
                          <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                            {prog.source_path}
                          </div>
                          {prog.calls.length > 0 && (
                            <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                              Calls: {prog.calls.map((c) => c.target).join(', ')}
                            </div>
                          )}
                          {prog.file_dependencies.length > 0 && (
                            <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                              Files: {prog.file_dependencies.map((f) => `${f.name} (${f.operation})`).join(', ')}
                            </div>
                          )}
                        </div>
                        {prog.entry_points.length > 0 && (
                          <Badge variant="success" size="sm">ENTRY</Badge>
                        )}
                        {prog.calls.length > 0 && (
                          <Badge variant="info" size="sm">{prog.calls.length} CALL{prog.calls.length > 1 ? 'S' : ''}</Badge>
                        )}
                        {prog.copybooks.length > 0 && (
                          <Badge variant="purple" size="sm">{prog.copybooks.length} COPY</Badge>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Copybooks */}
              {discovery.copybooks.length > 0 && (
                <div>
                  <div style={subheadingStyle}>Copybooks</div>
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
                  <div style={subheadingStyle}>JCL Jobs</div>
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

              {/* Dependencies */}
              {discovery.dependency_edges.length > 0 && (
                <div>
                  <div style={subheadingStyle}>Dependencies</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs }}>
                    {discovery.dependency_edges.map((edge, i) => (
                      <div key={i} style={itemRowStyle}>
                        <span style={{ fontWeight: tokens.font.weights.medium }}>{edge.source}</span>
                        <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.sm }}>\u2192</span>
                        <span style={{ fontWeight: tokens.font.weights.medium }}>{edge.target}</span>
                        <Badge variant="info" size="sm">{edge.edge_type}</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </SectionCard>
        </>
      )}

      {/* Evidence artifacts — only when the backend returns them */}
      {artifacts && artifacts.length > 0 && (
        <>
          <div style={{ height: tokens.spacing.md }} />
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
                        {a.content_hash.slice(0, 24)}\u2026
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}

      {/* Capability Analysis — from universal pipeline report */}
      {showCapabilityReport && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Capability Analysis">
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm, fontSize: tokens.font.sizes.sm }}>
              {Object.entries(report.report.capability_report as Record<string, Record<string, string>>).map(([component, details]) => (
                <div key={component} style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm }}>
                  <Badge variant={details.status === 'SUPPORTED' ? 'success' : details.status === 'PARTIAL' ? 'warning' : 'error'} size="sm">
                    {details.status}
                  </Badge>
                  <span style={{ fontWeight: tokens.font.weights.medium }}>{component}</span>
                  {details.reason && (
                    <span style={{ color: tokens.colors.textMuted }}>\u2014 {details.reason}</span>
                  )}
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}

      {/* Transformation Plan — from universal pipeline report */}
      {showTransformationPlan && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Transformation Plan">
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm, fontSize: tokens.font.sizes.sm }}>
              {!!(report.report.transformation_plan as Record<string, unknown>).programs && (
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Programs: </span>
                  <span>{String(((report.report.transformation_plan as Record<string, unknown>).programs as unknown[])?.length ?? 0)}</span>
                </div>
              )}
              {!!(report.report.transformation_plan as Record<string, unknown>).entrypoint && (
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Entrypoint: </span>
                  <span>{String((report.report.transformation_plan as Record<string, unknown>).entrypoint ?? '')}</span>
                </div>
              )}
              {!!(report.report.transformation_plan as Record<string, unknown>).oracle_config && (
                <div>
                  <span style={{ color: tokens.colors.textMuted }}>Oracle: </span>
                  <Badge variant="info" size="sm">
                    {String(((report.report.transformation_plan as Record<string, unknown>).oracle_config as Record<string, unknown>)?.type ?? 'unknown')}
                  </Badge>
                </div>
              )}
            </div>
          </SectionCard>
        </>
      )}

      {/* Limitations — from universal pipeline report */}
      {showLimitations && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Limitations" count={(reportLimitations as unknown[]).length}>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: tokens.font.sizes.sm }}>
              {(reportLimitations as string[]).map((lim, i) => (
                <li key={i} style={{ color: tokens.colors.textSecondary, marginBottom: tokens.spacing.xs }}>{String(lim)}</li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}

      {/* Recommendations — from universal pipeline report */}
      {showRecommendations && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Recommendations" count={(reportRecommendations as unknown[]).length}>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: tokens.font.sizes.sm }}>
              {(reportRecommendations as string[]).map((rec, i) => (
                <li key={i} style={{ color: tokens.colors.textSecondary, marginBottom: tokens.spacing.xs }}>{String(rec)}</li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}

      {/* Verdict — all seven states rendered by VerdictDisplay */}
      {verdict && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <VerdictDisplay verdict={verdict} />
        </>
      )}

      {/* Download — canonical generated application only */}
      {run.stage === 'COMPLETED' && (
        <>
          <div style={{ height: tokens.spacing.md }} />
          <SectionCard title="Generated Application">
            <div style={{ display: 'flex', gap: tokens.spacing.md, alignItems: 'center' }}>
              <Button
                variant="gradient"
                size="lg"
                onClick={handleDownload}
                disabled={downloading}
              >
                {downloading ? 'Downloading...' : 'Download Generated Spring Boot Application'}
              </Button>
            </div>
            <div style={{ marginTop: tokens.spacing.sm, fontSize: tokens.font.sizes.sm, color: tokens.colors.textMuted }}>
              Behavioral/artifact validation within the declared validation scope.
            </div>
          </SectionCard>
        </>
      )}
    </PageContainer>
  );
}

function StatBadge({ label, value }: { label: string; value: number }) {
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

const pipelineViewportStyle: React.CSSProperties = {
  overflowX: 'auto',
  padding: '8px 4px 12px',
  scrollbarWidth: 'thin',
};

const pipelineTrackStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  minWidth: 1040,
  padding: '10px 4px 4px',
};

const pipelineNodeStyle: React.CSSProperties = {
  width: 72,
  flex: '0 0 72px',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  position: 'relative',
  textAlign: 'center',
};

function pipelineCircleStyle(state: 'complete' | 'active' | 'pending'): React.CSSProperties {
  return {
    width: 30,
    height: 30,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 11,
    fontWeight: 700,
    background:
      state === 'complete' ? '#2dd4bf'
        : state === 'active' ? '#1f8cff'
          : '#21364d',
    color: state === 'pending' ? '#6f91b2' : '#06101c',
    border: state === 'active' ? '3px solid rgba(111,196,255,0.28)' : '1px solid rgba(255,255,255,0.08)',
    boxSizing: 'border-box',
  };
}

function pipelineLabelStyle(state: 'complete' | 'active' | 'pending'): React.CSSProperties {
  return {
    marginTop: 8,
    minHeight: 30,
    width: 86,
    color:
      state === 'complete' ? '#2dd4bf'
        : state === 'active' ? '#fff'
          : '#6f91b2',
    fontSize: 9,
    lineHeight: 1.25,
    fontWeight: state === 'active' ? 700 : 500,
  };
}

const pipelineActiveStyle: React.CSSProperties = {
  position: 'absolute',
  top: 38,
  right: -2,
};

function pipelineConnectorStyle(done: boolean): React.CSSProperties {
  return {
    flex: '1 0 18px',
    minWidth: 18,
    height: 2,
    marginTop: 14,
    background: done ? '#2dd4bf' : '#29445f',
    opacity: done ? 0.8 : 0.75,
  };
}

const pipelineFailureStyle: React.CSSProperties = {
  marginTop: 8,
  padding: '10px 12px',
  borderRadius: 8,
  display: 'flex',
  flexDirection: 'column',
  gap: 3,
  background: '#35131a',
  border: '1px solid #7f3340',
  color: '#ff8797',
  fontSize: tokens.font.sizes.xs,
};

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
};

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontWeight: tokens.font.weights.semibold,
  color: tokens.colors.textSecondary,
};

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
};
