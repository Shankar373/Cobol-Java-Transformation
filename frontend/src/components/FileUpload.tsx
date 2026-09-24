import React, { useCallback, useRef, useState } from 'react';
import { tokens } from '../theme/tokens';

interface FileUploadProps {
  onFiles: (files: File[]) => void;
  accept?: string;
  label?: string;
}

export function FileUpload({ onFiles, accept, label }: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    },
    [onFiles],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length > 0) onFiles(files);
      e.target.value = '';
    },
    [onFiles],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        inputRef.current?.click();
      }
    },
    [],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={label || 'Upload file'}
      style={{
        border: '2px dashed ' + (dragOver ? tokens.colors.primary : tokens.colors.divider),
        borderRadius: tokens.radii.md,
        padding: `${tokens.spacing.xl} ${tokens.spacing.lg}`,
        textAlign: 'center',
        cursor: 'pointer',
        background: dragOver ? tokens.colors.primaryLight : tokens.colors.cardBg,
        transition: 'border-color 0.2s, background 0.2s',
        outline: 'none',
      }}
    >
      <div style={{ fontSize: 36, marginBottom: tokens.spacing.sm }} aria-hidden="true">&#128194;</div>
      <div
        style={{
          fontSize: tokens.font.sizes.md,
          fontWeight: tokens.font.weights.semibold,
          color: tokens.colors.textPrimary,
          marginBottom: tokens.spacing.xs,
        }}
      >
        Drop your ZIP archive here
      </div>
      <div style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textMuted }}>
        or click to browse
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        style={{ display: 'none' }}
        aria-hidden="true"
        tabIndex={-1}
      />
    </div>
  );
}
