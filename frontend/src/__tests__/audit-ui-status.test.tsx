import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getRunApproval: vi.fn(),
    setRunApproval: vi.fn(),
    getReadiness: vi.fn(),
  };
});

import { ApprovalPanel } from '../components/ApprovalPanel';
import { Sidebar } from '../components/Sidebar';
import { getReadiness, getRunApproval } from '../api/client';

const mockReadiness = vi.mocked(getReadiness);
const mockGetRunApproval = vi.mocked(getRunApproval);

beforeEach(() => {
  vi.clearAllMocks();
  mockGetRunApproval.mockResolvedValue({
    run_id: 'run-1',
    state: 'PENDING',
    approver: null,
    reason: null,
    decided_at: null,
    history: [],
  });
});

// Audit FE-04: the backend refuses APPROVED unless the run is VERIFIED.
describe('ApprovalPanel gates Approve on a VERIFIED verdict', () => {
  it('disables Approve and explains why for a non-VERIFIED run', async () => {
    render(<ApprovalPanel runId="run-1" verdictState="PARTIAL" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/Approver/i), { target: { value: 'reviewer' } });

    const approve = screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(screen.getByRole('note').textContent).toMatch(/Only a VERIFIED run can be approved \(this run is PARTIAL\)/);
  });

  it('keeps Reject available for a non-VERIFIED run', async () => {
    render(<ApprovalPanel runId="run-1" verdictState="FAILED" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/Approver/i), { target: { value: 'reviewer' } });
    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: 'mismatch on stdout' } });

    const reject = screen.getByRole('button', { name: 'Reject' }) as HTMLButtonElement;
    expect(reject.disabled).toBe(false);
  });

  it('enables Approve for a VERIFIED run with an approver', async () => {
    render(<ApprovalPanel runId="run-1" verdictState="VERIFIED" />);
    await waitFor(() => expect(screen.getByText(/Pending/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/Approver/i), { target: { value: 'reviewer' } });

    const approve = screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
    expect(screen.queryByRole('note')).toBeNull();
  });
});

// Audit FE-01: the status line used to be hard-coded "All Systems Operational".
describe('Sidebar system status reflects GET /ready', () => {
  const renderSidebar = () => render(<Sidebar currentPage="dashboard" onNavigate={() => {}} />);

  it('shows operational when the server is ready', async () => {
    mockReadiness.mockResolvedValue({ status: 'ready', checks: { database: { ok: true } } });
    renderSidebar();
    await waitFor(() =>
      expect(screen.getByRole('status').textContent).toBe('All Systems Operational'),
    );
  });

  it('names the failing checks when the server is degraded', async () => {
    mockReadiness.mockResolvedValue({
      status: 'not_ready',
      checks: { database: { ok: true }, workspace: { ok: false } },
    });
    renderSidebar();
    await waitFor(() =>
      expect(screen.getByRole('status').textContent).toBe('Degraded: workspace'),
    );
  });

  it('says unknown when the status cannot be read', async () => {
    mockReadiness.mockRejectedValue(new Error('network down'));
    renderSidebar();
    await waitFor(() =>
      expect(screen.getByRole('status').getAttribute('data-status')).toBe('unknown'),
    );
    expect(screen.getByRole('status').textContent).toBe('Status unknown');
  });
});
