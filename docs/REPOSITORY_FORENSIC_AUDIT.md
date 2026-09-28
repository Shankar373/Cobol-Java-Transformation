# Repository Forensic Audit

**Repository:** `Shankar373/Cobol-Java-Transformation`  
**Branch:** `codex/universal-core`  
**Audited HEAD:** `fd99b9e5a4935b994450dc31b5b03f18369fdd37`  
**Latest CI:** Run #175  
**Run ID:** `36397418842`  
**Commit:** `fix: restore evaluate lowering in active mapper`  
**Audit mode:** Read-only forensic inspection

> No production code, tests, CI, history, or configuration was modified as part of the audit.

---

# 1. CURRENT PRODUCT REALITY

The repository is a functioning deterministic COBOL modernization and behavioral-validation vertical slice.

Actual implemented flow:

```
COBOL input
  -> secure ingestion
  -> application discovery
  -> semantic IR
  -> capability analysis
  -> modernization plan
  -> deterministic COBOL -> Java transformation
  -> Java application model
  -> Spring Boot mapping/generation
  -> COBOL oracle execution
  -> Java candidate execution
  -> declaration-driven comparison
  -> evidence
  -> evidence integrity validation
  -> fail-closed verdict
```

The project is no longer greenfield.

However, the documented `TransformationProducer` architecture is not yet the authoritative production transformation boundary.

Actual active transformation path:

```
ApplicationGenerator
  -> map_cobol_programs_to_application()
  -> JavaGenerator
```

rather than:

```
TransformationProducer
  -> selected producer
  -> candidate
```

---

# 2. GREEN BASELINE

```
HEAD:
fd99b9e5a4935b994450dc31b5b03f18369fdd37

CI:
Run #175
Run ID: 36397418842

Commit:
fix: restore evaluate lowering in active mapper

Result:
GREEN
```

Run #175 passed:

- ingestion diagnostics
- frontend tests
- TypeScript
- frontend production build
- backend tests
- COBOL tests
- Java Docker tests
- Docker/oracle setup
- provenance/evidence validation
- integration tests

Green CI proves the current tested workload passes. It does **not** prove universal COBOL semantic equivalence.

---

# 3. ACTUAL END-TO-END PIPELINE

Authoritative API path:

```
api.app
  -> api.service.Service
  -> UniversalModernizationPipeline
  -> ApplicationDiscovery
  -> CapabilityAnalyzer
  -> TransformationPlanGenerator
  -> ApplicationGenerator
  -> map_cobol_programs_to_application()
  -> JavaApplication
  -> map_java_application_to_spring_boot()
  -> SpringBootGenerator
  -> generated Spring Boot project
  -> VerticalSlicePipeline
  -> DockerOracleAdapter
  -> candidate build
  -> candidate execution
  -> ComparatorRegistry
  -> EvidenceManifest
  -> EvidenceIntegrityValidator
  -> VerdictDeriver
```

Important files:

- `api/app.py`
- `api/service.py`
- `engine/modernization/pipeline.py`
- `engine/modernization/modernization_planner.py`
- `engine/modernization/capability_analyzer.py`
- `engine/modernization/transformation_plan.py`
- `engine/transformation/application_discovery.py`
- `engine/transformation/application_generator.py`
- `engine/transformation/cobol_parser.py`
- `engine/transformation/ir.py`
- `engine/transformation/cobol_to_java_mapping.py`
- `engine/transformation/java_generator.py`
- `engine/transformation/java_to_spring_mapping.py`
- `engine/transformation/spring_boot_generator.py`
- `engine/pipeline.py`
- `engine/oracle/docker_adapter.py`
- `engine/candidate/docker_spring_boot_adapter.py`
- `engine/comparators/framework.py`
- `engine/evidence/models.py`
- `engine/evidence/integrity.py`
- `engine/verdict/derivation.py`

---

# 4. PARSER -> IR

Primary parser:

```
engine/transformation/cobol_parser.py
```

Primary IR:

