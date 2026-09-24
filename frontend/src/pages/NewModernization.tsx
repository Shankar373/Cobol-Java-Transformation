import React, { useState, useCallback, useRef } from 'react';
import { tokens } from '../theme/tokens';
import { PageContainer, SectionCard, Button, FileUpload } from '../components';

interface NewModernizationProps {
  onSubmit: (data: {
    name: string;
    workloadId: string;
    description: string;
    zipFile: File;
  }) => void;
  loading?: boolean;
}

function deriveNameFromFilename(filename: string): string {
  const stem = filename.replace(/\.zip$/i, '');
  return stem
    .toLowerCase()
    .replace(/[_\s]+/g, '-')
    .replace(/[^a-z0-9\-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
    || 'application';
}

export function NewModernization({ onSubmit, loading }: NewModernizationProps) {
  const [name, setName] = useState('');
  const [workloadId, setWorkloadId] = useState('');
  const [description, setDescription] = useState('');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipError, setZipError] = useState<string | null>(null);
  const [nameAutoFilled, setNameAutoFilled] = useState(false);
  const nameEditedByUser = useRef(false);

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '10px 14px',
    border: '1px solid ' + tokens.colors.divider,
    borderRadius: tokens.radii.sm,
    fontSize: tokens.font.sizes.base,
    fontFamily: tokens.font.family,
    outline: 'none',
    transition: 'border-color 0.15s',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: tokens.font.sizes.sm,
    fontWeight: tokens.font.weights.semibold,
    color: tokens.colors.textSecondary,
    marginBottom: tokens.spacing.xs,
  };

  const handleFiles = useCallback((files: File[]) => {
    const zip = files.find((f) => f.name.toLowerCase().endsWith('.zip'));
    if (zip) {
      setZipFile(zip);
      setZipError(null);

      // Auto-fill name from ZIP filename if user hasn't edited it
      if (!nameEditedByUser.current) {
        const derived = deriveNameFromFilename(zip.name);
        setName(derived);
        setNameAutoFilled(true);
        // Auto-fill workload ID too
        if (!workloadId) {
          setWorkloadId(`wl-${derived}`);
        }
      }
    } else {
      setZipError('Please select a .zip archive');
    }
  }, [workloadId]);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setName(e.target.value);
    nameEditedByUser.current = true;
    setNameAutoFilled(false);
  };

  const canSubmit = !!name && !!workloadId && !!zipFile && !loading;

  return (
    <PageContainer
      title="New Modernization"
      subtitle="Import a legacy application and start the modernization pipeline"
    >
      <SectionCard title="Application Details">
        <div style={{ display: 'grid', gap: tokens.spacing.md, maxWidth: 600 }}>
          <div>
            <label style={labelStyle} htmlFor="app-name">Application Name *</label>
            <input
              id="app-name"
              style={inputStyle}
              value={name}
              onChange={handleNameChange}
              placeholder={zipFile ? "Auto-detected from archive" : "Select a ZIP archive first, or type a name"}
              required
              aria-required="true"
              aria-describedby={nameAutoFilled ? "name-hint" : undefined}
            />
            {nameAutoFilled && name && (
              <div
                id="name-hint"
                style={{
                  marginTop: tokens.spacing.xs,
                  fontSize: tokens.font.sizes.xs,
                  color: tokens.colors.primary,
                }}
              >
                Detected from uploaded archive
              </div>
            )}
          </div>
          <div>
            <label style={labelStyle} htmlFor="workload-id">Workload ID *</label>
            <input
              id="workload-id"
              style={inputStyle}
              value={workloadId}
              onChange={(e) => setWorkloadId(e.target.value)}
              placeholder="e.g., wl-payroll"
              required
              aria-required="true"
            />
          </div>
          <div>
            <label style={labelStyle} htmlFor="description">Description (optional)</label>
            <input
              id="description"
              style={inputStyle}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of the application"
            />
          </div>
        </div>
      </SectionCard>

      <div style={{ height: tokens.spacing.md }} />

      <SectionCard title="Source Archive">
        <div style={{ marginBottom: tokens.spacing.sm, fontSize: tokens.font.sizes.sm, color: tokens.colors.textMuted }}>
          Upload a ZIP archive containing your legacy application source (COBOL programs, copybooks, JCL).
        </div>
        <FileUpload
          onFiles={handleFiles}
          accept=".zip"
        />
        {zipError && (
          <div
            role="alert"
            style={{
              marginTop: tokens.spacing.sm,
              padding: '8px 12px',
              borderRadius: tokens.radii.sm,
              background: tokens.colors.errorBg,
              color: tokens.colors.error,
              fontSize: tokens.font.sizes.sm,
            }}
          >
            {zipError}
          </div>
        )}
        {zipFile && (
          <div style={{ marginTop: tokens.spacing.md }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 14px',
                borderRadius: tokens.radii.sm,
                background: tokens.colors.surfaceAlt,
                border: '1px solid ' + tokens.colors.cardBorder,
                fontSize: tokens.font.sizes.sm,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm }}>
                <span style={{ fontSize: 18 }}>&#128230;</span>
                <div>
                  <div style={{ fontWeight: tokens.font.weights.medium }}>{zipFile.name}</div>
                  <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.xs }}>
                    {(zipFile.size / 1024).toFixed(1)} KB
                  </div>
                </div>
              </div>
              <button
                onClick={() => { setZipFile(null); setZipError(null); }}
                style={{
                  background: 'none',
                  border: '1px solid ' + tokens.colors.divider,
                  borderRadius: tokens.radii.sm,
                  cursor: 'pointer',
                  color: tokens.colors.error,
                  fontSize: tokens.font.sizes.sm,
                  padding: '4px 10px',
                  transition: 'border-color 0.15s',
                }}
                aria-label={`Remove ${zipFile.name}`}
              >
                Remove
              </button>
            </div>
          </div>
        )}
      </SectionCard>

      <div style={{ height: tokens.spacing.lg }} />

      <div style={{ display: 'flex', gap: tokens.spacing.md, alignItems: 'center' }}>
        <Button
          variant="gradient"
          size="lg"
          disabled={!canSubmit}
          onClick={() => {
            if (zipFile) {
              onSubmit({ name, workloadId, description, zipFile });
            }
          }}
        >
          {loading ? 'Starting...' : 'Start Modernization \u2192'}
        </Button>
        {loading && (
          <span style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textMuted }}>
            Uploading and ingesting source...
          </span>
        )}
      </div>
    </PageContainer>
  );
}
