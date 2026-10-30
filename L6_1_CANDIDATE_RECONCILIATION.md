# L.6.1 Candidate Reconciliation

Date: 2026-10-30
Current HEAD: `92c51e52629f7dcb8b9dce18f412bd957897f6eb`
Historical baseline cited by reports: `2650b028f73dcff00416d39cbcfbac75ecd0a052`

## 1. Reproducible scan method

Candidate extraction rule used by the report and reproduced here:

> A test function named `test_*` is a candidate when **every** `assert`
> statement in its body is syntactically inside an `if`, `for`, `while`, or
> `async for` body.

Implementation: Python `ast` traversal over `tests/**/*.py`, excluding nested
function/lambda bodies. Kind classification:

- `conditional-only`: every guarded assert is guarded by `if` only.
- `loop-only`: every guarded assert is guarded by a loop only.
- `mixed`: the function contains both kinds of guarded asserts.

The scanner output was compared byte-for-byte against Appendix A of
`docs/reports/L6_1_TEST_QUALITY_FINAL_REPORT.md`: 173/173 rows matched
(file, line, test name), so the current report's enumerated candidate set is
reproducible.

## 2. Current HEAD candidate inventory (verified)

| Metric | Count |
|---|---:|
| Test files scanned under `tests/` | 259 |
| Candidate test functions | 173 |
| conditional-only | 9 |
| loop-only | 126 |
| mixed | 38 |
| Accepted | 173 |
| Rejected | 0 |
| Deferred | 0 |
| Duplicate/invalid | 0 |
| Unreviewed at current HEAD | 0 |

All 173 candidates are classified `ACCEPTABLE` in the report. The audit here
does not identify a candidate that is vacuous, false-positive, duplicate,
environment-dependent, or missing a negative case. No test expectations were
changed in this phase.

## 3. Historical 189-candidate reconciliation

Reported historical count at `2650b028`: 189
(`47 conditional-only + 142 loop-only`).

Reported current count: 173
(`9 conditional-only + 38 mixed + 126 loop-only`).

The report explains the difference of 16 as guarded-assertion sites removed or
converted by the capability-truth commit (`e8db971...`).

| Category | Count | Basis |
|---|---:|---|
| Original candidates reported | 189 | `L6_1_RECONCILIATION_FINAL_2026-10-29.md` |
| Accepted (current reproducible set) | 173 | AST scan + Appendix A exact match |
| Removed/converted (no longer a candidate) | 16 | Reported explanation for 189 -> 173 |
| Rejected | 0 | No candidate identified as vacuous or incorrect |
| Deferred | 0 | No candidate deferred |
| Duplicate/invalid | 0 | No duplicate or invalid candidate identified |
| Unaccounted | 0 | 173 + 16 = 189 |

## 4. Independent reproducibility finding (important)

The same AST scan run against a worktree at `2650b028` produced **168**
candidate functions, not 189:

| Kind | Reproduced at 2650b028 | Reported at 2650b028 |
|---|---:|---:|
| conditional-only | 9 | 47 (includes mixed under that report's grouping) |
| mixed | 38 | 0 (grouped into conditional-only above) |
| loop-only | 121 | 142 |
| Total | 168 | 189 |

Therefore:

1. The current 173 candidate set is fully reproducible and matches the report's
   Appendix A exactly.
2. The historical 189 count is **not reproducible** by the stated extraction
   rule. The gap is 21 candidates.
3. The reported 16 removed/converted sites are also **not observed** in the
   reproducible old-to-current diff: the reproducible scan shows 0 removals and
   5 additions (all new tests added by the capability commit).
4. No individual enumeration of the historical 189 (or the 16 removed sites)
   exists in the repository, so they cannot be dispositioned one by one from
   repository evidence.

## 5. Disposition of the reproducible candidate set

All 173 reproducible candidates are dispositioned `ACCEPTABLE`:

- 9 conditional-only candidates are fail-closed guards (Docker availability,
  workspace cleanup, capability truth) where the guard itself is the behavior
  under test.
- 126 loop-only candidates are collection/registry/property checks; each fails
  if any element violates the property.
- 38 mixed candidates combine collection iteration with conditional fail-closed
  checks.
- 0 `assert True` / empty-body tautologies remain.
- 11 `assert False` occurrences are legitimate failure paths.

No candidate requires rewrite, and no production code was changed to make a
candidate pass.

## 6. Conclusion

- Current candidate quality claim is verified: 173/173 reproducible and accepted.
- Historical count of 189 is preserved as reported evidence but is not
  independently reproducible; the 21-candidate gap and the 16 reported
  removals are documented as unverified report arithmetic, not as silently
  accepted candidates.
- No unreviewed reproducible candidate remains at current HEAD.
