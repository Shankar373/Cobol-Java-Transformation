import { useMemo, useState } from 'react';
import { tokens } from '../../theme/tokens';
import { Badge } from '../Badge';
import { SectionCard } from '../SectionCard';
import type { DiscoveryReportV2 } from '../../api/discoveryTypes';
import { Loc } from './SourceViewer';
import type { SourceTarget } from './SourceViewer';

const cell = { padding: '6px 10px', textAlign: 'left' as const, fontSize: 12, borderBottom: `1px solid ${tokens.colors.divider}`, verticalAlign: 'top' as const };

function verdictVariant(verdict: string): 'success' | 'warning' | 'error' | 'default' {
  if (verdict === 'COMPILES') return 'success';
  if (verdict === 'COMPILES_WITH_WARNINGS') return 'warning';
  if (verdict === 'COMPILE_ERRORS') return 'error';
  return 'default';
}

interface Props {
  report: DiscoveryReportV2;
  onOpen: (target: SourceTarget) => void;
}

export function CompilerSection({ report, onOpen }: Props) {
  const [filter, setFilter] = useState('');
  const [verdict, setVerdict] = useState('');
  const { compatibility, toolchain } = report;
  const rows = useMemo(
    () => compatibility.programs.filter((p) => (!verdict || p.verdict === verdict) && p.file.toLowerCase().includes(filter.trim().toLowerCase())),
    [compatibility.programs, filter, verdict],
  );
  const backend = compatibility.backend;
  return (
    <>
      <SectionCard title="Open-source toolchain" subtitle={compatibility.basis}>
        <div style={{ padding: 16, fontSize: 13 }}>
          <div data-testid="compiler-backend">
            Compiler backend: <strong>{backend.kind}</strong>
            {backend.version ? ` (GnuCOBOL ${backend.version}${backend.image ? ` in ${backend.image}` : ''})` : ''}
            {backend.reason ? ` - ${backend.reason}` : ''}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8 }}>
            <thead><tr><th style={cell}>Tool</th><th style={cell}>Status</th><th style={cell}>Licence</th></tr></thead>
            <tbody>
              {toolchain.tools.map((t) => (
                <tr key={t.tool}>
                  <td style={cell}>{t.tool}</td>
                  <td style={cell}>{t.available ? `available ${t.version ?? ''} (${t.via ?? ''})` : `not available: ${t.reason ?? ''}`}</td>
                  <td style={cell}>{t.license}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Toolchains the estate requires" count={toolchain.required.length} noPadding>
        {toolchain.required.length === 0 ? (
          <div style={{ padding: 16, fontSize: 13 }}>No compiler options, directives, build invocations or compile steps were found.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={cell}>Family</th><th style={cell}>Kind</th><th style={cell}>Name</th><th style={cell}>Evidence</th></tr></thead>
            <tbody>
              {toolchain.required.map((t) => (
                <tr key={`${t.family}:${t.kind}:${t.name}`}>
                  <td style={cell}>{t.family}</td><td style={cell}>{t.kind}</td><td style={cell}>{t.name}</td>
                  <td style={cell}>
                    {t.evidence.slice(0, 3).map((e) => <div key={`${e.file}:${e.line}`}><Loc file={e.file} line={e.line} onOpen={onOpen} /></div>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      <SectionCard
        title="Compiler compatibility"
        count={rows.length}
        headerRight={
          <span>
            <input aria-label="Filter programs" placeholder="Filter by file" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ marginRight: 8 }} />
            <select aria-label="Filter by verdict" value={verdict} onChange={(e) => setVerdict(e.target.value)}>
              <option value="">All verdicts</option>
              {Object.keys(compatibility.summary).map((v) => <option key={v} value={v}>{v} ({compatibility.summary[v]})</option>)}
            </select>
          </span>
        }
        noPadding
      >
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th style={cell}>Program file</th><th style={cell}>Dialect</th><th style={cell}>Verdict</th><th style={cell}>Details</th></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.file}>
                <td style={cell}>{p.file}</td>
                <td style={cell}>{p.dialect}, {p.source_format}</td>
                <td style={cell}><Badge variant={verdictVariant(p.verdict)} size="sm">{p.verdict}</Badge></td>
                <td style={cell}>
                  {p.reason && <div>{p.reason}</div>}
                  {p.diagnostics.slice(0, 5).map((d) => (
                    <div key={`${d.file}:${d.line}:${d.message}`}>
                      <Loc file={d.file} line={d.line} onOpen={onOpen} /> {d.severity}: {d.message}
                    </div>
                  ))}
                  {p.unsupported_features.map((f) => (
                    <div key={f.feature}>
                      <strong>Unsupported:</strong> {f.label}
                      {f.evidence[0] ? <> (<Loc file={p.file} line={f.evidence[0].line} onOpen={onOpen} />)</> : null}
                      <div style={{ color: tokens.colors.textMuted }}>{f.note}</div>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </>
  );
}
