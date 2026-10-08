import React from 'react';
import { tokens } from '../theme/tokens';
import type { IntegratedProofResponse } from '../api/client';
import { Badge } from './Badge';
import { SectionCard } from './SectionCard';
import { IconCheckCircle, IconAlert, IconXCircle, IconHelp, IconBan, IconDatabase, IconFileText, IconCode, IconLayers } from './icons';

interface IntegratedProofProps {
  proof: IntegratedProofResponse;
}

const proofStateColors: Record<string, { icon: React.ReactNode; color: string; bg: string; label: string }> = {
  VERIFIED: { icon: <IconCheckCircle size={20} />, color: tokens.colors.success, bg: tokens.colors.successBg, label: 'VERIFIED' },
  PARTIAL: { icon: <IconAlert size={20} />, color: tokens.colors.warning, bg: tokens.colors.warningBg, label: 'PARTIAL' },
  BLOCKED: { icon: <IconXCircle size={20} />, color: tokens.colors.error, bg: tokens.colors.errorBg, label: 'BLOCKED' },
  UNPROVEN: { icon: <IconHelp size={20} />, color: tokens.colors.textMuted, bg: tokens.colors.surfaceAlt, label: 'UNPROVEN' },
};

function formatProofState(state: string) {
  const cfg = proofStateColors[state] || proofStateColors.UNPROVEN;
  return cfg;
}

function dependencyKindIcon(kind: string): React.ReactNode {
  switch (kind) {
    case 'PROGRAM': return <IconCode size={20} />;
    case 'COPYBOOK': return <IconFileText size={20} />;
    case 'CALL': return <IconLayers size={20} />;
    case 'FILE': return <IconDatabase size={20} />;
    case 'JCL': return <IconFileText size={20} />;
    case 'DB2': return <IconDatabase size={20} />;
    case 'CICS': return <IconDatabase size={20} />;
    default: return <IconFileText size={20} />;
  }
}

export function IntegratedProof({ proof }: IntegratedProofProps) {
  const { proof: proofData } = proof;
  
  // Group dependencies by kind for display
  const dependenciesByKind: Record<string, Array<typeof proofData.dependency_ledger[0]>> = {};
  proofData.dependency_ledger.forEach(dep => {
    if (!dependenciesByKind[dep.kind]) {
      dependenciesByKind[dep.kind] = [];
    }
    dependenciesByKind[dep.kind].push(dep);
  });
  
  // Order of kinds to display
  const kindOrder = ['PROGRAM', 'COPYBOOK', 'CALL', 'FILE', 'JCL', 'DB2', 'CICS'];
  
  return (
    <>
      <SectionCard title="Integrated Proof">
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
          {/* Application-level proof status */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs }}>
            <div style={{ fontWeight: tokens.font.weights.semibold, fontSize: tokens.font.sizes.sm }}>
              Final Proof Status
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.sm }}>
              {formatProofState(proofData.central_status).icon}
              <span style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.lg }}>
                {proofData.central_status}
              </span>
            </div>
          </div>
          
          {/* Dependencies section */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
            <div style={{ fontWeight: tokens.font.weights.semibold, fontSize: tokens.font.sizes.sm }}>
              Dependencies
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: tokens.spacing.sm }}>
              {kindOrder.map(kind => {
                const deps = dependenciesByKind[kind] || [];
                if (deps.length === 0) return null;
                
                return (
                  <div key={kind} style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: tokens.spacing.xs }}>
                      <span style={{ fontWeight: tokens.font.weights.medium }}>{kind}</span>
                      <span style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>
                        {deps.length} dep{deps.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.xs }}>
                      {deps.map((dep, index) => (
                        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: tokens.spacing.xs }}>
                          {dependencyKindIcon(dep.kind)}
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <span style={{ fontWeight: tokens.font.weights.medium, fontSize: tokens.font.sizes.xs }}>
                              {dep.dependency_id}
                            </span>
                            <span style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textSecondary }}>
                              {dep.reason || ''}
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            {formatProofState(dep.proof_state).icon}
                            <Badge variant={dep.proof_state === 'PROVEN' ? 'success' : dep.proof_state === 'BLOCKED' ? 'error' : 'default'} size="sm">
                              {dep.proof_state}
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }).filter(Boolean)}
            </div>
          </div>
          
          {/* Evidence and runtime status */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
            <div style={{ fontWeight: tokens.font.weights.semibold, fontSize: tokens.font.sizes.sm }}>
              Evidence & Runtime
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: tokens.spacing.sm }}>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Evidence Complete</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.evidence_complete ? 'YES' : 'NO'}
                </div>
              </div>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Evidence Integrity</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.evidence_integrity_valid ? 'VALID' : 'INVALID'}
                </div>
              </div>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Runtime Verdict</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.proof.runtime_verdict_is_verified ? 'VERIFIED' : 'NOT_VERIFIED'}
                </div>
              </div>
            </div>
          </div>
          
          {/* Reasons for NOT VERIFIED */}
          {proof.reasons_for_not_verified.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
              <div style={{ fontWeight: tokens.font.weights.semibold, fontSize: tokens.font.sizes.sm }}>
                Reasons for NOT VERIFIED
              </div>
              <div style={{ background: tokens.colors.surfaceAlt, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                {proof.reasons_for_not_verified.map((reason, index) => (
                  <div key={index} style={{ padding: tokens.spacing.xs, borderBottom: `1px solid ${tokens.colors.divider}` }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sizes.sm }}>
                      • {reason}
                    </span>
                  </div>
                ))}
                {proof.reasons_for_not_verified.length > 0 && (
                  <div key="last" style={{ paddingTop: tokens.spacing.xs }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sizes.xs }}>
                      Total: {proof.reasons_for_not_verified.length} issue{proof.reasons_for_not_verified.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
          
          {/* Summary statistics */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacing.md }}>
            <div style={{ fontWeight: tokens.font.weights.semibold, fontSize: tokens.font.sizes.sm }}>
              Summary
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: tokens.spacing.sm }}>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Proven</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.proven_dependencies.length}
                </div>
              </div>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Unproven</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.unproven_dependencies.length}
                </div>
              </div>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Blocked</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.blocked_dependencies.length}
                </div>
              </div>
              <div style={{ border: `1px solid ${tokens.colors.divider}`, borderRadius: tokens.radii.sm, padding: tokens.spacing.sm }}>
                <div style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textMuted }}>Unsupported</div>
                <div style={{ fontWeight: tokens.font.weights.bold, fontSize: tokens.font.sizes.sm }}>
                  {proof.unsupported_dependencies.length}
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>
    </>
  );
}