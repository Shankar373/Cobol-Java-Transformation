# CICS Java/Spring Modernization Profile — Specification

This document specifies the isolated CICS modernization lane implemented in
`engine/cics/` and exposed through
`engine/transformation/cics_java_mapping.py`.

## 1. Scope and honesty boundary

This is a Java/Spring modernization profile for the supported CICS subset.
It does NOT claim CICS Transaction Server runtime equivalence.

The lane produces:

- COBOL source
- semantic mapping
- explicit Java/Spring representation
- generated source

It does not execute CICS transactions, emulate terminal behavior, reproduce
RESP-code semantics, recreate commarea copy behavior, or certify behavioral
equivalence. Runtime status is therefore:

- `NOT_RUNTIME_VERIFIED`

## 2. Supported subset version

Supported-subset contract version:

- `1.0.0`

The version constant lives in `engine/cics/subset.py` as
`SUPPORTED_SUBSET_VERSION`. The mapper stamps the same version onto every
generated `CicsSpringApplication`.

## 3. Command classifications

Classification is centralized in `engine/cics/subset.py`. The three possible
statuses are:

- `MAPPED`
- `EXPLICIT_ONLY`
- `UNSUPPORTED`

### 3.1 Terminal I/O request/response

Mapped:

- `SEND`
- `RECEIVE`

These become explicit `CicsTerminalIo` elements containing map names, mapsets,
terminal IDs, data fields, length fields, transaction IDs, and raw CICS text.

### 3.2 Program/service interaction

Mapped:

- `LINK`
- `XCTL`
- `RETURN`

These become explicit `CicsProgramInteraction` elements containing interaction
kind, target program, COMMAREA data/length, channel/container references,
transaction ID, and raw CICS text.

### 3.3 Transaction boundaries

Mapped:

- `SYNCPOINT`
- `ABEND`
- `RETURN`

These become explicit `CicsTransactionBoundary` elements.

### 3.4 Resource access

Mapped file operations:

- `READ`
- `WRITE`
- `REWRITE`
- `DELETE`
- `STARTBR`
- `READNEXT`
- `READPREV`
- `ENDBR`

Mapped temporary-storage queue operations:

- `WRITEQ`
- `READQ`
- `DELETEQ`

These become explicit `CicsResourceAccess` elements containing operation,
resource kind, resource name, key/data/length fields, RESP/RESP2 fields and
policy, and raw CICS text.

### 3.5 Explicit-only constructs

Carried verbatim but never translated into runtime behavior:

- `HANDLE_CONDITION`
- `HANDLE_AID`
- `ASSIGN`

They appear in the model as `CicsExplicitConstruct` elements and in generated
services as explicit comments.

### 3.6 Unsupported constructs

Explicitly unsupported today:

- `ALLOCATE`
- `FREE`
- `HOLD`
- `RELEASE`
- `SET`
- `IGNORE`
- `POP`
- `PUSH`

Unsupported commands are classified as `UNSUPPORTED`, retained in the model as
`CicsUnsupportedConstruct` elements, emitted verbatim in generated services,
and listed verbatim in the CICS mapping report.

## 4. Unknown-command policy

Any command value not present in the supported-subset tables uses the
fallback classification:

- status: `UNSUPPORTED`
- category: `UNSUPPORTED`

Unknown constructs are preserved with raw text and an explicit reason. They
are never silently dropped and never invented as supported behavior.

## 5. Semantic mapping

The mapper at `engine/cics/mapper.py` is the only boundary between the shared
CICS IR and the IR-free CICS output model.

Mapping guarantees:

- every parsed command becomes exactly one flow step;
- command order is preserved;
- host-variable names have a leading `:` removed and are deduplicated;
- RESP/RESP2 modes are carried as explicit policies;
- explicit-only structures are carried verbatim;
- unsupported commands are retained with reasons.

The output model in `engine/cics/model.py` does not import
`engine.transformation.ir`.

## 6. Transaction semantics

Boundary mapping:

- `SYNCPOINT` maps to `COMMIT`;
- `ABEND` maps to `ROLLBACK`;
- `RETURN` maps to `PSEUDO_CONVERSATIONAL`.

`RETURN` is dual-recorded:

- one `CicsProgramInteraction` with kind `RETURN`;
- one `CicsTransactionBoundary` with kind `PSEUDO_CONVERSATIONAL`.

Services are marked transactional when they contain transactional signals,
including write operations, LINK/XCTL interactions, SYNCPOINT, ABEND, or
RETURN. Model validation additionally requires a transactional service to
declare at least one explicit transaction boundary.

## 7. Request/response model

`SEND` and `RECEIVE` are modeled as terminal I/O exchanges rather than live
terminal operations. Generated seams accept operand references such as map
names and host-variable names.

Generated runtime-seam examples:

- `receive(String mapName)`
- `receive(String mapName, String intoField, String lengthField)`
- `send(String mapName)`
- `send(String mapName, String fromField, String lengthField)`

The generated service calls these seams in original CICS command order.

## 8. LINK/XCTL interaction model

`LINK` and `XCTL` targets become methods on the generated `ProgramClient`
delegation seam. Method names are deterministic derivations such as
`linkNextpgm`.

The generated seam contains no implementation. Each method documents the
originating CICS interaction verbatim. Implementing the target is an explicit,
manual, reviewed integration step.

## 9. Generated artifact model

For each application, the generator emits:

- `CicsApplication.java`
- `cics/CicsRuntime.java`
- `client/ProgramClient.java`
- `dto/<Program>CommArea.java` for each service
- `service/<Service>Service.java` for each service
- `cics-mapping/<app>-CICS-MAPPING.md`

Each service has an `execute()` method with one private `stepN()` method per
CICS command, preserving original order. Unsupported constructs are emitted as
`CICS-UNSUPPORTED` comments in both the service and mapping report.

The mapping report records subset/generator versions, services, boundaries,
request/response exchanges, interactions, resource access, explicit-only
constructs, and unsupported constructs.

## 10. `NO_EQUIVALENCE_DISCLAIMER`

Every generated source file and mapping report contains:

```text
NOT CICS TS EQUIVALENCE: this generated representation preserves the
 structural shape of the CICS program (transaction boundaries,
 request/response, program interaction, resource access). It does NOT
 reproduce IBM CICS Transaction Server runtime behavior (RESP codes,
 commarea copy semantics, transaction isolation, pseudo-conversational
 state, terminal I/O).
```

This disclaimer is normative for the lane.
