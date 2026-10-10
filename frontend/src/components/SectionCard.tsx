import React from 'react';
import { tokens } from '../theme/tokens';

interface SectionCardProps {
  title: string;
  count?: number;
  children: React.ReactNode;
  headerRight?: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  noPadding?: boolean;
}

export function SectionCard({
  title,
  count,
  children,
  headerRight,
  subtitle,
  icon,
  noPadding,
}: SectionCardProps) {
  return (
    <div className="card">
      <div className="card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          {icon && (
            <span
              style={{
                display: 'inline-flex',
                color: tokens.colors.primary,
                opacity: 0.8,
                flexShrink: 0,
              }}
            >
              {icon}
            </span>
          )}
          <div style={{ minWidth: 0 }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: tokens.colors.textSecondary,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}
            >
              {count !== undefined ? `${title} (${count})` : title}
            </span>
            {subtitle && (
              <div
                style={{
                  fontSize: 11,
                  color: tokens.colors.textMuted,
                  marginTop: 2,
                }}
              >
                {subtitle}
              </div>
            )}
          </div>
        </div>
        {headerRight && (
          <div style={{ flexShrink: 0 }}>{headerRight}</div>
        )}
      </div>
      <div style={noPadding ? undefined : { padding: '16px 20px' }}>{children}</div>
    </div>
  );
}