```
engine/transformation/ir.py
```

The IR contains explicit structures for:

- COBOL types
- source provenance
- field provenance
- data items
- file definitions
- file keys
- expressions
- literals
- field references
- unary/binary expressions
- comparisons
- logical conditions
- IF
- EVALUATE
- WHEN
- PERFORM
- CALL
- COMPUTE
- arithmetic statements
- file statements
- paragraphs
- programs
- applications
- dependencies

Classification: **IMPLEMENTED**

Relevant tests:

- `tests/transformation/test_parser.py`
- `tests/transformation/test_ir.py`
- `tests/transformation/test_semantic_foundation.py`

---

# 5. COBOL CONSTRUCT SUPPORT

| Construct | Current state |
|---|---|
| MOVE | IMPLEMENTED |
| ADD | IMPLEMENTED subset |
| SUBTRACT | IMPLEMENTED subset |
| MULTIPLY | IMPLEMENTED subset |
| DIVIDE | IMPLEMENTED subset |
| COMPUTE | IMPLEMENTED subset |
| IF / ELSE | IMPLEMENTED |
| EVALUATE | IMPLEMENTED subset |
| WHEN / WHEN OTHER | IMPLEMENTED subset |
| PERFORM | PARTIAL |
| PERFORM TIMES | IMPLEMENTED subset |
| PERFORM UNTIL | IMPLEMENTED subset |
| PERFORM VARYING | PARTIAL |
| PERFORM THRU | IMPLEMENTED subset |
| CALL | IMPLEMENTED subset |
| LINKAGE | IMPLEMENTED subset |
| COPY | IMPLEMENTED subset |
| STRING | PARTIAL |
| UNSTRING | PARTIAL |
| GO TO | PARSED, transformation unsupported |
| FD | PARTIAL |
| Indexed files | PARTIAL |
| Relative files | PARTIAL |
| Dynamic CALL | UNSUPPORTED |
| EVALUATE ALSO | UNSUPPORTED |
| SET | UNSUPPORTED |
| ROUNDED | UNSUPPORTED |
| ON SIZE ERROR | UNSUPPORTED |
| INSPECT | UNSUPPORTED |
| ACCEPT | UNSUPPORTED |

---

# 6. DATA / TYPE SEMANTICS

The parser/IR preserves meaningful metadata for:

- PIC type
- length
- decimal places
- signedness
- USAGE
- source provenance
- field provenance

This is tested by:

```
tests/transformation/test_semantic_foundation.py
```

However, semantic information is not fully preserved through Java generation.

## Important gaps

- COMP semantics
- COMP-3 storage semantics
- fixed-point decimal semantics
- exact scale
- exact precision
- COBOL rounding
- truncation
- overflow behavior
- figurative constants
- REDEFINES storage overlays
- OCCURS runtime representation
- level-88 condition-name semantics

Classification:

**PARTIAL**

---

# 7. COMP-3

COMP-3 metadata is recognized and represented.

The repository contains COMP-3 fixtures/tests.

However, there is no sufficient end-to-end differential proof that generated Java preserves the full behavioral semantics of packed decimal values.

Therefore:

- parsing: **IMPLEMENTED**
- metadata: **IMPLEMENTED**
- runtime semantic equivalence: **UNPROVEN / PARTIAL**

---

# 8. FIGURATIVE CONSTANTS

Dedicated semantic treatment is missing for:

- SPACES
- ZEROS
- HIGH-VALUES
- LOW-VALUES

These are not represented as a dedicated semantic literal type throughout the transformation path.

Classification:

**UNSUPPORTED / PARTIAL**

---

# 9. REDEFINES

The IR contains a `redefines` relationship.

This proves representation of the relationship, not COBOL storage-overlay semantics.

Generated Java does not establish a general equivalent shared-storage model.

Classification:

- metadata: **IMPLEMENTED**
- runtime semantics: **PARTIAL / UNPROVEN**

---

# 10. OCCURS

OCCURS/table metadata exists in the IR.

