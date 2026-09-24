/**
 * Canonical run-stage model shared by all UI surfaces.
 *
 * Mirrors the backend lifecycle in `api/models.py` (RunStage) and the
 * emission order in `api/service.py`:
 *
 *   CREATED → DISCOVERING → DISCOVERY_COMPLETED → ANALYZING →
 *   ANALYSIS_COMPLETED → PLANNING → PLAN_COMPLETED → TRANSFORMING →
 *   GENERATING → ASSEMBLING → ASSEMBLY_COMPLETED → EXECUTING_ORACLE →
 *   BUILDING → EXECUTING_GENERATED → COMPARING → VALIDATING_EVIDENCE →
 *   COMPLETED / FAILED
 *
 * Notes:
 * - `INGESTING` exists in the backend enum but is never emitted by the
 *   modernization worker (ingestion is a separate, synchronous API
 *   operation that completes before the run starts). It is therefore NOT
 *   part of the run stepper. Ingestion is rendered as a completed
 *   pre-run step instead — see `IngestSummary`.
 * - `FAILED` is terminal, not a progression step.
 * - No stage may be added here unless the backend emits it.
 */

import type { RunStage } from './client';

/** Linear run progression in exact backend emission order. */
export const RUN_STAGES: RunStage[] = [
  'CREATED',
  'DISCOVERING',
  'DISCOVERY_COMPLETED',
  'ANALYZING',
  'ANALYSIS_COMPLETED',
  'PLANNING',
  'PLAN_COMPLETED',
  'TRANSFORMING',
  'GENERATING',
  'ASSEMBLING',
  'ASSEMBLY_COMPLETED',
  'EXECUTING_ORACLE',
  'BUILDING',
  'EXECUTING_GENERATED',
  'COMPARING',
  'VALIDATING_EVIDENCE',
  'COMPLETED',
];

export const STAGE_LABELS: Record<RunStage, string> = {
  CREATED: 'Created',
  INGESTING: 'Ingesting',
  DISCOVERING: 'Discovering',
  DISCOVERY_COMPLETED: 'Discovery Complete',
  ANALYZING: 'Analyzing Capabilities',
  ANALYSIS_COMPLETED: 'Analysis Complete',
  PLANNING: 'Planning Transformation',
  PLAN_COMPLETED: 'Plan Complete',
  TRANSFORMING: 'Transforming',
  GENERATING: 'Generating',
  ASSEMBLING: 'Assembling',
  ASSEMBLY_COMPLETED: 'Assembly Complete',
  BUILDING: 'Building',
  EXECUTING_ORACLE: 'Executing Oracle',
  EXECUTING_GENERATED: 'Executing Generated',
  COMPARING: 'Comparing',
  VALIDATING_EVIDENCE: 'Validating Evidence',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
};

export const TERMINAL_STAGES: RunStage[] = ['COMPLETED', 'FAILED'];

export function isTerminalStage(stage: RunStage): boolean {
  return stage === 'COMPLETED' || stage === 'FAILED';
}

/**
 * Summary of the synchronous ingestion step that precedes a run.
 * Populated from POST /applications/{id}/ingest — never fabricated.
 */
export interface IngestSummary {
  applicationId: string;
  sourceFileCount: number;
  detectedName: string;
}
