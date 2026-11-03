/* Design tokens for the SystemaOps Modernization Control Plane.

   Palette decisions:
   - Professional blue primary (#2563eb family) for actions, section
     headers and active states.
   - Navy sidebar (#0f172a family) for the left navigation rail.
   - Amber warning (#d97706) so warnings never read as errors.
   - Slate neutrals for surfaces, dividers and text.
*/

export const tokens = {
  colors: {
    // Page
    pageBg: '#f1f5f9',
    cardBg: '#ffffff',
    cardBorder: '#e2e8f0',

    // Primary accent (blue — section headers, badges, primary actions)
    primary: '#2563eb',
    primaryHover: '#1d4ed8',
    primaryLight: '#eff6ff',
    primarySoft: 'rgba(37,99,235,0.08)',

    // Secondary accent (cyan — CTA gradient end, highlight badges)
    accent: '#0284c7',
    accentHover: '#0369a1',

    // Sidebar (navy)
    sidebarBg: '#0f172a',
    sidebarBorder: '#1e293b',
    sidebarText: '#cbd5e1',
    sidebarTextActive: '#f8fafc',
    sidebarHoverBg: 'rgba(148,163,184,0.12)',
    sidebarActiveBg: '#1d4ed8',

    // Status colors
    success: '#16a34a',
    successBg: '#f0fdf4',
    successDot: '#22c55e',
    successSoft: 'rgba(22,163,74,0.08)',
    warning: '#d97706',
    warningBg: '#fffbeb',
    error: '#dc2626',
    errorBg: '#fef2f2',
    info: '#0284c7',
    infoBg: '#f0f9ff',

    // Surfaces
    surfaceAlt: '#f8fafc',

    // Text
    textPrimary: '#0f172a',
    textSecondary: '#475569',
    textMuted: '#94a3b8',
    textOnPrimary: '#ffffff',

    // Misc
    divider: '#e2e8f0',
    shadow: '0 1px 3px rgba(15,23,42,0.08), 0 1px 2px rgba(15,23,42,0.06)',
    shadowMd: '0 4px 6px rgba(15,23,42,0.07), 0 2px 4px rgba(15,23,42,0.06)',
    gradient: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 50%, #0ea5e9 100%)',
  },

  radii: {
    sm: '6px',
    md: '10px',
    lg: '14px',
    xl: '20px',
    pill: '9999px',
  },

  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
    xxl: '48px',
  },

  font: {
    family: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    sizes: {
      xs: '11px',
      sm: '13px',
      base: '14px',
      md: '16px',
      lg: '20px',
      xl: '28px',
      xxl: '36px',
    },
    weights: {
      normal: 400,
      medium: 500,
      semibold: 600,
      bold: 700,
    },
  },
} as const;

export type Tokens = typeof tokens;
