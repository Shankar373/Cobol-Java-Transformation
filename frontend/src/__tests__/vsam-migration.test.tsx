import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { VsamMigration, validateVsamForm } from '../pages/VsamMigration';
import { Sidebar } from '../components/Sidebar';
import type { ApplicationResponse } from '../api/client';

const APP = { id: 'app-1', name: 'Payroll' } as ApplicationResponse;
const HASH = 'a'.repeat(64);
const UPLOAD_PATH = '/vsam/migrations/job-1/upload';

function jobBody(over: Record<string, unknown> = {}) {
  return {
    job_id: 'job-1',
    application_id: 'app-1',
    state: 'CREATED',
    runtime_path: 'data/customer.vsam',
    output_name: null,
    records: null,
    bytes_processed: null,
    dataset_bytes: 3,
    output_sha256: null,
    output_bytes: null,
    error_code: null,
    error_message: null,
    created: true,
    upload_path: UPLOAD_PATH,
    ...over,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

function installFetch(handlers: { post?: Handler; put?: Handler; get?: Handler }) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'POST' && handlers.post) return handlers.post(url, init);
    if (method === 'PUT' && handlers.put) return handlers.put(url, init);
    if (method === 'GET' && handlers.get) return handlers.get(url, init);
    return jsonResponse(500, { detail: `unexpected ${method} ${url}` });
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function postBodies(mock: ReturnType<typeof installFetch>) {
  return mock.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([, init]) => JSON.parse(init!.body as string));
}

function renderPage(apps: ApplicationResponse[] = [APP]) {
  return render(<VsamMigration applications={apps} pollIntervalMs={5} />);
}

