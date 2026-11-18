import React, { useEffect, useState } from 'react';
import { tokens } from '../../theme/tokens';
import { Badge, Button, EmptyState, SectionCard } from '../index';
import * as api from '../../api/client';
import type { KgDiffResponse, KgEdge, KgImpactResponse, KgPathResponse, KgSliceDocument } from '../../api/client';
import { kgEdgeEndpoints } from '../../api/client';
import { GraphView } from './GraphView';
import { formatSource, groupByKind } from './layout';
import { ErrorLine, Field, inputStyle, kgError, mono } from './shared';

type Direction = 'in' | 'out' | 'both';
/** Server-side ceiling is enforced by the API; the UI keeps depth small and sane. */
export const MAX_UI_DEPTH = 50;

interface PanelProps {
  runId: string;
  selected: string;
  onSelect: (id: string) => void;
}

function DirectionSelect({ value, onChange }: { value: Direction; onChange: (d: Direction) => void }) {
  return (
    <Field label="Direction">
      <select value={value} onChange={(e) => onChange(e.target.value as Direction)} style={inputStyle}>
        <option value="in">in (who depends on it)</option>
        <option value="out">out (what it depends on)</option>
        <option value="both">both</option>
      </select>
    </Field>
  );
}

function NodeInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <Field label={label}>
      <input value={value} onChange={(e) => onChange(e.target.value)} style={{ ...inputStyle, ...mono, minWidth: 260 }} />
    </Field>
  );
}

function parseDepth(text: string): number | undefined | 'invalid' {
  const trimmed = text.trim();
  if (trimmed === '') return undefined;
  const n = Number(trimmed);
  if (!Number.isInteger(n) || n < 0 || n > MAX_UI_DEPTH) return 'invalid';
  return n;
}

function IdButton({ id, onSelect }: { id: string; onSelect: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onSelect(id)} style={{ ...mono, background: 'none', border: 'none', color: tokens.colors.primary, cursor: 'pointer', padding: '2px 0', textAlign: 'left' }}>
      {id}
    </button>
  );
}

