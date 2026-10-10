# SystemaOps Modernization Platform

## Master Implementation README

**Document Type:** Master Engineering Specification  
**Project:** SystemaOps Modernization Platform  
**Repository:** `Shankar373/Cobol-Java-Transformation`  
**Primary Branch:** `codex/universal-core`  
**Purpose:** Single source of truth for implementation, architecture, verification, and OpenCode execution.

---

# 1. Purpose of This Document

This document is the **master implementation contract** for SystemaOps.

It defines:

- what the product is
- what the customer must receive
- the target architecture
- the implementation strategy
- the COBOL/mainframe capabilities that must eventually be covered
- transformation requirements
- runtime requirements
- verification requirements
- security and trust requirements
- testing requirements
- implementation phases
- acceptance criteria
- OpenCode implementation rules
- model-switch/checkpoint behavior
- forbidden implementation shortcuts
- final release requirements

This document must be treated as the primary implementation specification.

Historical reports, audit documents, old completion reports, previous CI reports, and earlier README claims are **evidence/history**, not automatically the current source of truth.

Current repository behavior must always be verified against the actual code.

---

# 2. Product Mission

SystemaOps is an enterprise deterministic application-modernization platform.

Its objective is to ingest legacy COBOL/mainframe applications, discover their complete technical and semantic dependencies, construct a comprehensive semantic representation, deterministically transform their semantics into modern Java applications, build and execute the resulting application in an isolated environment, execute the original application as an independent oracle where available, compare behavior, preserve evidence integrity, and provide a trusted modernization verdict.

The long-term product objective is:

> Modernize complete enterprise COBOL/mainframe applications — not isolated COBOL files — while providing deterministic transformation, independent execution, evidence-backed comparison, and trustworthy certification.

---

# 3. Core Product Principle

SystemaOps is **not an AI code-generation wrapper**.

The product must not depend on an LLM for deterministic transformation decisions.

The modernization pipeline must remain deterministic.

LLM/agent-based systems may potentially be used outside the deterministic core for optional assistance such as:

- documentation assistance
- explanation
- user guidance
- search
- non-authoritative recommendations

They must never become the authority for:

- COBOL semantic interpretation
- transformation decisions
- generated business semantics
- evidence creation
- verdict generation
- certification

---

# 4. Customer Problem

Enterprise customers may have applications containing:

- COBOL programs
- copybooks
- JCL
- DB2
- VSAM
- CICS
- MQ
- IMS
- sequential datasets
- indexed files
- relative files
- CALL relationships
- batch jobs
- transaction dependencies
- external utilities
- configuration
- environment dependencies
- decades of accumulated business logic

The customer does not want to manually modernize thousands of files.

The customer needs to know:

1. What exists in the legacy application?
2. What depends on what?
3. What can be modernized?
4. What cannot yet be modernized?
5. What Java application was generated?
6. Does the Java application actually behave like the original?
7. What evidence proves that?
8. Can the result be trusted?
9. What remains unresolved?
10. Can the customer export and operate the resulting application?

SystemaOps must answer these questions systematically.

---

# 5. Customer Journey

The intended customer journey is:

```text
Customer Application
        ↓
Secure Ingestion
        ↓
Application Discovery
        ↓
Dependency Graph
        ↓
Capability Analysis
        ↓
Modernization Plan
        ↓
COBOL Parsing
        ↓
Universal Semantic IR
        ↓
Semantic Transformation
        ↓
Java IR
        ↓
Runtime Adapter
        ↓
Java Project Generation
        ↓
Build / Package
        ↓
Isolated Execution
        ↓
Original COBOL Oracle Execution
        ↓
Java Candidate Execution
        ↓
Differential Comparison
        ↓
Evidence Validation
        ↓
Deterministic Verdict
        ↓
Customer Review / Approval
        ↓
Production Repository Export
```

---

# 6. What SystemaOps Must Deliver

For a complete modernization workload, SystemaOps should eventually produce:

- discovered application inventory
- application/dependency graph
- capability report
- modernization plan
- semantic representation
- transformed Java application
- selected runtime architecture
- build configuration
- executable Java artifact
- execution results
- original COBOL oracle results where available
- candidate execution results
- behavioral comparison
- evidence package
- integrity validation
- deterministic verdict
- unresolved/unsupported dependency report
- migration documentation
- exportable Java repository

---

# 7. Universal Modernization Objective

The final product objective is comprehensive enterprise modernization.

However:

```text
Universal analysis
        ≠
Universal transformation
        ≠
Universal runtime equivalence
        ≠
Universal certification
```