The active Java model does not provide a complete equivalent array/table representation with COBOL-compatible indexing/storage semantics.

Classification:

**PARTIAL / UNPROVEN**

---

# 11. LEVEL 88

Level-88 metadata is recognized.

However, the semantic relationship:

```
condition-name
  -> parent field
  -> value/range
```

is not fully modeled and lowered.

`SET` is also unsupported.

Classification:

**PARTIAL**

---

# 12. CONTROL FLOW

## IF

Structured `IfStatement` exists with:

- condition
- then body
- else body

Classification: **IMPLEMENTED**

## EVALUATE

Current HEAD specifically restores EVALUATE lowering in the active mapper.

Supported EVALUATE structures are lowered deterministically to Java conditional logic.

Classification: **IMPLEMENTED SUBSET**

Complex `EVALUATE ALSO` remains unsupported.

## PERFORM

The implementation handles several forms:

- paragraph PERFORM
- PERFORM THRU
- TIMES
- UNTIL
- VARYING
- TEST BEFORE
- TEST AFTER

Complex semantics remain only partially structured.

Classification: **PARTIAL**

## GO TO

GO TO is parsed/represented, but arbitrary GO TO transformation is not implemented.

Capability analysis correctly treats it as unsupported.

Classification: **UNSUPPORTED**

---

# 13. EXPRESSIONS / ARITHMETIC

Implemented syntax/generation includes:

- ADD
- SUBTRACT
- MULTIPLY
- DIVIDE
- COMPUTE
- parentheses
- operator precedence
- unary expressions
- expression trees

Not fully implemented semantically:

- ROUNDED
- ON SIZE ERROR
- fixed-point arithmetic
- COBOL overflow rules
- exact precision/scale
- truncation rules

Classification:

- arithmetic mapping: **IMPLEMENTED**
- COBOL numeric equivalence: **PARTIAL**

Relevant tests include arithmetic and COMPUTE mapping tests.

---

# 14. CALL / MULTI-PROGRAM

Implemented subset:

- static CALL discovery
- CALL relationships
- program dependencies
- LINKAGE SECTION
- PROCEDURE DIVISION USING
- CALL parameters
- COPY dependencies
- entry programs

Tests:

- `tests/test_call_execution_p0.py`
- `tests/integration/test_oracle_multiprogram.py`

Unsupported:

- dynamic CALL
- recursive CALL
- cyclic CALL graphs
- unresolved dynamic program selection

Classification:

**IMPLEMENTED SUBSET**

---

# 15. TRANSFORMATION PRODUCER ARCHITECTURE

The repository contains:

```
engine/transformation/contracts.py
engine/transformation/producer.py
engine/transformation/producers/internal_native.py
engine/transformation/producers/opensource4j.py
```

Real producer implementations exist:

- `InternalNativeJavaProducer`
- `OpenSourceCOBOL4JProducerAdapter`

But the authoritative pipeline bypasses them.

Current production route:

```
ApplicationGenerator
  -> map_cobol_programs_to_application()
  -> JavaGenerator
```

Therefore:

| Question | State |
|---|---|
| Producer abstraction exists | IMPLEMENTED |
| Native producer exists | IMPLEMENTED |
| OpenSource COBOL 4J adapter exists | IMPLEMENTED |
| Producer selected by main pipeline | NOT IMPLEMENTED |
| Producer substitution | UNPROVEN |
| Producer identity in evidence | NOT IMPLEMENTED |

This is **ARCHITECTURAL DRIFT**.

---

# 16. STALE PRODUCER METADATA

The native producer's capability metadata still describes some constructs as unsupported even though the active mapper now implements them, including:

- COMPUTE
- SUBTRACT
- MULTIPLY
- CALL
- EVALUATE

Classification:

**STALE / ARCHITECTURAL DRIFT**

---

# 17. OPEN SOURCE COBOL 4J

The OpenSourceCOBOL4J adapter is executable and uses Docker to invoke the toolchain and retrieve generated Java.

