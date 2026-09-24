import React from 'react';
import { tokens } from '../theme/tokens';

interface PageContainerProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export function PageContainer({ children, title, subtitle, actions }: PageContainerProps) {
  return (
    <div
      style={{
        maxWidth: 1100,
        margin: '0 auto',
        padding: tokens.spacing.xl,
      }}
    >
      {title && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: tokens.spacing.lg,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: tokens.font.sizes.xl,
                fontWeight: tokens.font.weights.bold,
                color: tokens.colors.textPrimary,
                marginBottom: tokens.spacing.xs,
              }}
            >
              {title}
            </h1>
            {subtitle && (
              <p
                style={{
                  fontSize: tokens.font.sizes.base,
                  color: tokens.colors.textSecondary,
                }}
              >
                {subtitle}
              </p>
            )}
          </div>
          {actions && <div>{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
