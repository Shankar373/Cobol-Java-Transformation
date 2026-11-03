# False-success baseline and remediation (2026-11-01)

Branch `fix/false-success-baseline`, based on `b79f348`.  Deterministic, no
LLM anywhere in the path: every change is a parser check, a mapper lowering,
a pipeline comparison rule or an API gate, and every behavioural claim below
is pinned against the GnuCOBOL 3.1.2 oracle image (`gnucobol-ocesql:latest`).

A **false success** is a translation reported as successful (or a run that
could be approved) whose Java behaves differently from the COBOL program.

## 1. Trustworthy test baseline

| | Result |
|---|---|
| `b79f348`, plain `pytest tests` | 166 failed, 27 errors, 4,220 passed — Docker-dependent tests mixed with unit tests, so red carried no signal |
| Hermetic lane (default) | `tests/conftest.py` pins `DOCKER_HOST` to an unreachable endpoint and skips the node ids in `tests/docker_lane.txt` unless `RUN_DOCKER_TESTS=1` |
| Docker lane | `RUN_DOCKER_TESTS=1` (CI `backend-oracle` job) runs everything against the real images |

The Docker adapters now pass the controlled stdin they hash into the
evidence (`docker run -i` + `input=`); previously the evidence recorded an
input the program never received.

## 2. Differential corpus (41 programs, GnuCOBOL vs generated Java)

| | False successes | Byte-identical | Fail closed |
|---|---|---|---|
| `b79f348` | 28 | 13 | 0 |
| this branch | **0** | **33** | 8 |

Supplementary probes (this batch): 16 control-flow programs (12 identical,
4 fail closed), 24 group-storage programs (14 identical, 10 fail closed),
10 group-operand programs (1 identical, 9 fail closed) — 0 false successes.

## 3. Translation fixes (now byte-identical to the oracle)

* High-order truncation for integer receivers; exact BigDecimal
  intermediates for nested division and ROUNDED; DIVIDE REMAINDER from the
  stored quotient.
* PERFORM VARYING updates the COBOL field; PERFORM … THRU … n TIMES.
* Space-padded alphanumeric comparison (`=`, `NOT =`, ordering, compound).
* PIC/VALUE clauses on continuation lines.
* **Paragraph fall-through**: `main` runs the driver paragraph, then each
  following paragraph until one with a top-level STOP RUN/GOBACK
  (`engine/transformation/control_flow.py`).  Single-program generator
  only: the Spring Boot application runner still enters the driver
  paragraph method, and the analyzer keeps that path PARTIAL.
* **EXIT PROGRAM in a program that was not CALLed is a no-op** (it used to
  return from `main`).
* **Group items as views** (`engine/transformation/group_storage.py`):
  DISPLAY of a group and MOVE group → `PIC X` field read the leaves'
  characters in order; MOVE literal / printable figurative / `PIC X` field /
  group → group writes the leaves when every leaf is a named `PIC X`.

## 4. Fail-closed (refused with a named `UNSUPPORTED_CONSTRUCT`)

DIVIDE/arith `ON SIZE ERROR`; STOP RUN/GOBACK/EXIT PROGRAM outside the
provable chain position; STOP RUN in a CALLed program; CALL of a
fall-through program without LINKAGE; groups with OCCURS / REDEFINES / COMP /
signed or scaled leaves / reference modification; MOVE into a group with a
numeric leaf or FILLER; group operands of STRING / UNSTRING / INSPECT / READ /
WRITE / CALL; duplicated data names; level 66; JUSTIFIED; BLANK WHEN ZERO;
`DISPLAY … WITH NO ADVANCING`; two statements on one line; unexpanded COPY
in the single-source producer; any `UNSUPPORTED_*$` symbol in generated Java.

## 5. Verification and approval

* **Approval requires VERIFIED** (`api/service.py`, `set_run_approval`): 409
  unless the verdict is VERIFIED, hash-matches its evidence and the evidence
  passes integrity validation.  REJECTED always works.
* **Comparison surface** (`engine/pipeline.py`): every generated file is
  compared byte-exactly, declared or not; one-sided files are MISMATCH;
  database / CICS / MQ effects that nothing observes yield UNSUPPORTED.
* **CRLF**: comparators no longer normalize implicitly; `crlf_to_lf` applies
  only where a workload declares it and is recorded in the evidence.  The
  host-JVM candidate lane runs with `-Dline.separator=\n` so a Windows host
  emits the same LF record endings as the Linux oracle instead of relying
  on CRLF folding.

## 6. Tests added

* `tests/transformation/test_false_success_regressions.py` — 29 oracle-pinned
  programs (Java output asserted locally, pins re-derived from GnuCOBOL in
  the Docker lane) and 15 fail-closed programs.
* `tests/test_comparison_contract_strength.py` — 34 pipeline tests (declared
  and legacy paths).
* `tests/test_phase12_p4_bl091_approval_workflow.py::TestApprovalRequiresVerified`.
* `tests/verified_run_support.py` — seeds verdicts through the real
  validated derivation path (no hand-written VERIFIED).

## 7. Remaining blockers

See `docs/KNOWN_ISSUES.md` § "False-success baseline (2026-11-01)".
