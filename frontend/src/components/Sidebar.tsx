import React from 'react';
import { tokens } from '../theme/tokens';
import {
  IconGrid,
  IconPlus,
  IconBox,
  IconDatabase,
  IconPulse,
  IconCheckCircle,
  IconFileText,
} from './icons';

export type SidebarPage = 'dashboard' | 'new' | 'run';

interface SidebarProps {
  currentPage: SidebarPage;
  onNavigate: (page: string, id?: string) => void;
}

const NAV_ITEMS: { key: SidebarPage; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: 'Dashboard',        icon: <IconGrid size={17} /> },
  { key: 'new',       label: 'New Modernization', icon: <IconPlus size={17} /> },
];

const PLACEHOLDER_ITEMS: { label: string; icon: React.ReactNode }[] = [
  { label: 'Applications', icon: <IconBox size={17} /> },
  { label: 'Runs',         icon: <IconPulse size={17} /> },
  { label: 'Artifacts',    icon: <IconDatabase size={17} /> },
  { label: 'Reports',      icon: <IconFileText size={17} /> },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="sidebar-label"
      style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: '0.08em',
        color: '#475569',
        textTransform: 'uppercase',
        padding: '10px 14px 4px',
      }}
    >
      {children}
    </div>
  );
}

function NavItem({
  icon,
  label,
  isActive,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  isActive?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <a
      href="#"
      className="sidebar-nav-item"
      title={label}
      aria-current={isActive ? 'page' : undefined}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 12px',
        borderRadius: 7,
        color: isActive
          ? '#ffffff'
          : disabled
          ? '#334155'
          : '#94a3b8',
        background: isActive ? '#1d4ed8' : 'transparent',
        fontSize: 13,
        fontWeight: isActive ? 600 : 400,
        textDecoration: 'none',
        opacity: disabled ? 0.45 : 1,
        cursor: disabled ? 'default' : 'pointer',
        transition: 'background 0.15s, color 0.15s',
      }}
      onClick={(e) => {
        e.preventDefault();
        if (!disabled) onClick?.();
      }}
    >
      <span style={{ flexShrink: 0, display: 'flex' }}>{icon}</span>
      <span className="sidebar-label">{label}</span>
    </a>
  );
}

export function Sidebar({ currentPage, onNavigate }: SidebarProps) {
  const activeKey: SidebarPage = currentPage === 'run' ? 'dashboard' : currentPage;

  return (
    <aside className="sidebar" aria-label="Primary navigation">

      {/* ── Official SystemaOps Brand Lockup ── */}
      <div
        className="sidebar-brand"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 11,
          padding: '20px 16px 18px',
          borderBottom: '1px solid #1e293b',
        }}
      >
        {/* Official logo mark — exact asset, no recreation */}
        <img
          src="/logo.svg"
          alt="SystemaOps logo"
          width={36}
          height={36}
          style={{
            objectFit: 'contain',
            flexShrink: 0,
            display: 'block',
          }}
        />

        {/* Official name + product line */}
        <div className="sidebar-brand-text" style={{ minWidth: 0, lineHeight: 1 }}>
          {/*
           * Official brand typography:
           *   "Systema" = dark navy  (#1a2d5a)
           *   "Ops"     = teal-cyan  (#0891b2)
           * Rendered here to match the supplied official branding exactly.
           */}
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              letterSpacing: '-0.02em',
              lineHeight: 1.15,
              whiteSpace: 'nowrap',
            }}
          >
            <span style={{ color: '#e2e8f0' }}>Systema</span>
            <span style={{ color: '#38bdf8' }}>Ops</span>
          </div>
          <div
            style={{
              color: '#475569',
              fontSize: 9.5,
              fontWeight: 500,
              marginTop: 3,
              letterSpacing: '0.01em',
              whiteSpace: 'nowrap',
            }}
          >
            Modernization Control Plane
          </div>
        </div>
      </div>

      {/* ── Navigation ── */}
      <div style={{ flex: 1, padding: '6px 8px', overflow: 'hidden' }}>
        <SectionLabel>Main</SectionLabel>
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {NAV_ITEMS.map((item) => (
            <NavItem
              key={item.key}
              icon={item.icon}
              label={item.label}
              isActive={activeKey === item.key}
              onClick={() => onNavigate(item.key)}
            />
          ))}
        </nav>

        <div style={{ height: 8 }} />
        <SectionLabel>Explore</SectionLabel>
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {PLACEHOLDER_ITEMS.map((item) => (
            <NavItem
              key={item.label}
              icon={item.icon}
              label={item.label}
              disabled
            />
          ))}
        </nav>
      </div>

      {/* ── System health ── */}
      <div
        style={{
          padding: '12px 16px 14px',
          borderTop: '1px solid #1e293b',
        }}
      >
        <div
          className="sidebar-label"
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#4ade80',
              flexShrink: 0,
              boxShadow: '0 0 0 2px rgba(74,222,128,0.25)',
            }}
          />
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b' }}>System Status</div>
            <div style={{ fontSize: 10, color: '#4ade80', marginTop: 1 }}>All Systems Operational</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