However, it is not integrated into the authoritative modernization pipeline.

Classification:

- adapter: **IMPLEMENTED**
- active pipeline integration: **NOT IMPLEMENTED**

---

# 18. JAVA GENERATION

The intended active architecture is:

```
COBOL
  -> COBOL IR
  -> JavaApplication
  -> JavaGenerator
```

Spring mapping then operates on the Java application model.

Classification:

**IMPLEMENTED**

Relevant files:

- `engine/transformation/java_generator.py`
- `engine/transformation/java_to_spring_mapping.py`
- `engine/transformation/spring_boot_generator.py`

---

# 19. DUPLICATE GENERATION / MAPPING CODE

There are legacy direct-generation helpers in `JavaGenerator`, including older statement/expression generation paths.

More importantly, `engine/transformation/cobol_to_java_mapping.py` contains duplicate definitions of important mapper functions.

Examples:

- `map_pic_to_java_type`
- `map_pic_to_java_default`
- `map_cobol_expr_to_java`
- `map_cobol_condition_to_java`
- `map_cobol_statement`
- `map_cobol_data_items_to_fields`

Later Python definitions shadow earlier ones.

Classification:

**DUPLICATED / SHADOWED LEGACY CODE**

No deletion was performed.

---

# 20. SPRING BOOT GENERATION

The Spring Boot generator is real and executable.

Flow:

```
JavaApplication
  -> map_java_application_to_spring_boot()
  -> SpringBootApplication
  -> SpringBootGenerator.generate_project()
```

Generated project artifacts include:

- Maven project
- application class
- services
- repositories/adapters
- configuration
- resources

Integration tests prove generated applications can build and run.

Classification:

**IMPLEMENTED**

---

# 21. ORACLE EXECUTION

Oracle:

```
GnuCOBOL
```

Adapter:

```
engine/oracle/docker_adapter.py
```

The oracle executes in Docker with:

- network isolation
- CPU limits
- memory limits
- PID limits
- timeout
- staged source
- stdout/stderr capture
- exit status
- generated-file collection

Relevant tests:

- `tests/integration/test_vertical_slice.py`
- `tests/integration/test_oracle_multiprogram.py`

Classification:

**IMPLEMENTED**

---

# 22. ORACLE DIGEST PROVENANCE GAP

The configured oracle image is referenced using a mutable tag:

```
gnucobol-ocesql:latest
```

while evidence records a digest.

The actual runtime invocation is not cryptographically bound to the recorded digest.

Therefore:

- declared digest: **YES**
- runtime digest binding: **NO**

Classification:

**P0 PROVENANCE GAP**

---

# 23. CANDIDATE EXECUTION

The candidate path uses Docker.

It provides:

- Java compilation
- Maven build
- staged inputs
- execution
- stdout/stderr capture
- exit status
- output-file capture
- timeout
- resource limits
- network isolation
- cleanup

Classification:

**IMPLEMENTED**

---

# 24. CANDIDATE ENVIRONMENT PROVENANCE GAP

The normal candidate runtime uses Java 21.

However, candidate manifest construction currently records Java 25.

This is inconsistent with the actual runtime environment.

Classification:

**P1 PROVENANCE BUG**

---

# 25. UNIVERSAL EXECUTION

Execution abstractions exist:

- CandidateAdapter
- OracleAdapter
- ExecutionEvidence

However, the real adapters remain technology-specific:

- DockerOracleAdapter
- DockerJavaCandidateAdapter
- DockerSpringBootCandidateAdapter

The main production path assumes a COBOL oracle and Java/Spring candidate.

Classification:

- execution abstraction: **IMPLEMENTED**
- truly producer-neutral execution: **PARTIAL**

---

# 26. COMPARISON

Comparator framework:

```
engine/comparators/framework.py
```

Current comparison types include:

- stdout
- stderr
- exit status
- text files
- fixed-record files

Normalization is intentionally conservative.

It does not generally perform:

