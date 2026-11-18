import React, { useCallback, useEffect, useRef, useState } from 'react';
import { tokens } from '../theme/tokens';
import { Badge, Button, EmptyState, Header, PageContainer, SectionCard } from '../components';
import * as api from '../api/client';
import { ApplicationsSection } from '../components/discovery/ApplicationsSection';
import { CompilerSection } from '../components/discovery/CompilerSection';
import { Loc, SourceViewer } from '../components/discovery/SourceViewer';
import type { SourceTarget } from '../components/discovery/SourceViewer';
import type { DiscoveryReportV2 } from '../api/discoveryTypes';
import type {
  DiscoveryArtefact,
  DiscoveryGate,
  DiscoveryRun,
  DiscoveryUnresolved,
  DiscoveryVerification,
} from '../api/client';

const POLL_INTERVAL_MS = 1500;
const ARTEFACTS: { key: DiscoveryArtefact; label: string; file: string }[] = [
  { key: 'report', label: 'Discovery report', file: 'discovery-report.json' },
  { key: 'graph', label: 'Dependency graph', file: 'dependency-graph.json' },
  { key: 'inventory', label: 'File inventory', file: 'file-inventory.json' },
  { key: 'unresolved', label: 'Unresolved references', file: 'unresolved-references.json' },
  { key: 'summary', label: 'Summary', file: 'discovery-summary.md' },
];

const GATE_TEXT: Record<DiscoveryGate, { variant: 'success' | 'warning' | 'error'; text: string }> = {
  COMPLETE: { variant: 'success', text: 'Discovery complete' },
  COMPLETE_WITH_OPEN_ITEMS: { variant: 'warning', text: 'Discovery complete with open items' },
  INCOMPLETE: { variant: 'error', text: 'Discovery incomplete: transformation is not allowed yet' },
};

interface DiscoveryProps {
  onNavigate?: (page: string, id?: string) => void;
  authRequired?: boolean;
  pollIntervalMs?: number;
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-US');
}

