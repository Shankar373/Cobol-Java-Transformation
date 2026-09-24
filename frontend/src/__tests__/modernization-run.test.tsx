import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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
    downloadGenerated: vi.fn(),
  };
});

import { ModernizationRun } from '../pages/ModernizationRun';
import { VerdictDisplay } from '../components/VerdictDisplay';
import {
  getRun,
  getRunDetail,
  getVerdict,
  getDiscovery,
  getArtifacts,
  downloadGenerated,
} from '../api/client';

const mockGetRun = vi.mocked(getRun);
const mockGetRunDetail = vi.mocked(getRunDetail);
const mockGetVerdict = vi.mocked(getVerdict);
const mockGetDiscovery = vi.mocked(getDiscovery);
const mockGetArtifacts = vi.mocked(getArtifacts);
const mockDownload = vi.mocked(downloadGenerated);

function runResponse(stage: string, error: string | null = null) {
  return {
    id: 'run-1',
    application_id: 'app-1',
    workload_id: 'wl-demo',
    stage,
    // Fresh timestamp: the long-running notice keys off server age, so the
    // default fixture must not look stale.
    created_at: new Date().toISOString(),
    completed_at: null,
    error,
  };
}

function discoveryResponse() {
  return {
    application_id: 'app-1',
    cobol_programs: [
      {
        program_id: 'PAYROLL',
        source_path: 'src/PAYROLL.cob',
        file_dependencies: [{ name: 'TRANS.DAT', operation: 'READ', mode: 'INPUT' }],
        calls: [{ target: 'TAXCALC', arguments: [] }],
        copybooks: ['COMMON'],
        entry_points: ['MAIN'],
      },
    ],
    copybooks: ['COMMON'],
    jcl_jobs: [
      { name: 'NIGHTLY', steps: [{ name: 'STEP1', program: 'PAYROLL', procedure: null }] },
    ],
    file_dependencies: [{ program_id: 'PAYROLL', file_name: 'TRANS.DAT', operation: 'READ' }],
    call_dependencies: [{ caller: 'PAYROLL', target: 'TAXCALC' }],
    dependency_edges: [{ source: 'PAYROLL', target: 'TAXCALC', edge_type: 'CALL' }],
    source_file_count: 3,
    total_size_bytes: 1024,
  };
}

function verdictResponse(state: string) {
  return {
    run_id: 'run-1',
    state,
    workload_id: 'wl-demo',
    source_hash: 'sha256:abc',
    candidate_hash: 'sha256:def',
    oracle_id: 'gnucobol-3.1.2',
    oracle_digest: 'sha256:ghi',
    executed_check_count: 2,
    skipped_count: 0,
    unavailable_count: 0,
    supported_scope_statement: 'scope',
    evidence_manifest_hash: 'sha256:jkl',
    derivation_timestamp: '2024-01-01T00:00:00Z',
    differences: [],
    comparisons: [],
  };
}

