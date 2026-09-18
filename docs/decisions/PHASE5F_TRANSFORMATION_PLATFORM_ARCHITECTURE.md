# Phase 5F: Transformation Platform Architecture Decision

## Context

Phase 5F established whether the COBOL-to-Java transformation infrastructure
is a reusable transformation platform or a Claims-specific template behind a
reusable interface.

## Decision

**The current implementation is a Claims-specific transformer with reusable
architectural seams. Generic COBOL transformation is NOT YET PROVEN.**

## Architecture

```
COBOL source
    ↓
TransformationProducer (interface — reusable)
    ↓
InternalNativeJavaProducer (implementation — Claims-specific)
    ↓
CobolParser → CobolProgram IR (partially reusable)
    ↓
JavaGenerator → Generated Java (Claims-specific template)
    ↓
DockerJavaCandidateAdapter (reusable)
    ↓
Validation Engine (reusable, independent)
    ↓
Evidence + Verdict
```

## What IS Reusable

1. **TransformationProducer interface** (contracts.py) — Any producer can
   implement this. The validation engine accepts Java from any producer.

2. **CobolParser** — Parses COBOL into IR. Handles the Claims-specific subset.
   Parser architecture is extensible, but current implementation is limited.

3. **CobolProgram IR** (ir.py) — Generic IR dataclasses. Could represent any
   COBOL program if the parser populated them correctly.

4. **DockerJavaCandidateAdapter** — Compiles and executes Java in sandboxed
   Docker containers. Fully reusable.

5. **Validation Engine** — Comparators, EvidenceIntegrityValidator,
   VerdictDeriver. All reusable and independent of the producer.

6. **OpenSourceCOBOL4J adapter** (producers/opensource4j.py) — Alternative
   producer adapter. Demonstrates producer replacement is possible.

## What IS NOT Reusable

1. **JavaGenerator** — The generator is a single method
   `_generate_claims_java()` that emits a hardcoded Claims settlement template.
   It does NOT read business logic from the IR. Changing COBOL source values
   (thresholds, status codes) does NOT change the generated Java.

2. **Parser statement handling** — The parser silently skips unknown statements
   (line 405: `return None, start + 1`). This means unsupported COBOL
   constructs are silently ignored rather than reported.

3. **Source-driven generation** — Only file paths (from FILE-CONTROL) and
   class name (from PROGRAM-ID) are source-driven. All business logic is
   template-hardcoded.

## Source-Driven Proof Results

| Element | Source-driven? | Evidence |
|---------|---------------|----------|
| File paths | YES | Generator reads from IR file_definitions |
| Class name | NO | Generator ignores program_id parameter |
| Threshold (500) | NO | Template-hardcoded string |
| Status codes (R,P,A) | NO | Template-hardcoded strings |
| Payment matching logic | NO | Template-hardcoded |
| Report format | NO | Template-hardcoded |
| Settlement logic | NO | Template-hardcoded |
| Counter increments | NO | Template-hardcoded |

## Reusable Architecture Test

A minimal non-Claims COBOL program (HELLO-WORLD with MOVE, ADD, IF, DISPLAY)
was parsed into IR correctly. However, the generator emitted the same Claims
settlement template regardless of input. The parser also lost statements
(only 1 paragraph parsed instead of expected statements).

**Result: Parser → IR architecture is partially reusable. Generator is NOT
reusable for non-Claims programs.**

## Transformation Error Safety

Unsupported COBOL constructs (e.g., COMPUTE) are silently skipped by the
parser. The producer returns SUCCESS with no diagnostics. This violates the
required invariant that unsupported COBOL must not silently become successful
transformation.

## Producer Boundary

The producer does NOT import:
- VerdictDeriver
- EvidenceIntegrityValidator
- ComparatorRegistry
- Pipeline

The producer boundary is clean. Producer replacement is architecturally
possible (demonstrated by OpenSourceCOBOL4J adapter).

## OpenSourceCOBOL4J Status

- Transforms Claims COBOL → Java: YES
- Java compilation: YES (with libcobj.jar)
- JVM execution: YES (with libcobj.jar)
- Standalone native Java: NO
- Classification: OPTION D — Do not adopt as primary
- Retained as benchmark/alternative producer
