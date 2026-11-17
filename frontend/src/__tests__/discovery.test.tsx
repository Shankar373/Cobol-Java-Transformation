import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { Discovery } from '../pages/Discovery';

const RUN_ID = 'a'.repeat(32);

function run(over: Record<string, unknown> = {}) {
  return {
    run_id: RUN_ID, kind: 'zip', label: 'estate', state: 'queued', created_at: '2026-01-01T00:00:00Z', steps: [],
    checkpoint_id: '', gate_status: '', ready_for_transformation: false, summary: {}, error_code: '', error_message: '',
    ...over,
  };
}

const REPORT = {
  schema_version: 'systemaops.discovery-report/1.0',
  completeness: {
    status: 'INCOMPLETE', ready_for_transformation: false, blockers: ['no-blocking-unresolved-references'],
    checks: [{ id: 'checkpoint-verified', passed: true, detail: 'ok' }, { id: 'no-blocking-unresolved-references', passed: false, detail: '1 blocking' }],
    open_items: [],
  },
  summary: { files: 14, directories: 9, bytes: 2744, files_by_class: { cobol: 4 } },
  programs: [{ name: 'PAYROLL', file: 'src/PAYROLL.cbl', line: 2, source_format: 'fixed', calls: ['MISSING1'], copybooks: ['EMPREC'], db2_tables: [] }],
  dependency_graph: { nodes: 10, edges: 20, blocking_unresolved: 1, resolutions: {}, unresolved_by_reason: {} },
  dialects: { basis: 'indicative', summary: [] },
  runtime_dependencies: [{ category: 'subsystem', name: 'CICS', evidence_count: 1 }],
  limitations: ['Discovery is lexical.'],
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

let calls: string[];

function install(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`);
    return handler(url, init);
  }));
}

beforeEach(() => { calls = []; });
afterEach(() => { vi.unstubAllGlobals(); });

describe('Discovery page', () => {
  it('uploads a ZIP, polls to completion and shows the gate, programs and unresolved references', async () => {
    install((url) => {
      if (url === '/discovery/runs/zip') return json(202, run());
      if (url === `/discovery/runs/${RUN_ID}`) return json(200, run({ state: 'succeeded', checkpoint_id: 'CP-123456789abc', gate_status: 'INCOMPLETE' }));
      if (url.endsWith('/report')) return json(200, REPORT);
      if (url.endsWith('/unresolved')) return json(200, { unresolved: [{ to: 'program:MISSING1', reason: 'missing-program', blocking: true, file: 'src/PAYROLL.cbl', line: 9, from: 'program:PAYROLL', clause: 'CALL', relation: 'calls' }], ambiguous: [] });
      return json(404, { detail: 'nope' });
    });
    render(<Discovery pollIntervalMs={1} />);
    const file = new File(['zip'], 'estate.zip', { type: 'application/zip' });
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [file] } });
    fireEvent.click(screen.getByText('Start discovery'));

    await waitFor(() => expect(screen.getByTestId('discovery-state').textContent).toBe('succeeded'));
    await waitFor(() => expect(screen.getByText('PAYROLL')).toBeTruthy());
    expect(screen.getByTestId('discovery-gate').textContent).toContain('incomplete');
    expect(screen.getByText('program:MISSING1')).toBeTruthy();
    expect(screen.getByText('Fail: no-blocking-unresolved-references (1 blocking)')).toBeTruthy();
  });

  it('shows a refused input with its stable code', async () => {
    install((url) => {
      if (url === '/discovery/runs/zip') return json(202, run());
      return json(200, run({ state: 'failed', error_code: 'ARCHIVE_BAD_PATH', error_message: 'entry name escapes' }));
    });
    render(<Discovery pollIntervalMs={1} />);
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [new File(['x'], 'e.zip')] } });
    fireEvent.click(screen.getByText('Start discovery'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('ARCHIVE_BAD_PATH'));
  });

  it('requires a file or an https URL before calling the backend', () => {
    install(() => json(500, {}));
    render(<Discovery />);
    fireEvent.click(screen.getByText('Start discovery'));
    expect(screen.getByRole('alert').textContent).toContain('Select a ZIP');
    fireEvent.click(screen.getByLabelText('Git repository (https)'));
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'http://x.example/r.git' } });
    fireEvent.click(screen.getByText('Start discovery'));
    expect(screen.getByRole('alert').textContent).toContain('https://');
    expect(calls).toEqual([]);
  });

  it('verifies the checkpoint and reports a failed verification', async () => {
    install((url, init) => {
      if (url === '/discovery/runs/git') return json(202, run({ kind: 'git' }));
      if (url === `/discovery/runs/${RUN_ID}` ) return json(200, run({ state: 'succeeded', checkpoint_id: 'CP-123456789abc', gate_status: 'INCOMPLETE' }));
      if (url.endsWith('/report')) return json(200, REPORT);
      if (url.endsWith('/unresolved')) return json(200, { unresolved: [], ambiguous: [] });
      if (url.endsWith('/verify') && init?.method === 'POST') return json(200, { checkpoint_id: 'CP-1', ok: false, digest_ok: false, modified: ['a.cbl'], missing: [], extra: [], errors: [] });
      return json(404, {});
    });
    render(<Discovery pollIntervalMs={1} />);
    fireEvent.click(screen.getByLabelText('Git repository (https)'));
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://example.com/r.git' } });
    fireEvent.click(screen.getByText('Start discovery'));
    await waitFor(() => expect(screen.getByText('Verify checkpoint')).toBeTruthy());
    fireEvent.click(screen.getByText('Verify checkpoint'));
    await waitFor(() => expect(screen.getByTestId('discovery-verification').textContent).toContain('FAILED'));
  });

  it('asks for a token on 401', async () => {
    install(() => json(401, { detail: 'Unauthorized' }));
    render(<Discovery />);
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [new File(['x'], 'e.zip')] } });
    fireEvent.click(screen.getByText('Start discovery'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('authentication required'));
  });
});