export function Discovery({ onNavigate, authRequired, pollIntervalMs = POLL_INTERVAL_MS }: DiscoveryProps) {
  const [mode, setMode] = useState<'zip' | 'git'>('zip');
  const [file, setFile] = useState<File | null>(null);
  const [gitUrl, setGitUrl] = useState('');
  const [gitRef, setGitRef] = useState('');
  const [label, setLabel] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [report, setReport] = useState<DiscoveryReportV2 | null>(null);
  const [viewer, setViewer] = useState<SourceTarget | null>(null);
  const [programFilter, setProgramFilter] = useState('');
  const [unresolved, setUnresolved] = useState<DiscoveryUnresolved[]>([]);
  const [verification, setVerification] = useState<DiscoveryVerification | null>(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const token = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      token.current += 1;
    };
  }, []);

  const message = (err: unknown, prefix: string): string => {
    if (err instanceof api.ApiError && err.status === 401) {
      return `${prefix}: authentication required. Enter your API token on the Dashboard, then retry.`;
    }
    return `${prefix}: ${err instanceof Error ? err.message : String(err)}`;
  };

  const loadResults = useCallback(async (finished: DiscoveryRun) => {
    const [rep, unres] = await Promise.all([
      api.getDiscoveryReportV2(finished.run_id),
      api.getDiscoveryUnresolved(finished.run_id),
    ]);
    if (!mounted.current) return;
    setReport(rep);
    setUnresolved(unres.unresolved);
  }, []);

  const poll = useCallback(
    async (first: DiscoveryRun, mine: number) => {
      let current = first;
      while (!api.isDiscoveryTerminal(current.state)) {
        await new Promise((r) => setTimeout(r, pollIntervalMs));
        if (!mounted.current || token.current !== mine) return;
        try {
          current = await api.getDiscoveryRun(first.run_id);
          if (!mounted.current || token.current !== mine) return;
          setRun(current);
        } catch (err) {
          if (!mounted.current || token.current !== mine) return;
          setError(message(err, 'Status check failed'));
          return;
        }
      }
      if (current.state === 'succeeded') {
        try {
          await loadResults(current);
        } catch (err) {
          if (mounted.current) setError(message(err, 'Could not load the discovery results'));
        }
      }
    },
    [pollIntervalMs, loadResults],
  );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (mode === 'zip' && !file) return setError('Select a ZIP archive of the COBOL estate.');
    if (mode === 'git' && !/^https:\/\//i.test(gitUrl.trim())) return setError('Enter an https:// Git URL.');
    const mine = (token.current += 1);
    setBusy(true);
    setReport(null);
    setViewer(null);
    setUnresolved([]);
    setVerification(null);
    try {
      const created =
        mode === 'zip'
          ? await api.submitDiscoveryZip(file as File, label.trim() || undefined)
          : await api.submitDiscoveryGit(gitUrl.trim(), gitRef.trim() || undefined, label.trim() || undefined);
      if (!mounted.current || token.current !== mine) return;
      setRun(created);
      await poll(created, mine);
    } catch (err) {
      if (mounted.current) setError(message(err, 'Could not start discovery'));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const verify = async () => {
    if (!run) return;
    try {
      setVerification(await api.verifyDiscoveryRun(run.run_id));
    } catch (err) {
      setError(message(err, 'Verification failed'));
    }
  };

  const download = async (artefact: DiscoveryArtefact, filename: string) => {
    if (!run) return;
    try {
      const blob = await api.downloadDiscoveryArtefact(run.run_id, artefact);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(message(err, 'Download failed'));
    }
  };

  const input: React.CSSProperties = {
    width: '100%',
    padding: '8px 12px',
    border: `1px solid ${tokens.colors.divider}`,
    borderRadius: tokens.radii.sm,
    fontSize: tokens.font.sizes.base,
    fontFamily: tokens.font.family,
    background: '#fff',
  };
  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: tokens.font.sizes.sm,
    fontWeight: tokens.font.weights.semibold,
    color: tokens.colors.textSecondary,
    marginBottom: 4,
  };
  const cell: React.CSSProperties = { padding: '6px 10px', textAlign: 'left', fontSize: 12, borderBottom: `1px solid ${tokens.colors.divider}` };
  const gate = report?.completeness.status ?? (run?.gate_status || null);

  return (
    <>
      <Header
        breadcrumb={[
          { label: 'Dashboard', onClick: onNavigate ? () => onNavigate('dashboard') : undefined },
          { label: 'Estate Discovery' },
        ]}
        title="Estate Discovery"
        meta={
          <span style={{ fontSize: 12, color: tokens.colors.textMuted }}>
            Freeze the source in an immutable checkpoint, then inventory every file and dependency. No LLM is used.
          </span>
        }
      />
      <PageContainer>
        <form onSubmit={submit} noValidate style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div role="radiogroup" aria-label="Source type" style={{ display: 'flex', gap: 16 }}>
              {(['zip', 'git'] as const).map((m) => (
                <label key={m} style={{ fontSize: 13 }}>
                  <input type="radio" name="discovery-mode" checked={mode === m} disabled={busy} onChange={() => setMode(m)} />{' '}
                  {m === 'zip' ? 'ZIP archive' : 'Git repository (https)'}
                </label>
              ))}
            </div>
            {mode === 'zip' ? (
              <div>
                <label htmlFor="discovery-file" style={labelStyle}>COBOL estate (ZIP)</label>
                <input id="discovery-file" type="file" accept=".zip" disabled={busy} onChange={(ev) => setFile(ev.target.files?.[0] ?? null)} />
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="discovery-url" style={labelStyle}>Repository URL</label>
                  <input id="discovery-url" style={input} type="text" value={gitUrl} disabled={busy} onChange={(ev) => setGitUrl(ev.target.value)} />
                </div>
                <div>
                  <label htmlFor="discovery-ref" style={labelStyle}>Branch, tag or commit (pinned to the exact commit)</label>
                  <input id="discovery-ref" style={input} type="text" value={gitRef} disabled={busy} onChange={(ev) => setGitRef(ev.target.value)} />
                </div>
              </>
            )}
            <div>
              <label htmlFor="discovery-label" style={labelStyle}>Label (optional)</label>
              <input id="discovery-label" style={input} type="text" value={label} disabled={busy} onChange={(ev) => setLabel(ev.target.value)} />
            </div>
          </div>
          <div><Button type="submit" disabled={busy}>{busy ? 'Discovering...' : 'Start discovery'}</Button></div>
        </form>

        {authRequired && !run && (
          <EmptyState title="Authentication required" description="Enter your API token on the Dashboard before starting discovery." />
        )}
        {error && (
          <div role="alert" style={{ marginTop: 16, padding: '10px 14px', borderRadius: tokens.radii.sm, background: tokens.colors.errorBg, color: tokens.colors.error, fontSize: 13 }}>
            {error}
          </div>
        )}

        {run && (
          <div style={{ marginTop: 20, display: 'grid', gridTemplateColumns: viewer ? 'minmax(0, 1fr) minmax(320px, 420px)' : 'minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
            <SectionCard title="Run" subtitle={`run ${run.run_id}`}>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>State: <strong data-testid="discovery-state">{run.state}</strong>
                  {run.checkpoint_id && <span style={{ marginLeft: 12, fontFamily: 'monospace', fontSize: 12 }}>{run.checkpoint_id}</span>}
                </div>
                <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                  {run.steps.map((s) => <li key={s.id}>{s.id}: {s.status}{s.message ? ` (${s.message})` : ''}</li>)}
                </ol>
                {run.state === 'failed' && (
                  <div role="alert" style={{ color: tokens.colors.error, fontSize: 13 }}>
                    Discovery refused the input ({run.error_code}): {run.error_message}
                  </div>
                )}
                {run.state === 'interrupted' && <div role="alert">The service stopped before this run finished; submit it again.</div>}
              </div>
            </SectionCard>

            {gate && (
              <div role="status" data-testid="discovery-gate">
                <Badge variant={GATE_TEXT[gate].variant}>{GATE_TEXT[gate].text}</Badge>
              </div>
            )}
            {report && (
              <div role="status" data-testid="readiness" style={{ fontSize: 13 }}>
                Transformation readiness: <Badge variant={report.readiness.status === 'READY' ? 'success' : report.readiness.status === 'NOT_SUPPORTED' ? 'warning' : 'error'}>{report.readiness.status}</Badge>
                {report.readiness.status === 'BLOCKED' && ' Modernization is refused until the blocking items below are resolved.'}
                {report.readiness.status === 'NOT_SUPPORTED' && ` ${report.readiness.unsupported_total} unsupported item(s) will not be handled; ${report.readiness.unverified_total} program(s) received no compiler verdict (compiler check did not run); both are listed under compiler compatibility.`}
              </div>
            )}

            {report && (
              <>
                <SectionCard title="Completeness checks" count={report.completeness.checks.length}>
                  <ul style={{ margin: 0, padding: 16, listStyle: 'none', fontSize: 13 }}>
                    {report.completeness.checks.map((c) => (
                      <li key={c.id}>{c.passed ? 'Pass' : 'Fail'}: {c.id} ({c.detail})</li>
                    ))}
                    {report.completeness.open_items.map((o) => (
                      <li key={o.id}>Open item: {o.id} x{o.count} ({o.detail})</li>
                    ))}
                  </ul>
                </SectionCard>

                <SectionCard title="Inventory">
                  <div style={{ padding: 16, fontSize: 13 }}>
                    {formatNumber(report.summary.files)} files in {formatNumber(report.summary.directories)} directories,{' '}
                    {formatNumber(report.summary.bytes)} bytes. Dependency graph: {formatNumber(report.dependency_graph.nodes)} nodes,{' '}
                    {formatNumber(report.dependency_graph.edges)} edges, {report.dependency_graph.blocking_unresolved} blocking unresolved.
                    <div style={{ marginTop: 8 }}>
                      {Object.entries(report.summary.files_by_class).map(([cls, n]) => (
                        <span key={cls} style={{ marginRight: 8 }}><Badge size="sm">{cls}: {n}</Badge></span>
                      ))}
                    </div>
                  </div>
                </SectionCard>

                <SectionCard
                  title="Programs"
                  count={report.programs.length}
                  headerRight={<input aria-label="Filter programs by name" placeholder="Filter by name" value={programFilter} onChange={(e) => setProgramFilter(e.target.value)} />}
                  noPadding
                >
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead><tr><th style={cell}>Program</th><th style={cell}>Source</th><th style={cell}>Calls</th><th style={cell}>Copybooks</th><th style={cell}>DB2 tables</th></tr></thead>
                    <tbody>
                      {report.programs.filter((p) => p.name.toLowerCase().includes(programFilter.trim().toLowerCase())).map((p) => (
                        <tr key={`${p.file}:${p.name}:${p.line}`}>
                          <td style={cell}>{p.name}</td><td style={cell}><Loc file={p.file} line={p.line} onOpen={setViewer} /></td>
                          <td style={cell}>{p.calls.join(', ')}</td><td style={cell}>{p.copybooks.join(', ')}</td><td style={cell}>{p.db2_tables.join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </SectionCard>

                <SectionCard title="Unresolved references" count={unresolved.length} noPadding>
                  {unresolved.length === 0 ? (
                    <div style={{ padding: 16, fontSize: 13 }}>None.</div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead><tr><th style={cell}>Target</th><th style={cell}>Reason</th><th style={cell}>Blocking</th><th style={cell}>Source</th></tr></thead>
                      <tbody>
                        {unresolved.map((u, i) => (
                          <tr key={`${u.file}:${u.line}:${u.to}:${i}`}>
                            <td style={cell}>{u.to}</td><td style={cell}>{u.reason}</td>
                            <td style={cell}>{u.blocking ? 'yes' : 'no'}</td><td style={cell}><Loc file={u.file} line={u.line} onOpen={setViewer} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </SectionCard>

                <CompilerSection report={report} onOpen={setViewer} />
                <ApplicationsSection applications={report.applications} onOpen={setViewer} />

                <SectionCard title="Runtime dependencies" count={report.runtime_dependencies.length}>
                  <div style={{ padding: 16, fontSize: 13 }}>
                    {report.runtime_dependencies.map((d) => (
                      <span key={`${d.category}:${d.name}`} style={{ marginRight: 8 }}><Badge size="sm">{d.category}: {d.name}</Badge></span>
                    ))}
                  </div>
                </SectionCard>

                <SectionCard title="Limitations">
                  <ul style={{ margin: 0, padding: '12px 28px', fontSize: 12 }}>
                    {report.limitations.map((l) => <li key={l}>{l}</li>)}
                  </ul>
                </SectionCard>
              </>
            )}

            {run.state === 'succeeded' && (
              <SectionCard title="Artefacts and integrity">
                <div style={{ padding: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {ARTEFACTS.map((a) => (
                    <Button key={a.key} type="button" onClick={() => download(a.key, a.file)}>{a.label}</Button>
                  ))}
                  <Button type="button" onClick={verify}>Verify checkpoint</Button>
                </div>
                {verification && (
                  <div role="status" data-testid="discovery-verification" style={{ padding: '0 16px 16px', fontSize: 13 }}>
                    {verification.ok
                      ? 'Checkpoint verified: every preserved file matches its recorded hash.'
                      : `Checkpoint FAILED verification: ${verification.modified.length} modified, ${verification.missing.length} missing, ${verification.extra.length} extra.`}
                  </div>
                )}
              </SectionCard>
            )}
          </div>
          {viewer && run && <SourceViewer runId={run.run_id} target={viewer} onClose={() => setViewer(null)} />}
          </div>
        )}
      </PageContainer>
    </>
  );
}