The correct engineering chain is:

```text
Detect
  ↓
Classify
  ↓
Model
  ↓
Transform
  ↓
Execute
  ↓
Compare
  ↓
Prove
  ↓
Certify
```

If a capability is detected but cannot be proven equivalent, SystemaOps must not fabricate success.

It must explicitly report the limitation.

---

# 8. Current Reality vs Final Target

The current repository contains a working deterministic modernization platform with a proven subset.

Current implementation must NOT be represented as universal COBOL support.

Current known state includes:

- secure ingestion
- discovery
- dependency analysis
- capability analysis
- modernization planning
- COBOL parser
- semantic IR
- deterministic COBOL→Java mapping
- Java generation
- Docker execution
- GnuCOBOL oracle execution
- differential comparison
- evidence validation
- deterministic verdict
- API
- frontend control plane
- CI

Several enterprise capabilities remain incomplete.

The final target is broader than today's implementation.

OpenCode must implement the missing capabilities rather than converting incomplete capabilities into misleading "supported" claims.

---

# 9. Canonical Architecture

SystemaOps must maintain one canonical modernization pipeline.

```text
COBOL / Mainframe Application
            ↓
        Ingestion
            ↓
        Discovery
            ↓
 Capability / Semantic Analysis
            ↓
      Dependency Analysis
            ↓
     Modernization Planner
            ↓
       COBOL Parser
            ↓
    Universal Semantic IR
            ↓
    Semantic Transformation
            ↓
          Java IR
            ↓
      Runtime Adapter
            ↓
     Java Application
            ↓
       Build / Package
            ↓
    Isolated Candidate Run
            ↕
    Independent COBOL Oracle
            ↓
 Differential Comparison
            ↓
      Evidence System
            ↓
       Verdict System
            ↓
     Customer Approval
            ↓
        Export
```

---

# 10. One Canonical Pipeline

The project must NOT develop multiple independent pipelines that solve the same problem.

There must be one canonical:

- parser
- semantic IR
- transformation engine
- Java IR
- runtime abstraction
- execution framework
- comparison framework
- evidence framework
- verdict framework

Specialized capabilities must integrate into these existing systems.

Do not create duplicate implementations merely because an existing implementation is incomplete.

Improve and extend the canonical architecture.

---

# 11. Ingestion

SystemaOps must support application-level ingestion.

Inputs may include:

- ZIP
- Git repository
- uploaded source tree
- future enterprise repository integrations

Ingestion must preserve:

- original files
- paths
- source identity
- workload identity
- metadata
- provenance

Security requirements include:

- path traversal protection
- archive extraction limits
- bounded upload size
- sanitized paths
- deterministic workload identity
- source hashing

---

# 12. Application Discovery

Discovery must identify the application as a system rather than treating each COBOL file independently.

Discovery must eventually identify:

- COBOL programs
- copybooks
- CALL relationships
- JCL
- DB2 references
- CICS references
- MQ references
- IMS references
- files
- datasets
- VSAM
- external utilities
- configuration
- dependencies
- entry points
- batch relationships
- transaction relationships

Discovery must preserve source locations.

---

# 13. Dependency Graph

SystemaOps must construct an application dependency graph.

Example:

```text
JOB
 ↓
PROGRAM-A
 ├── COPYBOOK-1
 ├── CALL PROGRAM-B
 │       └── COPYBOOK-2
 ├── DB2 TABLE
 ├── VSAM FILE
 └── MQ QUEUE
```

The graph must distinguish:

- resolved dependencies
- unresolved dependencies
- ambiguous dependencies
- dynamic dependencies
- cyclic dependencies
- external dependencies

Dependency uncertainty must affect planning and certification.

---

# 14. Capability Analysis

Capabilities must have explicit states.

At minimum:

```text
SUPPORTED
PARTIAL
UNSUPPORTED
UNAVAILABLE
UNKNOWN
```

Capability analysis must be derived from actual implementation capability.

Do not mark something SUPPORTED simply because:

- syntax can be parsed
- Java can compile
- a fixture passes
- a parser recognizes the construct

Capability requires sufficient semantic and verification coverage.

---

# 15. Modernization Planning

The planner must determine whether an application can proceed through the modernization pipeline.

The planner must consider:

- executable entry point
- dependency completeness
- transformation capability
- runtime availability
- unsupported constructs
- unresolved dependencies
- semantic risks
- verification availability

A plan must fail closed when required conditions are not satisfied.

---

# 16. COBOL Parser

