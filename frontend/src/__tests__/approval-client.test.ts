import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { getRunApproval, setRunApproval, ApiError } from '../api/client';

// ---------------------------------------------------------------------------
// BL-091 client contract — real module, stubbed fetch.
// (The panel-behaviour tests mock this module; here we pin the actual HTTP
// paths, methods and payloads the backend contract expects.)
// ---------------------------------------------------------------------------

const PENDING = {
  run_id: 'run-1',
  state: 'PENDING' as const,
  approver: null,
  reason: null,
  decided_at: null,
};

describe('approval client contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('getRunApproval GETs the approval record', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => PENDING,
    } as Response);

    const body = await getRunApproval('run-1');

    expect(body.state).toBe('PENDING');
    expect(fetchMock).toHaveBeenCalledWith('/runs/run-1/approval', undefined);
  });

  it('setRunApproval POSTs the decision payload as JSON', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => PENDING,
    } as Response);

    await setRunApproval('run-1', {
      decision: 'REJECTED',
      approver: 'reviewer-b',
      reason: 'scope mismatch',
    });

    expect(fetchMock).toHaveBeenCalledWith('/runs/run-1/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision: 'REJECTED',
        approver: 'reviewer-b',
        reason: 'scope mismatch',
      }),
    });
  });

  it('setRunApproval surfaces a non-2xx as ApiError with the detail', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({ detail: 'Export blocked: run approval is PENDING' }),
    } as Response);

    const err = await setRunApproval('run-1', {
      decision: 'APPROVED',
      approver: 'a',
    }).then(
      () => null,
      (e: unknown) => e,
    );

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toContain('Export blocked');
  });
});
