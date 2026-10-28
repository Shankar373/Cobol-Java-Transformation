import React, { useCallback, useEffect, useState } from 'react';
import { tokens } from '../theme/tokens';
import { Badge } from './Badge';
import { Button } from './Button';
import { SectionCard } from './SectionCard';
import {
  ApiError,
  getRunApproval,
  setRunApproval,
  type ApprovalState,
  type RunApprovalResponse,
} from '../api/client';

/**
 * Customer approval workflow.
 *
 * Scope notes honoured here:
 * - the approver string is recorded INPUT, not a verified identity (the
 *   panel makes no claim about who the human is; only the bearer token
 *   authenticates the request);
 * - rejection requires a reason, approval reason is optional — the panel
 *   mirrors the backend contract so invalid payloads are not even sent;
 * - a later decision supersedes the earlier one; the panel always shows
 *   the current record and allows a new decision;
 * - no RBAC and no evidence-seal claim anywhere in this component.
 */

interface ApprovalPanelProps {
  runId: string;
  /** Optional callback invoked whenever the approval state changes. */
  onStateChange?: (state: ApprovalState | null) => void;
}

const stateLabel: Record<ApprovalState, string> = {
  PENDING: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
};

const stateVariant: Record<ApprovalState, 'success' | 'error' | 'warning'> = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'error',
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: tokens.font.sizes.sm,
  fontWeight: tokens.font.weights.semibold,
  color: tokens.colors.textSecondary,
  marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '8px 10px',
  border: `1px solid ${tokens.colors.divider}`,
  borderRadius: tokens.radii.sm,
  fontSize: tokens.font.sizes.sm,
  fontFamily: 'inherit',
  background: '#ffffff',
};

export function ApprovalPanel({ runId, onStateChange }: ApprovalPanelProps) {
  const [approval, setApproval] = useState<RunApprovalResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [approver, setApprover] = useState('');
  const [reason, setReason] = useState('');
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const record = await getRunApproval(runId);
      setApproval(record);
      setLoadError(null);
      onStateChange?.(record.state);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
      onStateChange?.(null);
    }
  }, [runId, onStateChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const approverValid = approver.trim().length > 0;
  const reasonValid = reason.trim().length > 0;

  const decide = async (decision: 'APPROVED' | 'REJECTED') => {
    if (!approverValid) return;
    if (decision === 'REJECTED' && !reasonValid) return;
    setSubmitting(true);
    setDecisionError(null);
    try {
      const input: { decision: 'APPROVED' | 'REJECTED'; approver: string; reason?: string } = {
        decision,
        approver: approver.trim(),
      };
      const trimmedReason = reason.trim();
      if (decision === 'REJECTED' || (decision === 'APPROVED' && trimmedReason)) {
        input.reason = trimmedReason;
      }
      await setRunApproval(runId, input);
      setReason('');
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setDecisionError(`Decision rejected: ${e.message}`);
      } else {
        setDecisionError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <SectionCard title="Customer Approval">
        <div style={{ color: tokens.colors.error, fontSize: tokens.font.sizes.sm }}>
          Could not load approval state: {loadError}
        </div>
      </SectionCard>
    );
  }

  if (!approval) {
    return (
      <SectionCard title="Customer Approval">
        <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sizes.sm }}>
          Loading approval state…
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="Customer Approval"
      subtitle={
        'Export (download) is blocked until a reviewer approves this run.'
      }
      headerRight={<Badge variant={stateVariant[approval.state]}>{stateLabel[approval.state]}</Badge>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {approval.state !== 'PENDING' && (
          <div
            data-testid="approval-record"
            style={{
              padding: '8px 12px',
              borderRadius: tokens.radii.sm,
              background: tokens.colors.surfaceAlt,
              fontSize: tokens.font.sizes.sm,
              color: tokens.colors.textSecondary,
            }}
          >
            <div>
              <strong>{stateLabel[approval.state]}</strong>
              {approval.approver ? <> by <strong>{approval.approver}</strong></> : null}
              {approval.decided_at ? <> at {approval.decided_at}</> : null}
            </div>
            {approval.reason && <div>Reason: {approval.reason}</div>}
            {approval.state === 'APPROVED' && !approval.reason && (
              <div>No reason recorded (optional for approval).</div>
            )}
          </div>
        )}

        <div>
          <label className="approval-approver-label" style={labelStyle} htmlFor={`approver-${runId}`}>
            Approver (recorded as entered — not a verified identity)
          </label>
          <input
            id={`approver-${runId}`}
            style={inputStyle}
            type="text"
            placeholder="Approver name…"
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
            disabled={submitting}
          />
        </div>

        <div>
          <label className="approval-reason-label" style={labelStyle} htmlFor={`reason-${runId}`}>
            Reason (required to reject, optional to approve)
          </label>
          <textarea
            id={`reason-${runId}`}
            style={{ ...inputStyle, minHeight: 64, resize: 'vertical' }}
            placeholder="Reason…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={submitting}
          />
        </div>

        {decisionError && (
          <div
            role="alert"
            style={{
              color: tokens.colors.error,
              fontSize: tokens.font.sizes.sm,
              padding: '6px 10px',
              background: tokens.colors.errorBg,
              borderRadius: tokens.radii.sm,
            }}
          >
            {decisionError}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button
            variant="primary"
            size="md"
            onClick={() => void decide('APPROVED')}
            disabled={submitting || !approverValid}
          >
            Approve
          </Button>
          <Button
            variant="secondary"
            size="md"
            onClick={() => void decide('REJECTED')}
            disabled={submitting || !approverValid || !reasonValid}
          >
            Reject
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
