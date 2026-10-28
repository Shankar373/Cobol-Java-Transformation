/**
 * Type declarations for `verify-bundle-secrets.mjs` (plain ESM JavaScript:
 * this package has no Node type definitions, and the script must stay
 * runnable by bare `node` during `npm run build`).
 */
export interface BundleSecretVerdict {
  ok: boolean;
  messages: string[];
}

export interface BundleSecretInput {
  /** Value of VITE_CONTROL_PLANE_API_TOKEN (empty = not set). */
  token?: string;
  /** Explicit acknowledgement of bundling (`ALLOW_BUNDLED_API_TOKEN=1`). */
  allowBundled?: boolean;
  /** Built assets to scan for an inlined token value. */
  assets?: Array<{ name: string; content: string }>;
}

/** The inlined-env signature of a baked token. */
export declare const BAKED_TOKEN_PATTERN: RegExp;

/**
 * Pure decision logic: no filesystem, no process, no exit.
 * Returns `ok: false` when a FATAL message was produced.
 */
export declare function evaluateBundleSecrets(
  input?: BundleSecretInput,
): BundleSecretVerdict;
