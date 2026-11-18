import { useEffect, useState } from 'react';
import { tokens } from '../../theme/tokens';
import * as api from '../../api/client';
import type { DiscoverySourceExcerpt } from '../../api/discoveryTypes';

export interface SourceTarget {
  file: string;
  line: number;
}

interface SourceViewerProps {
  runId: string;
  target: SourceTarget;
  onClose: () => void;
}

/** Shows the lines around one finding, read from the immutable checkpoint (never from the original upload). */
export function SourceViewer({ runId, target, onClose }: SourceViewerProps) {
  const [excerpt, setExcerpt] = useState<DiscoverySourceExcerpt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setExcerpt(null);
    setError(null);
    api.getDiscoverySource(runId, target.file, target.line).then(
      (value) => {
        if (active) setExcerpt(value);
      },
      (err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      },
    );
    return () => {
      active = false;
    };
  }, [runId, target.file, target.line]);

  return (
    <aside
      aria-label="Source viewer"
      style={{
        position: 'sticky', top: 8, border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm,
        background: '#fff', padding: 12, maxHeight: '80vh', overflow: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <strong style={{ fontSize: 12, fontFamily: 'monospace', wordBreak: 'break-all' }}>{target.file}:{target.line}</strong>
        <button type="button" onClick={onClose} aria-label="Close source viewer">Close</button>
      </div>
      {error && <div role="alert" style={{ color: tokens.colors.error, fontSize: 12, marginTop: 8 }}>Source unavailable: {error}</div>}
      {!excerpt && !error && <div style={{ fontSize: 12, marginTop: 8 }}>Loading...</div>}
      {excerpt && (
        <>
          <div style={{ fontSize: 11, color: tokens.colors.textMuted, margin: '6px 0' }}>
            {excerpt.encoding}, {excerpt.total_lines} lines, sha256 {excerpt.sha256.slice(0, 12)}
          </div>
          <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.45 }}>
            {excerpt.lines.map((l) => (
              <div
                key={l.number}
                data-testid={l.number === excerpt.line ? 'source-hit' : undefined}
                style={{ background: l.number === excerpt.line ? tokens.colors.warningBg : undefined, whiteSpace: 'pre-wrap' }}
              >
                <span style={{ color: tokens.colors.textMuted, display: 'inline-block', width: 44 }}>{l.number}</span>
                {l.text}
              </div>
            ))}
          </pre>
        </>
      )}
    </aside>
  );
}

interface LocProps {
  file: string;
  line: number;
  onOpen: (target: SourceTarget) => void;
}

/** A clickable file:line reference that opens the source viewer. */
export function Loc({ file, line, onOpen }: LocProps) {
  return (
    <button
      type="button"
      onClick={() => onOpen({ file, line })}
      style={{ background: 'none', border: 0, padding: 0, color: tokens.colors.primary, cursor: 'pointer', fontFamily: 'monospace', fontSize: 12, textAlign: 'left' }}
    >
      {file}:{line}
    </button>
  );
}