function runDetailResponse() {
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
    generated_files: ['src/main/java/app/Payroll.java', 'pom.xml'],
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockGetRun.mockReset();
  mockGetRunDetail.mockReset();
  mockGetVerdict.mockReset();
  mockGetDiscovery.mockReset();
  mockGetArtifacts.mockReset();
  mockDownload.mockReset();
  mockGetRunDetail.mockRejectedValue(new Error('detail unavailable'));
  mockGetVerdict.mockResolvedValue(verdictResponse('VERIFIED') as never);
  mockGetArtifacts.mockResolvedValue({ run_id: 'run-1', artifacts: [] } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ModernizationRun stage order', () => {
  it('renders EXECUTING_ORACLE before BUILDING (backend order)', async () => {
    mockGetRun.mockResolvedValue(runResponse('TRANSFORMING') as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Transforming')).toBeInTheDocument());

    const progress = screen.getByText('Progress').closest('div')!.parentElement!;
    const text = progress.textContent ?? '';
    expect(text.indexOf('Executing Oracle')).toBeLessThan(text.indexOf('Building'));
  });

  it('never renders INGESTING as a run stage', async () => {
    mockGetRun.mockResolvedValue(runResponse('DISCOVERING') as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);
    await waitFor(() => expect(screen.getByText('Discovering')).toBeInTheDocument());

    expect(screen.queryByText('Ingesting')).not.toBeInTheDocument();
  });

  it('renders the ingest summary as a completed pre-run step when provided', async () => {
    mockGetRun.mockResolvedValue(runResponse('CREATED') as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(
      <ModernizationRun
        runId="run-1"
        applicationId="app-1"
        ingest={{ applicationId: 'app-1', sourceFileCount: 5, detectedName: 'payroll' }}
      />,
    );

    await waitFor(() => expect(screen.getByText('Source Ingestion')).toBeInTheDocument());
    expect(screen.getByText(/5 source files ingested/)).toBeInTheDocument();
    expect(screen.getByText(/detected name: payroll/)).toBeInTheDocument();
  });

  it('omits the ingestion section when no summary was provided (no fabrication)', async () => {
    mockGetRun.mockResolvedValue(runResponse('CREATED') as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);
    await waitFor(() => expect(screen.getByText('Created')).toBeInTheDocument());

    expect(screen.queryByText('Source Ingestion')).not.toBeInTheDocument();
  });
});

describe('ModernizationRun discovery', () => {
  it('shows programs, copybooks, CALLs, dependencies and JCL whenever provided', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Discovery Results')).toBeInTheDocument());
    // Program/JCL/edge rows repeat names — assert presence, not uniqueness.
    expect(screen.getAllByText('PAYROLL').length).toBeGreaterThan(0);
    expect(screen.getByText('COMMON')).toBeInTheDocument();
    expect(screen.getAllByText(/TAXCALC/).length).toBeGreaterThan(0);
    expect(screen.getByText('NIGHTLY')).toBeInTheDocument();
    expect(screen.getByText(/TRANS\.DAT \(READ\)/)).toBeInTheDocument();
  });

  it('shows discovery on FAILED runs with terminal explanation', async () => {
    mockGetRun.mockResolvedValue(runResponse('FAILED', 'Maven build failed') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Discovery Results')).toBeInTheDocument());
    expect(screen.getAllByText('PAYROLL').length).toBeGreaterThan(0);
    expect(screen.getByText('Maven build failed')).toBeInTheDocument();
    expect(screen.getByText(/Run ID: run-1/)).toBeInTheDocument();
    // No download on failure — only the generated artifact may be served.
    expect(
      screen.queryByText('Download Generated Spring Boot Application'),
    ).not.toBeInTheDocument();
  });
});

describe('ModernizationRun polling failures', () => {
  it('shows a visible interruption warning with retry after repeated failures', async () => {
    mockGetRun.mockResolvedValueOnce(runResponse('TRANSFORMING') as never);
    mockGetRun.mockRejectedValue(new Error('network down'));
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" pollIntervalMs={50} />);
    expect(await screen.findByText('Transforming')).toBeInTheDocument();

    expect(await screen.findByText('Live updates interrupted')).toBeInTheDocument();
    expect(screen.getByText(/network down/)).toBeInTheDocument();
    expect(screen.getByText(/Run ID: run-1/)).toBeInTheDocument();
  });

  it('retry re-polls immediately', async () => {
    mockGetRun.mockResolvedValueOnce(runResponse('TRANSFORMING') as never);
    mockGetRun.mockRejectedValue(new Error('network down'));
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" pollIntervalMs={50} />);
    await screen.findByText('Live updates interrupted');

    const callsBefore = mockGetRun.mock.calls.length;
    mockGetRun.mockResolvedValueOnce(runResponse('GENERATING') as never);
    fireEvent.click(screen.getByText('Retry now'));

    await waitFor(() =>
      expect(mockGetRun.mock.calls.length).toBeGreaterThan(callsBefore),
    );
    expect(await screen.findByText('Generating')).toBeInTheDocument();
  });

  it('initial load failure shows run context with retry', async () => {
    mockGetRun.mockRejectedValue(new Error('connection refused'));
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-9" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Could not load run')).toBeInTheDocument());
    expect(screen.getByText(/connection refused/)).toBeInTheDocument();
    expect(screen.getByText(/Run ID: run-9/)).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });
});

describe('ModernizationRun artifacts', () => {
  it('renders the evidence artifacts table when the backend returns artifacts', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);
    mockGetArtifacts.mockResolvedValue({
      run_id: 'run-1',
      artifacts: [
        {
          artifact_id: 'a1',
          artifact_type: 'STDOUT',
          logical_name: 'stdout',
          producer_role: 'ORACLE',
          content_hash: 'sha256:0123456789abcdef0123456789abcdef',
          size_bytes: 42,
          record_count: null,
        },
      ],
    } as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText(/Evidence Artifacts/)).toBeInTheDocument());
    expect(screen.getByText('stdout')).toBeInTheDocument();
    expect(screen.getByText('ORACLE')).toBeInTheDocument();
  });

  it('omits the artifacts section when the backend returns none', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);
    mockGetArtifacts.mockResolvedValue({ run_id: 'run-1', artifacts: [] } as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Discovery Results')).toBeInTheDocument());
    expect(screen.queryByText(/Evidence Artifacts/)).not.toBeInTheDocument();
  });
});

