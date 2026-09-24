/* Design tokens extracted from reference screenshots.

   Screenshot 1 (Verify Recipe Changes):
   - Light gray-blue page background
   - White stat cards with subtle rounded corners and shadow
   - Teal section headers, uppercase, small, bold
   - Green EXECUTED badges
   - Dark titles, gray subtitles

   Screenshot 2 (Changed Files & Validation):
   - Same card pattern for stats
   - Green dot status indicator ("Passed")
   - Purple-to-blue gradient CTA button
   - Inline validation status row with colored icons
   - Final Validation section card with teal header
*/

export const tokens = {
  colors: {
    // Page
    pageBg: '#f0f2f5',
    cardBg: '#ffffff',
    cardBorder: '#e8eaed',

    // Primary accent (teal — section headers, badges, primary actions)
    primary: '#00897b',
    primaryHover: '#00796b',
    primaryLight: '#e0f2f1',
    primarySoft: 'rgba(0,137,123,0.08)',

    // Secondary accent (purple — CTA gradient start)
    accent: '#7c3aed',
    accentHover: '#6d28d9',

    // Status colors
    success: '#2e7d32',
    successBg: '#e8f5e9',
    successDot: '#4caf50',
    successSoft: 'rgba(46,125,50,0.08)',
    warning: '#f57c00',
    warningBg: '#fff3e0',
    error: '#c62828',
    errorBg: '#ffebee',
    info: '#1565c0',
    infoBg: '#e3f2fd',

    // Surfaces
    surfaceAlt: '#f8f9fa',

    // Text
    textPrimary: '#1a1a2e',
    textSecondary: '#5f6368',
    textMuted: '#9aa0a6',
    textOnPrimary: '#ffffff',

    // Misc
    divider: '#e8eaed',
    shadow: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06)',
    shadowMd: '0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.06)',
    gradient: 'linear-gradient(135deg, #7c3aed 0%, #3b82f6 50%, #06b6d4 100%)',
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
