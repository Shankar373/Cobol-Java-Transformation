import React, { useEffect, useState } from 'react';
import { tokens } from '../../theme/tokens';
import { Badge, SectionCard } from '../index';
import * as api from '../../api/client';
import type { KgEdge, KgNodeDetail } from '../../api/client';
import { kgEdgeEndpoints } from '../../api/client';
import { formatSource } from './layout';
import { ErrorLine, kgError, mono } from './shared';

const cell: React.CSSProperties = { padding: '6px 8px', textAlign: 'left', verticalAlign: 'top', borderBottom: `1px solid ${tokens.colors.divider}` };

function isBlocking(edge: KgEdge): boolean {
  return edge.blocking === true || edge.blocking === 1;
}

/** One edge table; unknown rule/confidence/mode values are shown verbatim. */
export function EdgeTable({
  edges,
  side,
  onOpen,
  caption,
}: {
  edges: KgEdge[];
  side: 'out' | 'in';
  onOpen?: (id: string) => void;
  caption: string;
}) {
  if (edges.length === 0) {
    return <div style={{ padding: 12, fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>{caption}: none.</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: tokens.font.sizes.sm }}>
        <caption style={{ textAlign: 'left', padding: '8px', fontWeight: tokens.font.weights.semibold }}>{caption}</caption>
        <thead>
          <tr>
            {['Relation', side === 'out' ? 'To' : 'From', 'Rule', 'Confidence', 'Mode', 'Resolution', 'Source (file:line:column)'].map((h) => (
              <th key={h} scope="col" style={cell}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {edges.map((edge, i) => {
            const { src, dst } = kgEdgeEndpoints(edge);
            const other = side === 'out' ? dst : src;
            const source = formatSource(edge);
            return (
              <tr key={`${edge.edge_id ?? i}:${other}:${edge.relation}:${i}`}>
                <td style={cell}>{edge.relation}</td>
                <td style={cell}>
                  {other && onOpen ? (
                    <button type="button" onClick={() => onOpen(other)} style={{ ...mono, background: 'none', border: 'none', color: tokens.colors.primary, cursor: 'pointer', padding: 0, textAlign: 'left' }}>
                      {other}
                    </button>
                  ) : (
                    <span style={mono}>{other}</span>
                  )}
                </td>
                <td style={cell}>{edge.rule ?? ''}</td>
                <td style={cell}>{edge.confidence ?? ''}</td>
                <td style={cell}>{edge.mode ?? ''}</td>
                <td style={cell}>
                  {edge.resolution ?? ''}
                  {isBlocking(edge) && <> <Badge variant="error" size="sm">blocking</Badge></>}
                  {edge.reason ? <div style={{ color: tokens.colors.textSecondary }}>{edge.reason}</div> : null}
                </td>
                <td style={cell}>{source ? <span style={mono}>{source}</span> : <span style={{ color: tokens.colors.textMuted }}>no source recorded</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface NodeDetailProps {
  runId: string;
  nodeId: string;
  onOpen: (id: string) => void;
}

export function NodeDetail({ runId, nodeId, onOpen }: NodeDetailProps) {
  const [detail, setDetail] = useState<KgNodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setError(null);
    api
      .getKgNode(runId, nodeId)
      .then((d) => live && setDetail(d))
      .catch((err) => live && setError(kgError(err, 'Could not load the node')));
    return () => {
      live = false;
    };
  }, [runId, nodeId]);

  return (
    <SectionCard title="Node detail" subtitle={<span style={mono}>{nodeId}</span>}>
      <div style={{ padding: 12 }} data-testid="kg-node-detail">
        <ErrorLine message={error} />
        {!detail && !error && <div role="status">Loading node...</div>}
        {detail && (
          <>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
              <Badge variant="info">{detail.node.kind}</Badge>
              <span style={{ fontSize: tokens.font.sizes.sm }}>origin: {detail.node.origin}</span>
              {detail.node.path ? <span style={mono}>{detail.node.path}</span> : null}
            </div>
            <EdgeTable edges={detail.outgoing} side="out" onOpen={onOpen} caption={`Outgoing edges (${detail.outgoing.length})`} />
            <EdgeTable edges={detail.incoming} side="in" onOpen={onOpen} caption={`Incoming edges (${detail.incoming.length})`} />
          </>
        )}
      </div>
    </SectionCard>
  );
}
