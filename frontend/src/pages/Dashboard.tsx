import React from 'react';
import { tokens } from '../theme/tokens';
import { PageContainer, StatCard, SectionCard, Badge, Button, EmptyState } from '../components';
import type { ApplicationResponse, RunResponse } from '../api/client';

interface DashboardProps {
  applications: ApplicationResponse[];
  runs: RunResponse[];
  onNavigate: (page: string, id?: string) => void;
  loading?: boolean;
  /** Where the listed history came from. The backend is authoritative;
   *  'session' means the persistent endpoints are unavailable and only
   *  in-memory session state is shown (lost on refresh). */
  historySource?: 'server' | 'session';
}

function stageBadgeVariant(stage: string): 'success' | 'error' | 'info' | 'warning' | 'default' {
  if (stage === 'COMPLETED') return 'success';
  if (stage === 'FAILED') return 'error';
  if (['CREATED', 'INGESTING', 'DISCOVERING', 'DISCOVERY_COMPLETED', 'TRANSFORMING', 'GENERATING',
       'EXECUTING_ORACLE', 'BUILDING', 'EXECUTING_GENERATED', 'COMPARING',
       'VALIDATING_EVIDENCE'].includes(stage)) return 'info';
  return 'default';
}

export function Dashboard({ applications, runs, onNavigate, loading, historySource = 'session' }: DashboardProps) {
  const completedRuns = runs.filter((r) => r.stage === 'COMPLETED');
  const failedRuns = runs.filter((r) => r.stage === 'FAILED');
  const inProgressRuns = runs.filter((r) => r.stage !== 'COMPLETED' && r.stage !== 'FAILED');

  if (loading) {
    return (
      <PageContainer title="Dashboard" subtitle="COBOL to Java modernization overview">
        <div style={{ textAlign: 'center', padding: tokens.spacing.xxl, color: tokens.colors.textMuted }}>
          Loading...
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="Dashboard"
      subtitle="COBOL to Java modernization overview"
      actions={
        <Button variant="gradient" onClick={() => onNavigate('new')}>
          + New Modernization
        </Button>
      }
    >
      {historySource === 'session' && (applications.length > 0 || runs.length > 0) && (
        <div
          style={{
            marginBottom: tokens.spacing.md,
            padding: '8px 12px',
            borderRadius: tokens.radii.sm,
            background: tokens.colors.warningBg,
            color: tokens.colors.warning,
            fontSize: tokens.font.sizes.sm,
          }}
        >
          Showing this session only — server history is unavailable, so this list is lost on refresh.
        </div>
      )}
      {/* Stats */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: tokens.spacing.md,
          marginBottom: tokens.spacing.xl,
        }}
      >
        <StatCard icon={'\u{1F3E2}'} value={applications.length} label="Applications" />
        <StatCard icon={'\u{1F504}'} value={runs.length} label="Total Runs" />
        <StatCard icon={'\u2705'} value={completedRuns.length} label="Completed" />
        <StatCard icon={'\u2699\uFE0F'} value={inProgressRuns.length} label="In Progress" />
        <StatCard icon={'\u274C'} value={failedRuns.length} label="Failed" />
      </div>

      {/* Applications */}
      {applications.length > 0 && (
        <>
          <SectionCard title="Applications" count={applications.length}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.sm }}>
              {applications.map((app) => (
                <div
                  key={app.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: `${tokens.spacing.sm} ${tokens.spacing.md}`,
                    borderRadius: tokens.radii.sm,
                    background: tokens.colors.surfaceAlt,
                    border: '1px solid ' + tokens.colors.cardBorder,
                  }}
                >
                  <div>
                    <div style={{ fontWeight: tokens.font.weights.medium, fontSize: tokens.font.sizes.base }}>
                      {app.name}
                    </div>
                    <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                      {app.workload_id} {app.description ? `\u2022 ${app.description}` : ''}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: tokens.spacing.sm, alignItems: 'center' }}>
                    <Badge variant={app.cobol_source_path ? 'success' : 'default'} size="sm">
                      {app.cobol_source_path ? 'SOURCE LOADED' : 'NO SOURCE'}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
          <div style={{ height: tokens.spacing.md }} />
        </>
      )}

      {/* Recent Runs */}
      <SectionCard title="Recent Runs" count={runs.length}>
        {runs.length === 0 ? (
          <EmptyState
            icon={'\u{1F680}'}
            title="No modernization runs yet"
            description="Create your first modernization to get started."
            action={
              <Button variant="primary" onClick={() => onNavigate('new')}>
                Start First Modernization
              </Button>
            }
          />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: tokens.font.sizes.base,
              }}
              aria-label="Recent modernization runs"
            >
              <thead>
                <tr style={{ borderBottom: '2px solid ' + tokens.colors.divider, textAlign: 'left' }}>
                  <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>Application</th>
                  <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>Workload</th>
                  <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>Stage</th>
                  <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>Created</th>
                  <th style={{ padding: '8px 12px' }}></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const app = applications.find((a) => a.id === run.application_id);
                  return (
                    <tr
                      key={run.id}
                      style={{ borderBottom: '1px solid ' + tokens.colors.divider }}
                    >
                      <td style={{ padding: '8px 12px', fontWeight: tokens.font.weights.medium }}>
                        {app?.name || run.application_id}
                      </td>
                      <td style={{ padding: '8px 12px' }}>{run.workload_id}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <Badge variant={stageBadgeVariant(run.stage)}>
                          {run.stage}
                        </Badge>
                      </td>
                      <td style={{ padding: '8px 12px', color: tokens.colors.textMuted, fontSize: tokens.font.sizes.sm }}>
                        {new Date(run.created_at).toLocaleString()}
                      </td>
                      <td style={{ padding: '8px 12px' }}>
                        <Button variant="ghost" size="sm" onClick={() => onNavigate('run', run.id)}>
                          View
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </PageContainer>
  );
}
