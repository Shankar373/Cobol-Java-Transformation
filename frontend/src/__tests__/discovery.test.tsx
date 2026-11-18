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
  readiness: {
    status: 'NOT_SUPPORTED', allowed: true, blockers: [], unsupported_total: 1, unverified_total: 0, unverified: [],
    unsupported: [{ file: 'src/ORDERS.cbl', feature: 'exec-cics', label: 'EXEC CICS', note: 'needs the IBM CICS translator', stops_check: true, evidence: [{ label: 'EXEC CICS LINK', line: 5 }] }],
    compile_errors: [],
  },
  toolchain: {
    required: [{ family: 'gnucobol', kind: 'invocation', name: 'cobc', evidence: [{ file: 'build/Makefile', line: 3 }], evidence_count: 1 }],
    tools: [
      { tool: 'cobc', available: true, version: '3.1.2.0', via: 'container:gnucobol-ocesql:latest', license: 'GPL-3.0-or-later (GnuCOBOL)' },
      { tool: 'gcobol', available: false, reason: 'not on PATH', license: 'GPL-3.0-or-later with GCC Runtime Library Exception' },
    ],
  },
  compatibility: {
    backend: { kind: 'container', reason: '', version: '3.1.2.0', image: 'gnucobol-ocesql:latest' },
    basis: 'syntax-only check with GnuCOBOL',
    summary: { COMPILES: 1, NOT_ATTEMPTED_PROPRIETARY: 1, COMPILE_ERRORS: 1 },
    programs: [
      { file: 'src/OK.cbl', dialect: 'undetermined', source_format: 'fixed', verdict: 'COMPILES', diagnostics: [], unsupported_features: [] },
      { file: 'src/ORDERS.cbl', dialect: 'ibm-enterprise', source_format: 'fixed', verdict: 'NOT_ATTEMPTED_PROPRIETARY', reason: 'needs the IBM CICS translator', diagnostics: [],
        unsupported_features: [{ feature: 'exec-cics', label: 'EXEC CICS', note: 'needs the IBM CICS translator', stops_check: true, evidence: [{ label: 'EXEC CICS LINK', line: 5 }], evidence_count: 1 }] },
      { file: 'src/BAD.cbl', dialect: 'gnucobol', source_format: 'fixed', verdict: 'COMPILE_ERRORS', diagnostics: [{ file: 'src/BAD.cbl', line: 7, severity: 'error', message: 'syntax error' }], unsupported_features: [] },
    ],
  },
  applications: {
    applications: [{
      id: 'APP-1', name: 'PAYJOB', readiness: 'BLOCKED', programs: ['PAYROLL'], jobs: ['PAYJOB'], files: ['src/PAYROLL.cbl'], copybooks: [], unsupported_features: [], compile_errors: [],
      compiler_verdicts: {}, blocking_unresolved: [{ file: 'src/PAYROLL.cbl', line: 9, reason: 'missing-program', to: 'program:MISSING1' }],
      entry_points: [{ program: 'PAYROLL', file: 'src/PAYROLL.cbl', kinds: ['batch-job-step'], invoked_by: ['job:PAYJOB'] }], resources: [],
    }],
    entry_points: [],
    relationships: [{ resource: 'table:HR.EMPLOYEE', kind: 'table', applications: [{ id: 'APP-1', name: 'PAYJOB', uses: 2 }, { id: 'APP-2', name: 'HRJOB', uses: 1 }] }],
  },
};

const SOURCE = {
  file: 'src/PAYROLL.cbl', line: 9, first_line: 7, total_lines: 20, encoding: 'ascii', sha256: 'a'.repeat(64),
  lines: [{ number: 7, text: '       PROCEDURE DIVISION.' }, { number: 8, text: '           CALL A.' }, { number: 9, text: "           CALL 'MISSING1'." }],
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
      if (url.includes('/source?')) return json(200, SOURCE);
      if (url.endsWith('/unresolved')) return json(200, { unresolved: [{ to: 'program:MISSING1', reason: 'missing-program', blocking: true, file: 'src/PAYROLL.cbl', line: 9, from: 'program:PAYROLL', clause: 'CALL', relation: 'calls' }], ambiguous: [] });
      return json(404, { detail: 'nope' });
    });
    render(<Discovery pollIntervalMs={1} />);
    const file = new File(['zip'], 'estate.zip', { type: 'application/zip' });
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [file] } });
    fireEvent.click(screen.getByText('Start discovery'));

    await waitFor(() => expect(screen.getByTestId('discovery-state').textContent).toBe('succeeded'));
    await waitFor(() => expect(screen.getAllByText('PAYROLL').length).toBeGreaterThan(0));
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

  it('shows readiness, the compiler toolchain, per-program verdicts, applications and relationships', async () => {
    install((url) => {
      if (url === '/discovery/runs/zip') return json(202, run());
      if (url === `/discovery/runs/${RUN_ID}`) return json(200, run({ state: 'succeeded', checkpoint_id: 'CP-123456789abc', gate_status: 'INCOMPLETE' }));
      if (url.endsWith('/report')) return json(200, REPORT);
      if (url.endsWith('/unresolved')) return json(200, { unresolved: [], ambiguous: [] });
      return json(404, {});
    });
    render(<Discovery pollIntervalMs={1} />);
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [new File(['zip'], 'e.zip')] } });
    fireEvent.click(screen.getByText('Start discovery'));

    await waitFor(() => expect(screen.getByTestId('readiness').textContent).toContain('NOT_SUPPORTED'));
    expect(screen.getByTestId('compiler-backend').textContent).toContain('GnuCOBOL 3.1.2.0');
    expect(screen.getByText(/not available: not on PATH/)).toBeTruthy();
    expect(screen.getByText('COMPILE_ERRORS')).toBeTruthy();
    expect(screen.getAllByText(/needs the IBM CICS translator/).length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('application-card')).toHaveLength(1);
    expect(screen.getByText('table:HR.EMPLOYEE')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Filter by verdict'), { target: { value: 'COMPILES' } });
    expect(screen.queryByText('src/BAD.cbl')).toBeNull();
  });

  it('opens the source viewer at the exact line from any file:line reference', async () => {
    install((url) => {
      if (url === '/discovery/runs/zip') return json(202, run());
      if (url === `/discovery/runs/${RUN_ID}`) return json(200, run({ state: 'succeeded', checkpoint_id: 'CP-123456789abc', gate_status: 'INCOMPLETE' }));
      if (url.endsWith('/report')) return json(200, REPORT);
      if (url.includes('/source?')) return json(200, SOURCE);
      if (url.endsWith('/unresolved')) return json(200, { unresolved: [], ambiguous: [] });
      return json(404, {});
    });
    render(<Discovery pollIntervalMs={1} />);
    fireEvent.change(screen.getByLabelText(/COBOL estate/), { target: { files: [new File(['zip'], 'e.zip')] } });
    fireEvent.click(screen.getByText('Start discovery'));
    await waitFor(() => expect(screen.getByText('src/PAYROLL.cbl:2')).toBeTruthy());
    fireEvent.click(screen.getByText('src/PAYROLL.cbl:2'));
    await waitFor(() => expect(screen.getByTestId('source-hit').textContent).toContain("CALL 'MISSING1'"));
    expect(calls.some((c) => c.includes('/source?path=src%2FPAYROLL.cbl&line=2'))).toBe(true);
    fireEvent.click(screen.getByLabelText('Close source viewer'));
    expect(screen.queryByLabelText('Source viewer')).toBeNull();
  });
});
