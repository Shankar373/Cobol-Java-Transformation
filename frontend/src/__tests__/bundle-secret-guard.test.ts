/**
 * Bundle secret guard: a frontend build must never ship the control-plane
 * bearer token.
 *
 * `client.ts` resolves `VITE_CONTROL_PLANE_API_TOKEN` from
 * `import.meta.env`, which Vite inlines into `dist/assets/*.js` — an
 * anonymous-visitor credential leak that also survives token rotation in
 * cached assets. `frontend/scripts/verify-bundle-secrets.mjs` runs as part
 * of `npm run build` (and therefore in CI's frontend job) and fails the
 * build in that configuration; this suite pins the guard's decision logic
 * directly through its exported `evaluateBundleSecrets` function, so the
 * gate is tested rather than assumed.
 *
 * The package.json wiring (`build` chains the script) is asserted from the
 * Python deployment-contract tests, which can read the file without Node
 * type definitions.
 */
import { describe, expect, it } from "vitest";
import {
  evaluateBundleSecrets,
  type BundleSecretVerdict,
} from "../../scripts/verify-bundle-secrets.mjs";

const SECRET = "sk-live-super-secret-token";

function verdict(input: Parameters<typeof evaluateBundleSecrets>[0] = {}): BundleSecretVerdict {
  return evaluateBundleSecrets(input);
}

describe("evaluateBundleSecrets", () => {
  it("passes a clean build (no token, no poisoned assets)", () => {
    const result = verdict({ assets: [{ name: "assets/index.js", content: "const x=1;" }] });
    expect(result.ok).toBe(true);
    expect(result.messages).toHaveLength(0);
  });

  it("fails when the token would be inlined, without printing it", () => {
    const result = verdict({ token: SECRET });
    expect(result.ok).toBe(false);
    const text = result.messages.join("\n");
    expect(text).toContain("VITE_CONTROL_PLANE_API_TOKEN");
    expect(text).toContain("runtime");
    // The guard must never echo the secret it is protecting.
    expect(text).not.toContain(SECRET);
    expect(text).not.toContain("sk-live");
  });

  it("warns loudly but allows an acknowledged bundled token", () => {
    const result = verdict({ token: SECRET, allowBundled: true });
    expect(result.ok).toBe(true);
    expect(result.messages.join("\n")).toContain("WARNING");
  });

  it("detects an inlined token value in built assets", () => {
    // Vite's real shape: the env object with the value inlined. Both the
    // quoted-key and unquoted-key forms must be caught.
    for (const content of [
      'const env={MODE:"production",VITE_CONTROL_PLANE_API_TOKEN:"sk-live-leaked"};',
      'const env={"VITE_CONTROL_PLANE_API_TOKEN":"sk-live-leaked"};',
    ]) {
      const result = verdict({ assets: [{ name: "assets/index.js", content }] });
      expect(result.ok, content).toBe(false);
      expect(result.messages.join("\n")).toContain("assets/index.js");
    }
  });

  it("accepts assets that reference the key without a value", () => {
    // The safe shape after a clean build: dynamic lookup, value absent.
    const result = verdict({
      assets: [
        {
          name: "assets/index.js",
          content: 'const t=env?.["VITE_CONTROL_PLANE_API_TOKEN"];',
        },
      ],
    });
    expect(result.ok).toBe(true);
  });

  it("stays fatal for poisoned assets unless bundling is acknowledged", () => {
    const assets = [
      {
        name: "assets/stale.js",
        content: '{"VITE_CONTROL_PLANE_API_TOKEN":"old-value"}',
      },
    ];
    expect(verdict({ assets }).ok).toBe(false);
    expect(verdict({ assets, allowBundled: true }).ok).toBe(true);
  });
});
