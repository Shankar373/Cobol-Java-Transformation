import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getRunApproval: vi.fn(),
    getReadiness: vi.fn(),
  };
});

import * as api from '../api/client';
import { ApprovalPanel } from '../components/ApprovalPanel';
import { Sidebar } from '../components/Sidebar';
import { NewModernization } from '../pages/NewModernization';

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getReadiness).mockResolvedValue({ status: 'ready', checks: {} });
});

// Audit FE-15: the approval panel hid the recorded decision history and
// offered no way out of a load failure.
describe('approval panel', () => {
  it('lists the decision history', async () => {
    vi.mocked(api.getRunApproval).mockResolvedValue({
      run_id: 'run-1',
      state: 'REJECTED',
      approver: 'qa-lead',
      reason: 'totals differ',
      decided_at: '2026-11-03T10:00:00+00:00',
      history: [
        { state: 'APPROVED', approver: 'ops', reason: null, recorded_at: '2026-11-02T09:00:00+00:00' },
        { state: 'RESET', approver: null, reason: null, recorded_at: '2026-11-02T12:00:00+00:00' },
        { state: 'REJECTED', approver: 'qa-lead', reason: 'totals differ', recorded_at: '2026-11-03T10:00:00+00:00' },
      ],
    } as api.RunApprovalResponse);

    render(<ApprovalPanel runId="run-1" verdictState="VERIFIED" />);

    expect(await screen.findByText('Decision history')).toBeTruthy();
    expect(screen.getByText(/APPROVED by ops/)).toBeTruthy();
    expect(screen.getByText(/Reset by a new validation/)).toBeTruthy();
  });

  it('retries after a load failure', async () => {
    vi.mocked(api.getRunApproval)
      .mockRejectedValueOnce(new api.ApiError(500, 'database is locked'))
      .mockResolvedValue({
        run_id: 'run-1', state: 'PENDING', approver: null, reason: null, decided_at: null, history: [],
      } as unknown as api.RunApprovalResponse);

    render(<ApprovalPanel runId="run-1" verdictState="VERIFIED" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(api.getRunApproval).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText(/Could not load approval state/)).toBeNull());
  });
});

// Audit FE-12: placeholder navigation items were focusable links.
describe('sidebar', () => {
  it('takes placeholder items out of the tab order', () => {
    render(<Sidebar currentPage="dashboard" onNavigate={() => {}} />);
    const runs = screen.getByTitle('Runs (not available yet)');
    expect(runs.getAttribute('aria-disabled')).toBe('true');
    expect(runs.getAttribute('tabindex')).toBe('-1');
  });

  // Audit FE-20: a token typed into the browser could not be removed.
  it('offers sign-out only when asked to', () => {
    const onSignOut = vi.fn();
    const { rerender } = render(<Sidebar currentPage="dashboard" onNavigate={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
    rerender(<Sidebar currentPage="dashboard" onNavigate={() => {}} onSignOut={onSignOut} />);
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(onSignOut).toHaveBeenCalled();
  });
});

describe('token storage', () => {
  it('reports and clears a stored token', () => {
    api.setApiToken('secret');
    expect(api.hasStoredApiToken()).toBe(true);
    api.setApiToken(null);
    expect(api.hasStoredApiToken()).toBe(false);
  });
});

// Audit FE-17: an oversize ZIP was only rejected by the edge after upload.
describe('upload zone', () => {
  it('rejects a ZIP over the 50 MB limit before submitting', () => {
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);
    const big = new File(['PK'], 'huge.zip', { type: 'application/zip' });
    Object.defineProperty(big, 'size', { value: 51 * 1024 * 1024 });
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [big] },
    });
    expect(screen.getByText(/upload limit is/)).toBeTruthy();
  });

  it('does not scroll the page when Space opens the picker', () => {
    render(<NewModernization onSubmit={vi.fn()} />);
    const zone = document.querySelector('[role="button"][tabindex="0"]') as HTMLElement;
    const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    zone.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});
