import React from 'react';
import { tokens } from '../theme/tokens';

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'default' | 'purple';
type BadgeSize = 'sm' | 'md';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: BadgeSize;
}

const variantStyles: Record<BadgeVariant, { bg: string; color: string }> = {
  success: { bg: tokens.colors.successBg, color: tokens.colors.success },
  warning: { bg: tokens.colors.warningBg, color: tokens.colors.warning },
  error: { bg: tokens.colors.errorBg, color: tokens.colors.error },
  info: { bg: tokens.colors.infoBg, color: tokens.colors.info },
  default: { bg: '#f1f3f4', color: tokens.colors.textSecondary },
  purple: { bg: '#f3e8ff', color: tokens.colors.accent },
};

const sizeStyles: Record<BadgeSize, { padding: string; fontSize: string }> = {
  sm: { padding: '2px 6px', fontSize: tokens.font.sizes.xs },
  md: { padding: '3px 10px', fontSize: tokens.font.sizes.xs },
};

export function Badge({ children, variant = 'default', size = 'md' }: BadgeProps) {
  const v = variantStyles[variant];
  const s = sizeStyles[size];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: s.padding,
        borderRadius: tokens.radii.pill,
        fontSize: s.fontSize,
        fontWeight: tokens.font.weights.semibold,
        background: v.bg,
        color: v.color,
        textTransform: 'uppercase',
        letterSpacing: '0.3px',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  );
}
