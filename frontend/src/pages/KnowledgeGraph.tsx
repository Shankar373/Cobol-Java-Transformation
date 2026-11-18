import React, { useCallback, useEffect, useState } from 'react';
import { tokens } from '../theme/tokens';
import { Badge, Button, EmptyState, Header, HeaderMetaItem, PageContainer, SectionCard } from '../components';
import * as api from '../api/client';
import type { KgExportFormat, KgNode, KgSliceDocument, KgSnapshot } from '../api/client';
import { GraphView } from '../components/kg/GraphView';
import { NodeDetail } from '../components/kg/NodeDetail';
import { BlockingPanel, DiffPanel, ImpactPanel, PathPanel, SlicePanel } from '../components/kg/AnalysisPanels';
import { ErrorLine, Field, inputStyle, kgError, mono } from '../components/kg/shared';

export const NODE_PAGE_SIZE = 50;
const TABS = ['nodes', 'blocking', 'impact', 'path', 'slice', 'diff'] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  nodes: 'Nodes',
  blocking: 'Unresolved',
  impact: 'Impact',
  path: 'Path',
  slice: 'Slice',
  diff: 'Diff',
};

interface KnowledgeGraphProps {
  runId: string | null;
  onNavigate?: (page: string, id?: string) => void;
}

function SnapshotHeader({ snap }: { snap: KgSnapshot }) {
  const rows: [string, string][] = [
    ['Graph id', snap.graph_id],
    ['Checkpoint', snap.checkpoint_id],
    ['Schema', snap.schema_version],
    ['Application', snap.application],
    ['Source digest', snap.source_digest],
    ['Parent graph', snap.parent_graph_id],
    ['Created', snap.created_at],
  ];
  return (
    <SectionCard title="Snapshot">
      <div style={{ padding: 12 }} data-testid="kg-snapshot">
        <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '4px 16px', margin: 0, fontSize: tokens.font.sizes.sm }}>
          {rows.filter(([, v]) => v).map(([k, v]) => (
            <React.Fragment key={k}>
              <dt style={{ color: tokens.colors.textSecondary }}>{k}</dt>
              <dd style={{ margin: 0, ...mono }}>{v}</dd>
            </React.Fragment>
          ))}
        </dl>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
          <Badge variant="info">{snap.counts.nodes} nodes</Badge>
          <Badge variant="info">{snap.counts.edges} edges</Badge>
          <Badge variant={snap.counts.unresolved ? 'warning' : 'success'}>{snap.counts.unresolved} unresolved</Badge>
          <Badge variant={snap.counts.blocking ? 'error' : 'success'}>{snap.counts.blocking} blocking</Badge>
        </div>
      </div>
    </SectionCard>
  );
}

function NodeList({ runId, selected, onSelect }: { runId: string; selected: string; onSelect: (id: string) => void }) {
  const [kindInput, setKindInput] = useState('');
  const [kind, setKind] = useState('');
  const [offset, setOffset] = useState(0);
  const [nodes, setNodes] = useState<KgNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setNodes(null);
    setError(null);
    api
      .getKgNodes(runId, { kind: kind || undefined, limit: NODE_PAGE_SIZE, offset })
      .then((page) => live && setNodes(page.nodes))
      .catch((err) => live && setError(kgError(err, 'Could not load nodes')));
    return () => {
      live = false;
    };
  }, [runId, kind, offset]);

  const applyKind = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setKind(kindInput.trim());
  };

  return (
    <SectionCard title="Nodes" count={nodes?.length}>
      <div style={{ padding: 12, display: 'grid', gap: 12 }}>
        <form onSubmit={applyKind} style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <Field label="Filter by kind (e.g. program, copybook)">
            <input value={kindInput} onChange={(e) => setKindInput(e.target.value)} style={inputStyle} />
          </Field>
          <Button type="submit" variant="secondary">Apply filter</Button>
        </form>
        <ErrorLine message={error} />
        {!nodes && !error && <div role="status">Loading nodes...</div>}
        {nodes && nodes.length === 0 && (
          <EmptyState title={offset > 0 ? 'No more nodes' : 'No nodes'} description={kind ? `No nodes of kind "${kind}" in this snapshot.` : 'This snapshot has no nodes.'} />
        )}
        {nodes && nodes.length > 0 && (
          <ul aria-label="Node list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {nodes.map((n) => (
              <li key={n.id} style={{ borderBottom: `1px solid ${tokens.colors.divider}`, padding: '4px 0', display: 'flex', gap: 8, alignItems: 'center' }}>
                <Badge size="sm">{n.kind}</Badge>
                <button
                  type="button"
                  aria-pressed={n.id === selected}
                  onClick={() => onSelect(n.id)}
                  style={{ ...mono, background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left', color: n.id === selected ? tokens.colors.primary : tokens.colors.textPrimary, fontWeight: n.id === selected ? 600 : 400 }}
                >
                  {n.id}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button type="button" variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - NODE_PAGE_SIZE))}>Previous</Button>
          <Button type="button" variant="secondary" size="sm" disabled={!nodes || nodes.length < NODE_PAGE_SIZE} onClick={() => setOffset(offset + NODE_PAGE_SIZE)}>Next</Button>
          <span style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
            rows {offset + 1}-{offset + (nodes?.length ?? 0)}
          </span>
        </div>
      </div>
    </SectionCard>
  );
}

