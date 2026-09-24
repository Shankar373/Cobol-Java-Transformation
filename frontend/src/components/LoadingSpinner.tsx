import React from 'react';
import { tokens } from '../theme/tokens';

interface LoadingSpinnerProps {
  message?: string;
  size?: number;
}

export function LoadingSpinner({ message = 'Loading...', size = 36 }: LoadingSpinnerProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: message ? 'column' : 'row',
        alignItems: 'center',
        gap: tokens.spacing.md,
        padding: message ? tokens.spacing.xxl : 0,
        color: tokens.colors.textSecondary,
      }}
    >
      <div
        style={{
          width: size,
          height: size,
          border: `${Math.max(2, size / 12)}px solid ${tokens.colors.divider}`,
          borderTopColor: tokens.colors.primary,
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }}
      />
      <style>{'@keyframes spin { to { transform: rotate(360deg); } }'}</style>
      {message && <span style={{ fontSize: tokens.font.sizes.sm }}>{message}</span>}
    </div>
  );
}
