import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, getEstate: vi.fn() };
});

import { EstatePanel } from '../components/EstatePanel';
import * as api from '../api/client';

const ESTATE: api.EstateResponse = {
  application_id: 'app-1',
  summary: {
    node_count: 5,
    edge_count: 3,
    nodes_by_kind: { PROGRAM: 2 },
    edges_by_relation: { CALLS: 3 },
    edges_by_proof_state: { PROVEN: 1, PARTIAL: 1, BLOCKED: 1, UNPROVEN: 0 },
    proven_edge_percent: 33.3,
    blocked_edges: ['PROGRAM:A -[CALLS]-> EXTERNAL_PROGRAM:X'],
  },
  nodes: [],
  edges: [
    { source: 'PROGRAM:A', target: 'PROGRAM:B', relation: 'CALLS', proof_state: 'PROVEN', evidence: 'static call' },
    { source: 'STEP:J.S', target: 'UTILITY:IEFBR14', relation: 'EXECUTES', proof_state: 'PARTIAL', evidence: 'no IBM/JES oracle' },
    { source: 'PROGRAM:A', target: 'EXTERNAL_PROGRAM:X', relation: 'CALLS', proof_state: 'BLOCKED', evidence: 'not in the upload' },
  ],
  discovery_errors: [],
};

beforeEach(() => {
  vi.clearAllMocks();
});

// Roadmap unit 17: a read-only, on-demand estate view with a proof state on every edge.
describe('estate panel', () => {
  it('loads nothing until asked, then shows counts, the proof share and every edge', async () => {
    vi.mocked(api.getEstate).mockResolvedValue(ESTATE);
    render(<EstatePanel appId="app-1" />);
    expect(api.getEstate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /load estate view/i }));
    await waitFor(() => expect(screen.getByTestId('estate-proven-percent').textContent).toContain('33.3%'));
    expect(api.getEstate).toHaveBeenCalledWith('app-1');
    expect(screen.getByText('3 edges')).toBeTruthy();
    expect(screen.getAllByTestId('estate-edge')).toHaveLength(3);
  });

  it('filters the edges by proof state', async () => {
    vi.mocked(api.getEstate).mockResolvedValue(ESTATE);
    render(<EstatePanel appId="app-1" />);
    fireEvent.click(screen.getByRole('button', { name: /load estate view/i }));
    await waitFor(() => screen.getByLabelText('Proof state filter'));
    fireEvent.change(screen.getByLabelText('Proof state filter'), { target: { value: 'BLOCKED' } });
    const rows = screen.getAllByTestId('estate-edge');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('EXTERNAL_PROGRAM:X');
    fireEvent.change(screen.getByLabelText('Proof state filter'), { target: { value: 'UNPROVEN' } });
    expect(screen.getByText('No edges in this proof state.')).toBeTruthy();
  });

  it('says so when discovery was partial', async () => {
    vi.mocked(api.getEstate).mockResolvedValue({
      ...ESTATE,
      discovery_errors: [{ stage: 'JCL_DISCOVERY', message: 'boom' }],
    });
    render(<EstatePanel appId="app-1" />);
    fireEvent.click(screen.getByRole('button', { name: /load estate view/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('partial'));
  });

  it('shows the failure and offers the load again', async () => {
    vi.mocked(api.getEstate).mockRejectedValue(new api.ApiError(404, 'No source has been ingested'));
    render(<EstatePanel appId="app-1" />);
    fireEvent.click(screen.getByRole('button', { name: /load estate view/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('No source has been ingested'));
    expect(screen.getByRole('button', { name: /load estate view/i })).toBeTruthy();
  });
});
