# Stage 1 Final Completion Report: COBOL + VSAM modernization

Branch `stage1/vsam-completion`, targeting `impl/enterprise-platform` only. `main` was not touched.

## Verdict

**PARTIALLY COMPLETE.** G-26 and G-27 are closed for their stated scope. G-28 and G-29 are partially closed. VSAM
migration is a verified library, and only its per-file assessment is wired into the product workflow. Nothing here is
IBM runtime verified.

## 1. Baseline

| Item | Value |
|---|---|
| Baseline branch | `impl/enterprise-platform` |
| Baseline head used for the rebase | `116152f` (docs only, on top of `fdf6f00`) |
| Baseline CI, code head `fdf6f00` | **success**, run 43429795022 (all jobs, Docker job included) |
| Baseline CI, `116152f` | docs-only commit; CI was still running when the rebase was done |
| Baseline certification | `eb14eed`: run 43423724085 **success**, `exact-run-certification-summary` artifact read: certified=True |
| Earlier baseline failure found and fixed | `d035327` and `eb14eed` CI failed one Docker-lane test (`test_none_java_application_fails_run`); the test's generator fake had no entrypoint. Fixed in `fdf6f00` (fake only, assertions unchanged). |

Phase 0 was handled as Case C and then Case B. The baseline had a real failure, which I fixed first. Stage 1 was developed in
an isolated worktree and integrated only after the baseline code head was green.

## 2. Gaps

| Gap | Status | What changed |
|---|---|---|
| G-26 COPY inside FD | **CLOSED** (unit-tested, equivalence proven) | `engine/transformation/fd_copybooks.py` expands FILE SECTION COPY in place. IR, layout and generated Java match the inline FD. Failures are ERROR diagnostics and no record is invented. Nested expansion is bounded. A member also used in WORKING-STORAGE is still merged there. |
| G-27 binary endianness / platform | **CLOSED for explicit documented platforms** | `engine/vsam/platform.py`. Binary layouts without explicit platforms and a target layout are refused. Width and byte order are converted, and every decision is in the report. GnuCOBOL presets are differential-verified. **IBM_ZOS is documented only.** |
| G-28 RDW / ESDS / RRDS / alternate indexes | **PARTIALLY CLOSED** | RDW migration for sequential/ESDS. ASCII<->EBCDIC in both directions. Alternate keys validated (not built). ESDS RBA refusal. RRDS BLOCKED. |
| G-29 layout coverage | **PARTIALLY CLOSED** | New differential tests: inline SIGN, nested OCCURS, group REDEFINES, SYNCHRONIZED slack. ODO, SYNCHRONIZED and COMP-1/2 are still refused by name. |

## 3. Implemented, unit-tested, GnuCOBOL-verified, IBM-verified

| Capability | Implemented | Unit-tested | GnuCOBOL-verified | IBM runtime-verified |
|---|---|---|---|---|
| FD COPY expansion | yes | yes | n/a (parser level) | no |
| Layout derivation (DISPLAY/COMP/COMP-5/COMP-3/SIGN/OCCURS/REDEFINES) | yes | yes | yes, default and `-std=ibm` | no |
| Binary platform conversion | yes | yes | GnuCOBOL presets yes | no (IBM_ZOS documented only) |
| Fixed-record migration, both directions | yes | yes | layout bytes yes; migrated data read only by our own reconciliation | no |
| RDW sequential/ESDS migration | yes | yes | payload differential vs re-framed GnuCOBOL records | no |
| Alternate key validation | yes | yes | no | no |
| Per-FD assessment in discovery | yes | yes | n/a | no |

Not implemented or refused by name: variable KSDS, binary fields in variable layouts, RRDS (BLOCKED), spanned records,
alternate index structures, ESDS RBA addressing, OCCURS DEPENDING ON, SYNCHRONIZED, COMP-1/COMP-2, an unselected REDEFINES,
several FD records without a choice. Nothing is **Production-ready**.

## 4. Product-workflow integration

