import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components';
import { Dashboard, NewModernization, ModernizationRun } from './pages';
import type { ApplicationResponse, RunResponse } from './api/client';
import type { IngestSummary } from './api/stages';
import { isTerminalStage } from './api/stages';
import * as api from './api/client';
import { tokens } from './theme/tokens';

type Page = 'dashboard' | 'new' | 'run';
type HistorySource = 'server' | 'session' | 'auth-required';

/** Runs newest first by creation time (audit FE-13: history was in server
 *  order - grouped by application, oldest first). */
function newestFirst(runs: RunResponse[]): RunResponse[] {
  return [...runs].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
}

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

  // `navigate()` must keep a stable identity (the layout effects below depend
  // on it) while still reading the newest runs to look up which application a
  // run belongs to, so we mirror runs through a ref.
  const runsRef = useRef<RunResponse[]>(runs);
  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);

  const navigate = useCallback((p: string, id?: string) => {
    if (p === 'run' && id) {
      setSelectedRunId(id);
      // Opening a run must select THAT run's own application, not keep a
      // stale selectedAppId left over from a previously created or opened
      // app — that rendered the wrong application's discovery/ingest summary.
      const run = runsRef.current.find((r) => r.id === id);
      if (run) {
        setSelectedAppId(run.application_id);
      }
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
  //
  // This is a named callback rather than a mount-only effect so that entering
  // an API token can simply re-run the same load and restore persistent
  // history, instead of telling the operator to reload the page.  The mounted
  // ref keeps the safety property the original effect had: neither the first
  // load nor a later token retry may set state after the component has gone
  // away.
  const historyMounted = useRef(true);
  useEffect(() => {
    historyMounted.current = true;
    return () => {
      historyMounted.current = false;
    };
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const serverApps = await api.listApplications();
      if (!historyMounted.current) return;
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
        if (!historyMounted.current) return;
        const serverRuns = runsByApp.flat();
        if (serverRuns.length > 0) {
          setRuns((prev) => {
            const seen = new Set(serverRuns.map((r) => r.id));
            return newestFirst([...serverRuns, ...prev.filter((r) => !seen.has(r.id))]);
          });
          // Runs still in progress after a reload are polled like runs
          // started in this session (audit FE-06: they stayed frozen).
          const inFlight = serverRuns.filter((r) => !isTerminalStage(r.stage));
          if (inFlight.length > 0) {
            setRunIds((prev) => {
              const next = new Set(prev);
              for (const r of inFlight) next.add(r.id);
              return next;
            });
          }
        }
      } catch {
        // Per-app run history is best-effort; applications already loaded.
      }
    } catch (err) {
      // A 401 means the backend answered but would not let us in — that is
      // something the operator can fix by supplying a token, so we surface it
      // as its own state.  Every other failure means the persistent endpoints
      // are simply unavailable, which keeps session state authoritative.  If
      // we merged the two, the one case a customer could resolve themselves
      // would be indistinguishable from "the server is not deployed".
      if (err instanceof api.ApiError && err.status === 401) {
        if (historyMounted.current) setHistorySource('auth-required');
      }
    } finally {
      if (historyMounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // Save the entered token and immediately retry the load, so the operator
  // sees their history appear without reloading the page.
  const handleTokenSubmit = useCallback(
    (token: string) => {
      api.setApiToken(token);
      setHasToken(true);
      void loadHistory();
    },
    [loadHistory],
  );

  // Sign out forgets the token stored in this browser (audit FE-20) and
  // drops server history fetched with it.
  const [hasToken, setHasToken] = useState(() => api.hasStoredApiToken());
  const handleSignOut = useCallback(() => {
    api.setApiToken(null);
    setHasToken(false);
    setApplications([]);
    setRuns([]);
    setRunIds(new Set());
    setPage('dashboard');
    void loadHistory();
  }, [loadHistory]);

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
        // Stop polling runs that have reached a terminal stage, so each
        // finished run is not re-polled every 2 seconds for the rest of the
        // session.  Previously runs were only ever added to the set, so the
        // poll load grew without bound.
        const finished = updated.filter((r) => isTerminalStage(r.stage));
        if (finished.length > 0) {
          setRunIds((prev) => {
            const next = new Set(prev);
            for (const r of finished) next.delete(r.id);
            return next;
          });
        }
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [runIds]);

  // The application a failed submit already created, keyed by what was
  // submitted: retrying the same upload reuses it instead of creating a
  // duplicate application (audit FE-07).
  const pendingApp = useRef<{ key: string; app: api.ApplicationResponse } | null>(null);

  const handleSubmit = async (data: {
    name: string;
    workloadId: string;
    description: string;
    zipFile: File;
    targetRuntime: string;
  }) => {
    if (!data.targetRuntime) {
      setSubmitError('Choose a target runtime before starting a modernization.');
      return;
    }
    setCreating(true);
    setSubmitError(null);
    const submitKey = [
      data.name, data.workloadId, data.targetRuntime, data.zipFile.name,
      data.zipFile.size, data.zipFile.lastModified,
    ].join('|');
    try {
      let app: api.ApplicationResponse;
      if (pendingApp.current && pendingApp.current.key === submitKey) {
        app = pendingApp.current.app;
      } else {
        app = await api.createApplication({
          name: data.name,
          workload_id: data.workloadId,
          description: data.description,
          target_runtime: data.targetRuntime,
        });
        pendingApp.current = { key: submitKey, app };
        setApplications((prev) => [...prev, app]);
      }

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

      pendingApp.current = null;
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
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar
        currentPage={page}
        onNavigate={(p, id) => navigate(p, id)}
        onSignOut={hasToken ? handleSignOut : undefined}
      />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <main style={{ flex: 1 }}>
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
            onSubmitToken={handleTokenSubmit}
          />
        )}
        {page === 'new' && (
          <NewModernization onSubmit={handleSubmit} loading={creating} onNavigate={navigate} />
        )}
        {page === 'run' && selectedRunId && (
          <ModernizationRun
            runId={selectedRunId}
            applicationId={selectedAppId || ''}
            ingest={selectedAppId ? (ingestByApp[selectedAppId] ?? null) : null}
            onNavigate={navigate}
          />
        )}
        </main>
      </div>
    </div>
  );
}
