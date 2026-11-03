import { describe, it, expect } from 'vitest';
import { discoveryIssuesMessage, type DiscoveryResult } from '../api/client';

/**
 * The backend reports `discovery_success` and `discovery_errors`, but the SPA
 * never typed or read them, so a discovery that only partly completed looked
 * exactly like one that fully succeeded.  These tests pin the warning message
 * built from those fields.
 */

const discovery = (overrides: Partial<DiscoveryResult>): DiscoveryResult => ({
  application_id: 'app-1',
  cobol_programs: [],
  copybooks: [],
  jcl_jobs: [],
  file_dependencies: [],
  call_dependencies: [],
  dependency_edges: [],
  source_file_count: 3,
  total_size_bytes: 512,
  discovery_success: true,
  discovery_errors: [],
  ...overrides,
});

describe('discoveryIssuesMessage', () => {
  it('returns null for a fully successful discovery', () => {
    expect(discoveryIssuesMessage(discovery({}))).toBeNull();
  });

  it('describes the failing stages when discovery_errors is populated', () => {
    const message = discoveryIssuesMessage(
      discovery({
        discovery_success: false,
        discovery_errors: [
          { stage: 'COPYBOOK_RESOLUTION', message: 'missing COPYBOOK CUSTREC' },
        ],
      }),
    );

    expect(message).not.toBeNull();
    expect(message).toContain('COPYBOOK_RESOLUTION');
    expect(message).toContain('missing COPYBOOK CUSTREC');
  });

  it('still reports incompleteness when the flag is false but no detail exists', () => {
    const message = discoveryIssuesMessage(
      discovery({ discovery_success: false, discovery_errors: [] }),
    );

    expect(message).not.toBeNull();
    expect(message).toMatch(/incomplete|failed|partial/i);
  });

  it('does not invent a warning when the flag is true and errors are empty', () => {
    expect(discoveryIssuesMessage(discovery({ discovery_success: true }))).toBeNull();
  });
});
