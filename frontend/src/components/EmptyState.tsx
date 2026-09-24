import React from 'react';
import { tokens } from '../theme/tokens';

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon = '\u{1F4CB}', title, description, action }: EmptyStateProps) {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: tokens.spacing.xxl + ' ' + tokens.spacing.xl,
        color: tokens.colors.textSecondary,
      }}
    >
      <div style={{ fontSize: 48, marginBottom: tokens.spacing.md }}>{icon}</div>
      <div
        style={{
          fontSize: tokens.font.sizes.lg,
          fontWeight: tokens.font.weights.semibold,
          color: tokens.colors.textPrimary,
          marginBottom: tokens.spacing.sm,
        }}
      >
        {title}
      </div>
      {description && (
        <div style={{ fontSize: tokens.font.sizes.base, marginBottom: tokens.spacing.lg }}>
          {description}
        </div>
      )}
      {action}
    </div>
  );
}