- arbitrary whitespace normalization
- ordering normalization
- numeric tolerance
- semantic COBOL-field normalization
- EBCDIC conversion
- field-aware numeric comparison

Classification:

**IMPLEMENTED V1**

---

# 27. API DEFAULT CERTIFICATION SCOPE

The normal API workload defaults to:

```
STDOUT
EXIT_STATUS
```

Therefore generated file outputs are not automatically certification obligations unless declared by the workload.

Important distinction:

```
Generated file exists
!=
Generated file is automatically certified
```

Classification:

**DECLARATION-DRIVEN / LIMITED DEFAULT SCOPE**

---

# 28. EVIDENCE

The evidence model records substantial execution information:

- source identity
- source hash
- candidate identity
- candidate hash
- generated artifact hashes
- oracle identity
- image digest
- compiler/runtime information where available
- commands
- environment information where populated
- exit status
- stdout/stderr hashes
- output artifacts
- comparison evidence
- input hashes
- manifest identity

Classification:

**IMPLEMENTED**

---

# 29. EVIDENCE INTEGRITY

`engine/evidence/integrity.py` validates relationships including:

- run binding
- workload binding
- source binding
- candidate binding
- oracle binding
- execution/artifact binding
- comparison/artifact binding
- required evidence
- integrity hash

Relevant tests:

- `tests/adversarial/test_evidence_tampering.py`
- `tests/adversarial/test_evidence_trust_boundary.py`
- `tests/integration/test_forensic_evidence.py`

Classification:

**IMPLEMENTED**

---

# 30. ENVIRONMENT EVIDENCE GAP

The pipeline currently constructs an empty environment identity collection.

Therefore the final evidence does not consistently bind the verdict to:

- Java version
- Maven version
- Python version
- Docker runtime identity
- complete compiler environment

Classification:

**PARTIAL**

---

# 31. PRODUCER EVIDENCE GAP

Candidate identity supports producer fields, but the active pipeline does not populate them.

Therefore final evidence does not reliably identify the exact transformation producer/version that generated the candidate.

Classification:

**P1 IMPORTANT GAP**

---

# 32. VERDICT / CERTIFICATION

Primary implementation:

```
engine/verdict/derivation.py
```

Current verdict states include:

- VERIFIED
- PARTIAL
- FAILED
- UNPROVEN
- UNAVAILABLE
- ERROR
- UNSUPPORTED

Important fail-closed behavior:

```
No comparisons
  -> UNPROVEN

Missing evidence
  -> UNPROVEN

Mismatch
  -> FAILED

Infrastructure unavailable
  -> UNAVAILABLE

Unsupported artifact
  -> UNSUPPORTED

Trust-boundary failure
  -> ERROR

All required evidence and comparisons pass
  -> VERIFIED
```

This is one of the strongest parts of the architecture.

---

# 33. CAPABILITY ANALYSIS

Primary implementation:

```
engine/modernization/capability_analyzer.py
```

It detects, among other things:

- GO TO
- unsupported constructs
- CALL dependencies
- dynamic CALL
- recursive CALL
- CALL cycles
- PERFORM dependencies
- unresolved dependencies
- some file capabilities
- infrastructure availability

However, it does not fully derive capability from actual semantic transformation support.

Missing/weak capability modeling includes:

- COMP-3 runtime semantics
- exact decimal semantics
- REDEFINES
- OCCURS
- level 88
- figurative constants
- ROUNDED
- SIZE ERROR
- producer capability
- complete file semantics

Classification:

**PARTIAL**

---

# 34. PLANNER / TRANSFORMER MISMATCH

The planner can classify a construct as supported based on syntax/dependency analysis while the active transformer may not faithfully preserve its complete semantics.

Therefore:

```
Planner support
!=
semantic equivalence
```

This is a major architectural gap.

---

# 35. TRANSFORMATION PLAN

The plan model contains:

- INTERNAL_NATIVE
- OPEN_SOURCE_4J
- SKIP