The parser must eventually provide comprehensive COBOL language coverage.

The parser must support or explicitly classify:

- IDENTIFICATION DIVISION
- ENVIRONMENT DIVISION
- DATA DIVISION
- PROCEDURE DIVISION
- WORKING-STORAGE
- LINKAGE SECTION
- FILE SECTION
- LOCAL-STORAGE
- COPY
- REPLACE
- compiler directives
- fixed-format COBOL
- free-format COBOL
- sequence columns
- comments
- literals
- figurative constants
- conditions
- arithmetic
- data movement
- file operations
- control flow
- subprogram calls
- strings
- tables
- numeric formats
- declarations
- error handling
- transaction semantics
- dialect-specific constructs

Recognized-but-unparsed constructs must never disappear silently.

They must produce explicit diagnostics.

---

# 17. COBOL Semantic IR

The Universal Semantic IR is the central abstraction.

The IR must represent semantics, not merely syntax.

It must eventually model:

- programs
- divisions
- sections
- paragraphs
- statements
- variables
- data items
- types
- PIC
- signed values
- decimal scale
- numeric representation
- arrays/OCCURS
- REDEFINES
- 88-level conditions
- files
- records
- control flow
- calls
- copybooks
- external dependencies
- error semantics
- transaction boundaries
- source locations
- provenance
- semantic diagnostics

---

# 18. Numeric Semantics

Numeric correctness is a high-risk area.

The implementation must explicitly address:

- PIC 9
- PIC X
- signed values
- PIC V
- COMP
- COMP-3
- binary representations
- decimal precision
- scale
- rounding
- overflow
- truncation
- negative values
- DISPLAY numeric representation
- arithmetic semantics

Do not assume IEEE-754 floating-point behavior is equivalent to COBOL decimal semantics.

Where required, use exact decimal/integer representations.

---

# 19. Data Semantics

The semantic model must eventually cover:

- PIC clauses
- VALUE
- OCCURS
- REDEFINES
- level-88 conditions
- group structures
- nested records
- signed fields
- numeric storage formats
- record layouts
- source-to-IR traceability

Binary record layouts must not be claimed as supported without proof.

---

# 20. COPYBOOK Support

COPYBOOK handling must include:

- resolution
- path handling
- nested dependencies
- duplicate names
- missing copybooks
- ambiguity
- COPY/REPLACE semantics
- source traceability

Missing or ambiguous copybooks must fail closed where required for correctness.

---

# 21. CALL Semantics

CALL handling must distinguish:

- static CALL
- dynamic CALL
- unresolved CALL
- cyclic CALL
- parameter mismatch
- linkage mismatch
- external CALL
- runtime service calls

Static resolved calls may be transformed where proven.

Dynamic/unresolved calls must not silently become successful transformations.

---

# 22. Mainframe Dependency Architecture

Each major mainframe dependency must have its own semantic strategy.

Required areas:

```text
JCL
DB2
VSAM
CICS
MQ
IMS
External utilities
Datasets
Files
System services
```

Each area must eventually provide:

1. discovery
2. semantic classification
3. dependency representation
4. modernization strategy
5. runtime strategy
6. verification strategy

---

# 23. JCL

JCL must eventually be modeled as an executable workload.

The target architecture should support concepts such as:

- JOB
- EXEC
- DD
- datasets
- DISP
- conditions
- return codes
- steps
- dependencies
- utilities
- SORT
- IDCAMS
- program execution

Possible modern targets may include:

- workflow engines
- shell/container jobs
- Java orchestration
- Kubernetes jobs
- enterprise schedulers

The target must be selected through an adapter architecture.

---

# 24. DB2 / SQL

DB2 support must address:

- embedded SQL discovery
- SQL parsing
- host variables
- cursors
- transactions
- COMMIT
- ROLLBACK
- SQLCODE
- SQLSTATE
- stored procedures
- database dependencies
- schema mapping

Apache Calcite and DB2 resources may be evaluated as open-source building blocks.

DB2 runtime equivalence must not be claimed merely because SQL parses.

---

# 25. VSAM / Files

File modernization must eventually cover:

- sequential files
- indexed files
- relative files
- record layouts
- keys
- file lifecycle
- OPEN
- CLOSE
- READ
- WRITE
- REWRITE
- DELETE
- START
- INVALID KEY
- EOF semantics
- file status

Target storage must be runtime-adapter based.

---

# 26. CICS

CICS modernization must eventually cover relevant:

