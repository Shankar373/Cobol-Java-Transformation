import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getRunApproval: vi.fn(),
    setRunApproval: vi.fn(),
  };
});

import { ApprovalPanel } from '../components/ApprovalPanel';
import { getRunApproval, setRunApproval, ApiError } from '../api/client';

const mockGetRunApproval = vi.mocked(getRunApproval);
const mockSetRunApproval = vi.mocked(setRunApproval);

const PENDING = {
  run_id: 'run-1',
  state: 'PENDING' as const,
  approver: null,
  reason: null,
  decided_at: null,
};

const APPROVED = {
  run_id: 'run-1',
  state: 'APPROVED' as const,
  approver: 'reviewer-a',
  reason: null,
  decided_at: '2026-10-17T10:00:00+00:00',
};

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// ApprovalPanel behaviour (BL-091)
//
// HTTP contract (paths/methods/payloads) is pinned separately in
// approval-client.test.ts against the real client module.
// ---------------------------------------------------------------------------

describe('ApprovalPanel', () => {
  it('renders the PENDING state with decision controls', async () => {
    mockGetRunApproval.mockResolvedValue(PENDING);

    render(<ApprovalPanel runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByText(/Pending/i)).toBeTruthy();
    });
    expect(screen.getByPlaceholderText(/approver/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /approve/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /reject/i })).toBeTruthy();
  });

  it('keeps Reject disabled until both approver and a real reason exist', async () => {
    mockGetRunApproval.mockResolvedValue(PENDING);

    render(<ApprovalPanel runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    const reject = screen.getByRole('button', { name: /reject/i }) as HTMLButtonElement;
    expect(reject.disabled).toBe(true);

    // Approver alone is not enough for a rejection.
    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: 'reviewer-a' },
    });
    expect(reject.disabled).toBe(true);

    // Whitespace-only reason still blocks the rejection.
    fireEvent.change(screen.getByPlaceholderText(/reason/i), {
      target: { value: '   ' },
    });
    expect(reject.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/reason/i), {
      target: { value: 'verdict scope mismatch' },
    });
    expect(reject.disabled).toBe(false);
  });

  it('approves with an optional reason', async () => {
    mockGetRunApproval.mockResolvedValueOnce(PENDING).mockResolvedValue(APPROVED);
    mockSetRunApproval.mockResolvedValue(APPROVED);

    render(<ApprovalPanel runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: 'reviewer-a' },
    });
    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => {
      expect(mockSetRunApproval).toHaveBeenCalledWith('run-1', {
        decision: 'APPROVED',
        approver: 'reviewer-a',
      });
    });
    // Approval refreshes the record so the badge reflects the new state.
    await waitFor(() => {
      expect(mockGetRunApproval).toHaveBeenCalledTimes(2);
    });
    expect(screen.getAllByText(/Approved/i).length).toBeGreaterThan(0);
  });

  it('rejects only with approver and reason, sending both', async () => {
    mockGetRunApproval.mockResolvedValueOnce(PENDING).mockResolvedValue({
      run_id: 'run-1',
      state: 'REJECTED',
      approver: 'reviewer-b',
      reason: 'scope mismatch',
      decided_at: '2026-10-17T10:05:00+00:00',
    });
    mockSetRunApproval.mockResolvedValue({
      run_id: 'run-1',
      state: 'REJECTED',
      approver: 'reviewer-b',
      reason: 'scope mismatch',
      decided_at: '2026-10-17T10:05:00+00:00',
    });

    render(<ApprovalPanel runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: 'reviewer-b' },
    });
    fireEvent.change(screen.getByPlaceholderText(/reason/i), {
      target: { value: 'scope mismatch' },
    });
    fireEvent.click(screen.getByRole('button', { name: /reject/i }));

    await waitFor(() => {
      expect(mockSetRunApproval).toHaveBeenCalledWith('run-1', {
        decision: 'REJECTED',
        approver: 'reviewer-b',
        reason: 'scope mismatch',
      });
    });
    // Badge (and record header) reflect REJECTED after refresh.
    await waitFor(() => {
      expect(screen.getAllByText(/Rejected/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/scope mismatch/i)).toBeTruthy();
  });

  it('disables decisions until approver is non-empty', async () => {
    mockGetRunApproval.mockResolvedValue(PENDING);

    render(<ApprovalPanel runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    const approve = screen.getByRole('button', { name: /approve/i }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: ' ' },
    });
    expect(approve.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: 'reviewer-a' },
    });
    expect(approve.disabled).toBe(false);
  });

  it('surfaces a decision error (e.g. 422) without changing state', async () => {
    mockGetRunApproval.mockResolvedValue(PENDING);
    mockSetRunApproval.mockRejectedValue(
      new ApiError(422, 'rejection requires a reason'),
    );

    render(<ApprovalPanel runId="run-1" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/approver/i), {
      target: { value: 'reviewer-a' },
    });
    fireEvent.click(screen.getByRole('button', { name: /approve/i }));

    await waitFor(() => {
      expect(screen.getByText(/rejection requires a reason/i)).toBeTruthy();
    });
    expect(screen.getByText(/Pending/i)).toBeTruthy();
  });

  it('shows the recorded approver and reason for a decided run', async () => {
    mockGetRunApproval.mockResolvedValue({
      run_id: 'run-1',
      state: 'REJECTED',
      approver: 'reviewer-c',
      reason: 'second look failed',
      decided_at: '2026-10-17T11:00:00+00:00',
    });

    render(<ApprovalPanel runId="run-1" />);

    await waitFor(() => {
      expect(screen.getAllByText(/Rejected/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByText('reviewer-c')).toBeTruthy();
    expect(screen.getByText(/second look failed/i)).toBeTruthy();
  });

  it('shows a load error when the approval record cannot be fetched', async () => {
    mockGetRunApproval.mockRejectedValue(new ApiError(404, "Run 'run-1' not found"));

    render(<ApprovalPanel runId="run-1" />);

    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeTruthy();
    });
  });
});
