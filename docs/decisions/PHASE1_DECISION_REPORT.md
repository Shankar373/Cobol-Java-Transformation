# PHASE 1 — ARCHITECTURE DECISIONS & CONTRACT FOUNDATION

> **Decision package. Not implementation.**
> This document converts the Phase-0 forensic/discovery knowledge into explicit
> decision records. Every unresolved decision carries a recommendation, but **no
> recommendation is confirmed**. Owner approval is required before dependent
> contracts are drafted and before any production code begins.
>
> Source of truth for requirements and principles: the repository
> [README.md](../../README.md) (Decision Register, Implementation Blockers,
> Lessons 1-25, Known Semantic Failure Classes).
>
> Evidence tags: `[FACT]` verified by repository/environment/execution inspection ·
> `[PREDECESSOR CODE]` · `[PREDECESSOR TEST]` · `[EXECUTION]` · `[ENVIRONMENT]` ·
> `[SYSTEMAOPS]` · `[UNKNOWN]`.

---

## Table of Contents

1. [Phase 0 Evidence Base (summary)](#phase-0-evidence-base-summary)
2. [P0 Decision Records](#p0-decision-records)
   - [PD-01 Oracle Authority (DR-08)](#pd-01-oracle-authority-dr-08)
   - [PD-02 INDEXED/RELATIVE Representation (DR-09)](#pd-02-indexedrelative-representation-dr-09)
   - [PD-03 V1 Artifact Scope (DR-11)](#pd-03-v1-artifact-scope-dr-11)
   - [PD-04 Java Candidate Contract (DR-13)](#pd-04-java-candidate-contract-dr-13)
   - [PD-05 Transformation Producer Boundary (DR-14)](#pd-05-transformation-producer-boundary-dr-14)
   - [PD-06 SQL / Database Scope (DR-12)](#pd-06-sql--database-scope-dr-12)
   - [PD-07 Certification Unit & Verdict Model (DR-15 / DR-06 / DR-30)](#pd-07-certification-unit--verdict-model-dr-15--dr-06--dr-30)
   - [PD-08 Platform Technology (DR-07)](#pd-08-platform-technology-dr-07)
3. [P1 Decision Briefs (deferrable detail)](#p1-decision-briefs-deferrable-detail)
4. [Confirmed This Phase](#confirmed-this-phase)
5. [Proposed Contract Schemas (inline, awaiting approval)](#proposed-contract-schemas-inline-awaiting-approval)
6. [Proposed Repository Structure (post-approval)](#proposed-repository-structure-post-approval)
7. [Implementation Sequence (post-approval)](#implementation-sequence-post-approval)
8. [First Vertical Slice Definition (post-approval)](#first-vertical-slice-definition-post-approval)
9. [Test-First Requirements Map](#test-first-requirements-map)
10. [Security & Isolation Controls Required](#security--isolation-controls-required)
11. [Contract Drafting Gate Status](#contract-drafting-gate-status)
12. [Consistency Audit](#consistency-audit)
13. [Final Report](#final-report)

---

## Phase-0 Evidence Base (summary)

The full forensic record lives in the README (Lessons 1-25, Key forensic evidence,
Known Semantic Failure Classes) plus the Phase-0 environment/predecessor discovery
(findings incorporated into the README in this phase). The facts most load-bearing
for the decisions below:

| # | Fact | Tag |
|---|---|---|
| E1 | **GnuCOBOL 3.1.2.0 + Open-COBOL-ESQL 1.4 (Docker, SHA-pinned Dockerfile) is the only COBOL oracle ever executed** — 85+ real differential runs; z/OS, Hercules, z390: no access evidence anywhere; host `cobc` not installed. | `[EXECUTION]` |
| E2 | **GnuCOBOL RELATIVE files on disk = `u64 little-endian length prefix + record bytes` per slot** — live-decoded from predecessor artifacts (20-byte record → `0x14` prefix). | `[EXECUTION]` |
| E3 | **GnuCOBOL INDEXED files on disk = 8,192-byte page-structured binary container** (BDB-style page headers, magic `… 62 31 05 00 09 …`), no newline structure. | `[EXECUTION]` |
| E4 | The predecessor's Java side for INDEXED/RELATIVE was a **relational emulation dumping newline text** — representations incommensurable by construction; comparison existed only as substring containment (**live false-PASS**) or was bypassed by tests. | `[EXECUTION]` |
| E5 | **Mock Spring JDBC stub classes were compiled into parity runs and labeled parity evidence** (stub `JdbcTemplate.java` inside java-run artifacts). | `[EXECUTION]` |
| E6 | Three SQL differential defects open in the predecessor: NULL semantics (DB2CURNULL01), host-variable binding, and **database state never compared anywhere**. | `[PREDECESSOR AUDIT]` |
| E7 | Two real Java-candidate shapes observed: **plain Java source tree** (no build system, zero external deps, stdin-driven main) and **Spring Boot 3.2.2 Maven fat-JAR** (H2/PG/DB2 profile). | `[EXECUTION]` |
| E8 | Oracle images referenced by **mutable `:latest` tags** — no digest pinning; no compiler-version, candidate-identity, environment, comparator-version, or contract-version stamps in evidence. | `[PREDECESSOR CODE]` |
| E9 | Local toolchain: **JDK 25.0.3, Maven 3.9.16, Python 3.14.3, Docker 29.6.2 (running), Node 24.15, git 2.54**; **PostgreSQL 16 container running healthy**; DB2 Community image present (container exited, never used in a passing test); no Gradle, Podman, Hercules, z390, host psql. | `[ENVIRONMENT]` |
| E10 | The genuinely proven predecessor path (harness, not the production gates): **stdout/stderr/exit-code/text/fixed-record differential equivalence** with independent oracle+Java execution and real mutation proofs, for core batch COBOL. | `[EXECUTION]` |
| E11 | `systemaops-ui` is a finished **visual** design system (React/TS/Vite, zero domain vocabulary — no job/run/artifact/evidence/verdict model, no API contract). A separate `modernization-platform` control plane exists (FastAPI/Celery/PG). Neither is this platform's architecture. | `[SYSTEMAOPS]` |
| E12 | Predecessor verdict-fabrication routes (6), `baseline_verified` flags, stale-baseline acceptance, skip-as-green CI, weighted-score certification model conflicting with the verdict-state model. | `[PREDECESSOR AUDIT]` |

---

## P0 Decision Records

### PD-01 Oracle Authority (DR-08)

**DECISION:**
Which runtime is the authoritative COBOL oracle for V1, and what does "authoritative" mean for verdict scoping?

**WHY IT MATTERS:**
The oracle defines what evidence can exist, which container/record formats must be handled (feeds PD-02), what every verdict's scope clause states, and whether verdicts can ever reference mainframe behavior. Every downstream contract (oracle, artifact, evidence, baseline) encodes the oracle identity.

**KNOWN EVIDENCE:**
E1: GnuCOBOL 3.1.2.0 + ocesql 1.4 is the only oracle ever executed; its image is built from a SHA-pinned Dockerfile (GnuCOBOL 3.1.2.0 on Alpine 3.19, OCESQL v1.4 tarball SHA-256-verified) — reproducible precedent. z/OS: zero access evidence. Hercules/z390: absent (E1, predecessor audit S7.4: they were scaffolding). Host `cobc`: not installed; all COBOL execution was containerized `[EXECUTION]`.

**OPTIONS:**

- **A.** GnuCOBOL 3.1.2.0 (digest-pinned) as the V1 authoritative oracle. Verdicts scoped as *"equivalent to GnuCOBOL 3.1.2.0 (image digest) under the declared environment"* — never as z/OS equivalence. z/OS remains FUTURE (DR-27).
- **B.** Wait for / require z/OS access before any oracle work. Blocks the entire platform indefinitely; no evidence z/OS is attainable.
- **C.** Dual-oracle model from day one (GnuCOBOL dev + z/OS certification). Requires infrastructure that does not exist (E1); violates smallest-architecture rule.

**RECOMMENDED:** **A.**

**WHY:**
It is the only option backed by executed evidence (85+ real differential runs). The pinned-image Dockerfile proves digest-level reproducibility is achievable. Scoping every verdict to the oracle identity is exactly the environment-scoped-verdict discipline the architecture already mandates; it converts GnuCOBOL's limitations from a hidden assumption into an explicit scope clause.

**RISKS:**
GnuCOBOL ≠ IBM Enterprise COBOL: dialect coverage gaps, ISAM-vs-VSAM container differences (CI/CA splits, alternate indexes), no DB2 z/OS, no CICS, no JCL runtime. Any stakeholder reading a verdict as "mainframe-equivalent" without the scope clause would be misled — mitigated by making the oracle identity a mandatory, visible verdict field. GnuCOBOL 3.1.2 is not the newest GnuCOBOL; staying on 3.1.2.0 is justified by execution precedent, not superiority `[UNKNOWN — whether a newer GnuCOBOL is materially better is untested]`.

**BLOCKS:**
`ORACLE_CONTRACT.md`, oracle adapter implementation, baseline spec (DR-17), PD-02 inputs, every verdict/evidence schema (oracle identity field).

**OWNER DECISION REQUIRED:** YES

---

### PD-02 INDEXED/RELATIVE Representation (DR-09)

**DECISION:**
How are INDEXED (KSDS) and RELATIVE (RRDS-class) file artifacts represented for semantic comparison in V1?

**WHY IT MATTERS:**
This is the predecessor's single confirmed live false-PASS class. Choosing wrong re-imports the most damaging defect in the forensic record; choosing expensively delays the trustworthy vertical slice.

**KNOWN EVIDENCE:**
E2/E3/E4: COBOL side = binary page container (INDEXED) / length-prefixed slots (RELATIVE), formats now decoded; Java side was relational emulation dumping text; no extraction mechanism existed anywhere; substring containment falsely passed live (7/10 adversarial cases wrongly green). The formats being decoded makes container-side extraction a concrete, bounded problem — but an unproven one.

**OPTIONS:**

| Option | Correctness | Complexity | Information preservation | Notes |
|---|---|---|---|---|
| **A.** Baseline-side logical extraction (parse GnuCOBOL container into logical records) | Sound once extractor is **certified** (fidelity-proven against oracle behavior + mutation-tested) | Medium-high — must re-implement page/slot parsing for the pinned GnuCOBOL build | Full (reads oracle's own bytes) | Formats decoded (E2/E3) — feasible, not proven |
| **B.** Require producers to emit an equivalent logical artifact | Soundness depends on producer correctness — pushes representation burden onto untrusted parties | Low for us, high risk | Loses oracle-side ground truth | Rejected pattern: producer claims are never evidence |
| **C.** Oracle-stage semantic dump: a controlled GnuCOBOL dump program (COBOL `READ`/`START` loops) runs inside the oracle container and emits normalized logical records | Strong — uses the oracle's **own** file semantics to extract; no container reverse-engineering; extraction fidelity = oracle fidelity by construction | Medium — extra evidence-bound oracle execution per workload + dump program must itself be versioned/pinned | Full logical (keys, ordering, duplicates); drops physical-layer info (which is not business semantics) | Cleanest long-term option |
| **D.** Exclude INDEXED/RELATIVE **content** equivalence from V1; validate only stdout/file-status behavior, explicitly scoped | Honest — no unproven comparator ships | Minimal | None (declared out of scope) | Verdicts must say `UNSUPPORTED` for file content, not silently skip |

**RECOMMENDED:** **D for V1; C as the V2 target (ADR-001), A as fallback if dump-program limits appear (e.g., alternate-key traversals).**

**WHY:**
V1's goal is one genuinely trustworthy end-to-end path. A/C are real engineering requiring certified extractors and their own mutation proofs before any verdict can rest on them; shipping them unproven repeats the predecessor's failure pattern under a new name. D keeps V1 honest (fail-closed `UNSUPPORTED` on file content) while the decoded formats (E2/E3) de-risk the V2 extractor work. C is preferred over A because it borrows the oracle's semantics instead of re-implementing them.

**RISKS:**
D leaves VSAM-content equivalence unvalidated in V1 — any workload whose business contract includes file content cannot be certified (must surface `UNSUPPORTED`, never PASS). Under C, the dump program becomes part of the trusted computing base and must be hash-pinned and covered by mutation validation.

**BLOCKS:**
`ARTIFACT_CONTRACT_SPEC.md` (INDEXED/RELATIVE type definitions), those comparators, VSAM mutation scenarios.

> **SUBSTRING CONTAINMENT IS FORBIDDEN AS A GENERAL EQUIVALENCE STRATEGY** — for INDEXED, RELATIVE, KSDS, RRDS, structured records, database state, or any semantic structured artifact. This is non-negotiable regardless of the option chosen above.

**OWNER DECISION REQUIRED:** YES

---

### PD-03 V1 Artifact Scope (DR-11)

**DECISION:**
Which artifact types are in the V1 artifact contract (the smallest trustworthy scope)?

**WHY IT MATTERS:**
Defines the comparator registry build order, the first vertical slice's contract set, and the honest boundary of V1 certification claims.

**KNOWN EVIDENCE:**
E10: the only predecessor comparisons ever proven trustworthy (independent execution + real mutation proofs) were **stdout, stderr, exit code, controlled stdin, text/line-sequential files, fixed-record binary**. Everything else was false-PASS, bypassed, or never compared (E4/E5/E6).

**OPTIONS:**

- **A. Core-proven set:** `STDOUT`, `STDERR`, `EXIT_STATUS`, `TEXT_FILE`, `FIXED_RECORD` + execution metadata and hashes as evidence envelope (not compared artifacts).
- **B.** A + `SEQUENTIAL` variable-length + `BINARY` opaque-byte.
- **C.** Broad set including INDEXED/RELATIVE/`DATABASE_STATE`/`SQLCODE` now.

**Classification by evidence:**

| Artifact | Status |
|---|---|
| STDOUT, STDERR, EXIT_STATUS, TEXT_FILE, FIXED_RECORD | **PROVEN/SUPPORTABLE** (E10) |
| SEQUENTIAL (variable), BINARY | POSSIBLE BUT UNPROVEN (needs new differential fixtures + mutation proofs) |
| INDEXED, RELATIVE, KSDS, RRDS | OUT OF V1 pending PD-02 (recommend D) |
| DATABASE_STATE, SQLCODE, SQLSTATE | OUT OF V1 pending PD-06 |
| Execution metadata, hashes, timing, termination | Evidence envelope — SUPPORTABLE (captured, not compared) |

**RECOMMENDED:** **A.**

**WHY:**
Every type in A has execution-proven comparison semantics and a real mutation-proof precedent. Adding unproven types to the V1 contract would let workloads claim coverage the validator cannot honestly certify. B is acceptable **only if** the owner accepts slightly wider scope with new fixtures built during the slice; C is rejected outright.

**RISKS:**
A means stdout-visible behavior dominates V1 — a workload whose business contract needs file/database artifacts gets `UNSUPPORTED` for those artifacts. This is the honest trade.

**BLOCKS:**
`ARTIFACT_CONTRACT_SPEC.md`, comparator build order, first vertical slice contracts, certification scope statement (PD-07).

**OWNER DECISION REQUIRED:** YES

---

### PD-04 Java Candidate Contract (DR-13)

**DECISION:**
What candidate shape(s) must the V1 execution layer be able to build and run, and what must the candidate declare about itself?

**WHY IT MATTERS:**
The Java execution layer, sandbox design, and the candidate-identity fields in evidence/verdicts are all shaped by this. Over-specifying couples us to one producer's output; under-specifying makes execution impossible to control.

**KNOWN EVIDENCE:**
E7: two real shapes observed — plain Java source tree (no build system, zero external deps, class `main` reading stdin, CWD-relative file outputs) and Spring Boot 3.2.2 Maven fat-JAR (H2/PG/DB2 datasources, port-bound server execution). The plain-tree shape is the one the proven harness path executed `[EXECUTION]`.

**OPTIONS:**

- **A.** V1 supports exactly one canonical shape: **plain Java source tree + `javac` + explicit entrypoint manifest** (the proven shape). Maven/Spring adapters deferred to V2.
- **B.** Support both observed shapes from V1.
- **C.** Mandate a single new canonical packaging format defined by this platform.

**RECOMMENDED:** **A**, with the **Java Candidate Manifest** (below, in Proposed Contract Schemas) as the neutral declaration layer so that adding shapes later is adapter work, not contract redesign.

**WHY:**
The plain-tree shape is the only one with executed differential evidence; it has no build-system coupling, no framework dependency resolution, no ports/servers — the smallest sandbox and timeout surface. B multiplies build/isolation/security complexity in V1 for zero proven validation gain. C pushes packaging burdens onto producers before the producer contract (PD-05) is negotiated.

**RISKS:**
If the actual transformation producer cannot emit plain-tree candidates, A stalls candidate execution until a V2 adapter — this is why PD-05 must be answered jointly with the LLM owner **before** the execution layer is built.

**BLOCKS:**
`JAVA_CANDIDATE_CONTRACT.md`, Java execution layer, sandbox policy (DR-18), mutation candidate-regeneration step.

**OWNER DECISION REQUIRED:** YES (joint with LLM integration owner)

---

### PD-05 Transformation Producer Boundary (DR-14)

**DECISION:**
What does the platform require from the external transformation producer, in what physical form, with which mandatory metadata?

**WHY IT MATTERS:**
This is the platform's only input channel for candidates. Too demanding = producer friction; too lax = identity/provenance gaps that poison evidence. Also: mutation validation requires the producer to **regenerate candidates from mutated COBOL on demand** — a discovered contract requirement no predecessor ever had.

**KNOWN EVIDENCE:**
Predecessor was monolithic (it was its own producer); no producer contract, no candidate identity, no transformation IDs ever existed `[PREDECESSOR CODE]`. E7: two output shapes. DR-02/DR-03: producer external, replaceable, untrusted; metadata never evidence.

**OPTIONS:**

- **A.** Minimal mandatory manifest + source-tree package: candidate files + manifest declaring the fields below; anything undeclared is absent, never guessed.
- **B.** Rich contract including semantic mapping/coverage claims from the producer.
- **C.** No contract — accept whatever arrives, infer shape.

**RECOMMENDED:** **A.**

**WHY:**
A gives provenance and executability without trusting producer claims (B's semantic claims would violate "producer claims are never evidence"; C guarantees ambiguity). Mandatory fields (proposed):

```text
producer identity + version          (branding only — never evidence)
candidate identity                   (platform-assigned on intake, ideally)
source workload identity             (binding to the COBOL workload)
source hash(es)                      (so candidate↔source binding is checkable)
generated-file list                  (with per-file hashes)
entrypoint declaration               (main class; args; stdin convention)
java version + dependency declarations
runtime requirements                 (env vars, expected CWD, output paths)
generation timestamp + transformation metadata (optional, informational)
mutation regeneration capability     (REQUIRED: on-demand regeneration
                                      for mutated COBOL — mutation validation
                                      depends on it; absence caps mutation
                                      validation at UNAVAILABLE for that producer)
```

**RISKS:**
If the real producer cannot stamp all mandatory fields, intake must fail closed (no verdict beyond `UNPROVEN` for unidentifiable candidates). The mutation-regeneration requirement is new — the LLM owner must confirm feasibility.

**BLOCKS:**
`TRANSFORMATION_PRODUCER_CONTRACT.md`, candidate ingestion, mutation validation (hard dependency), Java execution layer identity binding.

**OWNER DECISION REQUIRED:** YES (joint with LLM integration owner)

---

### PD-06 SQL / Database Scope (DR-12)

**DECISION:**
Is SQL/database validation in V1, deferred, or excluded?

**WHY IT MATTERS:**
DB equivalence was the predecessor's biggest false-claim area. All three known SQL defects are still open; including SQL in V1 ships known-broken equivalence.

**KNOWN EVIDENCE:**
E6: NULL divergence (DB2CURNULL01) and host-variable binding are live failures; DB state was **never compared anywhere**; E5: mock JDBC stubs contaminated runs; fabricated `PGHOST → VERIFIED_POSTGRESQL` literal route. E9: PostgreSQL 16 running locally (ocesql→PG COBOL-side path executed in predecessor); DB2 image present but never used in a passing test.

**OPTIONS:**

- **A.** Exclude SQL/DB from V1. SQL-containing workloads fail closed (`UNSUPPORTED` for SQL artifacts) with the exclusion stated in the verdict.
- **B.** Controlled PostgreSQL-only in V1 (ocesql+PG oracle side, PG candidate side).
- **C.** PostgreSQL + real `DATABASE_STATE` artifact comparison (snapshot-diff both sides, real DB mandatory both sides, mocks forbidden from positive verdicts).

**RECOMMENDED:** **A for V1; C as the V2 target** (B alone would repeat stdout-only DB verdicts — the exact B-6 defect).

**WHY:**
Three open defects (NULL, host-var, no state comparison) must each get a semantic definition + artifact contract + differential fixtures + mutation proofs before any SQL equivalence claim — that is a phase of work, not a V1 add-on. A is the fail-closed honest scope; C is the only sound end-state because DB equivalence without observed state is not equivalence.

**RISKS:**
A excludes a capability the local environment could technically exercise (PG is running) — but executable ≠ provable. Under C, every DB-involving verdict must carry the backend identity of both sides; mocks may never contribute to positive verdicts.

**BLOCKS:**
DB adapters, `DATABASE_STATE` comparator, SQL artifact contract types, DB-involving workloads.

**OWNER DECISION REQUIRED:** YES

---

### PD-07 Certification Unit & Verdict Model (DR-15 / DR-06 / DR-30)

**DECISION:**
(a) What is the smallest certifiable unit? (b) Is partial certification allowed? (c) Final verdict vocabulary. (d) Verdict-state vs weighted-score certification model.

**WHY IT MATTERS:**
This defines what a "certified" claim means, what evidence is mandatory, what invalidates it, and how the verdict engine aggregates — the heart of the certification spec and the UI's trust display. Two vocabularies are currently in conflict (README six-state vs proposed `ERROR`), and the predecessor's weighted-score model (CERTIFICATION_MODEL.md) was never adopted nor rejected.

**KNOWN EVIDENCE:**
README: equivalence unit = workload (never global); DR-06 conflict documented (six states + proposed `ERROR`); DR-30 conflict flagged (weighted 5-tier/100-point scoring vs evidence-derived verdict states). Predecessor failure modes: partial evidence silently promoted to full certification; review-required verdicts flowing green; `PARTIAL` existing as a verdict but no policy for certifying subsets `[PREDECESSOR AUDIT]`.

**OPTIONS:**

**(a) Smallest certifiable unit:**
- A1. **One workload-run** — a single validation execution of one workload under one fully-declared identity set.
- A2. A program (aggregating its workload runs).
- A3. An application/release (aggregating programs).

**(b) Partial certification:**
- B1. Not in V1 — certification is all-or-nothing per unit; `PARTIAL` remains a **run verdict**, not a certification.
- B2. Allow scoped subset certification ("certified for artifacts X,Y under environment E").

**(c) Verdict vocabulary:**
- C1. Six states: `VERIFIED / PARTIAL / FAILED / UNPROVEN / UNAVAILABLE / UNSUPPORTED`.
- C2. Seven states: C1 + `ERROR` (platform-internal failure — validator itself crashed/could not process), keeping `UNAVAILABLE` for infrastructure and `FAILED` for behavioral divergence.

**(d) Certification model:**
- D1. Verdict-state, evidence-derived (a run is certified only if its evidence manifest is complete and its verdict is `VERIFIED`).
- D2. Predecessor-style weighted tier scoring (100-point, grades).

**RECOMMENDED:** **A1 + B1 + C2 + D1.**

**WHY:**
A1 is the only unit with a closed, checkable evidence set (one identity tuple). B1 is the smallest honest policy; subset certification (B2) can be added later as a *derived* statement, but inventing it now recreates the "partial evidence → full claim" failure. C2 separates the three real failure kinds the predecessor conflated (behavioral vs infrastructure vs platform-internal — swallowed baseline exceptions became warnings); it is additive to the documented six-state model. D1: certification must be a pure derivation from evidence; weighted scores let partial evidence average into a passing grade — structurally the failure mode the audit proved.

**RISKS:**
C2 adds a state the UI and reports must render distinctly (ERROR ≠ UNAVAILABLE ≠ FAILED); all three must be non-green. Under A1+B1, multi-workload programs cannot be "certified" until every workload run is VERIFIED — conservative by design.

**Certification invalidation (any → certification void):** any identity change (source hash, candidate hash, oracle digest, environment, contract/comparator versions) · stale evidence · mutation-gate failure · evidence-manifest incompleteness · unsupported artifact silently ignored.

**BLOCKS:**
`VERDICT_CONTRACT.md`, certification spec, verdict engine schema, aggregation logic, UI verdict components.

**OWNER DECISION REQUIRED:** YES

---

### PD-08 Platform Technology (DR-07)

**DECISION:**
Implementation language/build stack for the validation engine, backend/control plane, and frontend.

**WHY IT MATTERS:**
Every module, contract schema, test stack, packaging, CI, and the frontend/backend/engine process boundaries hang on this. It also determines how easily the LLM-integration owner can interface at the producer boundary.

**KNOWN EVIDENCE:**
E10: the only genuinely proven execution-control path for this exact problem class (container orchestration, byte-level artifact capture, differential comparison) is the predecessor's **Python** parity harness `[PREDECESSOR TEST]`. Local: Python 3.14.3, JDK 25.0.3, Maven 3.9.16, Node 24.15 (E9). Candidates are JVM programs but execute inside containers — the engine need not share their runtime `[ENVIRONMENT]`. Predecessor's Python 3.12 CI vs local 3.14 gap noted. `systemaops-ui` is React/TS/Vite but is NOT a dependency (E11, DR-24-style boundary; new UI must be project-owned).

**OPTIONS:**

| Dimension | Python (engine) + FastAPI (backend) + React/TS/Vite (frontend) | Java (engine+backend, Spring) + React frontend | Polyglot |
|---|---|---|---|
| Evidence for this domain | Proven harness precedent — direct pattern reuse at the *architecture* level (not code) | Candidates are JVM; strong typing for contract schemas | Best-of-each, worst-of-complexity |
| Process/execution control | subprocess/docker tooling mature; predecessor proven | JVM process control fine but heavier | — |
| Contract schemas | Pydantic-style typed validation, JSON-native | Jackson/records, JSON-native | — |
| CI/test | pytest precedent; local 3.14 vs CI 3.12 pin needed | JUnit/Maven; JDK 25 local vs Java 17 candidates (containers decouple) | — |
| Frontend | React/TS/Vite, new project-owned design system (mandatory: no systemaops dependency) | same | — |
| Complexity | Single language for engine+backend possible (separate processes, separate deployables) | Single language for engine+backend | Multi-language ops burden; violates smallest-architecture rule without evidence |

**RECOMMENDED:** **Engine: Python (pin 3.12, matching executed precedent — local 3.14 remains for tooling only) · Backend: FastAPI as a separate process/deployable · Frontend: React + TypeScript + Vite with a NEW project-owned design system.** Engine and backend may share a language while remaining strictly separate processes with the engine independently executable (no HTTP dependency).

**WHY:**
The recommendation rests on executed precedent for the hardest part (controlled containerized differential execution), not popularity. Java remains a credible alternative — the owner should weigh team skills; if the owner prefers Java for the engine, the contracts are unaffected (schemas are JSON/neutral), only implementation ergonomics change. That is why this decision, though P0, does not block contract *design* — only contract *implementation*.

**RISKS:**
Python version drift (3.12 pin required); the backend must never import engine internals that would let it duplicate comparator logic — enforced by process boundary + import rules. Java choice would forfeit the harness-pattern precedent but gain type-safety in comparators `[MODEL INFERENCE]`.

**BLOCKS:**
All implementation code (not contract design); CI topology; packaging.

**OWNER DECISION REQUIRED:** YES

---

## P1 Decision Briefs (deferrable detail)

| DR | Question | Recommendation (PROPOSED) | Why / note |
|---|---|---|---|
| DR-10 | Semantic-analysis depth V1 | **Discovery + data-division record/key model only; no procedure-division AST in V1** | First slice's artifact contracts can be declared in the workload definition; data-division (layouts, keys, file orgs) is what contract derivation actually needs. Trusted predecessor evidence came from oracle differentials, not parser depth. |
| DR-16 | Evidence manifest format | **JSON manifests + SHA-256 content-addressed artifacts; no signing in V1; oracle images pinned by digest** (digest-pinning is a requirement, not an option) | E8: mutable `:latest` oracle tags are a live reproducibility defect. Signing deferred until an owner requires third-party verifiability. |
| DR-17 | Baseline lifecycle | **V1: fresh oracle execution every run — no baseline reuse at all in the first slice**; identity-bound reuse (source/dep/input/env/oracle/contract hashes) introduced only with the regression suite | Removes the entire stale-baseline failure class from V1 by construction; E10 oracle runs are seconds-scale, so freshness is cheap. |
| DR-18 | Sandbox / isolation | **Container-per-execution: read-only staged source copy, `network none` (SQL later needs scoped network), mem/cpu/pids limits, hard timeout, no host RW mounts, no chmod 777, no default creds** | Predecessor hardening params are a sound base; its RW mounts/777/admin:admin are the documented holes (security section of README). |
| DR-19 | Product identity / users | **OPEN — no recommendation**; three evidence-supported models exist (standalone w/ SystemaOps visual language / integrated validation service of modernization-platform / internal tool) | E11 gives real options; this is a business-owner call. Blocks branding/naming and UI deployment story, not engine work. |
| DR-20 | Scale / concurrency | **Single-user, single-workload-at-a-time V1; no queueing/persistence beyond manifests-on-disk** | No scale evidence exists; building distribution now violates the no-over-engineering rule. |

---

## Confirmed This Phase

Per owner instruction in the Phase-1 mandate (the three-layer separation is mandated architecture):

- **DR-29 — Frontend / Backend / Validation Engine separation: CONFIRMED.** Frontend = presentation only; backend = API/orchestration/persistence, **never** semantic truth; validation engine = the sole semantic trust boundary, independently executable without HTTP/frontend/backend. The existing SystemaOps UI is **not** an implementation dependency. Specific frontend/backend technologies remain inside DR-07/PD-08.

Also confirmed by standing README decisions (unchanged): DR-01…DR-05, DR-26, DR-27, DR-28.

---

## Proposed Contract Schemas (inline, awaiting approval)

These are **proposals**. Contract documents are NOT created until their gating decisions are approved (see [Contract Drafting Gate Status](#contract-drafting-gate-status)).

### Artifact Contract (gated by PD-03)

```text
artifact_id            platform-assigned, globally unique
workload_id            binding to workload identity
execution_id           binding to the producing execution
producer_role          ORACLE | CANDIDATE
artifact_type          STDOUT | STDERR | EXIT_STATUS | TEXT_FILE | FIXED_RECORD
                       (V1 set per PD-03; further types appended per future DRs)
logical_name           stable name within the workload contract
location               path/logical location within the execution workspace
media_type / encoding  e.g., text/plain; ISO-8859-1 | UTF-8 | binary
size                   bytes
record_count           where applicable (FIXED_RECORD)
content_hash           SHA-256
captured_at            timestamp (execution-bound)
environment_id         binding
contract_version       schema version of this contract
completeness           COMPLETE | MISSING | MALFORMED (MISSING/MALFORMED never compare green)
provenance             execution + capture mechanism identity
-- comparison policy block (per artifact):
comparison_policy      comparator id + version
normalization_policy   explicitly enumerated permitted normalizations (e.g., CRLF)
                       — anything not listed is forbidden
failure_policy         fail-closed state on missing/malformed/unsupported
```

Semantics: missing artifact → artifact-level `MISSING` + verdict contribution `UNAVAILABLE`/`FAILED` per policy, never empty-success; duplicate artifact → intake error, not last-wins; unsupported type → `UNSUPPORTED`, no fallback comparator, **no substring containment anywhere**.

### Verdict Contract (gated by PD-07)

```text
run identity: run_id, workload_id, source_hash, candidate_hash
scope identity: oracle_id (image digest), environment_id, contract_versions,
                comparator_versions, executed_check_count, skipped/unavailable counts
verdict: VERIFIED | PARTIAL | FAILED | UNPROVEN | UNAVAILABLE | UNSUPPORTED | ERROR
        (per PD-07 recommendation; final set = owner decision)
derivation: pure function of the evidence manifest — inputs listed explicitly;
            forbidden inputs: booleans, env vars, source text, file existence,
            test counts, hardcoded metrics, producer claims, baseline existence
invariants: 0 executed checks → never VERIFIED; skip → never PASS;
            monotone downgrade only; every verdict carries its full scope block
certification: present only when verdict == VERIFIED and evidence completeness == true
```

### Oracle Contract (gated by PD-01)

```text
oracle_id              adapter id + image DIGEST (never mutable tag)
compiler/runtime versions (cobc --version output captured as evidence)
status model           AVAILABLE | UNAVAILABLE | FAILED | SUCCEEDED (observed, probed)
isolation              staged read-only source copy; source tree hash verified unchanged post-run
evidence obligations   command, env, exit code, stdout, stderr, generated files + hashes,
                       start/end, execution id
hard rules             no fabrication; no config-presence-as-evidence; no source mutation
```

### Java Candidate Contract (gated by PD-04)

```text
candidate identity + hash (intake-assigned)
source workload identity + source hash binding
shape: V1 = plain Java source tree (per PD-04 recommendation)
build: platform-run javac (no candidate build system in V1)
entrypoint: main class; args; stdin convention; CWD; output-path conventions
exit semantics: process exit code captured; timeout = platform-enforced failure (ERROR)
dependencies: declared, must be empty or vendored in V1 (no network fetch during execution)
sandbox: per DR-18 policy
```

### Transformation Producer Contract (gated by PD-05; external interface only)

The mandatory-manifest fields listed in PD-05, plus: intake fail-closed on missing mandatory fields; producer metadata stored as provenance, never as validation evidence; mutation-regeneration capability declaration.

---

## Proposed Repository Structure (post-approval)

`[PROPOSAL]` — replaces the README's `platform/`-centric proposed tree (README updated to this shape as PROPOSED). Do not create until decisions land.

```text
Cobol-Java-Transformation/
├── contracts/            # versioned contract specs + schemas (the stable boundary)
├── engine/               # THE validation engine — independently executable
│   ├── oracle/           #   oracle adapters (GnuCOBOL first, per PD-01)
│   ├── execution/        #   process/container execution abstraction
│   ├── artifacts/       #   capture + artifact contracts
│   ├── comparators/      #   typed comparator registry
│   ├── differential/     #   differential orchestration
│   ├── mutation/         #   production-path mutation validation
│   ├── evidence/         #   manifests, provenance, content-addressed store
│   ├── verdict/          #   pure derivation from evidence
│   └── certification/    #   certification policy application
├── backend/              # control plane: API, auth, workload mgmt, persistence
├── frontend/            # presentation only; new project-owned design system
├── tests/                # per Test-First Requirements Map
├── benchmarks/  fixtures/  reference-runtimes/   # later phases
├── docs/                 # architecture, decisions, ADRs, specs
└── tools/
```

---

## Implementation Sequence (post-approval)

1. contracts (schemas + validation) → 2. artifact model → 3. execution abstraction → 4. oracle adapter → 5. candidate adapter/intake → 6. evidence model → 7. verdict model → 8. comparator interfaces → 9. first vertical slice → 10. production-path mutation → 11. backend/control plane → 12. frontend.

Contract-first: no parser, no transformer, no LLM code, no VSAM engine, no SQL emulator, no giant pipeline before the boundaries exist.

## First Vertical Slice Definition (post-approval)

Arithmetic + IF + DISPLAY COBOL program, controlled stdin → oracle execution (Docker, digest-pinned GnuCOBOL) → stdout/stderr/exit artifacts → plain-tree Java candidate → sandboxed Java execution → artifacts → contract validation → typed comparison → evidence manifest → verdict (honestly derived — `VERIFIED` only if every invariant holds) → one production-path mutation (arithmetic operand) detected through the same comparator stack. Purpose: prove the architecture produces trustworthy evidence — not COBOL coverage.

## Test-First Requirements Map

| Area | Mandatory non-vacuous tests |
|---|---|
| Artifact contracts | missing · duplicate · wrong hash · wrong identity · wrong type · wrong encoding · incomplete |
| Verdict logic | VERIFIED-with-valid-evidence · FAILED-with-real-difference · UNPROVEN-insufficient · ERROR-execution-failure · UNAVAILABLE-missing-env · NOT_RUN · zero-comparisons · skipped · stale-evidence · identity-mismatch |
| Comparators | exact equality · meaningful difference · policy-scoped normalization (only where contract allows) · unsupported type (fail closed) · malformed artifact |
| Mutation | production-path detection; a sabotaged comparator MUST show as NOT_DETECTED (proving the metric is computed, not hardcoded) |
| Baselines (V2) | stale-reuse rejected · identity mismatch rejected · source tree byte-identical after oracle runs |

## Security & Isolation Controls Required

Untrusted generated Java AND untrusted COBOL inputs: container-per-execution; read-only staged copies; `network none` (SQL phases later require scoped networking — explicit decision); memory/CPU/pids limits; hard timeouts with timeout-as-ERROR (not PASS); workspace cleanup; secrets via environment-injected config, never hardcoded (predecessor's `admin:admin`/`postgres`/`secret` literals are the anti-pattern); artifacts integrity-hashed at capture. **No production-security claim until implemented and tested.**

## Contract Drafting Gate Status

| Contract | Gated by | Status |
|---|---|---|
| `contracts/ORACLE_CONTRACT.md` | PD-01 | **BLOCKED — owner approval required** |
| `contracts/ARTIFACT_CONTRACT_SPEC.md` | PD-03 (+PD-02 for file types) | **BLOCKED** |
| `contracts/VERDICT_CONTRACT.md` | PD-07 | **BLOCKED** |
| `contracts/JAVA_CANDIDATE_CONTRACT.md` | PD-04 | **BLOCKED (joint with LLM owner)** |
| `contracts/TRANSFORMATION_PRODUCER_CONTRACT.md` | PD-05 | **BLOCKED (joint with LLM owner)** |

Per the stop conditions, **zero contract files and zero implementation were produced this phase.**

## Consistency Audit

- No OPEN/PROPOSED decision was converted to CONFIRMED — the only new CONFIRMED entry (DR-29) is an explicit owner mandate from the Phase-1 instructions. ✔
- No implementation status fabricated; no predecessor code modified (predecessor git state unchanged); no SystemaOps UI code imported or referenced as a dependency. ✔
- No LLM/transformation logic implemented (producer boundary defined as interface only). ✔
- No comparator logic in backend/frontend descriptions; engine remains sole semantic boundary. ✔
- No fake certification, no source-text certification, no env-var certification, no SKIP→PASS, no UNKNOWN→PASS, no zero-checks→PASS, no stale-evidence reuse, **no substring containment anywhere**, no silent semantic fallback. ✔

## Final Report

**PHASE 1 STATUS: PARTIALLY READY** — the decision package is complete; contract drafting and all implementation are **BLOCKED** pending the owner decisions below.

| Category | Items |
|---|---|
| **CONFIRMED** | DR-29 (layer separation, owner-mandated) |
| **PROPOSED (recommended)** | PD-01:A · PD-02:D-for-V1/C-for-V2 · PD-03:A · PD-04:A · PD-05:A · PD-06:A-for-V1/C-for-V2 · PD-07:(A1+B1+C2+D1) · PD-08:Python/FastAPI/React · DR-10/16/17/18/20 briefs |
| **OWNER DECISION REQUIRED** | All eight P0 records above (DR-06,07,08,09,11,12,13,14,15,19,30 as mapped) — PD-04 and PD-05 jointly with the LLM integration owner |
| **BLOCKED** | All five contract documents; all production code |

**Files created:** `docs/decisions/PHASE1_DECISION_REPORT.md` (this file).
**Files modified:** `README.md` (DR-29/30/31 added; layer-separation section; discovery facts; proposed tree; status pointers — details in the README's own change context).
**Files deleted:** none. **Contracts created:** none (gated). **Implementation created:** NO. **Tests added/executed:** none (documentation phase).

**Outstanding blockers (exact list to answer before the first production vertical slice can safely begin):**
1. **PD-01 / DR-08** — Oracle authority (recommend GnuCOBOL 3.1.2.0 digest-pinned, scoped)
2. **PD-02 / DR-09** — INDEXED/RELATIVE strategy (recommend: exclude from V1; oracle-dump for V2)
3. **PD-03 / DR-11** — V1 artifact scope (recommend: the five proven types)
4. **PD-04 / DR-13** — Java candidate contract (recommend: plain-tree V1) — **joint with LLM owner**
5. **PD-05 / DR-14** — Producer I/O contract + mutation-regeneration capability — **joint with LLM owner**
6. **PD-06 / DR-12** — SQL/DB scope (recommend: exclude from V1; PG+state-compare for V2)
7. **PD-07 / DR-15+DR-06+DR-30** — Certification unit + verdict vocabulary + model
8. **PD-08 / DR-07** — Platform technology (blocks implementation, not contract design)

**Recommended next step:** Owner answers the eight P0 decisions (five are single-owner; two joint with the LLM integration owner; PD-07 resolves three conflicts at once). On approval, the five contract documents are drafted from the schemas above, ADRs 001-004 are recorded, and the first vertical slice begins under the test-first map.
