# npm audit exception: GHSA-fc5q-39xc-vjpf (picomatch ReDoS)

Status: **active, approved by the project owner (Option B)**. Review date / hard expiry: **2027-03-01**.

## What
`picomatch <= 4.0.7` has a regular-expression denial of service (GHSA-fc5q-39xc-vjpf). No patched release exists (4.0.7 is the latest). `npm audit` therefore also flags the
packages that depend on it: `fdir`, `tinyglobby`, `vite`, `vitest`. The only fix npm suggests (downgrading vitest to 3.1.4) is worse: 7 findings including 2 critical.

## Why it is acceptable
* picomatch is reachable **only through test and build tooling** (vite's glob handling, vitest). `npm ls picomatch --omit=dev` is empty and `npm audit --omit=dev` reports 0 vulnerabilities:
  production dependencies are `react` and `react-dom` only. The shipped bundle contains no picomatch.
* The pattern strings come from our own `vite.config`/`vitest` configuration, never from user input.

## How the gate works (`tools/npm_audit_gate.py`, run by `.github/workflows/supply-chain.yml`)
* The **complete** audit (dev included) is still produced and uploaded as `npm-audit.json`.
* The gate fails on **every other** vulnerability, including any new advisory on picomatch itself or on a package not flagged solely because of picomatch.
* The exception is void (gate fails) if picomatch appears in the production tree, if a picomatch release newer than 4.0.7 exists, or after 2027-03-01.
* `npm audit --omit=dev` is a separate, strict step with no exception.

## Removal
When picomatch publishes a fixed release: `npm update picomatch`, delete `tools/npm_audit_gate.py`'s exception (or the whole script), restore plain `npm audit`, delete this file.
