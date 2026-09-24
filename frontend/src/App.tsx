import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components';
import { Dashboard, NewModernization, ModernizationRun } from './pages';
import type { ApplicationResponse, RunResponse } from './api/client';
import type { IngestSummary } from './api/stages';
import * as api from './api/client';
import { tokens } from './theme/tokens';

type Page = 'dashboard' | 'new' | 'run';
type HistorySource = 'server' | 'session';

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedAppId, setSelectedAppId] = useState<string | null>(null);
  const [applications, setApplications] = useState<ApplicationResponse[]>([]);
  const [runs, setRuns] = useState<RunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [historySource, setHistorySource] = useState<HistorySource>('session');
  const [ingestByApp, setIngestByApp] = useState<Record<string, IngestSummary>>({});

  const [runIds, setRunIds] = useState<Set<string>>(new Set());

  const navigate = useCallback((p: string, id?: string) => {
    if (p === 'run' && id) {
      setSelectedRunId(id);
      setPage('run');
    } else if (p === 'new') {
      setPage('new');
    } else {
      setPage('dashboard');
    }
  }, []);

  // Application history: the backend is authoritative. When the persistent
  // endpoints exist, consume them directly (no local persistence). While
  // they are absent the calls reject and session state remains in use.
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const serverApps = await api.listApplications();
        if (!mounted) return;
        setApplications((prev) => {
          const seen = new Set(serverApps.map((a) => a.id));
          return [...serverApps, ...prev.filter((a) => !seen.has(a.id))];
        });
        setHistorySource('server');
        try {
          const runsByApp = await Promise.all(
            serverApps.map((a) =>
              api.listApplicationRuns(a.id).catch(() => [] as RunResponse[]),
            ),
          );
          if (!mounted) return;
          const serverRuns = runsByApp.flat();
          if (serverRuns.length > 0) {
            setRuns((prev) => {
              const seen = new Set(serverRuns.map((r) => r.id));
              return [...serverRuns, ...prev.filter((r) => !seen.has(r.id))];
            });
          }
        } catch {
          // Per-app run history is best-effort; applications already loaded.
        }
      } catch {
        // Persistent endpoints unavailable — session state stays authoritative.
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  // Poll runs that are in-progress
  useEffect(() => {
    if (runIds.size === 0) return;

    const interval = setInterval(async () => {
      const updated: RunResponse[] = [];
      for (const rid of runIds) {
        try {
          const r = await api.getRun(rid);
          updated.push(r);
        } catch {
          // Transient poll failure — the run page surfaces visible
          // per-run polling state; dashboard keeps last known state.
        }
      }
      if (updated.length > 0) {
        setRuns((prev) => {
          const map = new Map(prev.map((r) => [r.id, r]));
          for (const r of updated) map.set(r.id, r);
          return Array.from(map.values());
        });
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [runIds]);

  const handleSubmit = async (data: {
    name: string;
    workloadId: string;
    description: string;
    zipFile: File;
  }) => {
    setCreating(true);
    setSubmitError(null);
    try {
      const app = await api.createApplication({
        name: data.name,
        workload_id: data.workloadId,
        description: data.description,
      });
      setApplications((prev) => [...prev, app]);

      // Ingest ZIP (runs discovery). Ingestion is synchronous and
      // completes before the modernization run starts.
      const ingest = await api.ingestApplication(app.id, data.zipFile);
      setIngestByApp((prev) => ({
        ...prev,
        [app.id]: {
          applicationId: app.id,
          sourceFileCount: ingest.source_file_count,
          detectedName: ingest.detected_name,
        },
      }));

      // Start modernization
      const mod = await api.modernize(app.id);

      const run = await api.getRun(mod.run_id);
      setRuns((prev) => [run, ...prev]);
      setRunIds((prev) => new Set(prev).add(mod.run_id));

      setSelectedAppId(app.id);
      setSelectedRunId(mod.run_id);
      setPage('run');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSubmitError(message);
      setPage('new');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh' }}>
      <Header onNavigate={(p) => navigate(p)} currentPage={page} />
      <main>
        {submitError && page === 'new' && (
          <div style={{ maxWidth: 1100, margin: '0 auto', padding: `${tokens.spacing.md} ${tokens.spacing.xl} 0` }}>
            <div
              role="alert"
              style={{
                padding: '10px 14px',
                borderRadius: tokens.radii.sm,
                background: tokens.colors.errorBg,
                color: tokens.colors.error,
                fontSize: tokens.font.sizes.sm,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: tokens.spacing.md,
              }}
            >
              <span>Could not start modernization: {submitError}. Your form entries are preserved — fix the issue and retry.</span>
              <button
                onClick={() => setSubmitError(null)}
                aria-label="Dismiss error"
                style={{
                  background: 'none',
                  border: '1px solid currentColor',
                  borderRadius: tokens.radii.sm,
                  cursor: 'pointer',
                  color: 'inherit',
                  fontSize: tokens.font.sizes.sm,
                  padding: '2px 10px',
                  flexShrink: 0,
                }}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
        {page === 'dashboard' && (
          <Dashboard
            applications={applications}
            runs={runs}
            onNavigate={navigate}
            loading={loading}
            historySource={historySource}
          />
        )}
        {page === 'new' && (
          <NewModernization onSubmit={handleSubmit} loading={creating} />
        )}
        {page === 'run' && selectedRunId && (
          <ModernizationRun
            runId={selectedRunId}
            applicationId={selectedAppId || ''}
            ingest={selectedAppId ? (ingestByApp[selectedAppId] ?? null) : null}
          />
        )}
      </main>
    </div>
  );
}
