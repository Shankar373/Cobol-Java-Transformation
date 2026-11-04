import { useState } from 'react';
import { getEstate } from '../api/client';
import type { EstateResponse } from '../api/client';
import { tokens } from '../theme/tokens';
import { Badge } from './Badge';

type Variant = 'success' | 'warning' | 'error' | 'default';

const STATE_VARIANT: Record<string, Variant> = {
  PROVEN: 'success',
  PARTIAL: 'warning',
  BLOCKED: 'error',
  UNPROVEN: 'default',
};

const PROOF_STATES = ['PROVEN', 'PARTIAL', 'BLOCKED', 'UNPROVEN'] as const;

const rowStyle = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: tokens.spacing.sm,
  padding: `${tokens.spacing.xs} 0`,
  fontSize: tokens.font.sizes.xs,
};

/**
 * Read-only estate view: the dependency graph of the ingested application with a proof state on every
 * edge.  It is loaded on demand and never changes anything on the server.
 */
export function EstatePanel({ appId }: { appId: string }) {
  const [estate, setEstate] = useState<EstateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string>('ALL');

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setEstate(await getEstate(appId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The estate view could not be loaded');
    } finally {
      setLoading(false);
    }
  };

  if (!estate) {
    return (
      <div data-testid="estate-panel">
        <button type="button" onClick={load} disabled={loading}>
          {loading ? 'Loading estate…' : 'Load estate view'}
        </button>
        {error && <div role="alert" style={{ color: tokens.colors.error }}>{error}</div>}
      </div>
    );
  }

  const { summary } = estate;
  const edges = filter === 'ALL' ? estate.edges : estate.edges.filter((e) => e.proof_state === filter);

  return (
    <div data-testid="estate-panel">
      <div style={{ display: 'flex', gap: tokens.spacing.sm, flexWrap: 'wrap', alignItems: 'center' }}>
        <span>{summary.node_count} nodes</span>
        <span>{summary.edge_count} edges</span>
        {PROOF_STATES.map((state) => (
          <Badge key={state} variant={STATE_VARIANT[state]} size="sm">
            {state} {summary.edges_by_proof_state[state] ?? 0}
          </Badge>
        ))}
        <span data-testid="estate-proven-percent">{summary.proven_edge_percent}% of edges proven</span>
      </div>
      {estate.discovery_errors.length > 0 && (
        <div role="alert" style={{ color: tokens.colors.warning }}>
          The estate is partial: {estate.discovery_errors.length} discovery issue
          {estate.discovery_errors.length === 1 ? '' : 's'} reported.
        </div>
      )}
      <label>
        Proof state{' '}
        <select aria-label="Proof state filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="ALL">All</option>
          {PROOF_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <div>
        {edges.map((e) => (
          <div key={`${e.source}|${e.relation}|${e.target}`} style={rowStyle} data-testid="estate-edge">
            <span>{e.source} {e.relation} {e.target}</span>
            <span title={e.evidence}>
              <Badge variant={STATE_VARIANT[e.proof_state] ?? 'default'} size="sm">{e.proof_state}</Badge>
            </span>
          </div>
        ))}
        {edges.length === 0 && <div>No edges in this proof state.</div>}
      </div>
    </div>
  );
}
