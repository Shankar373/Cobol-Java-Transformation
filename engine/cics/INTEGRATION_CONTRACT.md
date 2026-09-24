# CICS Lane Integration Contract

This contract describes how an external consumer may use the isolated CICS
lane without modifying shared pipeline, API, oracle, frontend, parser, IR, or
Spring-generator code.

No CICS Transaction Server runtime equivalence is claimed. Runtime status is
`NOT_RUNTIME_VERIFIED`.

## 1. Public entry points

The public facade is:

- `engine/transformation/cics_java_mapping.py`

Supported entry points:

- `extract_cics_blocks(cobol_source: str) -> list[CicsApplication]`
- `map_cics_programs(...) -> CicsSpringApplication`
- `generate_cics_spring(application: CicsSpringApplication) -> list[CicsGeneratedFile]`
- `map_and_generate_cics(...) -> list[CicsGeneratedFile]`
- `transform_cics_program(cobol_source, ...) -> tuple[CicsSpringApplication, list[CicsGeneratedFile]]`
- `to_shared_generated_files(files: list[CicsGeneratedFile]) -> list[SharedGeneratedFile]`

`SharedGeneratedFile` is an alias for the existing
`engine.transformation.contracts.GeneratedFile`. The shared contracts module
is consumed read-only and is not modified by this lane.

## 2. Input contract

Accepted inputs:

- COBOL source containing a single `PROGRAM-ID`;
- one or more `EXEC CICS ... END-EXEC` blocks;
- optionally, pre-parsed `CicsApplication` objects.

Facade guarantees:

- source text is not modified;
- blocks are returned in source order;
- unbalanced blocks without `END-EXEC` are skipped rather than invented;
- multiple blocks belonging to the same `PROGRAM-ID` are consolidated into
  one service while preserving command order.

Limitation:

- A source string containing multiple distinct `PROGRAM-ID` sections should be
  split by program before extraction, or supplied as pre-parsed applications
  with distinct program IDs.

## 3. Output contract

The lane returns two complementary representations:

1. `CicsSpringApplication`
   - deterministic semantic model;
   - one `CicsService` per COBOL program;
   - explicit transaction, interaction, resource, explicit-only, and
     unsupported information;
   - validation errors through `validate()`.

2. `list[CicsGeneratedFile]`
   - native generated-file representation;
   - includes Java class/file names and project-relative paths;
   - includes the explicit CICS mapping report;
   - contains the normative no-equivalence disclaimer.

`transform_cics_program` returns both representations together.

## 4. Generated-file contract

Native CICS files use:

```python
CicsGeneratedFile(
    filename="DemoprgService.java",
    source_code="...",
    class_name="DemoprgService",
    path="src/main/java/com/generated/cics/service/DemoprgService.java",
)
```

Expected file kinds for a one-service application are:

- `CicsApplication.java`
- `cics/CicsRuntime.java`
- `client/ProgramClient.java`
- `service/<Service>Service.java`
- `dto/<Program>CommArea.java`
- `cics-mapping/<app>-CICS-MAPPING.md`

Generated Java files use ASCII source text.

## 5. Diagnostics

Unsupported CICS constructs are diagnostics, not silent omissions.

Each unsupported construct carries:

- command name;
- original raw CICS text;
- explicit outside-subset reason.

Unsupported constructs appear in:

- `CicsService.unsupported_constructs`;
- `CicsSpringApplication.all_unsupported()`;
- generated service `CICS-UNSUPPORTED` comments;
- the mapping-report unsupported section.

Structural mapping problems, such as missing resources or missing LINK/XCTL
program names, are carried as `CicsMappingIssue` values with `INFO`,
`WARNING`, or `ERROR` severity.

## 6. Status semantics

Relevant classifications:

- `IMPLEMENTED`
  - supported CICS mapping, model, generation, facade, tests, fixture, and
    documentation described here.
- `STRUCTURALLY_VERIFIED`
  - behavior covered by deterministic unit, mapping, generation, facade, and
    fixture tests.
- `NOT_RUNTIME_VERIFIED`
  - no CICS TS execution, oracle comparison, or runtime-equivalence claim.
- `UNSUPPORTED`
  - commands outside the supported subset, retained explicitly.
- `RUNTIME_VERIFIED`
  - not claimed by this lane.

## 7. `GeneratedFile` compatibility

`to_shared_generated_files` converts native CICS files into shared contract
objects while preserving:

- filename;
- complete source text.

It records:

- `language="java"` for generated `.java` files;
- `language="markdown"` for the generated mapping report.

CICS-specific `class_name` and project-relative `path` remain available only
on the native `CicsGeneratedFile`.

## 8. Application and program boundaries

One COBOL program maps to one CICS service. Multiple programs map to multiple
services within one `CicsSpringApplication`.

The lane does not create shared controllers, shared repositories, database
migrations, production Spring wiring, or cross-program business logic.

Runtime seams are interfaces:

- `CicsRuntime`;
- `ProgramClient`.

Their implementations remain manual and reviewable.

## 9. Future API and pipeline integration points

A future consumer may integrate without changing the isolated implementation
by:

- calling `extract_cics_blocks` for CICS-aware source ingestion;
- calling `map_cics_programs` when only the semantic model is needed;
- calling `map_and_generate_cics` or `transform_cics_program` when generated
  source is needed;
- calling `to_shared_generated_files` before passing results to a consumer
  that expects shared `contracts.GeneratedFile` objects;
- presenting `CicsMappingIssue` and unsupported-construct records as
  user-facing mapping diagnostics;
- treating `NOT_RUNTIME_VERIFIED` as a hard boundary until a real,
  independently validated CICS execution oracle exists.

Future pipeline or API work must not reinterpret generated seams as proof of
CICS runtime behavior.
