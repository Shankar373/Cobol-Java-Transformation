import React, { useCallback, useEffect, useRef, useState } from 'react';
import { tokens } from '../theme/tokens';
import { PageContainer, Button, Header, EmptyState } from '../components';
import * as api from '../api/client';
import type { ApplicationResponse, VsamJob, VsamManifest } from '../api/client';

const POLL_INTERVAL_MS = 2000;
const CODE_PAGES = ['ascii', 'cp037', 'cp500', 'cp1047', 'cp1140', 'latin-1'];
const SHA256_RE = /^[0-9a-fA-F]{64}$/;

export interface VsamFormValues {
  datasetName: string;
  runtimePath: string;
  organization: 'KSDS' | 'ESDS' | 'RRDS';
  recordFormat: 'FIXED' | 'VARIABLE_RDW';
  minRecordLength: string;
  maxRecordLength: string;
  keyOffset: string;
  keyLength: string;
  codePage: string;
  recordCount: string;
  sha256: string;
  exportPlatform: string;
  exportTool: string;
  exportToolVersion: string;
  provenance: string;
  cobolSource: string;
  cobolFile: string;
}

const INITIAL_VALUES: VsamFormValues = {
  datasetName: '',
  runtimePath: '',
  organization: 'KSDS',
  recordFormat: 'FIXED',
  minRecordLength: '',
  maxRecordLength: '',
  keyOffset: '0',
  keyLength: '',
  codePage: 'ascii',
  recordCount: '',
  sha256: '',
  exportPlatform: '',
  exportTool: '',
  exportToolVersion: '',
  provenance: '',
  cobolSource: '',
  cobolFile: '',
};

function isPositiveInt(v: string): boolean {
  return /^\d+$/.test(v.trim()) && Number(v) > 0;
}

function isNonNegativeInt(v: string): boolean {
  return /^\d+$/.test(v.trim());
}

/** Client-side validation; returns field -> message (empty when valid). */
export function validateVsamForm(v: VsamFormValues, file: File | null): Record<string, string> {
  const e: Record<string, string> = {};
  const required: [keyof VsamFormValues, string][] = [
    ['datasetName', 'Dataset name is required.'],
    ['runtimePath', 'Runtime path is required.'],
    ['exportPlatform', 'Export platform is required.'],
    ['exportTool', 'Export tool is required.'],
    ['exportToolVersion', 'Export tool version is required.'],
    ['provenance', 'Provenance is required.'],
  ];
  for (const [k, msg] of required) if (!v[k].trim()) e[k] = msg;
  if (!file) e.file = 'Select the VSAM export file to upload.';
  else if (file.size <= 0) e.file = 'The selected file is empty.';
  if (!isPositiveInt(v.minRecordLength)) e.minRecordLength = 'Enter a positive whole number.';
  if (v.recordFormat === 'VARIABLE_RDW' && !isPositiveInt(v.maxRecordLength)) {
    e.maxRecordLength = 'Enter a positive whole number.';
  }
  if (
    v.recordFormat === 'VARIABLE_RDW' && !e.minRecordLength && !e.maxRecordLength &&
    Number(v.minRecordLength) > Number(v.maxRecordLength)
  ) {
    e.maxRecordLength = 'Maximum must be at least the minimum.';
  }
  if (v.organization === 'KSDS') {
    if (!isPositiveInt(v.keyLength)) e.keyLength = 'Enter a positive whole number.';
    if (!isNonNegativeInt(v.keyOffset)) e.keyOffset = 'Enter zero or a positive whole number.';
  }
  if (!isPositiveInt(v.recordCount)) e.recordCount = 'Enter a positive whole number.';
  if (!SHA256_RE.test(v.sha256.trim())) e.sha256 = 'SHA-256 must be 64 hexadecimal characters.';
  return e;
}

function buildManifest(v: VsamFormValues, datasetBytes: number): VsamManifest {
  const fixed = v.recordFormat === 'FIXED';
  const min = Number(v.minRecordLength);
  const isKsds = v.organization === 'KSDS';
  return {
    dataset_name: v.datasetName.trim(),
    organization: v.organization,
    layout: {
      record_format: v.recordFormat,
      min_record_length: min,
      max_record_length: fixed ? min : Number(v.maxRecordLength),
      key_offset: isKsds ? Number(v.keyOffset) : 0,
      key_length: isKsds ? Number(v.keyLength) : 0,
      code_page: v.codePage,
    },
    duplicate_keys: 'REJECT',
    alternate_keys: [],
    record_count: Number(v.recordCount),
    dataset_bytes: datasetBytes,
    sha256: v.sha256.trim().toLowerCase(),
    export_platform: v.exportPlatform.trim(),
    export_tool: v.exportTool.trim(),
    export_tool_version: v.exportToolVersion.trim(),
    provenance: v.provenance.trim(),
  };
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-US');
}

