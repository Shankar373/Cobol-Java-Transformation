# ADR — DB2 / EXEC SQL Modernization Profile

- Status: Accepted (lane-scoped)
- Date: 2026-09-21
- Lane: DB2 / EXEC SQL modernization (isolated)

## Context

COBOL host programs embed DB2 access through `EXEC SQL ... END-EXEC`
blocks.  The repository already had a frozen SQL parser
(`engine/transformation/sql_parser.py`) producing SQL IR, plus shared
Java/Spring generators that were **off-limits** for this lane.  The lane
needed a self-contained, evidence-driven pipeline that:

1. extracts embedded SQL from COBOL,
2. analyzes host-variable binding and table usage,
3. produces a Java repository/service representation,
4. executes the supported subset deterministically for testing,
5. never conflates controlled-test behavior with DB2 runtime behavior.

## Requirements

- Deterministic pipeline: source → semantic model → Java representation.
- SQLCODE/SQLSTATE constants modeled at the DB2-documented semantic level
  (`0/00000`, `100/02000`, `-811/21000`, `-803/23505`).
- Strict compatibility-claim ordering so `DB2_RUNTIME_VERIFIED` can only
  come from real DB2 evidence.
- No modification of shared/frozen generator, parser, or pipeline files.

## Decision

Create the lane-owned `engine/sql/**` package plus the facade
`engine/transformation/sql_repository_mapping.py`:

- `extractor.py` — EXEC SQL region extraction (fixed-format prefix,
  comments excluded)
- `analyzer.py` — DB2 semantic analysis (binding directions, indicator
  pairing, table roles, possible statuses)
- `model.py` — `Db2SqlModel` / `Db2StmtSemantic` / host-variable
  semantics
- `status.py` — SQLCODE/SQLSTATE domain model
- `dialect.py` — compatibility classification
- `db2_sqlite.py` — DB2 → SQLite DDL/DML translation
- `execution.py` — `Db2ControlledDatabase` (stdlib sqlite3) executing the
  status boundary with DB2 domain statuses
- `harness.py` — workload driver producing a deterministic trace
- `repository_model.py` — Java repository/service representation with a
  `java_type_resolver` hook
- `transformation/sql_repository_mapping.py` — lane facade

Execution evidence is captured as a golden trace
(`fixtures/workload-db2/expected/db2_execution.trace`).

## Alternatives considered

- Directly modifying `spring_boot_generator.py` — rejected: off-limits;
  integration deferred to the consumer layer via a documented hook.
- Using `cobol_parser.py` for EXEC SQL extraction — rejected: off-limits
  and out of its scope; the lane owns a minimal block extractor instead.
- Shipping an embedded DB2 emulator — rejected: over-engineering; the
  controlled SQLite backend satisfies the testability requirement at the
  `PORTABLE_EXECUTABLE` level.

## Trade-offs

- The controlled test database shares SQL semantics enough for a faithful
  test of the *translated subset*, but it is **not** DB2.  Status values
  are modeled domain values, not runtime observations.
- COBOL flow (loops, `MOVE` values) is not modeled by this lane; input
  bindings are supplied deterministically via `statement_bindings`.

## Consequences

- Claimable statuses from lane evidence: `PARSED`, `MODELED`,
  `TRANSFORMED`, `CONTROLLED_EXECUTABLE`, `DB2_SYNTAX`, `DB2_SEMANTIC`,
  `PORTABLE_EXECUTABLE`.
- `DB2_RUNTIME_VERIFIED` is **NOT_ESTABLISHED** until a real DB2
  subsystem executes the workload and the evidence is recorded.
- Spring generator integration remains a documented contract for the
  consumer/integration lane.