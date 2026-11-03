import { useState } from 'react';
import { tokens } from '../theme/tokens';
import { PageContainer, StatCard, SectionCard, Badge, Button, EmptyState, Header } from '../components';
import {
  IconBox,
  IconPulse,
  IconCheckCircle,
  IconClock,
  IconXCircle,
  IconShieldCheck,
  IconChevronRight,
} from '../components/icons';
import type { ApplicationResponse, RunResponse } from '../api/client';

interface DashboardProps {
  applications: ApplicationResponse[];
  runs: RunResponse[];
  onNavigate: (page: string, id?: string) => void;
  loading?: boolean;
  /**
   * Where the visible history came from.
   *
   * `auth-required` is deliberately kept separate from `session`.  A 401 means
   * the backend answered but would not let us in — that is something the
   * operator can actually fix by supplying a token.  `session` means those
   * endpoints simply are not available at all.  Merging the two into one state
   * hid the only case the customer could resolve themselves, so we keep them
   * apart and show a different message for each.
   */
  historySource?: 'server' | 'session' | 'auth-required';
  /** Called with the entered token; App persists it and reloads history. */
  onSubmitToken?: (token: string) => void;
}

function stageBadgeVariant(stage: string): 'success' | 'error' | 'info' | 'warning' | 'default' {
  if (stage === 'COMPLETED') return 'success';
  if (stage === 'FAILED') return 'error';
  if (
    [
      'CREATED', 'INGESTING', 'DISCOVERING', 'DISCOVERY_COMPLETED',
      'ANALYZING', 'ANALYSIS_COMPLETED', 'PLANNING', 'PLAN_COMPLETED',
      'TRANSFORMING', 'GENERATING', 'ASSEMBLING', 'ASSEMBLY_COMPLETED',
      'EXECUTING_ORACLE', 'BUILDING', 'EXECUTING_GENERATED', 'COMPARING',
      'VALIDATING_EVIDENCE',
    ].includes(stage)
  )
    return 'info';
  return 'default';
}

