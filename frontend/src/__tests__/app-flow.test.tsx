import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    listApplications: vi.fn(),
    listApplicationRuns: vi.fn(),
    createApplication: vi.fn(),
    ingestApplication: vi.fn(),
    modernize: vi.fn(),
    getRun: vi.fn(),
    getRunDetail: vi.fn(),
    getVerdict: vi.fn(),
    getDiscovery: vi.fn(),
    getArtifacts: vi.fn(),
    getReport: vi.fn(),
    getIntegratedProof: vi.fn(),
    getRunApproval: vi.fn(),
    getReadiness: vi.fn(),
  };
});

import App from '../App';
import * as api from '../api/client';

const app = {
  id: 'app-1',
  name: 'payroll',
  description: '',
  workload_id: 'wl-payroll',
  java_entrypoint: '',
  cobol_source_path: null,
  java_candidate_path: null,
  generated_app_path: null,
  generated_entrypoint: null,
  discovered_program_ids: [],
  generated_program_ids: [],
  target_runtime: 'spring_boot',
  created_at: '2026-11-03T10:00:00+00:00',
};

const run = (id: string, stage: api.RunStage, created_at: string): api.RunResponse => ({
  id,
  application_id: 'app-1',
  workload_id: 'wl-payroll',
  stage,
  created_at,
  completed_at: null,
  error: null,
});

const notFound = () => new api.ApiError(404, 'Not Found');

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getReadiness).mockResolvedValue({ status: 'ready', checks: {} });
  for (const fn of [api.getRunDetail, api.getVerdict, api.getDiscovery, api.getArtifacts,
    api.getReport, api.getIntegratedProof, api.getRunApproval]) {
    vi.mocked(fn).mockRejectedValue(notFound());
  }
});

describe('history after a reload', () => {
  it('lists runs newest first and keeps polling runs still in progress', async () => {
    // FE-13: server order was per application, oldest first.
    // FE-06: in-flight runs from history were never polled.
    vi.mocked(api.listApplications).mockResolvedValue([app]);
    vi.mocked(api.listApplicationRuns).mockResolvedValue([
      run('run-old', 'COMPLETED', '2026-11-03T09:00:00+00:00'),
      run('run-new', 'TRANSFORMING', '2026-11-03T11:00:00+00:00'),
    ]);
    vi.mocked(api.getRun).mockResolvedValue(run('run-new', 'COMPLETED', '2026-11-03T11:00:00+00:00'));

    render(<App />);

    await waitFor(() => expect(screen.getByText('run-new')).toBeTruthy());
    const text = document.body.textContent ?? '';
    expect(text.indexOf('run-new')).toBeLessThan(text.indexOf('run-old'));
    await waitFor(() => expect(api.getRun).toHaveBeenCalledWith('run-new'), { timeout: 4000 });
  });
});

describe('submitting a new modernization', () => {
  it('sends the chosen runtime and reuses the created application on retry', async () => {
    vi.mocked(api.listApplications).mockResolvedValue([]);
    vi.mocked(api.listApplicationRuns).mockResolvedValue([]);
    vi.mocked(api.createApplication).mockResolvedValue(app);
    vi.mocked(api.ingestApplication)
      .mockRejectedValueOnce(new api.ApiError(500, 'disk full'))
      .mockResolvedValue({
        application_id: 'app-1', source_file_count: 1, detected_name: 'payroll',
      } as unknown as Awaited<ReturnType<typeof api.ingestApplication>>);
    vi.mocked(api.modernize).mockResolvedValue({ run_id: 'run-9' } as Awaited<ReturnType<typeof api.modernize>>);
    vi.mocked(api.getRun).mockResolvedValue(run('run-9', 'COMPLETED', '2026-11-03T12:00:00+00:00'));

    render(<App />);
    fireEvent.click(await screen.findByText('New Modernization'));
    const file = new File(['PK'], 'payroll.zip', { type: 'application/zip' });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [file] },
    });
    fireEvent.change(screen.getByLabelText('Target runtime'), { target: { value: 'quarkus' } });

    // FE-08: the runtime reaches the API.
    fireEvent.click(screen.getByText('Start Modernization →'));
    await waitFor(() => expect(screen.getByText(/disk full/)).toBeTruthy());
    expect(api.createApplication).toHaveBeenCalledWith(
      expect.objectContaining({ target_runtime: 'quarkus' }),
    );

    // FE-07: the retry reuses the application instead of creating another.
    fireEvent.click(screen.getByText('Start Modernization →'));
    await waitFor(() => expect(api.modernize).toHaveBeenCalledWith('app-1'));
    expect(api.createApplication).toHaveBeenCalledTimes(1);
  });
});
