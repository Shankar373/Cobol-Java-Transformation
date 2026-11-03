import React, { useState } from 'react';
import { tokens } from '../theme/tokens';
import { IconCopy } from './icons';

interface CopyButtonProps {
  value: string;
  /** Accessible label, e.g. "Copy src/main/java/App.java". */
  label?: string;
}

/** Copies `value` to the clipboard with visible + screen-reader feedback. */
export function CopyButton({ value, label }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (permissions/insecure context): keep silent —
      // the path is still selectable text next to the button.
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={label ?? `Copy ${value}`}
      title={label ?? `Copy ${value}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        borderRadius: tokens.radii.sm,
        border: `1px solid ${tokens.colors.cardBorder}`,
        background: copied ? tokens.colors.successBg : tokens.colors.cardBg,
        color: copied ? tokens.colors.success : tokens.colors.textSecondary,
        cursor: 'pointer',
        transition: 'background 0.15s, color 0.15s',
      }}
    >
      {copied ? '✓' : <IconCopy size={14} />}
    </button>
  );
}
