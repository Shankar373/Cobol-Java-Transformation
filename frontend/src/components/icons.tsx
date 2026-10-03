import React from 'react';

/**
 * Minimal line-icon set (no emoji, no icon dependency).
 * All icons render as inline SVG in `currentColor` so they inherit
 * the surrounding text color.
 */

export interface IconProps {
  size?: number;
  title?: string;
}

function svg(path: React.ReactNode, { size = 16, title }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      style={{ flexShrink: 0, display: 'block' }}
    >
      {title && <title>{title}</title>}
      {path}
    </svg>
  );
}

export const IconGrid = (p: IconProps = {}) =>
  svg(
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>,
    p,
  );

export const IconPlus = (p: IconProps = {}) =>
  svg(
    <>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </>,
    p,
  );

export const IconBox = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M21 8.5v7l-9 5-9-5v-7l9-5 9 5z" />
      <path d="M3.3 7.7l8.7 4.9 8.7-4.9" />
      <line x1="12" y1="12.6" x2="12" y2="20.5" />
    </>,
    p,
  );

export const IconPulse = (p: IconProps = {}) =>
  svg(<polyline points="3 12 7 12 10 5 14 19 17 12 21 12" />, p);

export const IconCheckCircle = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <polyline points="8 12.5 11 15.5 16.5 9" />
    </>,
    p,
  );

export const IconClock = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15.5 14" />
    </>,
    p,
  );

export const IconXCircle = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="9" y1="9" x2="15" y2="15" />
      <line x1="15" y1="9" x2="9" y2="15" />
    </>,
    p,
  );

export const IconAlert = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M12 4l9 16H3l9-16z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <line x1="12" y1="17" x2="12" y2="17.01" />
    </>,
    p,
  );

export const IconHelp = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.4" />
      <line x1="12" y1="16.8" x2="12" y2="16.9" />
    </>,
    p,
  );

export const IconBan = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
    </>,
    p,
  );

export const IconInbox = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M4 13h4l1.5 3h5L16 13h4" />
      <path d="M5.4 5.6h13.2L21 13v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5l2.4-7.4z" />
    </>,
    p,
  );

export const IconCopy = (p: IconProps = {}) =>
  svg(
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v1" />
    </>,
    p,
  );

export const IconDownload = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M12 4v10" />
      <polyline points="8 10.5 12 14.5 16 10.5" />
      <path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" />
    </>,
    p,
  );

export const IconCheck = (p: IconProps = {}) =>
  svg(<polyline points="5 12.5 10 17.5 19 7" />, p);

export const IconX = (p: IconProps = {}) =>
  svg(
    <>
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </>,
    p,
  );

export const IconFile = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7l-4-4z" />
      <polyline points="14 3 14 7 18 7" />
    </>,
    p,
  );

export const IconFileText = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7l-4-4z" />
      <polyline points="14 3 14 7 18 7" />
      <line x1="9" y1="12" x2="15" y2="12" />
      <line x1="9" y1="15.5" x2="15" y2="15.5" />
    </>,
    p,
  );

export const IconCode = (p: IconProps = {}) =>
  svg(
    <>
      <polyline points="9 7 4.5 12 9 17" />
      <polyline points="15 7 19.5 12 15 17" />
      <line x1="13" y1="5" x2="11" y2="19" />
    </>,
    p,
  );

export const IconDatabase = (p: IconProps = {}) =>
  svg(
    <>
      <ellipse cx="12" cy="6" rx="7.5" ry="3" />
      <path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6" />
      <path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3" />
    </>,
    p,
  );

export const IconPackage = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M20.5 7.5v9L12 21l-8.5-4.5v-9L12 3l8.5 4.5z" />
      <path d="M3.5 7.5L12 12l8.5-4.5" />
      <line x1="12" y1="12" x2="12" y2="21" />
    </>,
    p,
  );

export const IconTimer = (p: IconProps = {}) =>
  svg(
    <>
      <circle cx="12" cy="13.5" r="7.5" />
      <line x1="12" y1="9.5" x2="12" y2="13.5" />
      <line x1="10" y1="2.5" x2="14" y2="2.5" />
      <line x1="12" y1="2.5" x2="12" y2="6" />
    </>,
    p,
  );

export const IconLayers = (p: IconProps = {}) =>
  svg(
    <>
      <polygon points="12 3 21 7.5 12 12 3 7.5 12 3" />
      <polyline points="3 12.5 12 17 21 12.5" />
      <polyline points="3 16.5 12 21 21 16.5" />
    </>,
    p,
  );

export const IconChevronRight = (p: IconProps = {}) =>
  svg(<polyline points="9 5 16 12 9 19" />, p);

export const IconShieldCheck = (p: IconProps = {}) =>
  svg(
    <>
      <path d="M12 3l7.5 3v5.5c0 4.4-3.1 8-7.5 9.5-4.4-1.5-7.5-5.1-7.5-9.5V6L12 3z" />
      <polyline points="8.5 12 11 14.5 15.5 9.5" />
    </>,
    p,
  );
