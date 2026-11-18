import React from 'react';
import { tokens } from '../../theme/tokens';
import * as api from '../../api/client';

export const mono: React.CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: tokens.font.sizes.sm,
  wordBreak: 'break-all',
};
export const inputStyle: React.CSSProperties = {
  padding: '6px 10px',
  border: `1px solid ${tokens.colors.divider}`,
  borderRadius: tokens.radii.sm,
  fontSize: tokens.font.sizes.base,
  fontFamily: tokens.font.family,
  background: '#fff',
};

/** Human message for a failed kg call; server text is only ever shown as plain text. */
export function kgError(err: unknown, prefix: string): string {
  if (err instanceof api.ApiError) {
    if (err.status === 401) return `${prefix}: authentication required. Enter your API token on the Dashboard, then retry.`;
    if (err.status === 403) return `${prefix}: your role may not read this knowledge graph.`;
    return `${prefix}: ${err.message}`;
  }
  return `${prefix}: ${err instanceof Error ? err.message : 'unexpected error'}`;
}

export function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      style={{
        color: tokens.colors.error,
        background: tokens.colors.errorBg,
        padding: '8px 12px',
        borderRadius: tokens.radii.sm,
        fontSize: tokens.font.sizes.sm,
      }}
    >
      {message}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>
      {label}
      {children}
    </label>
  );
}
