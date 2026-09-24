import React from 'react';
import { tokens } from '../theme/tokens';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'gradient' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
}

const sizeStyles = {
  sm: { padding: '6px 14px', fontSize: tokens.font.sizes.sm },
  md: { padding: '10px 20px', fontSize: tokens.font.sizes.base },
  lg: { padding: '12px 28px', fontSize: tokens.font.sizes.md },
};

export function Button({
  variant = 'primary',
  size = 'md',
  children,
  style,
  ...rest
}: ButtonProps) {
  const base: React.CSSProperties = {
    border: 'none',
    borderRadius: tokens.radii.sm,
    fontWeight: tokens.font.weights.semibold,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: tokens.spacing.sm,
    transition: 'opacity 0.15s, transform 0.1s',
    ...sizeStyles[size],
  };

  const variants: Record<string, React.CSSProperties> = {
    primary: {
      background: tokens.colors.primary,
      color: tokens.colors.textOnPrimary,
    },
    secondary: {
      background: 'transparent',
      color: tokens.colors.primary,
      border: '1px solid ' + tokens.colors.primary,
    },
    gradient: {
      background: tokens.colors.gradient,
      color: tokens.colors.textOnPrimary,
      boxShadow: '0 2px 8px rgba(124,58,237,0.3)',
    },
    ghost: {
      background: 'transparent',
      color: tokens.colors.textSecondary,
    },
  };

  return (
    <button
      style={{ ...base, ...variants[variant], ...style }}
      {...rest}
    >
      {children}
    </button>
  );
}