- EXEC CICS commands
- transaction boundaries
- COMMAREA
- channels/containers
- file access
- program invocation
- queues
- synchronization
- error handling

Possible targets may include:

- REST APIs
- Spring services
- Java transactions
- messaging
- application service boundaries

No CICS equivalence claim without runtime evidence.

---

# 27. MQ

MQ modernization must eventually support:

- queue discovery
- PUT
- GET
- message formats
- correlation
- transaction behavior
- retry semantics
- dead-letter behavior

IBM MQ samples/patterns may be used as reference material.

---

# 28. IMS

IMS must eventually be classified explicitly.

This includes potentially:

- IMS DB
- IMS TM
- EXEC DLI
- transaction semantics
- hierarchical data access

Unknown IMS constructs must not silently pass through the system.

---

# 29. External Utilities

The system must identify dependencies such as:

- SORT
- IDCAMS
- system utilities
- external scripts
- external programs
- scheduler dependencies
- environment services

Each must have:

```text
Detected
→ Classified
→ Transformation Strategy
→ Runtime Strategy
→ Verification Strategy
```

---

# 30. Semantic Transformation

Transformation must be deterministic.

```text
COBOL
 ↓
Parser
 ↓
Universal IR
 ↓
Semantic Analysis
 ↓
Java IR
 ↓
Runtime Adapter
 ↓
Java
```

Do not bypass the IR.

Do not directly concatenate strings from COBOL source into Java as a substitute for semantic transformation.

---

# 31. Java IR

Java IR must represent:

- classes
- methods
- fields
- types
- control flow
- expressions
- statements
- exceptions
- dependencies
- annotations
- runtime metadata
- source mapping

Java IR must remain independent of a specific runtime framework.

---

# 32. Runtime Adapter Architecture

The same semantic transformation must be capable of targeting multiple Java runtime architectures.

Initial targets:

```text
Spring Boot
Jakarta EE
Plain Java
```

Future targets may include other enterprise runtimes.

Example configuration:

```json
{
  "target_runtime": "spring_boot",
  "java_version": "21",
  "build_tool": "maven",
  "packaging": "jar",
  "execution_mode": "batch"
}
```

Runtime-specific behavior belongs in adapters.

Do not duplicate the COBOL parser or semantic transformer for every runtime.

---

# 33. Build and Packaging

Generated applications must be real buildable repositories.

The system must support:

- Maven
- Java version selection
- dependency management
- packaging
- JAR generation
- runtime configuration
- reproducible builds where possible
- dependency provenance

Compilation alone is not modernization proof.

---

# 34. Isolated Execution

Execution must occur in a controlled environment.

Current Docker requirements include:

- isolated container
- network disabled where appropriate
- CPU limits
- memory limits
- PID limits
- timeout
- staged source
- isolated work directory
- captured stdout
- captured stderr
- exit code
- start/end time
- termination reason
- SHA-256 identity

Docker is authoritative.

Host fallback must never upgrade a verdict.

---

# 35. Oracle Execution

The original COBOL application must be treated as an independent oracle where possible.

Current oracle technology includes GnuCOBOL.

However:

> GnuCOBOL execution must not automatically be interpreted as proof of complete z/OS behavioral equivalence.

Future oracle strategy must explicitly identify:

- compiler/runtime
- version
- environment
- dialect
- runtime assumptions
- unavailable mainframe services

---

# 36. Candidate Execution

The generated Java candidate must be built and executed independently.

The candidate must not use:

- pre-built stale artifacts
- copied outputs
- host execution that bypasses isolation
- fabricated execution results

Fresh candidate execution is required for fresh verification.

---

# 37. Differential Comparison

Comparison must eventually include more than stdout.

Depending on workload:

- exit code
- stdout
- stderr
- generated files
- file contents
- dataset state
- database state
- transaction results
- messages
- return codes
- error behavior
- side effects
- ordering where semantically relevant

Comparison must be contract-aware.

---

# 38. Evidence

Evidence must bind:

- workload identity
- source identity
- candidate identity
- execution role
- environment
- artifacts
- comparison
- hashes
- provenance
- timestamps
- schema/version

Evidence must be integrity validated.

Producer metadata is provenance.

Producer metadata alone is NOT evidence.

---

# 39. Verdict System

Verdicts must remain deterministic.

Possible states:

```text
VERIFIED
FAILED
PARTIAL
UNPROVEN
UNAVAILABLE
UNSUPPORTED
ERROR
```

The system must never upgrade:

```text
UNKNOWN → VERIFIED
UNSUPPORTED → VERIFIED
PARTIAL → VERIFIED
SKIPPED → PASS
STALE → FRESH
```

