import { describe, it, expect } from 'vitest';
import { RUN_STAGES, STAGE_LABELS, isTerminalStage } from '../api/stages';

/**
 * The frontend stepper must match the backend emission order exactly
 * (api/models.py RunStage + api/service.py stage transitions).
 */
describe('run stage order (backend contract)', () => {
  it('matches the exact backend emission sequence', () => {
    expect(RUN_STAGES).toEqual([
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
    ]);
  });

  it('places EXECUTING_ORACLE before BUILDING (oracle runs first in the pipeline)', () => {
    expect(RUN_STAGES.indexOf('EXECUTING_ORACLE')).toBeLessThan(
      RUN_STAGES.indexOf('BUILDING'),
    );
  });

  it('includes DISCOVERY_COMPLETED as its own observable step', () => {
    expect(RUN_STAGES).toContain('DISCOVERY_COMPLETED');
  });

  it('does not treat INGESTING as a run stage (separate sync operation)', () => {
    expect(RUN_STAGES).not.toContain('INGESTING');
  });

  it('does not treat FAILED as a progression step', () => {
    expect(RUN_STAGES).not.toContain('FAILED');
  });

  it('labels every run stage plus terminal FAILED', () => {
    for (const stage of [...RUN_STAGES, 'FAILED' as const]) {
      expect(STAGE_LABELS[stage]).toBeTruthy();
    }
  });

  it('recognises terminal stages', () => {
    expect(isTerminalStage('COMPLETED')).toBe(true);
    expect(isTerminalStage('FAILED')).toBe(true);
    expect(isTerminalStage('BUILDING')).toBe(false);
    expect(isTerminalStage('CREATED')).toBe(false);
  });
});
