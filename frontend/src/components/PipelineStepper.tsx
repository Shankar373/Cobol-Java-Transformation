import React from 'react';
import { tokens } from '../theme/tokens';
import type { RunStage } from '../api/client';

/**
 * Customer-facing pipeline stepper — horizontal 7-step presentation.
 *
 * Renders exactly 7 fixed progression nodes regardless of internal lifecycle
 * granularity.  The internal run.stage drives which group is active, but the
 * 7 nodes are defined independently from RUN_STAGES so no duplicates occur.
 *
 * Grouping:
 *   CREATED, DISCOVERING, DISCOVERY_COMPLETED   → Discovery
 *   ANALYZING, ANALYSIS_COMPLETED               → Capability Analysis
 *   PLANNING, PLAN_COMPLETED                    → Transformation Planning
 *   TRANSFORMING, GENERATING, ASSEMBLING,
 *   ASSEMBLY_COMPLETED                          → Transformation & Generation
 *   EXECUTING_ORACLE, BUILDING,
 *   EXECUTING_GENERATED, COMPARING              → Execution & Comparison
 *   VALIDATING_EVIDENCE                         → Evidence Validation
 *   COMPLETED                                   → Completed
 *
 * INGESTING: separate sync operation — NOT a progression node.
 * FAILED: terminal error — shown as an 8th indicator appended at the end.
 */

type NodeStatus = 'done' | 'active' | 'pending' | 'failed';

type GroupKey =
  | 'discovery'
  | 'capability'
  | 'planning'
  | 'transform'
  | 'execution'
  | 'validation'
  | 'completed';

interface CustomerGroup {
  key: GroupKey;
  label: string;
  sublabel: string;
  stages: RunStage[];
}

const CUSTOMER_GROUPS: CustomerGroup[] = [
  {
    key: 'discovery',
    label: 'Discovery',
    sublabel: 'Source analysis',
    stages: ['CREATED', 'DISCOVERING', 'DISCOVERY_COMPLETED'],
  },
  {
    key: 'capability',
    label: 'Capability Analysis',
    sublabel: 'Feature evaluation',
    stages: ['ANALYZING', 'ANALYSIS_COMPLETED'],
  },
  {
    key: 'planning',
    label: 'Transformation Planning',
    sublabel: 'Execution plan',
    stages: ['PLANNING', 'PLAN_COMPLETED'],
  },
  {
    key: 'transform',
    label: 'Transformation & Generation',
    sublabel: 'Java generation',
    stages: ['TRANSFORMING', 'GENERATING', 'ASSEMBLING', 'ASSEMBLY_COMPLETED'],
  },
  {
    key: 'execution',
    label: 'Execution & Comparison',
    sublabel: 'Oracle vs candidate',
    stages: ['EXECUTING_ORACLE', 'BUILDING', 'EXECUTING_GENERATED', 'COMPARING'],
  },
  {
    key: 'validation',
    label: 'Evidence Validation',
    sublabel: 'Artifact verification',
    stages: ['VALIDATING_EVIDENCE'],
  },
  {
    key: 'completed',
    label: 'Completed',
    sublabel: 'Modernization done',
    stages: ['COMPLETED'],
  },
];

function groupIndexForStage(stage: RunStage): number {
  for (let i = 0; i < CUSTOMER_GROUPS.length; i++) {
    if ((CUSTOMER_GROUPS[i].stages as string[]).includes(stage)) return i;
  }
  return -1;
}

function nodeStatus(groupIdx: number, activeGroupIdx: number, isFailed: boolean): NodeStatus {
  if (isFailed) {
    if (groupIdx < activeGroupIdx) return 'done';
    return 'pending';
  }
  if (groupIdx < activeGroupIdx) return 'done';
  if (groupIdx === activeGroupIdx) return 'active';
  return 'pending';
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="5 12.5 10 17.5 19 7" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  );
}

export interface PipelineStepperProps {
  stage: RunStage;
  showIngested?: boolean;
  failedReachedIndex?: number;
}

export function PipelineStepper({ stage }: PipelineStepperProps) {
  const isFailed = stage === 'FAILED';
  const rawIdx = groupIndexForStage(stage);
  const activeGroupIdx = isFailed ? Math.max(0, rawIdx !== -1 ? rawIdx : 0) : Math.max(0, rawIdx);

  const groups = isFailed
    ? [...CUSTOMER_GROUPS, { key: 'failed' as const, label: 'Failed', sublabel: 'Pipeline halted', stages: ['FAILED' as RunStage] }]
    : CUSTOMER_GROUPS;

  return (
    <div
      className="pipeline-h"
      role="list"
      aria-label="Modernization pipeline stages"
    >
      {groups.map((group, i) => {
        const isFinalFailed = group.key === 'failed';
        const status: NodeStatus = isFinalFailed
          ? 'failed'
          : nodeStatus(i, activeGroupIdx, isFailed);

        const dotColorMap: Record<NodeStatus, string> = {
          done: tokens.colors.success,
          active: tokens.colors.primary,
          pending: tokens.colors.cardBorder,
          failed: tokens.colors.error,
        };
        const labelColorMap: Record<NodeStatus, string> = {
          done: tokens.colors.success,
          active: tokens.colors.primary,
          pending: tokens.colors.textMuted,
          failed: tokens.colors.error,
        };

        // Connector: color based on whether this node is done
        const showConnector = i < groups.length - 1;
        const connectorDone = status === 'done';

        return (
          <React.Fragment key={group.key}>
            <div
              className={`pipeline-node-h ${status}`}
              role="listitem"
              aria-label={`${group.label}: ${status}`}
            >
              <div
                className={`pipeline-dot ${status}`}
                style={
                  status === 'pending'
                    ? { background: '#f1f5f9', border: '2px solid #e2e8f0' }
                    : { background: dotColorMap[status] }
                }
              >
                {status === 'done' && <CheckIcon />}
                {status === 'failed' && <XIcon />}
                {status === 'active' && (
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#fff', opacity: 0.9 }} />
                )}
                {status === 'pending' && (
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#cbd5e1' }} />
                )}
              </div>
              <div>
                <div
                  className="pipeline-label"
                  style={{ color: labelColorMap[status], fontWeight: status === 'active' ? 600 : 500 }}
                >
                  {group.label}
                </div>
                <div className="pipeline-sub">{group.sublabel}</div>
              </div>
            </div>
            {showConnector && (
              <div
                aria-hidden="true"
                style={{
                  flex: '1 1 0',
                  height: 2,
                  marginTop: 14,
                  background: connectorDone ? tokens.colors.success : '#e2e8f0',
                  transition: 'background 0.3s',
                  alignSelf: 'flex-start',
                  minWidth: 8,
                  maxWidth: 48,
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}