without actual evidence.

---

# 40. Verification Ladder

SystemaOps must maintain explicit verification levels.

```text
LEVEL 0 — NOT_TESTED
LEVEL 1 — PARSED_ONLY
LEVEL 2 — MODELED_ONLY
LEVEL 3 — TRANSFORMED
LEVEL 4 — BUILDS
LEVEL 5 — EXECUTES
LEVEL 6 — ORACLE_MATCHED
LEVEL 7 — FRESH_VERIFIED
```

Fresh verification requires fresh:

- oracle execution
- Java execution
- actual outputs
- relevant side-effect comparison
- integrity validation
- hashes

---

# 41. Integrated Proof

The final trusted verdict must combine:

- modernization report
- runtime evidence
- dependency evidence
- JCL evidence
- DB2 evidence
- CICS evidence
- evidence integrity

The central verdict must be fail-closed.

Conceptually:

```text
central VERIFIED
<=
runtime VERIFIED
AND
evidence complete
AND
integrity valid
AND
every required dependency PROVEN
```

The integrated proof path must eventually be wired completely through the API/service layer.

---

# 42. Security and Trust Boundary

The trust model is:

```text
Customer Source
      ↓
UNTRUSTED
      ↓
Discovery
      ↓
Transformation
      ↓
Generated Java
      ↓
UNTRUSTED
      ↓
Isolated Execution
      ↓
Artifacts
      ↓
Validation
      ↓
Evidence
      ↓
Trusted Verdict
```

Security requirements include:

- archive extraction protection
- path sanitization
- upload limits
- execution isolation
- network controls
- resource limits
- authentication
- authorization
- evidence integrity
- stale evidence protection
- replay protection
- auditability

---

# 43. Enterprise Security Target

Future production requirements include:

- durable job queue
- resumable execution
- retention/TTL
- tenant isolation
- RBAC
- audit logging
- external secret management
- TLS
- controlled egress
- multi-node coordination
- production database
- vulnerability scanning
- dependency scanning
- SBOM
- image provenance

SQLite/single-node architecture must not be presented as full enterprise multi-node infrastructure.

---

# 44. Open-Source Strategy

SystemaOps should reuse mature open-source technology wherever it reduces unnecessary reinvention.

Potential technologies include:

- ProLeap COBOL Parser
- OpenSource COBOL 4J
- mapa_cobol
- Apache Calcite
- z390
- IBM DB2 resources
- IBM MQ samples
- OpenRewrite

Open-source components must be evaluated using:

- license compatibility
- feature coverage
- correctness
- test coverage
- performance
- maintenance/activity
- security
- integration impact

Before replacing an existing component:

```text
KEEP
AUGMENT
REPLACE
```

must be evaluated.

Existing functionality must not be removed until the replacement passes existing regression and E2E tests.

---

# 45. Open-Source Component Strategy

| Capability            | Candidate                      | Initial Strategy          |
| --------------------- | ------------------------------ | ------------------------- |
| COBOL parsing         | ProLeap                        | Evaluate for replacement  |
| COBOL→Java reference  | OpenSource COBOL 4J            | Reference/benchmark first |
| Copybooks             | ProLeap / mapa_cobol           | Augment                   |
| Dependency analysis   | ProLeap / mapa_cobol           | Augment                   |
| JCL                   | mapa_cobol / grammar tools     | Evaluate                  |
| DB2 / SQL             | Apache Calcite + DB2 resources | Augment                   |
| CICS                  | ProLeap / mapa_cobol           | Augment                   |
| VSAM                  | z390/reference tooling         | Reference                 |
| MQ                    | IBM MQ resources               | Augment                   |
| COBOL IR              | SystemaOps                     | KEEP                      |
| Java IR               | SystemaOps                     | KEEP                      |
| Transformation engine | SystemaOps                     | KEEP / expand             |
| Runtime adapters      | SystemaOps                     | KEEP / expand             |
| Oracle/comparison     | SystemaOps                     | KEEP                      |
| Evidence/verdict      | SystemaOps                     | KEEP                      |

GPL/AGPL/commercially restricted components must remain isolated/reference-only unless explicit legal review permits integration.

No open-source project becomes proof of modernization merely because it parses or generates code.

---

# 46. Product Modes

SystemaOps should support two major modernization modes.

## Mode A — SystemaOps Transformation

```text
Customer Source
→ SystemaOps Analysis
→ SystemaOps Transformation
→ Java Candidate
→ Verification
```

