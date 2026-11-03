import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getRunDetail: vi.fn(),
    getVerdict: vi.fn(),
    getDiscovery: vi.fn(),
    getArtifacts: vi.fn(),
    getReport: vi.fn(),
    getIntegratedProof: vi.fn(),
    getRunApproval: vi.fn(),
    revalidateRun: vi.fn(),
  };
});

import { ModernizationRun } from '../pages/ModernizationRun';
import {
  ApiError,
  getArtifacts,
  getDiscovery,
  getIntegratedProof,
  getReport,
  getRun,
  getRunApproval,
  getRunDetail,
  getVerdict,
  revalidateRun,
  type RunResponse,
  type RunStage,
} from '../api/client';

const run = (stage: RunStage): RunResponse => ({
  id: 'run-1',
  application_id: 'app-1',
  workload_id: 'wl',
  stage,
  created_at: new Date().toISOString(),
  completed_at: null,
  error: null,
});

const notFound = () => new ApiError(404, 'Not Found');

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getRunDetail).mockRejectedValue(notFound());
  vi.mocked(getDiscovery).mockRejectedValue(notFound());
  vi.mocked(getArtifacts).mockRejectedValue(notFound());
  vi.mocked(getReport).mockRejectedValue(notFound());
  vi.mocked(getIntegratedProof).mockRejectedValue(notFound());
  vi.mocked(getRunApproval).mockRejectedValue(notFound());
});

// Audit FE-05: every terminal fetch used .catch(() => null), so a 401/500
// looked exactly like "not produced" and was never retried.
describe('terminal results that fail to load', () => {
  it('keeps a 404 silent but shows a server error with a retry', async () => {
    vi.mocked(getRun).mockResolvedValue(run('FAILED'));
    vi.mocked(getVerdict).mockRejectedValueOnce(new ApiError(500, 'database is locked'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" pollIntervalMs={20} />);

    await waitFor(() =>
      expect(screen.getByText('Some results could not be loaded')).toBeTruthy(),
    );
    expect(screen.getByText(/Verdict: database is locked/)).toBeTruthy();
    // The 404s (artifacts, report, proof...) are not reported as errors.
    expect(screen.queryByText(/Artifacts:/)).toBeNull();

    vi.mocked(getVerdict).mockRejectedValue(notFound());
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading results' }));
    await waitFor(() =>
      expect(screen.queryByText('Some results could not be loaded')).toBeNull(),
    );
  });
});

// Audit FE-10: there was no way to re-run validation from the UI.
describe('re-running validation', () => {
  it('posts a revalidation and polls the run again', async () => {
    vi.mocked(getRun).mockResolvedValue(run('FAILED'));
    vi.mocked(getVerdict).mockRejectedValue(notFound());
    vi.mocked(revalidateRun).mockResolvedValue({ run_id: 'run-1', stage: 'CREATED' });

    render(<ModernizationRun runId="run-1" applicationId="app-1" pollIntervalMs={20} />);
    const button = await screen.findByRole('button', { name: 'Re-run validation' });
    const pollsBefore = vi.mocked(getRun).mock.calls.length;

    fireEvent.click(button);

    await waitFor(() => expect(revalidateRun).toHaveBeenCalledWith('run-1'));
    await waitFor(() =>
      expect(vi.mocked(getRun).mock.calls.length).toBeGreaterThan(pollsBefore),
    );
  });

  it('shows why a revalidation was refused', async () => {
    vi.mocked(getRun).mockResolvedValue(run('FAILED'));
    vi.mocked(getVerdict).mockRejectedValue(notFound());
    vi.mocked(revalidateRun).mockRejectedValue(new ApiError(409, 'Run lacks source or candidate paths'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" pollIntervalMs={20} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Re-run validation' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText(/Run lacks source or candidate paths/)).toBeTruthy();
  });
});