function runDuration(run: RunResponse): string {
  const start = new Date(run.created_at).getTime();
  const end = run.completed_at
    ? new Date(run.completed_at).getTime()
    : Date.now();
  const secs = Math.round((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function Dashboard({
  applications,
  runs,
  onNavigate,
  loading,
  historySource = 'session',
  onSubmitToken,
}: DashboardProps) {
  const [tokenValue, setTokenValue] = useState('');
  const completedRuns = runs.filter((r) => r.stage === 'COMPLETED');
  const failedRuns = runs.filter((r) => r.stage === 'FAILED');
  const activeRuns = runs.filter((r) => r.stage !== 'COMPLETED' && r.stage !== 'FAILED');
  // "Verified" must count VERIFIED *verdicts*, not completed runs: a run can
  // complete with a FAILED or UNPROVEN verdict, and presenting it as verified
  // would overclaim certification.  `verdict_state` is served fail-closed by
  // the backend (only hash-matched evidence counts).
  const verifiedRuns = runs.filter((r) => r.verdict_state === 'VERIFIED');

  const headerActions = (
    <Button variant="gradient" onClick={() => onNavigate('new')}>
      + New Modernization
    </Button>
  );

  if (loading) {
    return (
      <>
        <Header title="Dashboard" right={headerActions} />
        <PageContainer>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '80px 0',
              color: tokens.colors.textMuted,
              gap: 12,
            }}
          >
            <div
              style={{
                width: 20,
                height: 20,
                borderRadius: '50%',
                border: `2px solid ${tokens.colors.primary}`,
                borderTopColor: 'transparent',
                animation: 'spin 0.8s linear infinite',
              }}
            />
            Loading dashboard…
          </div>
        </PageContainer>
      </>
    );
  }

  return (
    <>
      <Header
        title="Dashboard"
        breadcrumb={[{ label: 'SystemaOps' }, { label: 'Dashboard' }]}
        meta={
          <span style={{ fontSize: 12, color: tokens.colors.textMuted }}>
            {historySource === 'server'
              ? `${runs.length} run${runs.length !== 1 ? 's' : ''} loaded from API`
              : historySource === 'auth-required'
                ? 'Authentication required'
                : 'Session history only'}
          </span>
        }
        right={headerActions}
      />

      <PageContainer>
        {historySource === 'auth-required' && (
          <div
            role="alert"
            style={{
              marginBottom: tokens.spacing.md,
              padding: '12px 14px',
              borderRadius: tokens.radii.sm,
              background: tokens.colors.errorBg,
              border: '1px solid #fecaca',
              color: tokens.colors.error,
              fontSize: tokens.font.sizes.sm,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 14 }}>🔒</span>
              <strong>Authentication required</strong>
            </div>
            <p style={{ margin: '6px 0 10px 24px', lineHeight: 1.5 }}>
              The control plane refused the request. Supply the deployment
              token to load persistent history instead of this session only.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                onSubmitToken?.(tokenValue);
              }}
              style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginLeft: 24 }}
            >
              <label
                htmlFor="dashboard-api-token"
                style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
              >
                API token
                <input
                  id="dashboard-api-token"
                  type="password"
                  value={tokenValue}
                  onChange={(event) => setTokenValue(event.target.value)}
                  autoComplete="off"
                  style={{
                    padding: '6px 8px',
                    borderRadius: tokens.radii.sm,
                    border: '1px solid #d1d5db',
                    minWidth: 240,
                    fontSize: tokens.font.sizes.sm,
                  }}
                />
              </label>
              <Button type="submit">Connect</Button>
            </form>
          </div>
        )}

        {historySource === 'session' && (applications.length > 0 || runs.length > 0) && (
          <div
            style={{
              marginBottom: tokens.spacing.md,
              padding: '9px 14px',
              borderRadius: tokens.radii.sm,
              background: tokens.colors.warningBg,
              border: `1px solid #fde68a`,
              color: tokens.colors.warning,
              fontSize: tokens.font.sizes.sm,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span style={{ fontSize: 14 }}>⚠</span>
            Showing this session only — persistent history is unavailable and will be lost on refresh.
          </div>
        )}

        {/* ── Summary metrics ── */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: 12,
            marginBottom: tokens.spacing.xl,
          }}
        >
          <StatCard
            icon={<IconBox size={22} />}
            value={applications.length}
            label="Applications"
          />
          <StatCard
            icon={<IconPulse size={22} />}
            value={runs.length}
            label="Total Runs"
          />
          <StatCard
            icon={<IconClock size={22} />}
            value={activeRuns.length}
            label="In Progress"
            iconColor={tokens.colors.primary}
          />
          <StatCard
            icon={<IconCheckCircle size={22} />}
            value={completedRuns.length}
            label="Completed"
            iconColor={tokens.colors.success}
          />
          <StatCard
            icon={<IconShieldCheck size={22} />}
            value={verifiedRuns.length}
            label="Verified"
            iconColor="#7c3aed"
          />
          <StatCard
            icon={<IconXCircle size={22} />}
            value={failedRuns.length}
            label="Failed"
            iconColor={tokens.colors.error}
          />
        </div>

        {/* ── Recent Runs table ── */}
        <SectionCard
          title="Recent Modernization Runs"
          count={runs.length}
          headerRight={
            runs.length > 0 ? (
              <Button variant="ghost" size="sm" onClick={() => onNavigate('new')}>
                + New Run
              </Button>
            ) : undefined
          }
        >
          {runs.length === 0 ? (
            <EmptyState
              title="No modernization runs yet"
              description="Upload a COBOL application and start your first modernization run."
              action={
                <Button variant="primary" onClick={() => onNavigate('new')}>
                  Start First Modernization
                </Button>
              }
            />
          ) : (
            <div style={{ overflowX: 'auto', margin: '0 -20px' }}>
              <table className="data-table" aria-label="Recent modernization runs">
                <thead>
                  <tr>
                    <th>Application</th>
                    <th>Workload</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Started</th>
                    <th style={{ width: 80 }} />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => {
                    const app = applications.find((a) => a.id === run.application_id);
                    return (
                      <tr
                        key={run.id}
                        className="run-row"
                        onClick={() => onNavigate('run', run.id)}
                      >
                        <td>
                          <div
                            style={{
                              fontWeight: tokens.font.weights.semibold,
                              color: tokens.colors.textPrimary,
                              fontSize: 13,
                            }}
                          >
                            {app?.name || run.application_id}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              color: tokens.colors.textMuted,
                              fontFamily: 'monospace',
                              marginTop: 1,
                            }}
                          >
                            {run.id}
                          </div>
                        </td>
                        <td style={{ color: tokens.colors.textSecondary, fontSize: 12 }}>
                          {run.workload_id}
                        </td>
                        <td>
                          <Badge variant={stageBadgeVariant(run.stage)}>
                            {run.stage}
                          </Badge>
                        </td>
                        <td style={{ color: tokens.colors.textSecondary, fontSize: 12 }}>
                          {runDuration(run)}
                        </td>
                        <td style={{ color: tokens.colors.textMuted, fontSize: 12 }}>
                          {timeAgo(run.created_at)}
                        </td>
                        <td>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onNavigate('run', run.id);
                            }}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              padding: '5px 10px',
                              border: `1px solid ${tokens.colors.cardBorder}`,
                              borderRadius: tokens.radii.sm,
                              background: 'transparent',
                              color: tokens.colors.primary,
                              fontSize: 12,
                              fontWeight: 500,
                              cursor: 'pointer',
                              transition: 'background 0.15s',
                            }}
                            aria-label={`View run for ${app?.name ?? run.id}`}
                          >
                            View <IconChevronRight size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        {/* ── Applications card (if present and not too large) ── */}
        {applications.length > 0 && (
          <>
            <div style={{ height: 16 }} />
            <SectionCard title="Applications" count={applications.length}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                  gap: 10,
                }}
              >
                {applications.slice(0, 8).map((app) => (
                  <div
                    key={app.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      borderRadius: tokens.radii.sm,
                      background: tokens.colors.surfaceAlt,
                      border: `1px solid ${tokens.colors.cardBorder}`,
                      gap: 10,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: tokens.font.weights.semibold,
                          fontSize: 13,
                          color: tokens.colors.textPrimary,
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {app.name}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: tokens.colors.textMuted,
                          marginTop: 2,
                        }}
                      >
                        {app.workload_id}
                      </div>
                    </div>
                    <Badge variant={app.cobol_source_path ? 'success' : 'default'} size="sm">
                      {app.cobol_source_path ? 'READY' : 'NO SOURCE'}
                    </Badge>
                  </div>
                ))}
              </div>
            </SectionCard>
          </>
        )}
      </PageContainer>
    </>
  );
}
