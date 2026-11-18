import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';
import { KnowledgeGraph } from '../pages/KnowledgeGraph';
import { layoutGraph, formatSource, groupByKind, MAX_DRAWN_NODES } from '../components/kg/layout';

const RUN = 'b'.repeat(32);
const EVIL = 'program:<img src=x onerror=alert(1)>';

const SNAPSHOT = {
  graph_id: 'KG-abc', schema_version: 'systemaops.kg/1.0', checkpoint_id: 'CP-123', source_digest: 'deadbeef',
  parent_graph_id: '', application: 'payroll', created_at: '2026-01-01T00:00:00Z',
  node_count: 3, edge_count: 2, unresolved_count: 1, blocking_count: 1,
  counts: { nodes: 3, edges: 2, unresolved: 1, blocking: 1 },
};
const NODES = [
  { id: 'program:PAYROLL', kind: 'program', origin: 'scan', path: 'src/PAYROLL.cbl' },
  { id: 'copybook:EMPREC', kind: 'copybook', origin: 'scan' },
  { id: EVIL, kind: 'program', origin: 'scan' },
];

type Handler = (url: string) => unknown | Response;

function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const out = handler(String(input));
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out), { status: 200, headers: { 'content-type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function err(status: number, detail: string) {
  return new Response(JSON.stringify({ detail }), { status, headers: { 'content-type': 'application/json' } });
}

const DETAIL = {
  graph_id: 'KG-abc', node: NODES[0],
  outgoing: [{ src: 'program:PAYROLL', dst: 'copybook:EMPREC', relation: 'copies', rule: 'copy-statement', confidence: 'exact', mode: 'static', file: 'src/PAYROLL.cbl', line: 12, column: 8 }],
  incoming: [],
};

function base(url: string): unknown | Response {
  if (url.includes('/kg/nodes')) return { graph_id: 'KG-abc', count: NODES.length, nodes: NODES };
  if (url.includes('/kg/node?')) return DETAIL;
  if (url.includes('/kg/slice')) {
    return { schema_version: 's', header: { graph_id: 'KG-s' }, nodes: NODES, edges: [{ from: 'program:PAYROLL', to: 'copybook:EMPREC', relation: 'copies' }], unresolved: [] };
  }
  if (url.includes('/kg/impact')) return { graph_id: 'KG-abc', node: 'copybook:EMPREC', direction: 'in', depth: null, count: 2, impact: ['program:PAYROLL', 'job:RUN1'] };
  if (url.includes('/kg/path')) return { graph_id: 'KG-abc', src: 'a', dst: 'b', direction: 'both', found: true, path: ['program:PAYROLL', 'copybook:EMPREC'] };
  if (url.includes('/kg/diff')) return { graph_id: 'KG-abc', against: 'KG-old', nodes: { added: ['program:NEW'], removed: [], changed: [] }, edges: { added: [], removed: [], changed: ['e1'] } };
  if (url.includes('/kg/export')) {
    return { schema_version: 's', header: { graph_id: 'KG-abc' }, nodes: NODES, edges: [], unresolved: [
      { from: 'program:PAYROLL', to: 'program:MISSING', relation: 'calls', reason: 'missing-program', blocking: true, file: 'src/PAYROLL.cbl', line: 30, column: 5 },
    ] };
  }
  if (url.endsWith('/kg')) return SNAPSHOT;
  return err(404, 'nope');
}

beforeEach(() => {
  mockFetch(base);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('KnowledgeGraph page', () => {
  it('shows an empty state when no run is selected', () => {
    render(<KnowledgeGraph runId={null} />);
    expect(screen.getByText('No discovery run selected')).toBeTruthy();
  });

  it('renders snapshot identity and node list', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    const snap = await screen.findByTestId('kg-snapshot');
    expect(snap.textContent).toContain('KG-abc');
    expect(snap.textContent).toContain('CP-123');
    expect(await screen.findByText('program:PAYROLL')).toBeTruthy();
    expect(screen.getByText('3 nodes')).toBeTruthy();
  });

  it('shows an error state when the snapshot fails', async () => {
    mockFetch(() => err(404, 'Discovery run not found or not finished'));
    render(<KnowledgeGraph runId={RUN} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Discovery run not found');
  });

  it('shows an empty-graph state', async () => {
    mockFetch((u) => (u.endsWith('/kg') ? { ...SNAPSHOT, counts: { nodes: 0, edges: 0, unresolved: 0, blocking: 0 } } : base(u)));
    render(<KnowledgeGraph runId={RUN} />);
    expect(await screen.findByText('Empty graph')).toBeTruthy();
  });

  it('filters nodes by kind through the API', async () => {
    const fn = mockFetch(base);
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByText('program:PAYROLL');
    fireEvent.change(screen.getByLabelText(/Filter by kind/), { target: { value: 'copybook' } });
    fireEvent.click(screen.getByText('Apply filter'));
    await waitFor(() => expect(fn.mock.calls.some((c) => String(c[0]).includes('kind=copybook'))).toBe(true));
  });

  it('shows edge rule, confidence, mode and file:line:column traceability for a node', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    fireEvent.click(await screen.findByRole('button', { name: 'program:PAYROLL' }));
    const detail = await screen.findByTestId('kg-node-detail');
    await waitFor(() => expect(detail.textContent).toContain('src/PAYROLL.cbl:12:8'));
    expect(detail.textContent).toContain('copy-statement');
    expect(detail.textContent).toContain('exact');
    expect(detail.textContent).toContain('static');
  });

  it('lists blocking unresolved dependencies with reasons', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByRole('tab', { name: 'Unresolved' }));
    expect(await screen.findByText('missing-program')).toBeTruthy();
    expect(screen.getByText('blocking')).toBeTruthy();
    expect(screen.getByText('src/PAYROLL.cbl:30:5')).toBeTruthy();
  });

  it('groups impact results by kind', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByRole('tab', { name: 'Impact' }));
    fireEvent.change(screen.getByLabelText('Node'), { target: { value: 'copybook:EMPREC' } });
    fireEvent.click(screen.getByText('Run impact'));
    const result = await screen.findByTestId('kg-impact-result');
    expect(within(result).getByRole('region', { name: 'program nodes' })).toBeTruthy();
    expect(within(result).getByRole('region', { name: 'job nodes' })).toBeTruthy();
  });

  it('rejects an out-of-range depth before calling the API', async () => {
    const fn = mockFetch(base);
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByRole('tab', { name: 'Impact' }));
    fireEvent.change(screen.getByLabelText('Node'), { target: { value: 'x' } });
    fireEvent.change(screen.getByLabelText(/Depth/), { target: { value: '999999' } });
    fireEvent.click(screen.getByText('Run impact'));
    expect((await screen.findByRole('alert')).textContent).toContain('Depth must be');
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/kg/impact'))).toBe(false);
  });

  it('finds a path and reports no path', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByRole('tab', { name: 'Path' }));
    fireEvent.change(screen.getByLabelText('From node'), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText('To node'), { target: { value: 'b' } });
    fireEvent.click(screen.getByText('Find path'));
    expect(await screen.findByTestId('kg-path-result')).toBeTruthy();
    mockFetch((u) => (u.includes('/kg/path') ? { graph_id: 'x', src: 'a', dst: 'b', direction: 'both', found: false, path: [] } : base(u)));
    fireEvent.click(screen.getByText('Find path'));
    expect(await screen.findByTestId('kg-path-none')).toBeTruthy();
  });

  it('renders a diff and an informative notice when there is no earlier snapshot', async () => {
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByRole('tab', { name: 'Diff' }));
    fireEvent.click(screen.getByText('Compare'));
    const diff = await screen.findByTestId('kg-diff-result');
    expect(diff.textContent).toContain('program:NEW');
    mockFetch((u) => (u.includes('/kg/diff') ? err(400, 'there is no earlier snapshot to compare against') : base(u)));
    fireEvent.click(screen.getByText('Compare'));
    expect((await screen.findByTestId('kg-diff-notice')).textContent).toContain('no earlier snapshot');
  });

  it('downloads each export format through an authenticated fetch', async () => {
    const fn = mockFetch((u) => (u.includes('format=dot') ? new Response('digraph {}', { status: 200 }) : base(u)));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }));
    render(<KnowledgeGraph runId={RUN} />);
    await screen.findByTestId('kg-snapshot');
    fireEvent.click(screen.getByText('Export DOT'));
    await waitFor(() => expect(fn.mock.calls.some((c) => String(c[0]).includes('format=dot'))).toBe(true));
    for (const f of ['JSON', 'DOT', 'GRAPHML', 'CSV']) expect(screen.getByText(`Export ${f}`)).toBeTruthy();
  });

  it('never injects node ids as HTML and supports keyboard selection in the graph view', async () => {
    const { container } = render(<KnowledgeGraph runId={RUN} />);
    fireEvent.click(await screen.findByRole('button', { name: 'program:PAYROLL' }));
    const view = await screen.findByTestId('kg-graph-view');
    expect(container.querySelector('img')).toBeNull();
    expect(view.textContent).toContain('program:<img');
    const node = view.querySelector('[data-node-id="copybook:EMPREC"]') as SVGGElement;
    expect(node.getAttribute('tabindex')).toBe('0');
    fireEvent.keyDown(node, { key: 'Enter' });
    await waitFor(() => expect(screen.getAllByText('copybook:EMPREC').length).toBeGreaterThan(0));
  });
});