export function ImpactPanel({ runId, selected, onSelect }: PanelProps) {
  const [node, setNode] = useState(selected);
  const [direction, setDirection] = useState<Direction>('in');
  const [depthText, setDepthText] = useState('');
  const [result, setResult] = useState<KgImpactResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setNode(selected), [selected]);

  const run = async () => {
    const depth = parseDepth(depthText);
    if (depth === 'invalid') return setError(`Depth must be a whole number from 0 to ${MAX_UI_DEPTH}, or empty for unlimited.`);
    if (!node.trim()) return setError('Pick or type a node id first.');
    setBusy(true);
    setError(null);
    try {
      setResult(await api.getKgImpact(runId, node.trim(), direction, depth));
    } catch (err) {
      setResult(null);
      setError(kgError(err, 'Impact query failed'));
    } finally {
      setBusy(false);
    }
  };

  const groups = result ? groupByKind(result.impact) : [];
  return (
    <SectionCard title="Impact explorer" subtitle="The transitive set a change to a node would reach">
      <div style={{ padding: 12, display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <NodeInput label="Node" value={node} onChange={setNode} />
          <DirectionSelect value={direction} onChange={setDirection} />
          <Field label="Depth (empty = unlimited)">
            <input value={depthText} onChange={(e) => setDepthText(e.target.value)} inputMode="numeric" style={{ ...inputStyle, width: 90 }} />
          </Field>
          <Button type="button" onClick={run} disabled={busy}>Run impact</Button>
        </div>
        <ErrorLine message={error} />
        {result && (
          <div data-testid="kg-impact-result">
            <div role="status" style={{ fontSize: tokens.font.sizes.sm, marginBottom: 8 }}>
              {result.count} node(s) in the {result.direction} impact set of <span style={mono}>{result.node}</span>
              {result.depth !== null ? ` within ${result.depth} hop(s)` : ' (unlimited depth)'}.
            </div>
            {groups.length === 0 && <EmptyState title="No impact" description="Nothing is reached from this node in that direction." />}
            {groups.map(([kind, ids]) => (
              <section key={kind} aria-label={`${kind} nodes`} style={{ marginBottom: 8 }}>
                <h4 style={{ margin: '4px 0', fontSize: tokens.font.sizes.base }}>{kind} <Badge size="sm">{ids.length}</Badge></h4>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {ids.map((id) => <li key={id}><IdButton id={id} onSelect={onSelect} /></li>)}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </SectionCard>
  );
}

export function PathPanel({ runId, selected, onSelect }: PanelProps) {
  const [src, setSrc] = useState(selected);
  const [dst, setDst] = useState('');
  const [direction, setDirection] = useState<Direction>('both');
  const [result, setResult] = useState<KgPathResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setSrc(selected), [selected]);

  const run = async () => {
    if (!src.trim() || !dst.trim()) return setError('Both a source and a target node id are required.');
    setBusy(true);
    setError(null);
    try {
      setResult(await api.getKgPath(runId, src.trim(), dst.trim(), direction));
    } catch (err) {
      setResult(null);
      setError(kgError(err, 'Path query failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard title="Path finder" subtitle="A shortest path between two nodes">
      <div style={{ padding: 12, display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <NodeInput label="From node" value={src} onChange={setSrc} />
          <NodeInput label="To node" value={dst} onChange={setDst} />
          <DirectionSelect value={direction} onChange={setDirection} />
          <Button type="button" onClick={run} disabled={busy}>Find path</Button>
        </div>
        <ErrorLine message={error} />
        {result && !result.found && <div role="status" data-testid="kg-path-none">No path exists between these nodes in that direction.</div>}
        {result && result.found && (
          <ol data-testid="kg-path-result" aria-label="Path" style={{ margin: 0, paddingLeft: 24 }}>
            {result.path.map((id, i) => <li key={`${i}:${id}`}><IdButton id={id} onSelect={onSelect} /></li>)}
          </ol>
        )}
      </div>
    </SectionCard>
  );
}

export function SlicePanel({ runId, selected, onSelect }: PanelProps) {
  const [node, setNode] = useState(selected);
  const [depthText, setDepthText] = useState('1');
  const [slice, setSlice] = useState<KgSliceDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setNode(selected), [selected]);

  const run = async () => {
    const depth = parseDepth(depthText);
    if (depth === 'invalid') return setError(`Depth must be a whole number from 0 to ${MAX_UI_DEPTH}, or empty for unlimited.`);
    if (!node.trim()) return setError('Pick or type a node id first.');
    setBusy(true);
    setError(null);
    try {
      setSlice(await api.getKgSlice(runId, node.trim(), depth));
    } catch (err) {
      setSlice(null);
      setError(kgError(err, 'Slice failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard title="Slice view" subtitle="The subgraph around a node">
      <div style={{ padding: 12, display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <NodeInput label="Centre node" value={node} onChange={setNode} />
          <Field label="Depth (empty = unlimited)">
            <input value={depthText} onChange={(e) => setDepthText(e.target.value)} inputMode="numeric" style={{ ...inputStyle, width: 90 }} />
          </Field>
          <Button type="button" onClick={run} disabled={busy}>Show slice</Button>
        </div>
        <ErrorLine message={error} />
        {slice && (
          <div data-testid="kg-slice-result">
            <div role="status" style={{ fontSize: tokens.font.sizes.sm, marginBottom: 8 }}>
              {slice.nodes.length} node(s), {slice.edges.length} edge(s), {slice.unresolved.length} unresolved in this slice.
            </div>
            <GraphView title={`Slice around ${node}`} nodes={slice.nodes} edges={slice.edges} centre={node.trim()} selected={node.trim()} onSelect={onSelect} />
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function DiffList({ title, side }: { title: string; side: { added: string[]; removed: string[]; changed: string[] } }) {
  return (
    <div>
      <h4 style={{ margin: '8px 0 4px' }}>{title}</h4>
      {(['added', 'removed', 'changed'] as const).map((bucket) => (
        <details key={bucket} open={side[bucket].length > 0 && side[bucket].length <= 25}>
          <summary>{bucket} ({side[bucket].length})</summary>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {side[bucket].map((id) => <li key={id} style={mono}>{id}</li>)}
          </ul>
        </details>
      ))}
    </div>
  );
}

export function DiffPanel({ runId }: { runId: string }) {
  const [against, setAgainst] = useState('');
  const [diff, setDiff] = useState<KgDiffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setDiff(await api.getKgDiff(runId, against));
    } catch (err) {
      setDiff(null);
      if (err instanceof api.ApiError && err.status === 400) {
        setNotice(`No comparison available: ${err.message}`);
      } else {
        setError(kgError(err, 'Diff failed'));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard title="Checkpoint diff" subtitle="Added, removed and changed versus another snapshot">
      <div style={{ padding: 12, display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <NodeInput label="Compare against graph id (empty = previous snapshot)" value={against} onChange={setAgainst} />
          <Button type="button" onClick={run} disabled={busy}>Compare</Button>
        </div>
        <ErrorLine message={error} />
        {notice && <div role="status" data-testid="kg-diff-notice">{notice}</div>}
        {diff && (
          <div data-testid="kg-diff-result">
            <div role="status" style={{ fontSize: tokens.font.sizes.sm }}>
              Comparing <span style={mono}>{diff.against}</span> to <span style={mono}>{diff.graph_id}</span>.
            </div>
            <DiffList title="Nodes" side={diff.nodes} />
            <DiffList title="Edges" side={diff.edges} />
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function BlockingRow({ edge, onSelect }: { edge: KgEdge; onSelect: (id: string) => void }) {
  const { src, dst } = kgEdgeEndpoints(edge);
  const source = formatSource(edge);
  const blocking = edge.blocking === true || edge.blocking === 1;
  return (
    <tr>
      <td style={{ padding: 6 }}>{blocking ? <Badge variant="error" size="sm">blocking</Badge> : <Badge variant="warning" size="sm">open</Badge>}</td>
      <td style={{ padding: 6 }}>{edge.reason || edge.resolution || ''}</td>
      <td style={{ padding: 6 }}>{src ? <IdButton id={src} onSelect={onSelect} /> : ''}</td>
      <td style={{ padding: 6 }}><span style={mono}>{dst}</span>{edge.candidates && edge.candidates.length > 0 ? <div style={{ fontSize: tokens.font.sizes.xs }}>candidates: {edge.candidates.join(', ')}</div> : null}</td>
      <td style={{ padding: 6 }}>{source ? <span style={mono}>{source}</span> : ''}</td>
    </tr>
  );
}

export function BlockingPanel({ runId, onSelect }: { runId: string; onSelect: (id: string) => void }) {
  const [edges, setEdges] = useState<KgEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getKgDocument(runId)
      .then((doc) => live && setEdges(doc.unresolved ?? []))
      .catch((err) => live && setError(kgError(err, 'Could not load unresolved dependencies')));
    return () => {
      live = false;
    };
  }, [runId]);

  const ordered = (edges ?? []).slice().sort((a, b) => Number(b.blocking === true || b.blocking === 1) - Number(a.blocking === true || a.blocking === 1));
  return (
    <SectionCard title="Unresolved and blocking dependencies" count={edges?.length}>
      <div style={{ padding: 12 }}>
        <ErrorLine message={error} />
        {!edges && !error && <div role="status">Loading unresolved dependencies...</div>}
        {edges && edges.length === 0 && <EmptyState title="Nothing unresolved" description="Every dependency in this snapshot resolved." />}
        {edges && edges.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: tokens.font.sizes.sm }}>
              <thead>
                <tr>{['Status', 'Reason', 'From', 'Wanted', 'Source (file:line:column)'].map((h) => <th key={h} scope="col" style={{ padding: 6, textAlign: 'left' }}>{h}</th>)}</tr>
              </thead>
              <tbody>{ordered.map((e, i) => <BlockingRow key={`${i}:${e.edge_id ?? ''}`} edge={e} onSelect={onSelect} />)}</tbody>
            </table>
          </div>
        )}
      </div>
    </SectionCard>
  );
}
