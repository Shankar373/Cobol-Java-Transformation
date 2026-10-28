/**
 * Bearer-token auth integration for the API client.
 *
 * Production deployments require `CONTROL_PLANE_API_TOKEN` on the backend
 * (`api/app.py` middleware: every route except /health answers 401 without
 * `Authorization: Bearer <token>`), but the SPA client never attached the
 * header — with auth enabled the frontend received 401 on every call, because
 * it was missing the Authorization header.
 *
 * Contract pinned here:
 *  - token configured (localStorage override or VITE_CONTROL_PLANE_API_TOKEN
 *    build-time env) → every request carries the Authorization header,
 *    merged with any existing headers, including the download path;
 *  - no token configured (auth off, the documented dev default) → requests
 *    are byte-identical to the pre-auth client (no header, GET init stays
 *    `undefined`) so the development and test workflows are unchanged.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  createApplication,
  getRun,
  downloadGenerated,
  setApiToken,
  getApiToken,
} from '../api/client';

const TOKEN_KEY = 'systemaops.apiToken';

function capturedInit(callIndex = 0): RequestInit | undefined {
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls.length).toBeGreaterThan(callIndex);
  return calls[callIndex][1] as RequestInit | undefined;
}

function authHeaderOf(init: RequestInit | undefined): string | null {
  if (!init?.headers) return null;
  return new Headers(init.headers).get('Authorization');
}

afterEach(() => {
  localStorage.removeItem(TOKEN_KEY);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('API client bearer-token auth', () => {
  it('no token configured: GET carries no Authorization header (auth-off parity)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ id: 'run-1' }),
      }),
    );

    setApiToken(null);
    await getRun('run-1');

    // Identical to the pre-auth contract: no init object at all for GETs.
    expect(fetch).toHaveBeenCalledWith('/runs/run-1', undefined);
  });

  it('no token configured: POST headers stay exactly as before', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ id: 'app-1' }),
      }),
    );

    setApiToken(null);
    await createApplication({ name: 't', workload_id: 'wl' });

    const init = capturedInit();
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' });
    expect(authHeaderOf(init)).toBeNull();
  });

  it('localStorage token: GET carries Authorization: Bearer <token>', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ id: 'run-1' }),
      }),
    );

    setApiToken('sekret-token');
    expect(getApiToken()).toBe('sekret-token');
    await getRun('run-1');

    expect(authHeaderOf(capturedInit())).toBe('Bearer sekret-token');
  });

  it('localStorage token: POST merges Authorization with existing headers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ id: 'app-1' }),
      }),
    );

    setApiToken('sekret-token');
    await createApplication({ name: 't', workload_id: 'wl' });

    const init = capturedInit();
    const headers = new Headers(init?.headers);
    expect(headers.get('Authorization')).toBe('Bearer sekret-token');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('downloadGenerated carries the Authorization header when a token is set', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(new Blob(['zip'])),
      }),
    );

    setApiToken('sekret-token');
    await downloadGenerated('run-1');

    expect(authHeaderOf(capturedInit())).toBe('Bearer sekret-token');
  });

  it('downloadGenerated stays header-less when no token is configured', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(new Blob(['zip'])),
      }),
    );

    setApiToken(null);
    await downloadGenerated('run-1');

    // Pre-auth contract: the download path passed no init at all.
    expect(fetch).toHaveBeenCalledWith('/runs/run-1/download');
  });

  it('setApiToken(null) clears the stored token', () => {
    setApiToken('sekret-token');
    expect(getApiToken()).toBe('sekret-token');
    setApiToken(null);
    expect(getApiToken()).toBeNull();
  });

  it('a 401 from the backend surfaces as ApiError with status 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        json: () => Promise.resolve({ detail: 'Not authenticated' }),
      }),
    );

    setApiToken('wrong-token');
    await expect(getRun('run-1')).rejects.toMatchObject({ status: 401 });
  });
});
