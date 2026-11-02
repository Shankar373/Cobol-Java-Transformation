# Contributing

## Ground rules

- **Deterministic, no LLM.** Generation and verification are pure functions
  of the source; nothing calls a model.
- **Fail closed.** An unsupported construct is refused by name
  (`UNSUPPORTED_CONSTRUCT`, an `UNSUPPORTED_*$` symbol, or a SKIP in the
  plan) — never silently dropped, never approximated. A verdict is VERIFIED
  only when generated Java and GnuCOBOL agree on every observed effect.
- **No claim without GnuCOBOL proof.** A construct becomes SUPPORTED in
  `engine/transformation/semantic_capability.py` only with an oracle-backed
  test; `tests/test_phase5_certification.py` fails otherwise.

## Setup

```bash
python -m pip install --require-hashes -r requirements-dev.lock   # Python 3.11
(cd frontend && npm ci)
python -m pytest -q tests          # hermetic lane (no Docker)
```

The Docker lane (`RUN_DOCKER_TESTS=1`) needs the oracle and build images —
see the README. On that lane a test that skips for missing Docker, an image
or a JDK fails (`tests/conftest.py`).

## Changes

1. Write the failing test first; show it red against the current code.
2. Keep generated output byte-identical for constructs you did not mean to
   change: hash the generated project of every fixture application before
   and after (the method used throughout `docs/audits/CHANGE_LEDGER.md`).
3. Run focused tests locally; CI runs the full hermetic, pytest-only gate,
   Docker and frontend suites on the pushed commit. Put `[certify]` in the
   commit message when generation, the pipeline or verification changed —
   `.github/workflows/certification.yml` then re-certifies the whole corpus
   on all runtimes against GnuCOBOL.
4. Update `docs/CAPABILITY_MATRIX.md`, `docs/KNOWN_ISSUES.md` and, for
   audit items, `docs/audits/CHANGE_LEDGER.md`.
5. Do not edit `engine/verdict/derivation.py`, GO TO handling or oracle
   digest pinning without a dedicated review — they have a history of
   regressions (audit §5, do-not-regress ledger).

New runtime targets: [docs/RUNTIME_ADAPTERS.md](docs/RUNTIME_ADAPTERS.md).
Commits carry a `Co-Authored-By` trailer when an assistant contributed.

By contributing you agree that your work is licensed under the Apache
License 2.0 ([LICENSE](LICENSE)).