Ingestion -> COPY -> parser/IR -> FD discovery -> layout -> capability assessment: **integrated**. `discover_application`
(behind `GET /applications/{id}/discovery`) attaches a `vsam_assessment` per FD to each discovered program, reusing the programs
`ApplicationDiscovery` already parsed with COPY-in-FD expanded. Tests: `tests/test_vsam_assess.py` (11) and
`tests/test_vsam_discovery_integration.py` (5, one through the HTTP route).

Migration plan, conversion, Java-side access, reconciliation and evidence: **library only** (`engine/vsam/migrate*.py`).
There is no data-upload or migration endpoint. One would need size limits, storage and access control, which were not designed
in this stage. **Recorded limitation, not a closed gap.** No Java program has consumed migrated data, so
Java-side access is not claimed.

## 5. Independent reviews

| Review | Result |
|---|---|
| python-reviewer | 1 HIGH (key over a width-changing binary field), 7 MEDIUM, 7 LOW |
| security-reviewer | 0 CRITICAL, 2 HIGH (copybook dropped from WORKING-STORAGE; unbounded COPY fan-out), 4 MEDIUM, 3 LOW |
| code-reviewer, architect, tdd-guide | **not invoked** in this stage (the python and security reviewers were); TDD followed manually (RED recorded before each fix) |
| ADR | not written for the new decisions (platform model, FD expansion, RDW scope); documented in the gap register and module docstrings instead. **Open follow-up.** |

Fixed after review, each with a regression test that failed first: keys over binary fields whose width or byte order changes
are refused; a mismatched non-binary target layout is refused; `convert_record_between` requires an exact record length;
FD copybook consumption is per occurrence; fixed-format sequence numbers no longer hide the FILE SECTION; COPY expansion is
bounded; layout diagnostics are capped at 200.

Left open: server paths can still appear in copybook diagnostics (pre-existing); `rejected` / `alternate_indexes` report size is
uncapped (library level); `validate_layout` is not re-run on caller-built layouts in the binary path; the review's
other MEDIUM/LOW items (private helpers shared across modules, double `convert` call per record) were not changed.

## 6. Test commands and results (local)

| Command | Result |
|---|---|
| `python -m pytest -q tests/test_vsam_*.py tests/transformation tests/test_copybook*.py` | 2719 passed, 52 skipped |
| `python -m pytest -q` (full hermetic, started before the review fixes) | 6096 passed, 5 failed, 640 skipped; the 5 failures are the five regression tests written RED before their fixes, all green afterwards. **The full suite was not re-run after the fixes locally; CI runs it.** |
| `RUN_DOCKER_TESTS=1 pytest tests/integration/test_vsam_layout_oracle.py ..._g29.py test_vsam_variable_oracle.py` | 16 passed (GnuCOBOL in `gnucobol-ocesql:latest`) |
| `ruff check engine api tests tools` | all checks passed |
| `python tools/mypy_gate.py --check` | clean against the 209-error baseline |

Skipped Docker-lane tests are not counted as passes. The frontend was not touched.

## 7. GnuCOBOL differential evidence

GnuCOBOL wrote the records and the layout derived from the same source had to find every value at its derived offset. This
covers the default and `-std=ibm` dialects: DISPLAY, COMP, COMP-5, COMP-3, SIGN SEPARATE, inline SIGN, fixed and nested
OCCURS, selected REDEFINES, and SYNCHRONIZED (slack is the measured reason it is refused). Variable records: GnuCOBOL's
header (length excluding the header) differs from IBM RDW (length including it), so the file is re-framed with independent code
before migration. A GnuCOBOL pass does **not** establish IBM VSAM or IBM Enterprise COBOL equivalence.

## 8. Final CI

Recorded after the PR run: see the section added below once CI has completed.

## 9. Security and architecture observations

The migration library is not reachable remotely; only discovery assessment is. Discovery reaches COPY expansion on uploaded
input, now bounded. Fail-closed throughout: unsupported or ambiguous input yields REFUSED/BLOCKED with named reasons.
`engine/vsam/migrate_variable.py` and `fd_copybooks.py` import private helpers from sibling modules (coupling noted by review).
