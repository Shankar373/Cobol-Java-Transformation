import { tokens } from '../../theme/tokens';
import { Badge } from '../Badge';
import { SectionCard } from '../SectionCard';
import type { DiscoveryReportV2 } from '../../api/discoveryTypes';
import { Loc } from './SourceViewer';
import type { SourceTarget } from './SourceViewer';

const cell = { padding: '6px 10px', textAlign: 'left' as const, fontSize: 12, borderBottom: `1px solid ${tokens.colors.divider}`, verticalAlign: 'top' as const };

function variant(state: string): 'success' | 'warning' | 'error' {
  return state === 'READY' ? 'success' : state === 'NOT_SUPPORTED' ? 'warning' : 'error';
}

interface Props {
  applications: DiscoveryReportV2['applications'];
  onOpen: (target: SourceTarget) => void;
}

export function ApplicationsSection({ applications, onOpen }: Props) {
  return (
    <>
      <SectionCard title="Applications and entry points" count={applications.applications.length}>
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {applications.applications.length === 0 && <div style={{ fontSize: 13 }}>No COBOL programs or jobs were found.</div>}
          {applications.applications.map((a) => (
            <div key={a.id} className="card" style={{ padding: 12 }} data-testid="application-card">
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <strong>{a.name}</strong>
                <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{a.id}</span>
                <Badge variant={variant(a.readiness)} size="sm">{a.readiness}</Badge>
              </div>
              <div style={{ fontSize: 12, marginTop: 6 }}>
                {a.programs.length} programs, {a.jobs.length} jobs, {a.files.length} files, {a.copybooks.length} copybooks, {a.resources.length} data resources
              </div>
              {a.entry_points.length > 0 && (
                <div style={{ fontSize: 12, marginTop: 6 }}>
                  Entry points:{' '}
                  {a.entry_points.map((e) => (
                    <span key={e.program} style={{ marginRight: 10 }}>
                      {e.program} <Badge size="sm">{e.kinds.join(', ')}</Badge> <Loc file={e.file} line={1} onOpen={onOpen} />
                    </span>
                  ))}
                </div>
              )}
              {a.unsupported_features.length > 0 && (
                <div style={{ fontSize: 12, marginTop: 6 }}>Unsupported features: {a.unsupported_features.join(', ')}</div>
              )}
              {a.blocking_unresolved.length > 0 && (
                <div style={{ fontSize: 12, marginTop: 6, color: tokens.colors.error }}>
                  Blocking:{' '}
                  {a.blocking_unresolved.slice(0, 5).map((b) => (
                    <span key={`${b.file}:${b.line}:${b.to}`} style={{ marginRight: 10 }}>
                      {b.to} ({b.reason}) <Loc file={b.file} line={b.line} onOpen={onOpen} />
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Cross-application relationships" count={applications.relationships.length} noPadding>
        {applications.relationships.length === 0 ? (
          <div style={{ padding: 16, fontSize: 13 }}>No dataset, table, queue or copybook is shared between applications.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={cell}>Shared resource</th><th style={cell}>Kind</th><th style={cell}>Used by</th></tr></thead>
            <tbody>
              {applications.relationships.map((r) => (
                <tr key={r.resource}>
                  <td style={cell}>{r.resource}</td><td style={cell}>{r.kind}</td>
                  <td style={cell}>{r.applications.map((a) => `${a.name} (${a.uses})`).join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </>
  );
}
