import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createApplication, getRun, getRunDetail, getVerdict, ingestApplication, downloadGenerated, listApplications, getApplication, listApplicationRuns, ApiError } from '../api/client';

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('API client', () => {
  it('createApplication sends POST with JSON body', async () => {
    const mockResponse = {
      id: 'app-123',
      name: 'test',
      description: '',
      workload_id: 'wl-1',
      java_entrypoint: 'Main',
      cobol_source_path: null,
      java_candidate_path: null,
      created_at: '2024-01-01T00:00:00Z',
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      }),
    );

    const result = await createApplication({
      name: 'test',
      workload_id: 'wl-1',
    });

    expect(result.id).toBe('app-123');
    expect(fetch).toHaveBeenCalledWith(
      '/applications',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });

  it('getRun sends GET to correct path', async () => {
    const mockRun = {
      id: 'run-1',
      application_id: 'app-1',
      workload_id: 'wl-1',
      stage: 'COMPLETED',
      created_at: '2024-01-01T00:00:00Z',
      completed_at: null,
      error: null,
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockRun),
      }),
    );

    const result = await getRun('run-1');
    expect(result.stage).toBe('COMPLETED');
    expect(fetch).toHaveBeenCalledWith('/runs/run-1', undefined);
  });

  it('throws ApiError on non-OK response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: () => Promise.resolve({ detail: 'Run not found' }),
      }),
    );

    await expect(getRun('missing')).rejects.toThrow(ApiError);
  });

  it('getVerdict sends GET to correct path', async () => {
    const mockVerdict = {
      run_id: 'run-1',
      state: 'VERIFIED',
      workload_id: 'wl-1',
      source_hash: 'sha256:abc',
      candidate_hash: null,
      oracle_id: 'gnucobol',
      oracle_digest: 'sha256:def',
      executed_check_count: 3,
      skipped_count: 0,
      unavailable_count: 0,
      supported_scope_statement: 'V1',
      evidence_manifest_hash: 'sha256:ghi',
      derivation_timestamp: '2024-01-01T00:00:00Z',
      differences: [],
      comparisons: [],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockVerdict),
      }),
    );

    const result = await getVerdict('run-1');
    expect(result.state).toBe('VERIFIED');
    expect(fetch).toHaveBeenCalledWith('/runs/run-1/verdict', undefined);
  });

  it('ingestApplication sends POST with FormData', async () => {
    const mockIngest = {
      application_id: 'app-123',
      workspace_path: '/tmp/ingest-app-123',
      source_file_count: 5,
      total_size_bytes: 1024,
      discovery: {
        application_id: 'app-123',
        cobol_programs: [],
        copybooks: [],
        jcl_jobs: [],
        file_dependencies: [],
        call_dependencies: [],
        dependency_edges: [],
        source_file_count: 5,
        total_size_bytes: 1024,
      },
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockIngest),
      }),
    );

    const file = new File(['test'], 'test.zip', { type: 'application/zip' });
    const result = await ingestApplication('app-123', file);

    expect(result.application_id).toBe('app-123');
    expect(result.source_file_count).toBe(5);
    expect(fetch).toHaveBeenCalledWith(
      '/applications/app-123/ingest',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('downloadGenerated fetches blob from correct path', async () => {
    const mockBlob = new Blob(['zip-content'], { type: 'application/zip' });

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(mockBlob),
      }),
    );

    const result = await downloadGenerated('run-1');
    expect(result).toBeInstanceOf(Blob);
    expect(fetch).toHaveBeenCalledWith('/runs/run-1/download');
  });

  it('downloadGenerated throws on error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: () => Promise.resolve({ detail: 'Not found' }),
      }),
    );

    await expect(downloadGenerated('missing')).rejects.toThrow(ApiError);
  });

  it('listApplications sends GET to /applications (persistent history)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      }),
    );

    await listApplications();
    expect(fetch).toHaveBeenCalledWith('/applications', undefined);
  });

  it('getApplication sends GET to /applications/{id}', async () => {
    const mockApp = { id: 'app-1', name: 'payroll' };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockApp),
      }),
    );

    const result = await getApplication('app-1');
    expect(result.id).toBe('app-1');
    expect(fetch).toHaveBeenCalledWith('/applications/app-1', undefined);
  });

  it('listApplicationRuns sends GET to /applications/{id}/runs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      }),
    );

    await listApplicationRuns('app-1');
    expect(fetch).toHaveBeenCalledWith('/applications/app-1/runs', undefined);
  });

  it('persistent endpoints propagate ApiError when the backend lacks them', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: () => Promise.resolve({ detail: 'Not Found' }),
      }),
    );

    await expect(listApplications()).rejects.toThrow(ApiError);
  });

  it('getRunDetail sends GET to /runs/{id}/detail', async () => {
    const mockDetail = {
      id: 'run-1',
      application_id: 'app-1',
      application_name: 'payroll',
      workload_id: 'wl-1',
      stage: 'COMPLETED',
      created_at: '2024-01-01T00:00:00Z',
      completed_at: null,
      error: null,
      verdict_state: 'VERIFIED',
      discovery: null,
      stage_messages: ['COMPLETED'],
      generated_files: ['pom.xml'],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockDetail),
      }),
    );

    const result = await getRunDetail('run-1');
    expect(result.application_name).toBe('payroll');
    expect(result.generated_files).toEqual(['pom.xml']);
    expect(fetch).toHaveBeenCalledWith('/runs/run-1/detail', undefined);
  });
});