## Mode B — External Candidate Validation

An external:

- vendor
- migration tool
- agent
- AI system
- manually generated implementation

may provide a Java candidate.

SystemaOps can then:

```text
Discover
→ Analyze
→ Validate Candidate
→ Execute
→ Compare
→ Produce Evidence
→ Verdict
```

This creates a major differentiation:

> SystemaOps does not have to trust whoever generated the code. SystemaOps can independently validate it.

---

# 47. Why SystemaOps Is Different

An agent can say:

> "Here is the Java code."

SystemaOps should be able to say:

> "Here is the discovered application, dependency graph, capability analysis, modernization plan, generated Java repository, build result, isolated execution result, COBOL oracle result, behavioral comparison, evidence package, and deterministic verdict."

The platform is therefore focused on:

```text
Transformation
+
Execution
+
Evidence
+
Trust
```

not merely code generation.

---

# 48. Traceability

Eventually every important transformation should support:

```text
COBOL Source
   ↓
Source Location
   ↓
COBOL IR
   ↓
Semantic Transformation
   ↓
Java IR
   ↓
Generated Java
   ↓
Execution
   ↓
Evidence
```

Traceability should make it possible to answer:

> "Where did this Java behavior come from?"

---

# 49. Testing Strategy

Testing must exist at multiple levels.

## Unit Tests

Parser, IR, mapper, generator, runtime, evidence, verdict.

## Contract Tests

Validate:

- artifact contracts
- oracle contract
- candidate contract
- producer contract
- verdict contract

## Integration Tests

Test:

```text
COBOL
→ IR
→ Java
→ Build
→ Execution
→ Comparison
```

## Security Tests

Test:

- path traversal
- malicious archives
- oversized input
- stale evidence
- tampered artifacts
- replay
- resource exhaustion
- network isolation

## Regression Tests

Existing green behavior must not be weakened.

---

# 50. Fresh E2E Requirement

Passing unit tests is insufficient.

Before final certification, run a fresh end-to-end workload.

The E2E workload must exercise the real pipeline:

```text
Ingest
→ Discover
→ Plan
→ Parse
→ Transform
→ Generate
→ Build
→ Oracle
→ Candidate
→ Compare
→ Evidence
→ Verdict
```

No pre-existing result may be substituted for fresh execution.

---

# 51. CI/CD

CI must validate:

- Python tests
- frontend tests
- build
- parser tests
- transformation tests
- Docker tests
- integration tests
- security checks
- contract checks
- artifact checks
- fresh E2E where feasible

A green CI result means the tested repository state passes CI.

It does NOT automatically mean:

```text
Universal COBOL support
```

or:

```text
Universal runtime equivalence
```

---

# 52. Current Implementation Phases

Implementation should proceed through these phases.

```text
PHASE 0  Architecture + Master README Freeze

PHASE 1  Parser / Universal IR Expansion

PHASE 2  COBOL Semantic Coverage

PHASE 3  CALL / COPYBOOK / Application Graph

PHASE 4  Files / VSAM / Data Semantics

PHASE 5  JCL Modernization

PHASE 6  DB2 / SQL Modernization

PHASE 7  CICS / MQ / IMS / External Dependencies

PHASE 8  Runtime Adapter Architecture

PHASE 9  Build + Execution + Differential Verification

PHASE 10 Evidence / Certification / Integrated Proof

PHASE 11 Enterprise Security + Operations

PHASE 12 Full Regression + Fresh E2E + Release Gate
```

---

# 53. Phase Completion Rule

A phase is NOT complete because:

- code was written
- tests were added
- a few fixtures pass
- CI is green

A phase is complete only when:

1. implementation exists
2. relevant contracts are satisfied
3. focused tests pass
4. regression tests pass
5. integration behavior is verified
6. evidence exists
7. known limitations are documented
8. no silent semantic loss remains
9. acceptance criteria are satisfied

---

# 54. Current Known High-Risk Areas

Priority areas include:

### P0

- capability truth drift
- parser/IR/mapper/generator mismatch
- numeric semantics
- PIC/sign/V/COMP/COMP-3
- precision
- overflow
- rounding

### P1

- planning semantics
- CALL lifecycle proof
- evidence/verdict route coverage
- tamper/replay protection
- persistence/security
- JCL
- DB2
- CICS
- indexed/relative files

### P2

- deeper CI coverage
- mutation testing
- security/dependency scanning
- schema checks
- documentation synchronization
- large workload performance

---

# 55. Additional Enterprise Requirements

