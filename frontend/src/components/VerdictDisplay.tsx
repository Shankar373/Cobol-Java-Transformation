import React from 'react';
import { tokens } from '../theme/tokens';
import type { VerdictResponse } from '../api/client';
import { Badge } from './Badge';
import { SectionCard } from './SectionCard';
import { IconCheckCircle, IconAlert, IconXCircle, IconHelp, IconBan } from './icons';

interface VerdictDisplayProps {
  verdict: VerdictResponse;
}

const verdictConfig: Record<string, { icon: React.ReactNode; color: string; bg: string; label: string }> = {
  VERIFIED: { icon: <IconCheckCircle size={40} />, color: tokens.colors.success, bg: tokens.colors.successBg, label: 'VERIFIED' },
  PARTIAL: { icon: <IconAlert size={40} />, color: tokens.colors.warning, bg: tokens.colors.warningBg, label: 'PARTIAL' },
  FAILED: { icon: <IconXCircle size={40} />, color: tokens.colors.error, bg: tokens.colors.errorBg, label: 'FAILED' },
  UNPROVEN: { icon: <IconHelp size={40} />, color: tokens.colors.textMuted, bg: tokens.colors.surfaceAlt, label: 'UNPROVEN' },
  UNAVAILABLE: { icon: <IconBan size={40} />, color: tokens.colors.warning, bg: tokens.colors.warningBg, label: 'UNAVAILABLE' },
  UNSUPPORTED: { icon: <IconHelp size={40} />, color: tokens.colors.textMuted, bg: tokens.colors.surfaceAlt, label: 'UNSUPPORTED' },
  ERROR: { icon: <IconAlert size={40} />, color: tokens.colors.error, bg: tokens.colors.errorBg, label: 'ERROR' },
};

export function VerdictDisplay({ verdict }: VerdictDisplayProps) {
  const cfg = verdictConfig[verdict.state] || verdictConfig.UNPROVEN;

  return (
    <SectionCard title="Validation Evidence">
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: tokens.spacing.lg,
        }}
      >
        {/* Main verdict */}
        <div
          role="status"
          aria-label={`Verdict: ${cfg.label}`}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: tokens.spacing.md,
            padding: tokens.spacing.lg,
            borderRadius: tokens.radii.md,
            background: cfg.bg,
            border: '1px solid ' + cfg.color + '30',
          }}
        >
          <span aria-hidden="true">{cfg.icon}</span>
          <div>
            <div
              style={{
                fontSize: tokens.font.sizes.xl,
                fontWeight: tokens.font.weights.bold,
                color: cfg.color,
              }}
            >
              {cfg.label}
            </div>
            <div style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
              Workload: {verdict.workload_id}
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display: 'flex', gap: tokens.spacing.md, flexWrap: 'wrap' }}>
          {[
            { label: 'Checks Executed', value: verdict.executed_check_count },
            { label: 'Skipped', value: verdict.skipped_count },
            { label: 'Unavailable', value: verdict.unavailable_count },
          ].map((item) => (
            <div
              key={item.label}
              style={{
                flex: '1 1 100px',
                padding: tokens.spacing.md,
                borderRadius: tokens.radii.sm,
                background: tokens.colors.surfaceAlt,
                border: '1px solid ' + tokens.colors.cardBorder,
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: tokens.font.sizes.xl, fontWeight: tokens.font.weights.bold }}>
                {item.value}
              </div>
              <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                {item.label}
              </div>
            </div>
          ))}
        </div>

        {/* Scope statement lives in the Validation Scope card — see ValidationScope. */}

        {/* Comparisons table */}
        {verdict.comparisons.length > 0 && (
          <div>
            <div
              style={{
                fontSize: tokens.font.sizes.sm,
                fontWeight: tokens.font.weights.bold,
                color: tokens.colors.primary,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                marginBottom: tokens.spacing.sm,
              }}
            >
              Artifact Comparisons
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: tokens.font.sizes.base,
                }}
                aria-label="Artifact comparison results"
              >
                <thead>
                  <tr
                    style={{
                      borderBottom: '2px solid ' + tokens.colors.divider,
                      textAlign: 'left',
                    }}
                  >
                    <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>
                      Artifact
                    </th>
                    <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>
                      Comparator
                    </th>
                    <th style={{ padding: '8px 12px', fontWeight: tokens.font.weights.semibold, color: tokens.colors.textSecondary }}>
                      Result
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {verdict.comparisons.map((c) => (
                    <tr key={c.comparison_id} style={{ borderBottom: '1px solid ' + tokens.colors.divider }}>
                      <td style={{ padding: '8px 12px' }}>{c.artifact_type}</td>
                      <td style={{ padding: '8px 12px', color: tokens.colors.textMuted }}>{c.comparator_id}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <Badge variant={c.result === 'MATCH' ? 'success' : c.result === 'MISMATCH' ? 'error' : 'warning'}>
                          {c.result}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Differences */}
        {verdict.differences.length > 0 && (
          <div>
            <div
              style={{
                fontSize: tokens.font.sizes.sm,
                fontWeight: tokens.font.weights.bold,
                color: tokens.colors.error,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                marginBottom: tokens.spacing.sm,
              }}
            >
              Differences
            </div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {verdict.differences.map((d, i) => (
                <li key={i} style={{ color: tokens.colors.textSecondary, marginBottom: 4 }}>
                  {d}
                </li>
              ))}
            </ul>
          </div>
        )}

      </div>
    </SectionCard>
  );
}
