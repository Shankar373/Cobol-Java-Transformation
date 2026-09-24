import React from 'react';
import { tokens } from '../theme/tokens';

interface StatCardProps {
  icon: string;
  value: number | string;
  label: string;
  iconColor?: string;
}

export function StatCard({ icon, value, label, iconColor }: StatCardProps) {
  return (
    <div
      style={{
        background: tokens.colors.cardBg,
        borderRadius: tokens.radii.md,
        border: `1px solid ${tokens.colors.cardBorder}`,
        boxShadow: tokens.colors.shadow,
        padding: `${tokens.spacing.lg} ${tokens.spacing.md}`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spacing.xs,
        minWidth: 120,
        flex: '1 1 0',
      }}
    >
      <span style={{ fontSize: 28, filter: iconColor ? `drop-shadow(0 0 4px ${iconColor})` : undefined }}>
        {icon}
      </span>
      <span
        style={{
          fontSize: tokens.font.sizes.xxl,
          fontWeight: tokens.font.weights.bold,
          color: tokens.colors.textPrimary,
          lineHeight: 1,
        }}
      >
        {value}
      </span>
      <span
        style={{
          fontSize: tokens.font.sizes.sm,
          color: tokens.colors.textMuted,
          textAlign: 'center',
        }}
      >
        {label}
      </span>
    </div>
  );
}