describe('ModernizationRun download', () => {
  it('offers the canonical generated-application download on COMPLETED', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() =>
      expect(
        screen.getByText('Download Generated Spring Boot Application'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/java candidate/i)).not.toBeInTheDocument();
  });

  it('downloads the blob with a generated filename', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);
    const blob = new Blob(['zip'], { type: 'application/zip' });
    mockDownload.mockResolvedValue(blob);

    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(window.URL, 'createObjectURL', {
      value: createObjectURL,
      configurable: true,
    });
    Object.defineProperty(window.URL, 'revokeObjectURL', {
      value: revokeObjectURL,
      configurable: true,
    });

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);
    const btn = await screen.findByText('Download Generated Spring Boot Application');
    fireEvent.click(btn);

    await waitFor(() => expect(mockDownload).toHaveBeenCalledWith('run-1'));
    expect(createObjectURL).toHaveBeenCalledWith(blob);
  });
});

describe('VerdictDisplay — all seven states (render only, no rules)', () => {
  const states = [
    'VERIFIED',
    'PARTIAL',
    'FAILED',
    'UNPROVEN',
    'UNAVAILABLE',
    'UNSUPPORTED',
    'ERROR',
  ] as const;

  it.each(states)('renders the %s verdict', (state) => {
    render(<VerdictDisplay verdict={verdictResponse(state) as never} />);
    expect(screen.getByRole('status', { name: `Verdict: ${state}` })).toBeInTheDocument();
  });

  it('renders comparisons and differences without interpreting them', () => {
    const v = {
      ...verdictResponse('FAILED'),
      differences: ['stdout differs at line 1'],
      comparisons: [
        {
          comparison_id: 'c1',
          comparator_id: 'stdout-exact',
          artifact_type: 'STDOUT',
          result: 'MISMATCH',
          differences: [],
        },
      ],
    };
    render(<VerdictDisplay verdict={v as never} />);
    expect(screen.getByText('stdout differs at line 1')).toBeInTheDocument();
    expect(screen.getByText('MISMATCH')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Artifact comparison results' });
    expect(within(table).getByText('STDOUT')).toBeInTheDocument();
  });
});

describe('ModernizationRun run detail (GET /runs/{id}/detail)', () => {
  it('renders application name, verdict state and generated files when available', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetRunDetail.mockResolvedValue(runDetailResponse() as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Run Details')).toBeInTheDocument());
    // Title prefers the detail application name, which repeats in the panel.
    expect(screen.getAllByText('payroll-app').length).toBeGreaterThan(0);
    // The detail badge repeats the full verdict panel state (render-only).
    expect(screen.getAllByText('VERIFIED').length).toBeGreaterThan(0);
    expect(screen.getByText('src/main/java/app/Payroll.java')).toBeInTheDocument();
    expect(screen.getByText('pom.xml')).toBeInTheDocument();
  });

  it('works without run detail (endpoint unavailable)', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetRunDetail.mockRejectedValue(new Error('404'));
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Discovery Results')).toBeInTheDocument());
    expect(screen.queryByText('Run Details')).not.toBeInTheDocument();
  });
});

describe('ModernizationRun discovery timing', () => {
  it('shows discovery before the terminal state', async () => {
    mockGetRun.mockResolvedValue(runResponse('TRANSFORMING') as never);
    mockGetDiscovery.mockResolvedValue(discoveryResponse() as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Discovery Results')).toBeInTheDocument());
    expect(screen.getByText('Transforming')).toBeInTheDocument();
  });

  it('shows CALL and COPY edge counts from backend edges', async () => {
    mockGetRun.mockResolvedValue(runResponse('COMPLETED') as never);
    mockGetDiscovery.mockResolvedValue({
      ...discoveryResponse(),
      dependency_edges: [
        { source: 'PAYROLL', target: 'TAXCALC', edge_type: 'CALL' },
        { source: 'PAYROLL', target: 'COMMON', edge_type: 'COPY' },
        { source: 'PAYROLL', target: 'TRANS.DAT', edge_type: 'FILE_READ' },
      ],
    } as never);

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('CALL Edges')).toBeInTheDocument());
    expect(screen.getByText('COPY Edges')).toBeInTheDocument();
  });

  it('flags long-running non-terminal runs without changing polling', async () => {
    mockGetRun.mockResolvedValue({
      ...runResponse('BUILDING'),
      created_at: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
    } as never);
    mockGetDiscovery.mockRejectedValue(new Error('not yet'));

    render(<ModernizationRun runId="run-1" applicationId="app-1" />);

    await waitFor(() => expect(screen.getByText('Still running')).toBeInTheDocument());
    expect(screen.getByText('Building')).toBeInTheDocument();
  });
});
