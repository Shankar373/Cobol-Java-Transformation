# DB2 / EXEC SQL Modernization Lane

Lane-owned module that turns COBOL embedded SQL (`EXEC SQL ... END-EXEC`)
into a **DB2 semantic model** and a **Java repository/service
representation**, and executes the supported subset on a **controlled test
database**.

Scope boundary (strict): this lane owns `engine/sql/**`,
`engine/transformation/sql_repository_mapping.py`, `tests/test_db2_*.py`,
`fixtures/workload-db2/**`, and DB2-specific docs.  Shared COBOL
parser / IR / Spring generators are **off-limits** (frozen) — see section
"Spring integration hook".

## Architecture

```
fixtures/workload-db2/cobol/ACCOUNT-DB2.cob
        │  engine/sql/extractor.py           (EXEC SQL region extraction)
        ▼
engine/transformation/sql_parser.py          (frozen — IR production)
        │  EmbeddedSqlBlock / SqlStatement IR (engine/transformation/ir.py, frozen)
        ▼
engine/sql/analyzer.py                       (DB2 semantic analysis)
        │  Db2SqlModel, Db2StmtSemantic, host-variable binding directions,
        │  table read/write roles, possible SQLCODE/SQLSTATE statuses
        ▼
+--------------------+---------------------------+---------------------------+
| engine/sql/        | engine/sql/repository_model| engine/sql/execution.py   |
| dialect.py         | + transformation/sql_     | engine/sql/db2_sqlite.py  |
| compatibility      | repository_mapping.py      | controlled SQLite execution|
| claim levels       | Java repository/service    | + DB2→SQLite translation   |
+--------------------+---------------------------+---------------------------+
```

## Supported subset

- **SELECT INTO** (singleton) with SQLCODE `0` success, `100` no-data
  (`02000`), `-811` too-many-rows (`21000`)
- **INSERT / UPDATE / DELETE** with row counts and `-803` duplicate-key
  (`23505`) where meaningful
- **Cursor lifecycle**: DECLARE / OPEN / FETCH / CLOSE
- **Transactions**: COMMIT / ROLLBACK
- **SQLCODE / SQLSTATE observation** modeled as DB2-documented constants

Out of the execution subset (semantically modeled only): dynamic SQL
(`PREPARE`/`EXECUTE`), stored procedures (`CALL`).

## SQL semantic analysis

`Db2SemanticAnalyzer` derives semantics from source positions:

- Host variables inside an `INTO` clause → **OUTPUT**
- All other `:VAR` occurrences → **INPUT**
- A variable in both roles within one statement → **IN_OUT**
- `:A:B` indicator pairs mark **nullable** OUTPUT bindings
- `CALL` arguments cannot be classified from SQL text → **UNKNOWN**
- Table usage: SELECT reads, INSERT writes, UPDATE reads+writes,
  DELETE writes
- Per-statement **possible statuses** aggregate documented DB2 constants

## Controlled SQLite execution

`Db2ControlledDatabase` (stdlib `sqlite3`, in-memory) is a deterministic
harness used by `engine/sql/harness.py` and the lane tests.  It maps the
status boundary to DB2 domain values (`0/00000`, `100/02000`,
`-811/21000`, `-803/23505`) and produces a golden execution trace
(`fixtures/workload-db2/expected/db2_execution.trace`).

## DB2 → SQLite translation

`engine/sql/db2_sqlite.py` translates the supported subset:

- DDL: `CREATE TABLE` subset with identity, constraints
- DML: `FETCH FIRST n ROWS ONLY` → `LIMIT n`; `SELECT INTO` stripped
- Types: `VARCHAR`→`TEXT`, `DECIMAL`→`NUMERIC`, `INTEGER`→`INTEGER`,
  `TIMESTAMP`→`TEXT`, …

## Compatibility levels

Strict order (see `engine/sql/dialect.py`):

```
DB2_SYNTAX < DB2_SEMANTIC < PORTABLE_EXECUTABLE < DB2_RUNTIME_VERIFIED
```

- `DB2_SYNTAX` — recognized as valid DB2 syntax
- `DB2_SEMANTIC` — semantic model derived from source
- `PORTABLE_EXECUTABLE` — deterministically executable on the controlled
  test database
- `DB2_RUNTIME_VERIFIED` — **only claimable with evidence from a real DB2
  subsystem run**

**SQLite execution proves controlled semantic/executable behavior at
most (`PORTABLE_EXECUTABLE`).  It does NOT prove DB2 runtime
compatibility.**  Only a real DB2 runtime execution may reach
`DB2_RUNTIME_VERIFIED`.  The lane never manufactures that claim;
`runtime_verified_features()` is expected to stay empty.

## Java mapping

`map_db2_model_to_repository()` produces deterministic
`SqlRepositoryMapping` output:

- one `Repository` per table, methods named from verb + table
  (`findAccount`, `insertAccount`, `updateAccount`, `deleteAccount`)
- host-variable **parameters** use per-statement direction (pure OUTPUT
  are returns, not parameters)
- `status_outcomes` derived from possible statuses
- repeated operations get deterministic numeric suffixes
- COMMIT / ROLLBACK map to `commit` / `rollback` service methods
- default Java type is `String` with a **`java_type_resolver` hook**;
  COBOL PIC resolution is documented as deferred to the consumer layer

## Spring integration hook

The shared Spring generators (`spring_boot_ir.py`,
`spring_boot_generator.py`, `java_to_spring_mapping.py`) are **frozen /
off-limits** for this lane.  Integration is a documented contract:

1. Call `map_sql_model_to_repository()` (facade in
   `engine/transformation/sql_repository_mapping.py`).
2. Consume `SqlRepositoryMapping` repositories/service in the Spring
   generation lane (strategy methods, `status_outcomes` → exception or
   status handling).
3. Map `commit`/`rollback` service methods to Spring transaction
   semantics.
4. Provide a `java_type_resolver` for exact COBOL PIC → Java types.

Shared Spring generator integration is intentionally deferred to the
consumer/integration layer; this lane does not modify those files.

## Dependencies / frozen files consulted (not modified)

- `engine/transformation/sql_parser.py` (existing parser, unchanged)
- `engine/transformation/ir.py` (SQL IR, frozen)

## Tests

```
tests/test_db2_status.py
tests/test_db2_semantics.py
tests/test_db2_mapping.py
tests/test_db2_execution.py
tests/test_db2_compatibility.py
tests/test_db2_fixture.py
```

Run: `python -m pytest tests -q -k "db2_"`

## Limitations

- Not a DB2 compiler/runtime; status boundary is modeled, not verified.
- Extraction covers `EXEC SQL ... END-EXEC` blocks, not full COBOL flow
  (loops, MOVE values are lane-controlled via `statement_bindings`).
- `account_seed.sql` documents DB2-verifiable seed; the harness loads the
  CSV feed for determinism (consistency guarded by `test_db2_fixture.py`).