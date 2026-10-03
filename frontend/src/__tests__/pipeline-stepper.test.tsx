import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { PipelineStepper } from '../components/PipelineStepper';

/**
 * PipelineStepper customer-facing node requirements.
 *
 * Must render exactly 7 fixed progression nodes regardless of which
 * internal lifecycle stage is active.
 */

const EXPECTED_7_NODES = [
  'Discovery',
  'Capability Analysis',
  'Transformation Planning',
  'Transformation & Generation',
  'Execution & Comparison',
  'Evidence Validation',
  'Completed',
] as const;

describe('PipelineStepper — exactly 7 customer-facing nodes', () => {
  it('renders exactly 7 nodes when stage is DISCOVERING', () => {
    render(<PipelineStepper stage="DISCOVERING" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is ANALYZING', () => {
    render(<PipelineStepper stage="ANALYZING" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is PLANNING', () => {
    render(<PipelineStepper stage="PLANNING" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is GENERATING', () => {
    render(<PipelineStepper stage="GENERATING" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is COMPARING', () => {
    render(<PipelineStepper stage="COMPARING" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is VALIDATING_EVIDENCE', () => {
    render(<PipelineStepper stage="VALIDATING_EVIDENCE" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders exactly 7 nodes when stage is COMPLETED', () => {
    render(<PipelineStepper stage="COMPLETED" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });

  it('renders 8 nodes when stage is FAILED (7 + terminal failed node)', () => {
    render(<PipelineStepper stage="FAILED" />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(8);
  });
});

describe('PipelineStepper — correct node labels (no duplicates)', () => {
  it('renders all 7 expected labels exactly once', () => {
    render(<PipelineStepper stage="DISCOVERING" />);
    for (const label of EXPECTED_7_NODES) {
      const matches = screen.getAllByText(label);
      expect(matches).toHaveLength(1);
    }
  });

  it('has no duplicate visible progression labels', () => {
    const { container } = render(<PipelineStepper stage="ANALYZING" />);
    const text = container.textContent ?? '';
    for (const label of EXPECTED_7_NODES) {
      // Each label should appear exactly once
      const first = text.indexOf(label);
      const second = text.indexOf(label, first + 1);
      expect(second).toBe(-1);
    }
  });
});

describe('PipelineStepper — PLANNING and PLAN_COMPLETED mapping', () => {
  it('maps PLANNING to Transformation Planning node', () => {
    render(<PipelineStepper stage="PLANNING" />);
    expect(screen.getByText('Transformation Planning')).toBeInTheDocument();
  });

  it('maps PLAN_COMPLETED to Transformation Planning node', () => {
    render(<PipelineStepper stage="PLAN_COMPLETED" />);
    expect(screen.getByText('Transformation Planning')).toBeInTheDocument();
  });

  it('marks Transformation Planning as active when stage is PLANNING', () => {
    render(<PipelineStepper stage="PLANNING" />);
    const planningItem = screen.getByRole('listitem', { name: /Transformation Planning: active/i });
    expect(planningItem).toBeInTheDocument();
  });

  it('marks Transformation Planning as active when stage is PLAN_COMPLETED', () => {
    render(<PipelineStepper stage="PLAN_COMPLETED" />);
    const planningItem = screen.getByRole('listitem', { name: /Transformation Planning: active/i });
    expect(planningItem).toBeInTheDocument();
  });
});

describe('PipelineStepper — dynamic progression', () => {
  it('shows Discovery as active on DISCOVERING', () => {
    render(<PipelineStepper stage="DISCOVERING" />);
    expect(screen.getByRole('listitem', { name: /Discovery: active/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Capability Analysis: pending/i })).toBeInTheDocument();
  });

  it('shows Capability Analysis as active on ANALYZING', () => {
    render(<PipelineStepper stage="ANALYZING" />);
    expect(screen.getByRole('listitem', { name: /Discovery: done/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Capability Analysis: active/i })).toBeInTheDocument();
  });

  it('shows Transformation Planning as active on PLANNING', () => {
    render(<PipelineStepper stage="PLANNING" />);
    expect(screen.getByRole('listitem', { name: /Capability Analysis: done/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Transformation Planning: active/i })).toBeInTheDocument();
  });

  it('shows Transformation & Generation as active on GENERATING', () => {
    render(<PipelineStepper stage="GENERATING" />);
    expect(screen.getByRole('listitem', { name: /Transformation Planning: done/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Transformation & Generation: active/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Execution & Comparison: pending/i })).toBeInTheDocument();
  });

  it('shows Execution & Comparison as active on COMPARING', () => {
    render(<PipelineStepper stage="COMPARING" />);
    expect(screen.getByRole('listitem', { name: /Transformation & Generation: done/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Execution & Comparison: active/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Evidence Validation: pending/i })).toBeInTheDocument();
  });

  it('shows Evidence Validation as active on VALIDATING_EVIDENCE', () => {
    render(<PipelineStepper stage="VALIDATING_EVIDENCE" />);
    expect(screen.getByRole('listitem', { name: /Execution & Comparison: done/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Evidence Validation: active/i })).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Completed: pending/i })).toBeInTheDocument();
  });

  it('shows all 7 nodes as done/active on COMPLETED', () => {
    render(<PipelineStepper stage="COMPLETED" />);
    for (const label of EXPECTED_7_NODES) {
      // All nodes should be in done state on COMPLETED
      const item = screen.getByText(label).closest('[role="listitem"]');
      expect(item).not.toBeNull();
      const ariaLabel = item!.getAttribute('aria-label') ?? '';
      // Completed stage: all groups before 'completed' are 'done', 'completed' itself is 'active'
      expect(ariaLabel).toMatch(/: (done|active)/i);
    }
  });
});

describe('PipelineStepper — INGESTING is not a progression node', () => {
  it('never renders INGESTING as a node', () => {
    render(<PipelineStepper stage="DISCOVERING" />);
    expect(screen.queryByText('Ingesting')).not.toBeInTheDocument();
    expect(screen.queryByText('INGESTING')).not.toBeInTheDocument();
  });

  it('still renders 7 nodes even when showIngested is true', () => {
    render(<PipelineStepper stage="DISCOVERING" showIngested />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
  });
});

describe('PipelineStepper — FAILED terminal handling', () => {
  it('shows Failed as the 8th node on FAILED stage', () => {
    render(<PipelineStepper stage="FAILED" />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(8);
    // Failed node has aria-label containing 'failed'
    expect(screen.getByRole('listitem', { name: /Failed: failed/i })).toBeInTheDocument();
  });
});

describe('PipelineStepper — all internal stages map to exactly one group', () => {
  const ALL_INTERNAL_STAGES = [
    'CREATED', 'DISCOVERING', 'DISCOVERY_COMPLETED',
    'ANALYZING', 'ANALYSIS_COMPLETED',
    'PLANNING', 'PLAN_COMPLETED',
    'TRANSFORMING', 'GENERATING', 'ASSEMBLING', 'ASSEMBLY_COMPLETED',
    'EXECUTING_ORACLE', 'BUILDING', 'EXECUTING_GENERATED', 'COMPARING',
    'VALIDATING_EVIDENCE',
    'COMPLETED',
  ] as const;

  for (const stage of ALL_INTERNAL_STAGES) {
    it(`renders exactly 7 nodes for stage ${stage}`, () => {
      render(<PipelineStepper stage={stage as import('../api/client').RunStage} />);
      const items = screen.getAllByRole('listitem');
      expect(items).toHaveLength(7);
    });
  }
});