However, actual routing primarily selects native transformation or skip.

OpenSourceCOBOL4J is not a selectable producer in the authoritative pipeline.

The current topological ordering implementation is also not a complete dependency-topological sort.

Classification:

**PARTIAL**

---

# 36. COPYBOOKS

Copybook handling is implemented to a meaningful subset.

The application generator prepares copybooks and creates shared representations.

Missing/ambiguous copybooks fail deterministically.

Classification:

**IMPLEMENTED SUBSET**

Full COPY/REPLACING semantics are not proven.

---

# 37. TEST COVERAGE AS EVIDENCE

The test suite covers:

- parser
- IR
- semantic metadata
- arithmetic
- CALL
- PERFORM
- Java generation
- Spring generation
- Oracle
- candidate execution
- comparison
- evidence
- provenance
- verdict
- capability
- planner
- pipeline
- adversarial/security cases

Strong evidence exists for:

- parser fundamentals
- IR structure
- provenance metadata
- arithmetic subset
- EVALUATE lowering
- CALL linkage subset
- Spring generation
- Docker execution
- evidence integrity
- fail-closed verdict behavior

Important areas remain **UNPROVEN**:

- full COBOL semantic equivalence
- COMP-3 execution
- decimal equivalence
- REDEFINES runtime semantics
- OCCURS runtime semantics
- level-88 semantics
- figurative constants
- ROUNDED
- SIZE ERROR
- complete PERFORM semantics
- complete STRING/UNSTRING semantics
- indexed/relative file semantics
- producer substitution
- producer provenance
- oracle runtime digest binding
- complete environment provenance
- field-aware semantic comparison

---

# 38. CI / DOCKER / REPRODUCIBILITY

CI is Docker-backed and genuinely executes oracle/candidate tests.

Environment includes:

- Ubuntu 24.04 runner
- Python 3.11
- Node 20
- Java 21
- Maven
- GnuCOBOL
- Docker

Run #175 is green.

However, several build inputs use mutable tags/package repositories.

Examples:

- `ubuntu:22.04`
- `maven:3.9-eclipse-temurin-21`
- `gnucobol-ocesql:latest`

Therefore:

- CI repeatability: **GOOD**
- byte-for-byte environment reproducibility: **NOT FULLY GUARANTEED**

---

# 39. SECURITY

Implemented protections include:

- ZIP traversal protection
- absolute path rejection
- symlink rejection
- resource limits
- Docker network isolation
- timeouts
- read-only source/class mounts
- isolated output directories
- temporary directory cleanup
- evidence tamper detection

## Security risk: shell entrypoint

`DockerJavaCandidateAdapter` builds a shell command using `sh -c` with an entrypoint class.

The entrypoint should be strictly validated as a Java class identifier before shell interpolation.

Classification:

**P1 SECURITY HARDENING**

## Security risk: direct upload resource limits

The direct upload path does not have the same explicit resource limits as the ZIP path.

Potential risks:

- memory exhaustion
- oversized upload
- excessive file count

Classification:

**P1/P2 HARDENING**

---

# 40. DEAD / DUPLICATE / LEGACY CODE

Confirmed areas:

- duplicate mapping functions in `cobol_to_java_mapping.py`
- legacy direct-generation helpers in `java_generator.py`
- producer abstractions not used by the authoritative pipeline
- OpenSourceCOBOL4J adapter not connected to the active pipeline
- older candidate adapters
- generated/historical verification artifacts

No deletion was performed.

No legacy path should be removed without a separate compatibility analysis.

---

# 41. DOCUMENTATION DRIFT

README/documentation materially lags the implementation.

It still contains claims equivalent to:

- implementation is planned
- parser is planned
- Java execution is planned
- comparator is planned
- verdict engine is planned
- the project is not a COBOL-to-Java converter

These are inconsistent with current source and CI.

Current repository actually contains:

- real COBOL parsing
- real IR
- real deterministic transformation
- real Java generation
- real Spring generation
- real Docker execution
- real comparison
- real evidence
- real verdict
- real API
- real frontend