function type(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillForm(file: File | null = new File(['abc'], 'customer.dat')) {
  type('Dataset name', 'CUSTOMER');
  type('Runtime path', 'data/customer.vsam');
  type(/^Record length$/, '80');
  type('Key length', '10');
  type('Record count', '3');
  type(/^SHA-256/, HASH);
  type('Export platform', 'z/OS');
  type(/^Export tool$/, 'IDCAMS');
  type('Export tool version', '1.0');
  type('Provenance', 'nightly export');
  if (file) {
    fireEvent.change(screen.getByLabelText('VSAM export file'), { target: { files: [file] } });
  }
}

const submit = () => fireEvent.click(screen.getByRole('button', { name: /start migration|retry migration/i }));

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('VSAM migration page', () => {
  it('runs the lifecycle to SUCCEEDED and only then shows success and download', async () => {
    let polls = 0;
    const fetchMock = installFetch({
      post: () => jsonResponse(201, jobBody()),
      put: () => new Response(null, { status: 202 }),
      get: () => {
        polls += 1;
        return jsonResponse(200, polls < 2
          ? jobBody({ state: 'RUNNING', records: 1, bytes_processed: 1 })
          : jobBody({ state: 'SUCCEEDED', records: 3, bytes_processed: 3, output_name: 'customer.vsam', output_sha256: 'b'.repeat(64) }));
      },
    });
    renderPage();
    fillForm();
    submit();

    expect(await screen.findByText(/Migration succeeded/)).toBeInTheDocument();
    expect(screen.getByTestId('vsam-state')).toHaveTextContent('SUCCEEDED');
    expect(screen.getByRole('button', { name: /download migrated dataset/i })).toBeInTheDocument();

    const [body] = postBodies(fetchMock);
    expect(body.manifest.dataset_bytes).toBe(3);
    expect(body.manifest.organization).toBe('KSDS');
    expect(body.manifest.layout.key_length).toBe(10);
    expect(body.idempotency_key).toMatch(/[0-9a-f-]{36}/);
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!;
    expect(String(put[0])).toBe(UPLOAD_PATH);
    expect(put[1]!.body).toBeInstanceOf(File);
  });

  it('shows a REFUSED job with its code, an explanation and no download or upload', async () => {
    const fetchMock = installFetch({
      post: () => jsonResponse(201, jobBody({
        state: 'REFUSED', error_code: 'MANIFEST_MISMATCH', error_message: 'record_count does not match', upload_path: undefined,
      })),
    });
    renderPage();
    fillForm();
    submit();

    expect(await screen.findByText('MANIFEST_MISMATCH')).toBeInTheDocument();
    expect(screen.getByText(/record_count does not match/)).toBeInTheDocument();
    expect(screen.getByText(/Retrying the same input will give the same result/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Migration succeeded/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
  });

  it('shows an upload failure and retries with the same idempotency key', async () => {
    let puts = 0;
    const fetchMock = installFetch({
      post: () => jsonResponse(201, jobBody()),
      put: () => {
        puts += 1;
        return puts === 1
          ? jsonResponse(400, { detail: 'Content-Length does not match dataset_bytes' })
          : new Response(null, { status: 202 });
      },
      get: () => jsonResponse(200, jobBody({ state: 'SUCCEEDED', records: 3, bytes_processed: 3 })),
    });
    renderPage();
    fillForm();
    submit();

    expect(await screen.findByText(/Upload failed: Content-Length does not match dataset_bytes/)).toBeInTheDocument();
    expect(screen.queryByText(/Migration succeeded/)).not.toBeInTheDocument();

    submit();
    expect(await screen.findByText(/Migration succeeded/)).toBeInTheDocument();
    const keys = postBodies(fetchMock).map((b) => b.idempotency_key);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('shows progress from backend values and no success while RUNNING', async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((r) => { release = r; });
    installFetch({
      post: () => jsonResponse(201, jobBody()),
      put: () => new Response(null, { status: 202 }),
      get: async () => {
        await gate;
        return jsonResponse(200, jobBody({ state: 'SUCCEEDED', records: 3, bytes_processed: 3 }));
      },
    });
    // First poll is held; creation response is CREATED, so progress is not yet known.
    renderPage();
    fillForm();
    submit();
    expect(await screen.findByTestId('vsam-state')).toHaveTextContent('CREATED');
    expect(screen.queryByText(/Migration succeeded/)).not.toBeInTheDocument();
    release!();
    expect(await screen.findByText(/Migration succeeded/)).toBeInTheDocument();
  });

  it('renders records and byte progress exactly as reported by the backend', async () => {
    let polls = 0;
    let release: (() => void) | null = null;
    const gate = new Promise<void>((r) => { release = r; });
    installFetch({
      post: () => jsonResponse(201, jobBody({ dataset_bytes: 2000 })),
      put: () => new Response(null, { status: 202 }),
      get: async () => {
        polls += 1;
        if (polls === 1) {
          return jsonResponse(200, jobBody({ state: 'RUNNING', dataset_bytes: 2000, bytes_processed: 1500, records: 42 }));
        }
        await gate;
        return jsonResponse(200, jobBody({ state: 'FAILED', error_code: 'X', error_message: 'boom' }));
      },
    });
    renderPage();
    fillForm();
    submit();

    expect(await screen.findByText(/1,500 of 2,000 bytes processed/)).toBeInTheDocument();
    expect(screen.getByText(/Records processed: 42/)).toBeInTheDocument();
    const bar = screen.getByLabelText('Bytes processed') as HTMLProgressElement;
    expect(bar.value).toBe(1500);
    expect(bar.max).toBe(2000);
    expect(screen.getByTestId('vsam-state')).toHaveTextContent('RUNNING');
    expect(screen.queryByText(/Migration succeeded/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
    release!();
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });

  it('reports a 401 on job creation as authentication required', async () => {
    installFetch({ post: () => jsonResponse(401, { detail: 'Unauthorized' }) });
    renderPage();
    fillForm();
    submit();

    expect(await screen.findByText(/Authentication required \(401\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Migration succeeded/)).not.toBeInTheDocument();
  });

  it('shows an empty state when there are no applications', () => {
    renderPage([]);
    expect(screen.getByText('No applications available')).toBeInTheDocument();
    expect(screen.queryByLabelText('VSAM export file')).not.toBeInTheDocument();
  });

  it('blocks submission and sends nothing when the form is empty or invalid', () => {
    const fetchMock = installFetch({});
    renderPage();
    expect(screen.getByText('No file selected.')).toBeInTheDocument();
    submit();

    expect(screen.getByText('Select the VSAM export file to upload.')).toBeInTheDocument();
    expect(screen.getByText('Dataset name is required.')).toBeInTheDocument();
    expect(screen.getByText('SHA-256 must be 64 hexadecimal characters.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fillForm();
    type(/^SHA-256/, 'xyz');
    type('Record count', '-4');
    submit();
    expect(screen.getByText('SHA-256 must be 64 hexadecimal characters.')).toBeInTheDocument();
    expect(screen.getAllByText('Enter a positive whole number.').length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('validateVsamForm requires key length only for KSDS and max length for variable records', () => {
    const file = new File(['abc'], 'a.dat');
    const base = {
      datasetName: 'D', runtimePath: 'p', organization: 'ESDS' as const, recordFormat: 'VARIABLE_RDW' as const,
      minRecordLength: '10', maxRecordLength: '5', keyOffset: '0', keyLength: '', codePage: 'cp037',
      recordCount: '1', sha256: HASH, exportPlatform: 'a', exportTool: 'b', exportToolVersion: 'c',
      provenance: 'd', cobolSource: '', cobolFile: '',
    };
    const errs = validateVsamForm(base, file);
    expect(errs.keyLength).toBeUndefined();
    expect(errs.maxRecordLength).toMatch(/at least the minimum/);
    expect(validateVsamForm({ ...base, maxRecordLength: '20' }, file)).toEqual({});
    expect(validateVsamForm({ ...base, maxRecordLength: '20', organization: 'KSDS' }, file).keyLength).toBeDefined();
  });

  it('is reachable from the sidebar', () => {
    const onNavigate = vi.fn();
    installFetch({ get: () => jsonResponse(200, { status: 'ready', checks: {} }) });
    render(<Sidebar currentPage="vsam" onNavigate={onNavigate} />);
    fireEvent.click(screen.getByText('VSAM Migration'));
    expect(onNavigate).toHaveBeenCalledWith('vsam');
  });
});

describe('VSAM migration API safety', () => {
  it('refuses to send the upload to a non-relative path', async () => {
    const fetchMock = installFetch({
      post: () => jsonResponse(201, jobBody({ upload_path: 'https://evil.example/up' })),
    });
    renderPage();
    fillForm();
    submit();
    expect(await screen.findByText(/non-relative upload path/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
  });
});