The implementation must eventually address:

- COBOL dialects
- fixed/free format
- COPY/REPLACE
- compiler directives
- conditional compilation
- source-location preservation
- source-to-IR traceability
- IR-to-Java traceability
- dependency graph visualization
- transaction boundaries
- DB transaction semantics
- file lifecycle semantics
- error equivalence
- date/time determinism
- environment variables
- randomness
- concurrency
- workload/test-data generation
- customer-provided workloads
- regression corpus management
- oracle version pinning
- runtime image provenance
- dependency/license inventory
- SBOM
- vulnerability scanning
- migration/export
- audit log
- RBAC
- tenant model
- durable jobs
- cancellation/retry
- large application performance
- incremental modernization
- resume/checkpoint
- portfolio modernization
- rollback/rejection
- customer approval gate

---

# 56. Incremental Modernization

Large enterprise applications cannot always be modernized in one operation.

SystemaOps must eventually support:

- workload partitioning
- program-level modernization
- dependency-aware sequencing
- partial modernization
- incremental migration
- regression between migration stages
- rollback
- approval gates
- portfolio tracking

A partially modernized system must clearly identify which components remain legacy.

---

# 57. Model / OpenCode Execution Contract

OpenCode must follow these rules.

Before making changes:

1. Read this Master README.
2. Read `opencode.md`.
3. Inspect the current repository.
4. Verify the checkpoint against actual repository state.
5. Identify the current phase.
6. Identify completed work.
7. Identify remaining work.
8. Inspect existing implementation before creating new implementation.

Do not restart completed work without evidence of regression or an explicit requirement change.

---

# 58. Reuse Existing Architecture

Before creating a new class/module/system, OpenCode must search the repository.

If equivalent functionality already exists:

```text
REUSE
or
EXTEND
```

Do not create:

- second parser
- second IR
- second generator
- second runtime
- second comparator
- second evidence system
- second verdict system

unless the Master README explicitly changes the architecture.

---

# 59. Deterministic Implementation Rule

All transformation decisions must be deterministic.

Do not introduce an LLM into:

- parser
- semantic analysis
- transformation
- Java generation
- runtime decision
- evidence
- verdict

If a deterministic language rule is known, implementing it directly is acceptable.

However:

> Never hard-code expected output merely to make a fixture pass.

---

# 60. No Silent Loss

If a construct is:

- recognized
- partially parsed
- unsupported
- unknown
- ambiguous

the system must expose that fact.

It must never silently discard source semantics.

---

# 61. No Fake Verification

Forbidden:

```text
hard-coded VERIFIED
```

```text
fixture output hard-coded into implementation
```

```text
SKIPPED → PASS
```

```text
UNKNOWN → VERIFIED
```

```text
stale evidence → fresh evidence
```

```text
pre-built candidate → fresh candidate
```

```text
host execution → authoritative Docker result
```

---

# 62. Test Preservation

Never solve a failing test by:

- deleting it
- weakening it
- changing it to accept incorrect behavior
- skipping it without justification
- lowering assertions

When a test fails:

1. understand the intended contract
2. identify the implementation defect
3. fix the implementation
4. retain the test
5. add regression coverage if needed

---

# 63. Green Baseline Protection

The last known green baseline must be protected.

Before broad changes:

- record current commit
- record CI status
- record test status

After changes:

- run focused tests
- run regression
- run CI
- compare results against baseline

A new feature must not silently destroy previously verified functionality.

---

# 64. OpenCode Checkpoint Requirement

A separate file named exactly:

```text
opencode.md
```

must act as the **live implementation checkpoint**.

It is not the architecture specification.

The relationship is:

```text
MASTER_IMPLEMENTATION_README.md
        =
Specification / Architecture / Requirements

opencode.md
        =
Live State / Progress / Handoff Checkpoint
```

The Master README has architectural authority.

`opencode.md` has implementation-state authority.

---

# 65. Mandatory Checkpoint Updates

OpenCode must update `opencode.md`:

- after completing a meaningful phase
- after completing a major task
- before switching models
- before ending a work session
- when blocked
- when CI fails
- when a significant architectural decision is made
- when an implementation interruption occurs
- when token/context limits are reached
- when environment/tool failures stop implementation

The checkpoint must never intentionally be left misleading.

---

# 66. Model Switch / Interruption Rule

If OpenCode stops because of:

- token limit
- context limit
- model interruption
- tool failure
- CI failure
- environment failure
- time limit

the next model/session must be able to continue from `opencode.md`.