const REFUSED_EXPLANATION =
  'The migration was refused: the submitted manifest, layout or COBOL definition was rejected. ' +
  'Retrying the same input will give the same result. Change the input and submit again.';
const FAILED_EXPLANATION =
  'The migration failed while processing the export. Check the error below; you can correct the input and submit again.';

type Phase = 'idle' | 'submitting' | 'polling' | 'done';

interface Attempt {
  key: string;
  signature: string;
}

interface VsamMigrationProps {
  applications: ApplicationResponse[];
  initialApplicationId?: string | null;
  onNavigate?: (page: string, id?: string) => void;
  authRequired?: boolean;
  pollIntervalMs?: number;
}

export function VsamMigration({
  applications,
  initialApplicationId,
  onNavigate,
  authRequired,
  pollIntervalMs = POLL_INTERVAL_MS,
}: VsamMigrationProps) {
  const [appId, setAppId] = useState(initialApplicationId ?? '');
  const [values, setValues] = useState<VsamFormValues>(INITIAL_VALUES);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState<Phase>('idle');
  const [job, setJob] = useState<VsamJob | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const attempt = useRef<Attempt | null>(null);
  const mounted = useRef(true);
  const runId = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      runId.current += 1;
    };
  }, []);

  const set = <K extends keyof VsamFormValues>(k: K, val: VsamFormValues[K]) =>
    setValues((prev) => ({ ...prev, [k]: val }));

  const selectedAppId = appId || applications[0]?.id || '';

  const handleApiError = useCallback((err: unknown, prefix: string): string => {
    if (err instanceof api.ApiError && err.status === 401) {
      setUnauthorized(true);
      return `${prefix}: authentication required. Enter your API token on the Dashboard, then retry.`;
    }
    return `${prefix}: ${err instanceof Error ? err.message : String(err)}`;
  }, []);

  const pollUntilTerminal = useCallback(
    async (jobId: string, token: number, first: VsamJob) => {
      let current = first;
      while (!api.isVsamTerminal(current.state)) {
        await new Promise((r) => setTimeout(r, pollIntervalMs));
        if (!mounted.current || runId.current !== token) return;
        try {
          current = await api.getVsamMigration(jobId);
          if (!mounted.current || runId.current !== token) return;
          setPollWarning(null);
          setJob(current);
        } catch (err) {
          if (!mounted.current || runId.current !== token) return;
          if (err instanceof api.ApiError && err.status === 401) {
            setUnauthorized(true);
            setSubmitError('Status check failed: authentication required. Enter your API token on the Dashboard.');
            setPhase('idle');
            return;
          }
          setPollWarning(`Could not refresh status (${err instanceof Error ? err.message : String(err)}); retrying.`);
        }
      }
      setPhase('done');
    },
    [pollIntervalMs],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (phase === 'submitting' || phase === 'polling') return;
    const found = validateVsamForm(values, file);
    if (!selectedAppId) found.application = 'Select an application.';
    setErrors(found);
    if (Object.keys(found).length > 0 || !file) return;

    const manifest = buildManifest(values, file.size);
    const signature = JSON.stringify([
      selectedAppId, values.runtimePath.trim(), manifest, values.cobolSource, values.cobolFile,
      file.name, file.lastModified,
    ]);
    // One idempotency key per submission attempt; a retry with unchanged
    // input reuses it, changed input starts a new attempt.
    if (!attempt.current || attempt.current.signature !== signature) {
      attempt.current = { key: crypto.randomUUID(), signature };
    }
    const token = (runId.current += 1);
    setPhase('submitting');
    setSubmitError(null);
    setUnauthorized(false);
    setDownloadError(null);
    setPollWarning(null);
    setJob(null);

    let created: VsamJob;
    try {
      created = await api.createVsamMigration(selectedAppId, {
        idempotency_key: attempt.current.key,
        runtime_path: values.runtimePath.trim(),
        manifest,
        ...(values.cobolSource.trim() ? { cobol_source: values.cobolSource } : {}),
        ...(values.cobolFile.trim() ? { cobol_file: values.cobolFile.trim() } : {}),
      });
    } catch (err) {
      if (!mounted.current || runId.current !== token) return;
      setSubmitError(handleApiError(err, 'Could not create the migration job'));
      setPhase('idle');
      return;
    }
    if (!mounted.current || runId.current !== token) return;
    setJob(created);
    if (api.isVsamTerminal(created.state)) {
      setPhase('done');
      return;
    }
    if (created.state === 'CREATED') {
      try {
        await api.uploadVsamExport(created.upload_path ?? '', file);
      } catch (err) {
        if (!mounted.current || runId.current !== token) return;
        setSubmitError(
          `${handleApiError(err, 'Upload failed')}. You can retry; the same idempotency key is reused.`,
        );
        setPhase('idle');
        return;
      }
      if (!mounted.current || runId.current !== token) return;
    }
    setPhase('polling');
    await pollUntilTerminal(created.job_id, token, created);
  };

  const handleDownload = async () => {
    if (!job) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await api.downloadVsamMigration(job.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = job.output_name || `${job.job_id}.vsam`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(handleApiError(err, 'Download failed'));
    } finally {
      setDownloading(false);
    }
  };

  const busy = phase === 'submitting' || phase === 'polling';
  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '8px 12px',
    border: `1px solid ${tokens.colors.divider}`,
    borderRadius: tokens.radii.sm,
    fontSize: tokens.font.sizes.base,
    fontFamily: tokens.font.family,
    background: '#fff',
  };
  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: tokens.font.sizes.sm,
    fontWeight: tokens.font.weights.semibold,
    color: tokens.colors.textSecondary,
    marginBottom: 4,
  };
  const errStyle: React.CSSProperties = { color: tokens.colors.error, fontSize: tokens.font.sizes.xs, marginTop: 3 };
  const bannerStyle: React.CSSProperties = {
    marginTop: 16,
    padding: '10px 14px',
    borderRadius: tokens.radii.sm,
    background: tokens.colors.errorBg,
    color: tokens.colors.error,
    fontSize: tokens.font.sizes.sm,
  };
  const cardStyle: React.CSSProperties = { padding: 20, display: 'flex', flexDirection: 'column', gap: 14 };
  const grid: React.CSSProperties = {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: 14,
  };

  const field = (id: keyof VsamFormValues, label: string, placeholder?: string) => (
    <div key={id}>
      <label htmlFor={`vsam-${id}`} style={labelStyle}>{label}</label>
      <input
        id={`vsam-${id}`}
        style={inputStyle}
        type="text"
        placeholder={placeholder}
        value={values[id]}
        disabled={busy}
        onChange={(ev) => set(id, ev.target.value as never)}
        aria-invalid={errors[id] ? true : undefined}
      />
      {errors[id] && <div role="alert" style={errStyle}>{errors[id]}</div>}
    </div>
  );

  const selectField = (
    id: keyof VsamFormValues,
    label: string,
    options: string[],
  ) => (
    <div key={id}>
      <label htmlFor={`vsam-${id}`} style={labelStyle}>{label}</label>
      <select
        id={`vsam-${id}`}
        style={inputStyle}
        value={values[id]}
        disabled={busy}
        onChange={(ev) => set(id, ev.target.value as never)}
      >
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );

  const total = job?.dataset_bytes ?? null;
  const done = job?.bytes_processed ?? null;
  const showProgress = total !== null && total > 0 && done !== null;

  return (
    <>
      <Header
        breadcrumb={[
          { label: 'Dashboard', onClick: onNavigate ? () => onNavigate('dashboard') : undefined },
          { label: 'VSAM Migration' },
        ]}
        title="VSAM Migration"
        meta={
          <span style={{ fontSize: 12, color: tokens.colors.textMuted }}>
            Upload a VSAM export and its manifest. A migration is only reported as succeeded once the backend confirms it.
          </span>
        }
      />
      <PageContainer>
        {applications.length === 0 ? (
          <EmptyState
            title="No applications available"
            description={
              authRequired
                ? 'Authentication required: enter your API token on the Dashboard to load applications.'
                : 'Create an application with New Modernization before migrating VSAM data.'
            }
          />
        ) : (
          <form onSubmit={handleSubmit} noValidate style={{ maxWidth: 820, display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="card" style={cardStyle}>
              <div>
                <label htmlFor="vsam-application" style={labelStyle}>Application</label>
                <select
                  id="vsam-application"
                  style={inputStyle}
                  value={selectedAppId}
                  disabled={busy}
                  onChange={(ev) => setAppId(ev.target.value)}
                >
                  {applications.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div style={grid}>
                {field('datasetName', 'Dataset name')}
                {field('runtimePath', 'Runtime path', 'e.g. data/customer.vsam')}
                {selectField('organization', 'Organization', ['KSDS', 'ESDS', 'RRDS'])}
                {selectField('recordFormat', 'Record format', ['FIXED', 'VARIABLE_RDW'])}
                {field('minRecordLength', values.recordFormat === 'FIXED' ? 'Record length' : 'Minimum record length')}
                {values.recordFormat === 'VARIABLE_RDW' && field('maxRecordLength', 'Maximum record length')}
                {values.organization === 'KSDS' && field('keyLength', 'Key length')}
                {values.organization === 'KSDS' && field('keyOffset', 'Key offset')}
                {selectField('codePage', 'Code page', CODE_PAGES)}
                {field('recordCount', 'Record count')}
              </div>
              {field('sha256', 'SHA-256 of the export file')}
              <div style={grid}>
                {field('exportPlatform', 'Export platform')}
                {field('exportTool', 'Export tool')}
                {field('exportToolVersion', 'Export tool version')}
                {field('provenance', 'Provenance')}
              </div>
            </div>

            <div className="card" style={cardStyle}>
              <div>
                <label htmlFor="vsam-cobolSource" style={labelStyle}>
                  COBOL source for SELECT/FD validation (optional)
                </label>
                <textarea
                  id="vsam-cobolSource"
                  style={{ ...inputStyle, minHeight: 90, fontFamily: 'monospace' }}
                  value={values.cobolSource}
                  disabled={busy}
                  onChange={(ev) => set('cobolSource', ev.target.value)}
                />
              </div>
              {values.cobolSource.trim() && field('cobolFile', 'COBOL file name (SELECT entry)')}
            </div>

            <div className="card" style={{ padding: 20 }}>
              <label htmlFor="vsam-file" style={labelStyle}>VSAM export file</label>
              <input
                id="vsam-file"
                type="file"
                disabled={busy}
                onChange={(ev) => setFile(ev.target.files?.[0] ?? null)}
              />
              <div style={{ fontSize: 12, color: tokens.colors.textMuted, marginTop: 6 }}>
                {file
                  ? `${file.name}: ${formatNumber(file.size)} bytes (sent as dataset_bytes)`
                  : 'No file selected.'}
              </div>
              {errors.file && <div role="alert" style={errStyle}>{errors.file}</div>}
              {errors.application && <div role="alert" style={errStyle}>{errors.application}</div>}
            </div>

            <div>
              <Button type="submit" disabled={busy}>
                {phase === 'submitting' ? 'Submitting...' : submitError ? 'Retry migration' : 'Start migration'}
              </Button>
            </div>
          </form>
        )}

        {unauthorized && (
          <div role="alert" style={bannerStyle}>
            Authentication required (401). Enter your API token on the Dashboard and retry.
          </div>
        )}
        {submitError && !unauthorized && (
          <div role="alert" style={bannerStyle}>{submitError}</div>
        )}

        {job && (
          <div className="card" style={{ marginTop: 16, padding: 20, maxWidth: 820 }} aria-label="Migration status">
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: tokens.font.sizes.sm, color: tokens.colors.textSecondary }}>State</span>
              <strong data-testid="vsam-state">{job.state}</strong>
              <span style={{ fontSize: 11, color: tokens.colors.textMuted, fontFamily: 'monospace' }}>job {job.job_id}</span>
            </div>
            <div style={{ marginTop: 10, fontSize: tokens.font.sizes.sm }}>
              Records processed: {job.records !== null && job.records !== undefined ? formatNumber(job.records) : 'not reported yet'}
            </div>
            {showProgress && (
              <div style={{ marginTop: 10 }}>
                <progress value={done as number} max={total as number} aria-label="Bytes processed" style={{ width: '100%' }} />
                <div style={{ fontSize: 12, color: tokens.colors.textMuted }}>
                  {formatNumber(done as number)} of {formatNumber(total as number)} bytes processed
                </div>
              </div>
            )}
            {pollWarning && (
              <div role="status" style={{ marginTop: 8, fontSize: 12, color: tokens.colors.warning }}>{pollWarning}</div>
            )}

            {job.state === 'SUCCEEDED' && (
              <div style={{ marginTop: 14 }}>
                <div role="status" style={{ color: tokens.colors.success, fontWeight: 600 }}>
                  Migration succeeded. The backend confirmed the output
                  {job.output_sha256 ? ` (SHA-256 ${job.output_sha256})` : ''}.
                </div>
                <div style={{ marginTop: 10 }}>
                  <Button type="button" onClick={handleDownload} disabled={downloading}>
                    {downloading ? 'Downloading...' : 'Download migrated dataset'}
                  </Button>
                </div>
                {downloadError && <div role="alert" style={errStyle}>{downloadError}</div>}
              </div>
            )}

            {(job.state === 'REFUSED' || job.state === 'FAILED') && (
              <div role="alert" style={{ ...bannerStyle, marginTop: 14 }}>
                <div style={{ fontWeight: 600 }}>
                  {job.state === 'REFUSED' ? REFUSED_EXPLANATION : FAILED_EXPLANATION}
                </div>
                <div style={{ marginTop: 6 }}>
                  Error code: <code>{job.error_code ?? 'unknown'}</code>
                </div>
                <div>{job.error_message ?? 'No message was provided by the server.'}</div>
              </div>
            )}
          </div>
        )}
      </PageContainer>
    </>
  );
}
