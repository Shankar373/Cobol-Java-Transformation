import { describe, it, expect, vi, afterEach } from 'vitest';
import { ApiError, createApplication } from '../api/client';

/**
 * FastAPI returns `detail` as an ARRAY of Pydantic error objects for request-
 * validation failures (422), but the client typed it as a `string`.  That meant
 * the approval panel showed `[object Object]` to the customer instead of the
 * actual validation message.  These tests pin the normalisation that turns each
 * of those shapes back into readable text.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

function stub422(detail: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify({ detail }), {
        status: 422,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
}

describe('422 validation detail rendering', () => {
  it('surfaces each Pydantic error message when detail is an array', async () => {
    stub422([
      {
        type: 'string_too_short',
        loc: ['body', 'name'],
        msg: 'String should have at least 1 character',
        input: '',
      },
      {
        type: 'missing',
        loc: ['body', 'workload_id'],
        msg: 'Field required',
        input: {},
      },
    ]);

    await expect(
      createApplication({ name: '', workload_id: 'wl-demo' }),
    ).rejects.toBeInstanceOf(ApiError);
    await createApplication({ name: '', workload_id: 'wl-demo' }).catch((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const message = (err as ApiError).message;
      expect(message).not.toContain('[object Object]');
      expect(message).toContain('String should have at least 1 character');
      expect(message).toContain('Field required');
    });
  });

  it('keeps backend-authored string detail unchanged', async () => {
    stub422('Rejection reason is required');

    await createApplication({ name: 'x', workload_id: 'wl-demo' }).catch((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toBe('Rejection reason is required');
    });
  });

  it('renders object-shaped detail without collapsing it', async () => {
    stub422({ reason: 'too small', limit: 1 });

    await createApplication({ name: 'x', workload_id: 'wl-demo' }).catch((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const message = (err as ApiError).message;
      expect(message).not.toContain('[object Object]');
      expect(message).toContain('too small');
    });
  });
});
