import React from 'react';
import { tokens } from '../theme/tokens';
import type { VerdictResponse } from '../api/client';
import { SectionCard } from './SectionCard';

interface ValidationScopeProps {
  verdict: VerdictResponse;
}

/**
 * Validation Scope — the exact statement the backend derived the verdict
 * against, plus the identity and integrity hashes that pin it.
 * Text is rendered verbatim from the API response (never summarized).
 */
export function ValidationScope({ verdict }: ValidationScopeProps) {
  const rows: { label: string; value: string }[] = [
    { label: 'Oracle', value: verdict.oracle_id },
    { label: 'Oracle digest', value: verdict.oracle_digest },
    { label: 'Source hash', value: verdict.source_hash },
    { label: 'Candidate hash', value: verdict.candidate_hash ?? '—' },
    { label: 'Evidence manifest hash', value: verdict.evidence_manifest_hash },
    { label: 'Derived at', value: verdict.derivation_timestamp },
    ...(verdict.engine_run_id ? [{ label: 'Engine run', value: verdict.engine_run_id }] : []),
  ];

  return (
    <SectionCard title="Validation Scope">
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
        <div
          style={{
            padding: `${tokens.spacing.sm} ${tokens.spacing.md}`,
            borderRadius: tokens.radii.sm,
            background: tokens.colors.infoBg,
            border: `1px solid ${tokens.colors.info}20`,
            fontSize: tokens.font.sizes.sm,
            lineHeight: 1.6,
            color: tokens.colors.textSecondary,
          }}
        >
          {verdict.supported_scope_statement}
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: tokens.spacing.sm,
          }}
        >
          {rows.map((row) => (
            <div
              key={row.label}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                padding: `${tokens.spacing.sm} ${tokens.spacing.md}`,
                borderRadius: tokens.radii.sm,
                background: tokens.colors.surfaceAlt,
                border: `1px solid ${tokens.colors.cardBorder}`,
                minWidth: 0,
              }}
            >
              <span
                style={{
                  fontSize: tokens.font.sizes.xs,
                  color: tokens.colors.textMuted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.4px',
                  fontWeight: tokens.font.weights.semibold,
                }}
              >
                {row.label}
              </span>
              <span
                style={{
                  fontSize: tokens.font.sizes.xs,
                  fontFamily: 'monospace',
                  color: tokens.colors.textSecondary,
                  wordBreak: 'break-all',
                }}
              >
                {row.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </SectionCard>
  );
}