function Neighbourhood({ runId, node, onSelect }: { runId: string; node: string; onSelect: (id: string) => void }) {
  const [slice, setSlice] = useState<KgSliceDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setSlice(null);
    setError(null);
    api
      .getKgSlice(runId, node, 1)
      .then((s) => live && setSlice(s))
      .catch((err) => live && setError(kgError(err, 'Could not load the neighbourhood')));
    return () => {
      live = false;
    };
  }, [runId, node]);
  return (
    <SectionCard title="Neighbourhood" subtitle="Selected node and its direct neighbours">
      <div style={{ padding: 12 }}>
        <ErrorLine message={error} />
        {!slice && !error && <div role="status">Loading neighbourhood...</div>}
        {slice && <GraphView title={`Neighbourhood of ${node}`} nodes={slice.nodes} edges={slice.edges} centre={node} selected={node} onSelect={onSelect} />}
      </div>
    </SectionCard>
  );
}

function ExportButtons({ runId }: { runId: string }) {
  const [error, setError] = useState<string | null>(null);
  const download = async (format: KgExportFormat) => {
    setError(null);
    try {
      const blob = await api.downloadKgExport(runId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = api.KG_EXPORT_FILES[format];
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(kgError(err, `Export ${format} failed`));
    }
  };
  return (
    <SectionCard title="Export">
      <div style={{ padding: 12, display: 'grid', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {api.KG_EXPORT_FORMATS.map((f) => (
            <Button key={f} type="button" variant="secondary" onClick={() => download(f)}>
              Export {f.toUpperCase()}
            </Button>
          ))}
        </div>
        <ErrorLine message={error} />
      </div>
    </SectionCard>
  );
}

export function KnowledgeGraph({ runId, onNavigate }: KnowledgeGraphProps) {
  const [snapshot, setSnapshot] = useState<KgSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('nodes');
  const [selected, setSelected] = useState('');

  useEffect(() => {
    if (!runId) return;
    let live = true;
    setSnapshot(null);
    setError(null);
    setSelected('');
    api
      .getKgSnapshot(runId)
      .then((s) => live && setSnapshot(s))
      .catch((err) => live && setError(kgError(err, 'Could not load the knowledge graph')));
    return () => {
      live = false;
    };
  }, [runId]);

  const select = useCallback((id: string) => setSelected(id), []);
  const back = () => onNavigate?.('discovery');

  const header = (
    <Header
      breadcrumb={[{ label: 'Estate Discovery', onClick: back }, { label: 'Knowledge graph' }]}
      title="Knowledge graph"
      meta={runId ? <HeaderMetaItem label="Run" value={runId} /> : undefined}
    />
  );

  if (!runId) {
    return (
      <>
        {header}
        <PageContainer>
          <EmptyState
            title="No discovery run selected"
            description="Open a finished discovery run and choose Open knowledge graph."
            action={<Button type="button" onClick={back}>Back to discovery</Button>}
          />
        </PageContainer>
      </>
    );
  }

  return (
    <>
      {header}
      <PageContainer>
        <div style={{ display: 'grid', gap: tokens.spacing.md }}>
          <ErrorLine message={error} />
          {!snapshot && !error && <div role="status">Loading knowledge graph...</div>}
          {snapshot && snapshot.counts.nodes === 0 && (
            <EmptyState title="Empty graph" description="This snapshot contains no nodes." />
          )}
          {snapshot && snapshot.counts.nodes > 0 && (
            <>
              <SnapshotHeader snap={snapshot} />
              <ExportButtons runId={runId} />
              <div role="tablist" aria-label="Knowledge graph views" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {TABS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="tab"
                    aria-selected={tab === t}
                    onClick={() => setTab(t)}
                    style={{
                      padding: '8px 16px',
                      border: `1px solid ${tokens.colors.divider}`,
                      borderRadius: tokens.radii.sm,
                      cursor: 'pointer',
                      background: tab === t ? tokens.colors.primary : tokens.colors.cardBg,
                      color: tab === t ? tokens.colors.textOnPrimary : tokens.colors.textPrimary,
                      fontWeight: tokens.font.weights.semibold,
                    }}
                  >
                    {TAB_LABEL[t]}
                  </button>
                ))}
              </div>
              <div role="tabpanel" aria-label={TAB_LABEL[tab]}>
                {tab === 'nodes' && <NodeList runId={runId} selected={selected} onSelect={select} />}
                {tab === 'blocking' && <BlockingPanel runId={runId} onSelect={select} />}
                {tab === 'impact' && <ImpactPanel runId={runId} selected={selected} onSelect={select} />}
                {tab === 'path' && <PathPanel runId={runId} selected={selected} onSelect={select} />}
                {tab === 'slice' && <SlicePanel runId={runId} selected={selected} onSelect={select} />}
                {tab === 'diff' && <DiffPanel runId={runId} />}
              </div>
              {selected && <NodeDetail runId={runId} nodeId={selected} onOpen={select} />}
              {selected && <Neighbourhood runId={runId} node={selected} onSelect={select} />}
            </>
          )}
        </div>
      </PageContainer>
    </>
  );
}
