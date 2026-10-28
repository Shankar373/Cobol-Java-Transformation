import React from 'react';
import { tokens } from '../theme/tokens';
import { IconInbox } from './icons';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: tokens.spacing.xxl + ' ' + tokens.spacing.xl,
        color: tokens.colors.textSecondary,
      }}
    >
      <div
        style={{
          fontSize: 48,
          marginBottom: tokens.spacing.md,
          display: 'flex',
          justifyContent: 'center',
          color: tokens.colors.textMuted,
        }}
      >
        {icon ?? <IconInbox size={44} />}
      </div>
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
