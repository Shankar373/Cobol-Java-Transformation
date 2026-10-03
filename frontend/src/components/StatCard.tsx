import React from 'react';
import { tokens } from '../theme/tokens';

interface StatCardProps {
  icon: React.ReactNode;
  value: number | string;
  label: string;
  iconColor?: string;
}

export function StatCard({ icon, value, label, iconColor }: StatCardProps) {
  const color = iconColor ?? tokens.colors.primary;
  return (
    <div className="stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span
          style={{
            display: 'inline-flex',
            padding: 8,
            borderRadius: 8,
            background: `${color}14`,
            color: color,
          }}
        >
          {icon}
        </span>
      </div>
      <div style={{ marginTop: 4 }}>
        <div
          style={{
            fontSize: 26,
            fontWeight: tokens.font.weights.bold,
            color: tokens.colors.textPrimary,
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
          }}
        >
          {value}
        </div>
        <div
          style={{
            fontSize: 12,
            color: tokens.colors.textMuted,
            marginTop: 3,
            fontWeight: tokens.font.weights.medium,
          }}
        >
          {label}
        </div>
      </div>
    </div>
  );
}
