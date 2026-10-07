import React, { useState, useCallback, useRef } from 'react';
import { tokens } from '../theme/tokens';
import { PageContainer, Button, Header } from '../components';
import { IconFile, IconX, IconDownload } from '../components/icons';

interface NewModernizationProps {
  onSubmit: (data: {
    name: string;
    workloadId: string;
    description: string;
    zipFile: File;
  }) => void;
  loading?: boolean;
  onNavigate?: (page: string, id?: string) => void;
}

function deriveNameFromFilename(filename: string): string {
  const stem = filename.replace(/\.zip$/i, '');
  return (
    stem
      .toLowerCase()
      .replace(/[_\s]+/g, '-')
      .replace(/[^a-z0-9\-]/g, '')
      .replace(/-{2,}/g, '-')
      .replace(/^-|-$/g, '') || 'application'
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type UploadState = 'idle' | 'ready' | 'processing' | 'error';

export function NewModernization({ onSubmit, loading, onNavigate }: NewModernizationProps) {
  const [name, setName] = useState('');
  const [workloadId, setWorkloadId] = useState('');
  const [description, setDescription] = useState('');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipError, setZipError] = useState<string | null>(null);
  const [nameAutoFilled, setNameAutoFilled] = useState(false);
  const [dragging, setDragging] = useState(false);
  const nameEditedByUser = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadState: UploadState = loading
    ? 'processing'
    : zipFile
    ? 'ready'
    : zipError
    ? 'error'
    : 'idle';

  const handleFiles = useCallback(
    (files: File[]) => {
      const zip = files.find((f) => f.name.toLowerCase().endsWith('.zip'));
      if (zip) {
        setZipFile(zip);
        setZipError(null);
        if (!nameEditedByUser.current) {
          const derived = deriveNameFromFilename(zip.name);
          setName(derived);
          setNameAutoFilled(true);
          if (!workloadId) setWorkloadId(`wl-${derived}`);
        }
      } else {
        setZipError('Please select a .zip archive containing your COBOL source.');
      }
    },
    [workloadId],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(Array.from(e.dataTransfer.files));
    },
    [handleFiles],
  );

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setName(e.target.value);
    nameEditedByUser.current = true;
    setNameAutoFilled(false);
  };

  const canSubmit = !!name && !!workloadId && !!zipFile && !loading;

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '10px 14px',
    border: `1px solid ${tokens.colors.divider}`,
    borderRadius: tokens.radii.sm,
    fontSize: tokens.font.sizes.base,
    fontFamily: tokens.font.family,
    outline: 'none',
    transition: 'border-color 0.15s, box-shadow 0.15s',
    background: '#fff',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: tokens.font.sizes.sm,
    fontWeight: tokens.font.weights.semibold,
    color: tokens.colors.textSecondary,
    marginBottom: 6,
  };

  const uploadZoneClass =
    'upload-zone' +
    (dragging ? ' drag-over' : '') +
    (uploadState === 'ready' ? ' has-file' : '');

  return (
    <>
      <Header
        breadcrumb={[
          { label: 'Dashboard', onClick: onNavigate ? () => onNavigate('dashboard') : undefined },
          { label: 'New Modernization' },
        ]}
        title="New Modernization"
        meta={
          <span style={{ fontSize: 12, color: tokens.colors.textMuted }}>
            Upload a legacy COBOL application to begin the modernization pipeline. Upload → Discover → Understand → Plan → Transform → Validate → Certify. Compilation is not certification.
          </span>
        }
      />

      <PageContainer>
        <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* ── Source Archive Upload — first, auto-fills name ── */}
          <div className="card">
            <div className="card-header">
              <span style={{ fontSize: 12, fontWeight: 700, color: tokens.colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Source Archive
              </span>
              <span style={{ fontSize: 11, color: tokens.colors.textMuted }}>
                Upload a ZIP archive containing your legacy application source (COBOL programs, copybooks, JCL)
              </span>
            </div>
            <div style={{ padding: '20px' }}>
              {uploadState === 'ready' && zipFile ? (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '14px 18px',
                    borderRadius: 10,
                    background: tokens.colors.successBg,
                    border: `1px solid ${tokens.colors.successDot}30`,
                  }}
                >
                  <span style={{ color: tokens.colors.success, display: 'flex' }}>
                    <IconFile size={22} />
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: tokens.colors.textPrimary }}>
                      {zipFile.name}
                    </div>
                    <div style={{ fontSize: 12, color: tokens.colors.textMuted, marginTop: 2 }}>
                      {formatBytes(zipFile.size)} — ready to ingest
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove ${zipFile.name}`}
                    onClick={() => { setZipFile(null); setZipError(null); }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      border: `1px solid ${tokens.colors.cardBorder}`,
                      background: '#fff',
                      cursor: 'pointer',
                      color: tokens.colors.textMuted,
                      flexShrink: 0,
                    }}
                  >
                    <IconX size={13} />
                  </button>
                </div>
              ) : (
                <>
                  {/* Drop zone */}
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="Upload ZIP archive"
                    className={uploadZoneClass}
                    onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
                    onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 48,
                        height: 48,
                        borderRadius: 12,
                        background: dragging ? tokens.colors.primarySoft : tokens.colors.surfaceAlt,
                        margin: '0 auto 12px',
                        transition: 'background 0.2s',
                      }}
                    >
                      <IconDownload size={22} />
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: tokens.colors.textSecondary, marginBottom: 4 }}>
                      {dragging ? 'Drop archive here' : 'Drag & drop or click to upload'}
                    </div>
                    <div style={{ fontSize: 12, color: tokens.colors.textMuted }}>
                      Supports .zip archives — COBOL programs, copybooks, JCL
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".zip"
                      style={{ display: 'none' }}
                      onChange={(e) => { if (e.target.files) handleFiles(Array.from(e.target.files)); }}
                    />
                  </div>
                  {zipError && (
                    <div
                      role="alert"
                      style={{
                        marginTop: 10,
                        padding: '9px 14px',
                        borderRadius: tokens.radii.sm,
                        background: tokens.colors.errorBg,
                        color: tokens.colors.error,
                        fontSize: 13,
                        border: `1px solid ${tokens.colors.error}20`,
                      }}
                    >
                      {zipError}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* ── Application Details ── */}
          <div className="card">
            <div className="card-header">
              <span style={{ fontSize: 12, fontWeight: 700, color: tokens.colors.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Application Details
              </span>
            </div>
            <div style={{ padding: '20px', display: 'grid', gap: 16 }}>
              <div>
                <label style={labelStyle} htmlFor="app-name">
                  Application Name <span style={{ color: tokens.colors.error }}>*</span>
                </label>
                <input
                  id="app-name"
                  style={inputStyle}
                  value={name}
                  onChange={handleNameChange}
                  placeholder={zipFile ? 'Auto-detected from archive' : 'Select a ZIP archive first, or enter a name'}
                  required
                  aria-required="true"
                  aria-describedby={nameAutoFilled ? 'name-hint' : undefined}
                />
                {nameAutoFilled && name && (
                  <div id="name-hint" style={{ marginTop: 5, fontSize: 11, color: tokens.colors.primary }}>
                    Detected from uploaded archive
                  </div>
                )}
              </div>

              <div>
                <label style={labelStyle} htmlFor="workload-id">
                  Workload ID <span style={{ color: tokens.colors.error }}>*</span>
                </label>
                <input
                  id="workload-id"
                  style={inputStyle}
                  value={workloadId}
                  onChange={(e) => setWorkloadId(e.target.value)}
                  placeholder="e.g., wl-payroll-system"
                  required
                  aria-required="true"
                />
                <div style={{ marginTop: 5, fontSize: 11, color: tokens.colors.textMuted }}>
                  Unique identifier for this workload (auto-filled from archive name)
                </div>
              </div>

              <div>
                <label style={labelStyle} htmlFor="description">
                  Description <span style={{ color: tokens.colors.textMuted, fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  id="description"
                  style={inputStyle}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief description of the COBOL application"
                />
              </div>
            </div>
          </div>

          {/* ── Submit ── */}
          <div
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
            }}
          >
            <Button
              variant="gradient"
              size="lg"
              disabled={!canSubmit}
              onClick={() => {
                if (zipFile) onSubmit({ name, workloadId, description, zipFile });
              }}
              style={!canSubmit ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
            >
              {loading ? (
                <>
                  <span
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: '50%',
                      border: '2px solid rgba(255,255,255,0.4)',
                      borderTopColor: '#fff',
                      animation: 'spin 0.8s linear infinite',
                      display: 'inline-block',
                    }}
                  />
                  Starting…
                </>
              ) : (
                'Start Modernization →'
              )}
            </Button>

            {loading && (
              <span style={{ fontSize: 12, color: tokens.colors.textMuted }}>
                Uploading source and beginning ingestion…
              </span>
            )}

            {onNavigate && !loading && (
              <Button variant="ghost" onClick={() => onNavigate('dashboard')}>
                Cancel
              </Button>
            )}
          </div>

          {/* ── Pipeline preview ── */}
          {!loading && (
            <div
              style={{
                padding: '14px 18px',
                borderRadius: 10,
                background: tokens.colors.primarySoft,
                border: `1px solid ${tokens.colors.primary}20`,
                fontSize: 12,
                color: tokens.colors.textSecondary,
                lineHeight: 1.6,
              }}
            >
              <div style={{ fontWeight: 600, color: tokens.colors.primary, marginBottom: 4, fontSize: 13 }}>
                Modernization Pipeline
              </div>
              Discovery → Capability Analysis → Transformation Planning → Transformation &amp; Generation → Execution &amp; Comparison → Evidence Validation → <strong>VERIFIED</strong>
            </div>
          )}

        </div>
      </PageContainer>
    </>
  );
}