describe('kg layout helpers', () => {
  const mk = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `n:${String(i).padStart(3, '0')}`, kind: 'n', origin: 'x' }));

  it('is deterministic regardless of input order and caps the node count', () => {
    const nodes = mk(100);
    const a = layoutGraph(nodes, [], undefined);
    const b = layoutGraph([...nodes].reverse(), [], undefined);
    expect(a.nodes.map((n) => [n.node.id, n.x, n.y])).toEqual(b.nodes.map((n) => [n.node.id, n.x, n.y]));
    expect(a.nodes.length).toBe(MAX_DRAWN_NODES);
    expect(a.hiddenNodes).toBe(40);
  });

  it('keeps the centre node centred and skips edges with undrawn endpoints', () => {
    const nodes = mk(3);
    const out = layoutGraph(nodes, [{ from: 'n:000', to: 'n:001', relation: 'r' }, { from: 'n:000', to: 'ghost', relation: 'r' }], 'n:001');
    expect(out.nodes[0].node.id).toBe('n:001');
    expect(out.nodes[0].x).toBe(320);
    expect(out.edges.length).toBe(1);
  });

  it('formats file:line:column and groups by kind prefix', () => {
    expect(formatSource({ file: 'a.cbl', line: 3, column: 7 })).toBe('a.cbl:3:7');
    expect(formatSource({ file: 'a.cbl' })).toBe('a.cbl');
    expect(formatSource({})).toBe('');
    expect(groupByKind(['b:2', 'a:1', 'b:1'])).toEqual([['a', ['a:1']], ['b', ['b:1', 'b:2']]]);
  });
});
