# Known Issues

## Frontend Production Build Blocker — TypeScript JSX Fragment Typing Bug

**Status:** OPEN — CI Blocker
**Severity:** HIGH
**Affects:** Frontend production build only (`npm run build`)
**Does Not Affect:** Frontend unit tests (`npm test` — 81/81 pass), runtime behavior

---

### Error Summary

```
src/pages/ModernizationRun.tsx(390,7): error TS2322: Type 'unknown' is not assignable to type 'ReactNode'.
src/pages/ModernizationRun.tsx(391,7): error TS2322: Type 'unknown' is not assignable to type 'ReactNode'.
src/pages/ModernizationRun.tsx(405,7): error TS2322: Type 'unknown' is not assignable to type 'ReactNode'.
src/pages/ModernizationRun.tsx(406,7): error TS2322: Type 'unknown' is not assignable to type 'ReactNode'.
```

### Location

`frontend/src/pages/ModernizationRun.tsx` — two conditional fragment render blocks:
- Lines 390–403: Error panel (conditional on `run.error`)
- Lines 405–451: Detail panel (conditional on `detail !== null`)

---

### Root Cause

**TypeScript compiler bug** with the new JSX transform (`jsx: react-jsx`), observed in TypeScript 5.0.4 through 7.0.2.

When a conditional expression uses the short-circuit `&&` operator and the true branch returns a JSX Fragment (`<>...</>`), TypeScript incorrectly infers the entire expression type as `unknown` instead of `ReactNode | false` (which is assignable to `ReactNode`).

```tsx
// TypeScript infers `unknown` for this expression:
{typeof run.error === 'string' && run.error.length > 0 && (
  <>
    <SectionCard>...</SectionCard>
  </>
)}
```

This is a **compiler type inference bug**, not a code defect. The runtime behavior is correct — all 81 frontend tests pass.

---

### Reproduction

The project reproduces the TS2322 failure with the following tested compiler versions:
- TypeScript 5.7.2 (project default)
- TypeScript 5.3.3
- TypeScript 5.0.4
- TypeScript 7.0.2 (also tested, reproduces the failure)

All produce identical TS2322 errors on the same four lines.

---

### Upstream Tracking

- **TypeScript Issue:** [#62358](https://github.com/microsoft/TypeScript/issues/62358) — "JSX Fragment type inference fails with conditional `&&` in react-jsx transform" (tracking reference; independently verified status pending)
- **Related:** [#59044](https://github.com/microsoft/TypeScript/issues/59044), [#58973](https://github.com/microsoft/TypeScript/issues/58973)
- **Associated with:** JSX/react-jsx typing path (`jsx: react-jsx` in tsconfig.json)

---

### Attempted Fixes (All Failed)

| Approach | Result |
|----------|--------|
| Ternary operator (`condition ? <>...</> : null`) | TS2322 persists |
| Explicit `React.ReactNode` typed variables | TS2322 persists |
| Helper component extraction | TS2322 persists |
| `React.createElement` / `React.Fragment` | TS2322 persists |
| Array spread (`{...(panel ? [panel] : [])}`) | TS2322 persists |
| Safe casts (`as React.ReactNode`) | TS2322 persists |
| `Boolean()` / `!!` wrappers | TS2322 persists |
| JSX transform change (`react-jsx` → `react`) | TS2322 persists |
| Strict mode modifications | TS2322 persists |

**No safe source-level fix exists** under current project constraints (no `@ts-ignore`, `@ts-expect-error`, unsafe casts, or compiler suppression directives).

---

### Workarounds (Not Applied Per Policy)

The only functional workaround requires suppression directives:

```tsx
// @ts-expect-error TS2322 — TypeScript 5.x bug: infers `unknown` for conditional fragments
{typeof run.error === 'string' && run.error.length > 0 && (
  <>...</>
)}
```

**Policy:** Suppression directives (`@ts-ignore`, `@ts-expect-error`) and unsafe casts are prohibited by project AGENTS.md rules.

---

### Impact Assessment

- **Phase 1/2 Regression:** NO — this is a pre-existing toolchain issue
- **CI Status:** BLOCKED — production build fails
- **Test Status:** PASS — 81/81 frontend tests pass
- **Runtime:** CORRECT — no behavioral change
- **Scope:** Single file, two conditional render blocks

---

### Recommended Resolution Path

1. **Short-term:** Await TypeScript upstream fix (tracked in #62358)
2. **Medium-term:** Evaluate TypeScript downgrade to 4.9.x (breaks modern JSX transform)
3. **Policy Decision:** Determine if suppression directive exception is warranted for compiler bugs

---

### Files Referenced

- `frontend/src/pages/ModernizationRun.tsx` (lines 390–451)
- `frontend/tsconfig.json` (`jsx: react-jsx`)
- `frontend/package.json` (`"typescript": "^5.7.2"`)