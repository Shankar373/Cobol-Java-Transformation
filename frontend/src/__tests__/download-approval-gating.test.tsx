import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
    getRunApproval: vi.fn(),
    setRunApproval: vi.fn(),
    downloadGenerated: vi.fn(),
  };
});

import { ModernizationRun } from '../pages/ModernizationRun';
import {
  getRun,
  getRunDetail,
  getVerdict,
  getDiscovery,
  getArtifacts,
  getRunApproval,
  downloadGenerated,
} from '../api/client';

const mockGetRun = vi.mocked(getRun);
const mockGetRunDetail = vi.mocked(getRunDetail);
const mockGetVerdict = vi.mocked(getVerdict);
const mockGetDiscovery = vi.mocked(getDiscovery);
const mockGetArtifacts = vi.mocked(getArtifacts);
const mockGetRunApproval = vi.mocked(getRunApproval);
const mockDownload = vi.mocked(downloadGenerated);

const APPROVED_LABEL = /download generated spring boot application/i;
const PENDING_LABEL = /download \(awaiting approval\)/i;
const REJECTED_LABEL = /download \(awaiting approval — rejected\)/i;

function runResponse(stage: string, generatedFiles: string[] = ['src/main/java/app/Payroll.java', 'pom.xml']) {
  return {
    id: 'run-1',
    application_id: 'app-1',
    workload_id: 'wl-demo',
    stage,
    created_at: new Date().toISOString(),
    completed_at: null,
    error: null,
    verdict_state: 'VERIFIED',
    generated_files: generatedFiles,
  };
}

function runDetailResponse(generatedFiles: string[] = ['src/main/java/app/Payroll.java', 'pom.xml']) {
  return {
    id: 'run-1',
    application_id: 'app-1',
    application_name: 'payroll-app',
    workload_id: 'wl-demo',
    stage: 'COMPLETED',
    created_at: '2024-01-01T00:00:00Z',
    completed_at: '2024-01-01T00:01:00Z',
    error: null,
    verdict_state: 'VERIFIED',
    discovery: null,
    stage_messages: ['COMPLETED'],
    generated_files: generatedFiles,
  };
}

function approvalResponse(state: string) {
  return {
    run_id: 'run-1',
    state,
    approver: state === 'PENDING' ? null : 'alice',
    reason: null,
    decided_at: state === 'PENDING' ? null : '2024-01-01T00:02:00Z',
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockGetRun.mockReset();
  mockGetRunDetail.mockReset();
  mockGetVerdict.mockReset();
  mockGetDiscovery.mockReset();
  mockGetArtifacts.mockReset();
  mockGetRunApproval.mockReset();
  mockDownload.mockReset();
  mockGetVerdict.mockRejectedValue(new Error('no verdict'));
  mockGetDiscovery.mockRejectedValue(new Error('no discovery'));
  mockGetArtifacts.mockResolvedValue({ run_id: 'run-1', artifacts: [] } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ModernizationRun download gating on approval state', () => {
  describe('header entry point (generated files listed)', () => {
    it('disables the download button while approval is PENDING', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse() as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('PENDING') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: PENDING_LABEL });
        expect(btn).toBeDisabled();
      });
      expect(screen.getByText(/awaiting approval/i)).toBeInTheDocument();
    });

    it('enables the download button once approval is APPROVED', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse() as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('APPROVED') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: APPROVED_LABEL });
        expect(btn).not.toBeDisabled();
      });
      expect(screen.queryByText(/awaiting approval/i)).not.toBeInTheDocument();
    });

    it('disables the download button when approval is REJECTED', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse() as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('REJECTED') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: REJECTED_LABEL });
        expect(btn).toBeDisabled();
      });
      expect(screen.getByText(/awaiting approval — rejected/i)).toBeInTheDocument();
    });
  });

  describe('placeholder entry point (no generated files listed)', () => {
    it('disables the placeholder download button while approval is PENDING', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED', []) as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse([]) as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('PENDING') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: PENDING_LABEL });
        expect(btn).toBeDisabled();
      });
      expect(
        screen.getByText(/generated application files are reported by the assembly stage/i),
      ).toBeInTheDocument();
      // The header button does not render in this branch — the placeholder
      // button is the single download entry point and it is gated.
      expect(screen.getAllByRole('button', { name: /download/i })).toHaveLength(1);
    });

    it('enables the placeholder download button once approval is APPROVED', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED', []) as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse([]) as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('APPROVED') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: APPROVED_LABEL });
        expect(btn).not.toBeDisabled();
      });
      expect(screen.queryByText(/awaiting approval/i)).not.toBeInTheDocument();
    });

    it('disables the placeholder download button when approval is REJECTED', async () => {
      mockGetRun.mockResolvedValue(runResponse('COMPLETED', []) as never);
      mockGetRunDetail.mockResolvedValue(runDetailResponse([]) as never);
      mockGetRunApproval.mockResolvedValue(approvalResponse('REJECTED') as never);

      render(<ModernizationRun runId="run-1" applicationId="app-1" />);

      await waitFor(() => {
        const btn = screen.getByRole('button', { name: REJECTED_LABEL });
        expect(btn).toBeDisabled();
      });
      expect(screen.getByText(/awaiting approval — rejected/i)).toBeInTheDocument();
    });
  });
});