Source/tests/CI should be treated as authoritative over stale documentation.

---

# 42. NO-LLM VERIFICATION

The repository was searched for:

- LLM
- OpenAI
- Anthropic
- Gemini
- Ollama
- model providers
- prompts
- AI transformation
- generative transformation
- inference
- agent-based transformation

Findings:

| Category | Result |
|---|---|
| Executable LLM implementation | NONE FOUND |
| Dormant executable LLM implementation | NONE FOUND |
| LLM provider configuration | NONE FOUND |
| Tests invoking LLM | NONE FOUND |
| LLM dependencies | NONE FOUND |
| Documentation-only references | FOUND |

Architectural/documentation references to LLMs exist, but no executable LLM transformation path exists.

# FINAL NO-LLM DETERMINATION

**NO LLM IMPLEMENTATION FOUND**

No LLM fallback, provider, model invocation, prompt-based transformation, or hidden AI transformation path was found.

---

# 43. P0 BLOCKERS

## P0-1 — Oracle runtime digest is not bound to execution

**Problem:** Oracle execution uses a mutable image tag while evidence records a digest.

**Why it matters:** The verdict cannot be fully tied to the exact oracle runtime that executed.

**Evidence:**
- `engine/oracle/docker_adapter.py`
- `engine/pipeline.py`
- `engine/domain/identities.py`

**Existing tests:** Oracle execution/provenance tests.

**Missing tests:** Digest mismatch must prevent certification.

**Boundary:** Oracle adapter -> identity -> evidence.

---

## P0-2 — Capability analysis is broader than semantic support

**Problem:** Planner support is not fully derived from actual transformation semantics.

**Why it matters:** A construct may be allowed into transformation without behavioral equivalence being proven.

**Evidence:**
- `engine/modernization/capability_analyzer.py`
- `engine/transformation/cobol_to_java_mapping.py`
- `engine/transformation/ir.py`

**Missing tests:** Capability-vs-execution differential tests for semantic classes.

**Boundary:** Capability analyzer <-> transformation contract.

---

## P0-3 — Default certification scope is narrower than complete application behavior

**Problem:** API workloads default to stdout and exit status.

**Why it matters:** File-output differences may not affect the default verdict.

**Evidence:**
- `api/service.py`
- `engine/pipeline.py`

**Missing tests:** End-to-end workloads covering complete output-tree certification.

**Boundary:** Workload -> comparator -> verdict.

---

# 44. P1 IMPORTANT WORK

## P1-1 — Make TransformationProducer the real transformation boundary

The producer abstraction exists but the active pipeline bypasses it.

**Boundary:** transformation orchestration.

---

## P1-2 — Bind producer identity into evidence

Producer identity/version fields exist but are not populated by the active pipeline.

**Boundary:** candidate/evidence identity.

---

## P1-3 — Correct environment identity

Populate actual Java/Maven/compiler/runtime environment information and eliminate the Java 25 vs Java 21 mismatch.

**Boundary:** pipeline + execution adapters + evidence.

---

## P1-4 — Eliminate mapping duplication

Resolve duplicate/shadowed mapping definitions only after active call paths and compatibility tests are established.

**Boundary:** `engine/transformation/cobol_to_java_mapping.py`

---

## P1-5 — Align capability analysis with semantic transformation

Capability should reflect actual semantic support rather than only syntactic/dependency support.

---

## P1-6 — Implement correct COBOL numeric semantics

Define and test:

- PIC
- signedness
- scale
- precision
- DISPLAY
- COMP
- COMP-3
- rounding
- truncation
- overflow

---

## P1-7 — Implement level-88 semantic conditions

Boundary:

```
Parser -> IR -> condition mapper -> Java
```

---

## P1-8 — Implement OCCURS semantics

Boundary:

```
Data IR -> Java data model -> generated Java
```

---

## P1-9 — Implement REDEFINES semantics

Boundary:

```
Data model -> storage representation -> Java
```

---

## P1-10 — Correct file capability analysis

Boundary:

```
ApplicationDiscovery -> CapabilityAnalyzer -> transformation/runtime
```

---

## P1-11 — Make oracle image reproducible

Pin the image and verify actual runtime identity.

---

## P1-12 — Remove shell interpolation risk

Validate Java entrypoint identifiers before shell execution.

---

# 45. P2 HARDENING

- Expand ingestion tests for ZIP entry limits, extracted-size limits, symlinks, malformed archives.
- Add direct-upload resource limits.
- Add generated-code security tests.
- Add semantic differential workloads for figurative constants, level 88, OCCURS, REDEFINES, COMP-3, ROUNDED and SIZE ERROR.
- Separate historical generated verification artifacts from authoritative current results.
- Rewrite stale current-state documentation.

---

# 46. RECOMMENDED IMPLEMENTATION ORDER

Do not immediately expand COBOL syntax.

Recommended order:

```
Phase A: Trust + provenance
        ↓
Phase B: Capability truthfulness
        ↓
Phase C: Semantic data model
        ↓
Phase D: Control-flow completeness
        ↓
Phase E: File semantics
        ↓
Phase F: Producer architecture
        ↓
Phase G: Universal comparison
        ↓
Phase H: Legacy/duplicate cleanup
        ↓
Phase I: Documentation synchronization
```

Detailed order:

1. Bind actual oracle image digest to execution.
2. Correct Java runtime evidence.
3. Populate producer identity/version.
4. Populate environment identities.
5. Strengthen evidence hashing.
6. Align capability analysis with real mapper capabilities.
7. Define semantic support contracts.
8. Implement numeric semantics.
9. Implement figurative constants.
10. Implement level-88 semantics.
11. Implement OCCURS.
12. Implement REDEFINES.
13. Improve PERFORM semantics.
14. Improve file semantics.
15. Make `TransformationProducer` the real transformation boundary.
16. Bind producer identity into evidence.
17. Expand output comparison.
18. Remove duplicate/legacy paths only after compatibility verification.
19. Update documentation to match actual implementation.

---

# 47. FINAL CURRENT-STATE ASSESSMENT

The repository at:

```
fd99b9e5a4935b994450dc31b5b03f18369fdd37
```

is a functioning deterministic modernization vertical slice.

It genuinely implements:

- secure ingestion
- COBOL discovery
- semantic IR
- capability analysis
- deterministic COBOL-to-Java mapping
- Java IR
- Spring Boot generation
- Dockerized COBOL execution
- Dockerized Java execution
- declaration-driven comparison
- evidence
- evidence integrity validation
- fail-closed verdicts
- substantial integration/adversarial testing

It does **not** yet justify claims of:

- universal COBOL support
- complete COBOL semantic equivalence
- fully producer-neutral transformation
- complete producer provenance
- complete environment provenance
- complete oracle runtime identity binding
- automatic certification of all observable application outputs

Most important architectural fact:

```
The repository has a real working native transformation pipeline,
but the TransformationProducer abstraction is not yet the active
transformation boundary.
```

Most important semantic fact:

```
The parser/IR preserve substantially more COBOL meaning than the
current Java mapper actually preserves.
```

Most important certification fact:

```
The verdict engine is substantially fail-closed,
but the evidence identity/provenance chain still has gaps.
```

Most important documentation fact:

```
README/docs significantly lag the actual implementation.
```

Required AI determination:

```
NO LLM IMPLEMENTATION FOUND
```

---

# 48. AUDIT CONCLUSION

The repository should currently be treated as:

```
DETERMINISTIC MODERNIZATION + VALIDATION VERTICAL SLICE
```

rather than:

```
UNIVERSAL COBOL MODERNIZATION PLATFORM
```

The next implementation phase should focus on making the existing architecture truthful and semantically bounded before expanding feature breadth.

The green CI baseline is a valid foundation and should remain unchanged while the next implementation plan is prepared.
