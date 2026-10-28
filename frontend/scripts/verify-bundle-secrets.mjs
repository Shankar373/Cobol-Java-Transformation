#!/usr/bin/env node
/**
 * Fail a frontend build that would ship the control-plane bearer token.
 *
 * `frontend/src/api/client.ts` reads `VITE_CONTROL_PLANE_API_TOKEN` from
 * `import.meta.env`, and Vite inlines `VITE_*` values into
 * `dist/assets/*.js` — readable by any anonymous browser. A token baked in
 * that way is a permanent credential leak: it survives rotation (the old
 * value stays in every cached asset) and needs no attack beyond `curl`.
 * The supported entry point is the runtime override
 * (`localStorage.systemaops.apiToken` / `setApiToken`), or terminating
 * auth at a same-origin proxy.
 *
 * The decision logic is exported as `evaluateBundleSecrets` so the test
 * suite can pin it without spawning a process (this package has no Node
 * type definitions; see `verify-bundle-secrets.d.mts`).
 *
 * CLI checks, in order:
 *   1. `VITE_CONTROL_PLANE_API_TOKEN` set for this build -> FAIL, because
 *      the value is about to be inlined (override:
 *      `ALLOW_BUNDLED_API_TOKEN=1` for a closed internal deployment, which
 *      prints a loud warning instead of silently succeeding);
 *   2. built assets scanned for the inlined signature
 *      `"VITE_CONTROL_PLANE_API_TOKEN":"<value>"` -> FAIL, catching a
 *      stale/poisoned `dist/` even when this build itself is clean.
 *
 * Exit: 0 clean, 1 leak detected, 2 usage error.
 * `FRONTEND_DIST_DIR` overrides the scanned directory (tests).
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/** The inlined-env signature of a baked token (value present in the bundle).
 *  Vite emits the env object with quoted and/or unquoted keys:
 *  `{"VITE_X":"secret"}` or `{VITE_X:"secret"}` — both forms count. A bare
 *  dynamic lookup (`env?.["VITE_X"]`, no value) does not. */
export const BAKED_TOKEN_PATTERN =
  /["']?VITE_CONTROL_PLANE_API_TOKEN["']?\s*:\s*["'][^"']+["']/;

/**
 * Pure decision logic — no filesystem, no process, no exit.
 *
 * @param {object} input
 * @param {string} [input.token]  Value of VITE_CONTROL_PLANE_API_TOKEN.
 * @param {boolean} [input.allowBundled]  Explicit acknowledgement.
 * @param {Array<{name: string, content: string}>} [input.assets]
 * @returns {{ok: boolean, messages: string[]}}
 */
export function evaluateBundleSecrets({
  token = "",
  allowBundled = false,
  assets = [],
} = {}) {
  const messages = [];

  if (token && !allowBundled) {
    messages.push(
      [
        "FATAL: VITE_CONTROL_PLANE_API_TOKEN is set for this build.",
        "  Vite inlines VITE_* values into dist/assets/*.js, so anyone who",
        "  can fetch the bundle reads the control-plane bearer token, and",
        "  the value survives rotation in every cached copy of the asset.",
        "  Fix: unset VITE_CONTROL_PLANE_API_TOKEN and supply the token at",
        "  runtime instead (localStorage key `systemaops.apiToken`, or the",
        "  setApiToken() helper).",
        "  To bundle it deliberately (closed internal deployment only):",
        "    ALLOW_BUNDLED_API_TOKEN=1 npm run build",
      ].join("\n"),
    );
  } else if (token && allowBundled) {
    messages.push(
      "WARNING: VITE_CONTROL_PLANE_API_TOKEN is being bundled into public " +
        "assets (ALLOW_BUNDLED_API_TOKEN=1). Anyone who can download the " +
        "bundle can use the control-plane token.",
    );
  }

  const poisoned = assets.filter((asset) =>
    BAKED_TOKEN_PATTERN.test(asset.content),
  );
  if (poisoned.length > 0 && !allowBundled) {
    messages.push(
      [
        `FATAL: ${poisoned.length} built asset(s) contain an inlined ` +
          "VITE_CONTROL_PLANE_API_TOKEN value:",
        ...poisoned.map((asset) => `  - ${asset.name}`),
        "  Rebuild from a clean environment" +
          " (unset VITE_CONTROL_PLANE_API_TOKEN).",
      ].join("\n"),
    );
  }

  const fatal = messages.some((m) => m.startsWith("FATAL"));
  return { ok: !fatal, messages };
}

function listAssets(dir) {
  if (!existsSync(dir)) return [];
  const out = [];
  const walk = (current) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(js|mjs|cjs|html)$/.test(entry.name)) out.push(full);
    }
  };
  walk(dir);
  return out;
}

function main() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const distDir = process.env.FRONTEND_DIST_DIR
    ? path.resolve(process.env.FRONTEND_DIST_DIR)
    : path.join(root, "dist");

  const assets = listAssets(distDir).map((file) => ({
    name: path.relative(distDir, file),
    content: readFileSync(file, "utf8"),
  }));

  const verdict = evaluateBundleSecrets({
    token: process.env.VITE_CONTROL_PLANE_API_TOKEN ?? "",
    allowBundled: process.env.ALLOW_BUNDLED_API_TOKEN === "1",
    assets,
  });

  for (const message of verdict.messages) {
    (verdict.ok ? console.warn : console.error)(message);
  }
  if (!verdict.ok) process.exit(1);

  console.log(
    `bundle-secret-guard: OK (${assets.length} asset(s) checked in ` +
      `${path.relative(root, distDir) || "dist"})`,
  );
}

// Run only when executed directly (`node scripts/verify-bundle-secrets.mjs`),
// not when imported by the test suite.
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main();
}
