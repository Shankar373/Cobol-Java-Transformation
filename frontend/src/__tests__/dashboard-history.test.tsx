import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { Dashboard } from '../pages/Dashboard';

const apps = [
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
];

const runs = [
  {
    id: 'run-1',
    application_id: 'app-1',
    workload_id: 'wl-payroll',
    stage: 'COMPLETED' as const,
    created_at: '2024-01-01T00:00:00Z',
    completed_at: '2024-01-01T00:01:00Z',
    error: null,
  },
];

describe('Dashboard application history', () => {
  it('renders a server-provided applications list without a session warning', () => {
    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="server"
      />,
    );

    // Names repeat across the applications list and the runs table.
    expect(screen.getAllByText('payroll').length).toBeGreaterThan(0);
    expect(screen.getAllByText('wl-payroll').length).toBeGreaterThan(0);
    expect(
      screen.queryByText(/Showing this session only/),
    ).not.toBeInTheDocument();
  });

  it('warns that session history is lost on refresh when the server list is unavailable', () => {
    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="session"
      />,
    );

    expect(screen.getAllByText('payroll').length).toBeGreaterThan(0);
    expect(screen.getByText(/Showing this session only/)).toBeInTheDocument();
  });

  it('renders runs against their application names', () => {
    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="server"
      />,
    );

    const table = screen.getByRole('table', { name: 'Recent modernization runs' });
    expect(table.textContent).toContain('payroll');
    expect(table.textContent).toContain('COMPLETED');
  });
});