The next model must NOT need to rediscover the entire project from the beginning.

Before continuing, it must:

1. read Master README
2. read `opencode.md`
3. verify current repository state
4. identify the last completed task
5. identify the current unfinished task
6. continue from that point

---

# 67. `opencode.md` Required State

The checkpoint should contain:

```text
Current phase
Phase status
Current task
Last completed task
Next task
Current branch
Current commit
Last known green commit
Files changed
Tests run
Test results
CI result
Current blockers
Known failures
Known limitations
Architectural decisions
Open-source decisions
Fresh E2E status
Evidence status
Do-not-redo list
Next exact OpenCode action
```

---

# 68. Checkpoint Truth Rule

`opencode.md` must be verified against the repository.

If the checkpoint says:

```text
COMPLETE
```

but the repository proves otherwise:

```text
repository reality wins
```

Then correct the checkpoint.

If the checkpoint conflicts with the Master README:

```text
Master README architecture wins
```

unless an explicit architectural decision has changed the specification.

---

# 69. Do Not Redo Completed Work

Completed work must not be reopened merely because:

- a new model starts
- OpenCode context changed
- the task appears unfamiliar
- a historical document says it was incomplete

Reopen completed work only when:

- regression is detected
- new evidence invalidates it
- architecture changed
- requirements changed
- explicit audit identifies a real defect

---

# 70. Definition of Done

The final SystemaOps implementation is complete only when:

### Architecture

- canonical pipeline exists
- no duplicate transformation pipeline
- runtime adapters are separated from semantic IR

### Discovery

- complete application inventory
- dependency graph
- unresolved dependency detection

### Semantic Model

- comprehensive COBOL IR
- source traceability
- semantic diagnostics

### Transformation

- deterministic COBOL→Java transformation
- Java IR
- runtime adapters

### Mainframe Dependencies

- JCL strategy
- DB2 strategy
- VSAM strategy
- CICS strategy
- MQ strategy
- IMS strategy
- external utility strategy

### Execution

- isolated candidate execution
- independent oracle execution
- fresh execution

### Verification

- differential comparison
- evidence integrity
- deterministic verdict
- fail-closed behavior

### Security

- trust boundaries
- authentication/authorization
- isolation
- resource controls
- auditability
- dependency/security scanning

### Operations

- durable jobs
- retries
- resume
- cancellation
- retention
- production persistence

### Product

- customer export
- approval workflow
- documentation
- operational observability

---

# 71. Final Release Gate

SystemaOps cannot be declared enterprise-ready until all required release gates pass.

```text
[ ] Architecture complete
[ ] Discovery complete
[ ] Dependency graph complete
[ ] COBOL semantic coverage validated
[ ] IR validated
[ ] Transformation validated
[ ] Runtime adapters validated
[ ] Java build validated
[ ] Candidate execution validated
[ ] Oracle execution validated
[ ] Differential comparison validated
[ ] Evidence integrity validated
[ ] Verdict validated
[ ] Security validation passed
[ ] Regression suite passed
[ ] Fresh E2E passed
[ ] CI green
[ ] Documentation synchronized
[ ] Known limitations documented
[ ] Export validated
[ ] Customer approval workflow validated
```

---

# 72. Final Product Principle

The ultimate goal is not:

> "Generate Java from COBOL."

The goal is:

> **Understand the complete legacy application, deterministically modernize it, execute the result independently, compare it against the original behavior, preserve trustworthy evidence, and give the customer a defensible modernization decision.**

---

# 73. Implementation Philosophy

SystemaOps must optimize for:

```text
Correctness
+
Determinism
+
Traceability
+
Security
+
Evidence
+
Maintainability
+
Enterprise Scalability
```

not merely:

```text
More generated code
```

---

# 74. OpenCode Final Instruction

When implementing this project:

> **Do not build what looks impressive. Build what can be proven.**

Always prefer:

```text
existing architecture
→ correct implementation
→ explicit diagnostics
→ tests
→ fresh execution
→ evidence
→ trusted verdict
```

over:

```text
shortcut
→ fixture-specific behavior
→ green test
→ unsupported claim
```

The repository, tests, evidence, and actual execution must ultimately agree with the claims made by SystemaOps.

---

# 75. Current Implementation State

This section is intentionally maintained separately from the permanent architecture.

The live implementation state must be maintained in:

```text
opencode.md
```

The Master README should not become a historical progress log.

It defines **what must be built**.

`opencode.md` defines **where implementation currently is**.

---

# END OF MASTER IMPLEMENTATION README