import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { Dashboard } from '../pages/Dashboard';

/**
 * When `CONTROL_PLANE_API_TOKEN` is set on the server and the browser has no
 * token, the SPA used to swallow the 401 and show "Session history only /
 * persistent history is unavailable" — the same message as a missing backend.
 * That left the operator with no way to recover.  These tests pin the distinct
 * "auth required" state and the token form that resolves it.
 */

const apps: never[] = [];
const runs: never[] = [];

// Mirrors dashboard-history.test.tsx: the session-only banner is shown when
// there is something the operator is at risk of losing, so the non-auth
// fallback case renders with history present.
const appsWithHistory = [
  {
    id: 'app-1',
    name: 'payroll',
    description: '',
    workload_id: 'wl-payroll',
    java_entrypoint: 'Main',
    cobol_source_path: '/tmp/src',
    java_candidate_path: null,
    generated_app_path: null,
    generated_entrypoint: null,
    discovered_program_ids: [],
    generated_program_ids: [],
    created_at: '2024-01-01T00:00:00Z',
  },
] as never[];

describe('Dashboard authentication-required state', () => {
  it('distinguishes an authentication failure from an unavailable backend', () => {
    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="auth-required"
      />,
    );

    expect(screen.getByText(/API token/i)).toBeInTheDocument();
    expect(screen.queryByText(/Showing this session only/)).not.toBeInTheDocument();
  });

  it('offers a token entry that can restore persistent history', () => {
    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="auth-required"
      />,
    );

    const input = screen.getByLabelText(/API token/i);
    expect(input).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /connect|save|apply/i })).toBeInTheDocument();
  });

  it('keeps the existing session-only wording for non-auth fallbacks', () => {
    render(
      <Dashboard
        applications={appsWithHistory}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="session"
      />,
    );

    expect(screen.getByText(/Showing this session only/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API token/i)).not.toBeInTheDocument();
  });
});
