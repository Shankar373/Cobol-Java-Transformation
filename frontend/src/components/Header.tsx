import React from 'react';
import { tokens } from '../theme/tokens';

const s: Record<string, React.CSSProperties> = {
  header: {
    background: tokens.colors.cardBg,
    borderBottom: `1px solid ${tokens.colors.divider}`,
    padding: `${tokens.spacing.md} ${tokens.spacing.xl}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    position: 'sticky',
    top: 0,
    zIndex: 100,
    boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacing.sm,
  },
  logo: {
    width: 36,
    height: 36,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  title: {
    fontSize: tokens.font.sizes.md,
    fontWeight: tokens.font.weights.semibold,
    color: tokens.colors.textPrimary,
  },
  subtitle: {
    fontSize: tokens.font.sizes.xs,
    color: tokens.colors.textMuted,
  },
  nav: {
    display: 'flex',
    gap: tokens.spacing.md,
    alignItems: 'center',
  },
  navLink: {
    fontSize: tokens.font.sizes.base,
    color: tokens.colors.textSecondary,
    textDecoration: 'none',
    fontWeight: tokens.font.weights.medium,
    padding: `${tokens.spacing.xs} ${tokens.spacing.sm}`,
    borderRadius: tokens.radii.sm,
    transition: 'color 0.15s, background 0.15s',
  },
};


function SystemaOpsLogo() {
  return (
    <svg viewBox="0 0 190 190" width="36" height="36" role="img" aria-label="SystemaOps logo">
      <polygon points="36,55 96,27 157,57 98,88" fill="#29908f" />
      <polygon points="98,88 157,57 157,106 98,137" fill="#1b8281" />
      <polygon points="36,55 98,88 98,137 36,106" fill="#248787" />
      <polygon points="36,106 98,137 157,106 98,80" fill="#1d8180" />
      <circle cx="98" cy="96" r="11" fill="#e8ba32" />
    </svg>
  );
}

interface HeaderProps {
  onNavigate?: (page: string) => void;
  currentPage?: string;
}

export function Header({ onNavigate, currentPage }: HeaderProps) {
  return (
    <header style={s.header}>
      <div style={s.brand}>
        <div style={s.logo}><SystemaOpsLogo /></div>
        <div>
          <div style={s.title}>SystemaOps</div>
          <div style={s.subtitle}>COBOL → Java</div>
          <div style={{ ...s.subtitle, fontSize: 10 }}>Modernization Platform</div>
        </div>
      </div>
      <nav style={s.nav}>
        {[
          { key: 'dashboard', label: 'Dashboard' },
          { key: 'new', label: 'New Modernization' },
        ].map((item) => (
          <a
            key={item.key}
            href="#"
            style={{
              ...s.navLink,
              color: currentPage === item.key
                ? tokens.colors.primary
                : tokens.colors.textSecondary,
              background: currentPage === item.key
                ? tokens.colors.primaryLight
                : 'transparent',
            }}
            onClick={(e) => {
              e.preventDefault();
              onNavigate?.(item.key);
            }}
          >
            {item.label}
          </a>
        ))}
      </nav>
    </header>
  );
}
