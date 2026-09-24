import React from 'react';
import { tokens } from '../theme/tokens';

interface SectionCardProps {
  title: string;
  count?: number;
  children: React.ReactNode;
  headerRight?: React.ReactNode;
}

export function SectionCard({ title, count, children, headerRight }: SectionCardProps) {
  return (
    <div
      style={{
        background: tokens.colors.cardBg,
        borderRadius: tokens.radii.md,
        border: '1px solid ' + tokens.colors.cardBorder,
        boxShadow: tokens.colors.shadow,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: tokens.spacing.md + ' ' + tokens.spacing.lg,
          borderBottom: '1px solid ' + tokens.colors.divider,
        }}
      >
        <span
          style={{
            fontSize: tokens.font.sizes.sm,
            fontWeight: tokens.font.weights.bold,
            color: tokens.colors.primary,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
          }}
        >
          {title}
          {count !== undefined ? ' (' + count + ')' : ''}
        </span>
        {headerRight}
      </div>
      <div style={{ padding: tokens.spacing.lg }}>{children}</div>
    </div>
  );
}
