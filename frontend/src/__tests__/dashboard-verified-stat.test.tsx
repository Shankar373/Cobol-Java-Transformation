/**
 * Dashboard "Verified" stat must count VERIFIED verdicts, not COMPLETED runs.
 *
 * The stat previously used `completedRuns.length` for the "Verified" card,
 * so a completed run whose verdict was FAILED, UNPROVEN or UNAVAILABLE was
 * displayed as "Verified" — a capability-truth overclaim.  The backend now
 * threads `verdict_state` through `RunResponse` (see
 * tests/test_run_verdict_state_api.py) and the dashboard counts only runs
 * whose `verdict_state === 'VERIFIED'`.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { Dashboard } from '../pages/Dashboard';
import type { RunResponse } from '../api/client';

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

function run(
  id: string,
  stage: RunResponse['stage'],
  verdictState: string | null,
): RunResponse {
  return {
    id,
    application_id: 'app-1',
    workload_id: 'wl-payroll',
    stage,
    created_at: '2024-01-01T00:00:00Z',
    completed_at: stage === 'COMPLETED' ? '2024-01-01T00:01:00Z' : null,
    error: null,
    verdict_state: verdictState,
  };
}

/** Text content of the .stat-card that carries the given label. */
function statCardText(label: string): string {
  const labelEl = screen.getByText(label);
  const card = labelEl.closest('.stat-card');
  expect(card, `no .stat-card found above label ${label}`).not.toBeNull();
  return card!.textContent ?? '';
}

describe('Dashboard verified stat', () => {
  it('counts only VERIFIED verdicts, not every completed run', () => {
    const runs: RunResponse[] = [
      run('run-verified', 'COMPLETED', 'VERIFIED'),
      run('run-failed-verdict', 'COMPLETED', 'FAILED'),
      run('run-no-verdict', 'COMPLETED', null),
      run('run-in-flight', 'BUILDING', null),
      {
        ...run('run-stage-failed', 'FAILED', null),
        completed_at: '2024-01-01T00:02:00Z',
      },
    ];

    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="server"
      />,
    );

    // Three runs completed with a verdict-less/failed-verdict mix plus one
    // stage-failed run; exactly one carries a VERIFIED verdict.  The
    // "Failed" card counts stage failures only — a run that completed with
    // a FAILED verdict is completed, not stage-failed.
    expect(statCardText('Completed').startsWith('3')).toBe(true);
    expect(statCardText('Verified').startsWith('1')).toBe(true);
    expect(statCardText('Failed').startsWith('1')).toBe(true);
  });

  it('shows zero verified when no run has a VERIFIED verdict', () => {
    const runs: RunResponse[] = [
      run('run-a', 'COMPLETED', 'FAILED'),
      run('run-b', 'COMPLETED', null),
    ];

    render(
      <Dashboard
        applications={apps}
        runs={runs}
        onNavigate={() => {}}
        loading={false}
        historySource="server"
      />,
    );

    expect(statCardText('Completed').startsWith('2')).toBe(true);
    expect(statCardText('Verified').startsWith('0')).toBe(true);
  });
});
