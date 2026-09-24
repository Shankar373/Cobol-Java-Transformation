import React from 'react';
import { tokens } from '../theme/tokens';
import type { RunStage } from '../api/client';
import { RUN_STAGES } from '../api/stages';

interface StageIndicatorProps {
  current: RunStage;
  error?: string | null;
}

export function StageIndicator({ current, error }: StageIndicatorProps) {
  // FAILED is terminal, not a progression step: render the full backend
  // sequence with no active step and surface the error instead.
  const idx = current === 'FAILED' ? RUN_STAGES.length : RUN_STAGES.indexOf(current);
  const isFailed = current === 'FAILED';

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {RUN_STAGES.map((stage, i) => {
        const isActive = i === idx;
        const isDone = i < idx && !isFailed;
        return (
          <React.Fragment key={stage}>
            {i > 0 && (
              <div
                style={{
                  width: 24,
                  height: 2,
                  background: isDone ? tokens.colors.primary : tokens.colors.divider,
                  borderRadius: 1,
                }}
              />
            )}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 10px',
                borderRadius: tokens.radii.pill,
                fontSize: tokens.font.sizes.xs,
                fontWeight: tokens.font.weights.semibold,
                background: isActive
                  ? tokens.colors.primaryLight
                  : isDone
                  ? tokens.colors.successBg
                  : isFailed && i === idx
                  ? tokens.colors.errorBg
                  : '#f5f5f5',
                color: isActive
                  ? tokens.colors.primary
                  : isDone
                  ? tokens.colors.success
                  : isFailed && i === idx
                  ? tokens.colors.error
                  : tokens.colors.textMuted,
              }}
            >
              <span style={{ fontSize: 10 }}>
                {isDone ? '\u2713' : isActive && !isFailed ? '\u25CF' : isFailed && i === idx ? '\u2717' : '\u25CB'}
              </span>
              {stage}
            </div>
          </React.Fragment>
        );
      })}
      {isFailed && error && (
        <div
          style={{
            fontSize: tokens.font.sizes.xs,
            color: tokens.colors.error,
            marginLeft: tokens.spacing.sm,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
