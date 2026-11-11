import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// Several tests wait on chains of mocked fetches (polling, approval state). Under CPU contention - a parallel backend
// run, a busy CI runner - testing-library's 1s default budget was intermittently too short
// (download-approval-gating, app-flow history). A longer budget with the same assertions; a real failure still fails.
configure({ asyncUtilTimeout: 5000 });
