/** Compiler/toolchain, applications, readiness and source-viewer shapes of the discovery API (api/discovery_routes.py). */

import type { DiscoveryReport } from './client';

export type DiscoveryReadinessState = 'BLOCKED' | 'NOT_SUPPORTED' | 'READY';

export interface DiscoveryTool {
  tool: string;
  available: boolean;
  version?: string;
  via?: string;
  reason?: string;
  license: string;
}

export interface DiscoveryFeature {
  feature: string;
  label: string;
  note: string;
  stops_check: boolean;
  evidence: { label: string; line: number }[];
  evidence_count: number;
}

export interface DiscoveryCompileRow {
  file: string;
  dialect: string;
  source_format: string;
  verdict: string;
  reason?: string;
  diagnostics: { file: string; line: number; severity: string; message: string }[];
  unsupported_features: DiscoveryFeature[];
}

export interface DiscoveryApplication {
  id: string;
  name: string;
  readiness: DiscoveryReadinessState;
  programs: string[];
  jobs: string[];
  files: string[];
  copybooks: string[];
  unsupported_features: string[];
  compile_errors: string[];
  compiler_verdicts: Record<string, number>;
  blocking_unresolved: { file: string; line: number; reason: string; to: string }[];
  entry_points: { program: string; file: string; kinds: string[]; invoked_by: string[] }[];
  resources: { id: string; kind: string; origin: string; uses: number }[];
}

export interface DiscoverySourceExcerpt {
  file: string;
  line: number;
  first_line: number;
  total_lines: number;
  encoding: string;
  sha256: string;
  lines: { number: number; text: string }[];
}

export interface DiscoveryReadiness {
  status: DiscoveryReadinessState;
  allowed: boolean;
  blockers: { id: string; detail: string }[];
  unsupported_total: number;
  unsupported: { file: string; feature: string; label: string; note: string; stops_check: boolean; evidence: { label: string; line: number }[] }[];
  compile_errors: { file: string; dialect: string; diagnostics: { line: number; message: string }[] }[];
  unverified_total: number;
  unverified: { file: string; reason: string }[];
}

export interface DiscoveryReportV2 extends DiscoveryReport {
  readiness: DiscoveryReadiness;
  toolchain: {
    required: { family: string; kind: string; name: string; evidence: { file: string; line: number }[]; evidence_count: number }[];
    tools: DiscoveryTool[];
  };
  compatibility: {
    backend: { kind: string; reason: string; version: string; image?: string };
    basis: string;
    summary: Record<string, number>;
    programs: DiscoveryCompileRow[];
  };
  applications: {
    applications: DiscoveryApplication[];
    entry_points: { program: string; file: string; kinds: string[] }[];
    relationships: { resource: string; kind: string; applications: { id: string; name: string; uses: number }[] }[];
  };
}
