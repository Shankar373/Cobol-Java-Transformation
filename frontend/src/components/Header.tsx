import React from 'react';
import { tokens } from '../theme/tokens';
import { IconChevronRight, IconDownload } from './icons';

export interface BreadcrumbItem {
  label: string;
  onClick?: () => void;
}

interface HeaderProps {
  /** Legacy global header (brand + nav). Used when no page context is given. */
  onNavigate?: (page: string) => void;
  currentPage?: string;
  /** Page-context mode: breadcrumb trail shown above the title. */
  breadcrumb?: BreadcrumbItem[];
  /** Page-context mode: page title. */
  title?: string;
  /** Page-context mode: identifier chips (run id, application id, ...). */
  meta?: React.ReactNode;
  /** Page-context mode: right-aligned actions or status. */
  right?: React.ReactNode;
}

/** Identifier chip — label + monospaced value. */
export function HeaderMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: tokens.font.sizes.xs,
        color: tokens.colors.textMuted,
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ color: '#94a3b8' }}>{label}</span>
      <span
        style={{
          color: tokens.colors.textSecondary,
          fontFamily: 'monospace',
          background: tokens.colors.surfaceAlt,
          border: `1px solid ${tokens.colors.cardBorder}`,
          borderRadius: tokens.radii.sm,
          padding: '1px 6px',
          fontSize: 11,
        }}
      >
        {value}
      </span>
    </span>
  );
}

export function Header({
  onNavigate,
  currentPage,
  breadcrumb,
  title,
  meta,
  right,
}: HeaderProps) {
  const hasContext = title !== undefined || breadcrumb !== undefined;

  const headerStyle: React.CSSProperties = {
    background: '#ffffff',
    borderBottom: `1px solid ${tokens.colors.divider}`,
    padding: `${tokens.spacing.sm} ${tokens.spacing.xl}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: tokens.spacing.lg,
    position: 'sticky',
    top: 0,
    zIndex: 100,
    boxShadow: '0 1px 3px rgba(15,23,42,0.05)',
    minHeight: 56,
  };

  if (hasContext) {
    return (
      <header style={headerStyle}>
        <div style={{ minWidth: 0, flex: 1 }}>
          {breadcrumb && breadcrumb.length > 0 && (
            <nav
              aria-label="Breadcrumb"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                fontSize: 11,
                color: tokens.colors.textMuted,
                marginBottom: 3,
                flexWrap: 'wrap',
              }}
            >
              {breadcrumb.map((crumb, i) => (
                <React.Fragment key={`${crumb.label}-${i}`}>
                  {i > 0 && <IconChevronRight size={9} />}
                  {crumb.onClick ? (
                    <button
                      type="button"
                      onClick={crumb.onClick}
                      style={{
                        background: 'none',
                        border: 'none',
                        padding: 0,
                        font: 'inherit',
                        fontSize: 11,
                        color: tokens.colors.primary,
                        cursor: 'pointer',
                        fontWeight: 500,
                      }}
                    >
                      {crumb.label}
                    </button>
                  ) : (
                    <span>{crumb.label}</span>
                  )}
                </React.Fragment>
              ))}
            </nav>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.md, flexWrap: 'wrap' }}>
            {title && (
              <h1
                style={{
                  fontSize: tokens.font.sizes.lg,
                  fontWeight: tokens.font.weights.bold,
                  color: tokens.colors.textPrimary,
                  lineHeight: 1.2,
                  letterSpacing: '-0.01em',
                }}
              >
                {title}
              </h1>
            )}
            {meta && (
              <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm, flexWrap: 'wrap' }}>
                {meta}
              </div>
            )}
          </div>
        </div>

        {right && (
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm, flexShrink: 0 }}>
            {right}
          </div>
        )}
      </header>
    );
  }

  // Legacy global header with logo + nav
  return (
    <header style={headerStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm }}>
        <img
          src="/logo.svg"
          alt="SystemaOps"
          width={28}
          height={28}
          style={{ objectFit: 'contain', display: 'block' }}
        />
        <div>
          <div
            style={{
              fontSize: tokens.font.sizes.base,
              fontWeight: tokens.font.weights.bold,
              color: tokens.colors.textPrimary,
              lineHeight: 1.2,
              letterSpacing: '-0.01em',
            }}
          >
            SystemaOps
          </div>
          <div style={{ fontSize: 10, color: tokens.colors.textMuted }}>
            Modernization Control Plane
          </div>
        </div>
      </div>

      <nav style={{ display: 'flex', gap: tokens.spacing.md, alignItems: 'center' }}>
        {[
          { key: 'dashboard', label: 'Dashboard' },
          { key: 'new',       label: 'New Modernization' },
        ].map((item) => (
          <a
            key={item.key}
            href="#"
            style={{
              fontSize: tokens.font.sizes.sm,
              color: currentPage === item.key ? tokens.colors.primary : tokens.colors.textSecondary,
              background: currentPage === item.key ? tokens.colors.primaryLight : 'transparent',
              fontWeight: tokens.font.weights.medium,
              padding: `${tokens.spacing.xs} ${tokens.spacing.sm}`,
              borderRadius: tokens.radii.sm,
              textDecoration: 'none',
              transition: 'color 0.15s, background 0.15s',
            }}
            onClick={(e) => { e.preventDefault(); onNavigate?.(item.key); }}
          >
            {item.label}
          </a>
        ))}
      </nav>
    </header>
  );
}
