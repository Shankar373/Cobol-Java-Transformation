# SystemaOps Product Status

> **Baseline note (BL-009, 2026-10-10):** the commit SHA and CI run IDs recorded
> below are a *dated snapshot* of the state when this document was written, not a
> live pointer. The current verified commit, its CI run IDs and their conclusions are
> recorded in `opencode.md` (live checkpoint) and `docs/BACKLOG.md` (defect log).
> Do not treat the SHAs/CI numbers below as current without checking those two files.

Canonical product status and positioning document for SystemaOps.
Supersedes scattered status statements. Branch: `codex/universal-core`.
Baseline: `fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4`.
CI: Push CI #417 GREEN, PR CI #418 GREEN.

## 1. What SystemaOps is

SystemaOps is a deterministic modernization control plane that proves what it can
certify and blocks what it cannot. It modernizes a defined, supported subset of
COBOL workloads into Java and produces independent, evidence-bound certification
of what was transformed, what was tested, what matched, and what could not be
proven — and why.

SystemaOps doesn't ask you to trust the conversion. It shows what was transformed,
what was tested, what matched, what could not be proven, and why.

SystemaOps does not use an LLM for transformation decisions. Parser, IR,
capability analysis, mapping, generation, evidence validation, comparison, and
verdict derivation are deterministic code paths.

## 2. Who it is for

Teams accountable for COBOL-to-Java modernization who cannot accept unauditable
claims: modernization architects, platform/engineering leads, compliance reviewers,
and delivery teams that need defensible certification, not just generated code.

## 3. Architecture

Secure ingestion → discovery → dependency and capability analysis → semantic
COBOL IR → transformation planning → deterministic COBOL→Java mapping → Java
generation → candidate assembly → Docker Java execution → GnuCOBOL oracle
execution → artifact capture → contract-aware comparison → evidence integrity
validation → deterministic verdict → SQLite-backed persistence/API → React UI.

Trust boundaries:

- Uploaded COBOL is untrusted input.
- Generated Java is untrusted candidate input.
- Producer metadata is provenance, never validation evidence.
- Artifacts become evidence only after identity, completeness, hash, and binding checks.
- Verdicts derive from validated evidence, not generator claims.
- Docker is the authoritative execution path; host-only fallbacks cannot upgrade a verdict.

## 4. End-to-end workflow

Upload → Discover → Understand → Plan → Transform → Validate → Certify.

Compilation is not certification. Java that compiles has only crossed step 1 of
the evidence ladder; certification requires execution, oracle comparison,
evidence validation, and a deterministic verdict.

## 5. Application discovery

Secure ZIP ingestion (traversal and extraction limits) feeds application
discovery: programs, copybooks, files, and JCL/CICS/DB2 references are located
and indexed deterministically. Discovery output feeds the dependency graph and
capability analysis.

## 6. Dependency graph

Discovery produces CALL edges (static, literal targets), COPY edges (copybook
resolution), and file/program associations. Unresolved, dynamic, or cyclic CALL
targets are classified and blocked rather than silently assumed. Copybook
resolution must be unambiguous; missing/ambiguous copybooks fail closed.

## 7. Capability analysis

Every discovered construct is classified against an authoritative registry
(`engine/transformation/semantic_capability.py`):

- SUPPORTED — parser produces IR, mapper produces Java, runtime proof exists.
- PARTIAL — modeled/transformed only for a bounded subset; never silently upgraded.
- UNSUPPORTED — present in source but has no deterministic Java mapping; program
  carrying it is reported UNSUPPORTED, never silently SUPPORTED.
- UNAVAILABLE — infrastructure-dependent (e.g., Docker/oracle down); never VERIFIED.
- UNKNOWN — cannot be classified; treated as not certified.

Unsupported behavior remains visible and cannot silently become VERIFIED.

## 8. Modernization planning

The planner selects an executable entrypoint and only transformable units.
Plans that would include non-transformable units or select an entrypoint that
cannot execute are rejected. Copybook planning and entrypoint selection are
covered by planner contract tests.

## 9. Deterministic transformation

COBOL→Java mapping is deterministic and LLM-free. The deterministic lane
supports a proven subset (DISPLAY, MOVE, arithmetic, IF/ELSE, EVALUATE, PERFORM,
STRING/UNSTRING subset, static resolved CALL with arity/mode checks, sequential
LINE SEQUENTIAL files, copybooks via a shared Java model, EXIT PROGRAM).
Numeric semantics (VALUE normalization, sign, implied decimals, overflow
truncation, unsigned-receiver magnitude, locale-pinned formatting) are pinned to
GnuCOBOL byte-identical behavior for the proven fixtures.

## 10. Runtime proof

The Java candidate and the GnuCOBOL oracle execute in Docker. Runtime proof is
claimed only for fixtures with generated-project execution evidence under Docker.
Capability classification alone is not a runtime claim.

## 11. Evidence integrity

Evidence binds workload, source, candidate, execution role, artifact identity,
content hashes, environment/runtime identity, and comparison result. Missing,
malformed, stale, mismatched, corrupted, legacy, or tampered evidence fails
closed. Payloads are versioned, JSON-sealed, and bind a run lifecycle that is
forward-only; stale terminal writes are impossible.

## 12. Verdict model

Seven deterministic states:

VERIFIED, FAILED, PARTIAL, UNPROVEN, UNAVAILABLE, UNSUPPORTED, ERROR.

Verdicts derive from validated evidence and cannot be upgraded by claims,
skipped checks, or missing artifacts.

## 13. Integrated proof

`engine/modernization/integrated_proof.py` joins the modernization report,
runtime lane evidence, and non-runtime lanes (JCL/DB2/CICS) into one ledger and
applies a gate that can only downgrade:

    central VERIFIED <= runtime verdict VERIFIED
                     AND evidence manifest complete
                     AND evidence integrity validated
                     AND every required dependency PROVEN

JCL, DB2, and CICS have no runtime lane here, so they resolve to
PARTIAL/BLOCKED and force `CentralStatus.NOT_VERIFIED` even when the runtime
lane itself is VERIFIED. The negative demo proves this fail-closed behavior.

## 14. Security model

- Secure archive extraction (traversal/size/file-count limits).
- Isolated Docker execution with network restrictions and hard timeouts.
- API: opt-in bearer token (`CONTROL_PLANE_API_TOKEN`), bounded uploads,
  sanitized paths, typed errors without leaking tracebacks/paths.
- Persistence: versioned JSON envelopes (no pickle), seal checks, forward-only
  lifecycle state machine, startup reconciliation.
- Bounded in-process job threads; HTTP 429 when saturated.
- Not yet: TLS/egress policy at the deployment boundary (deployment's job),
  durable job queue with resume, per-client rate limiting, retention/TTL,
  audit logging, multi-node coordination (SQLite is single-node), secrets
  management beyond env var.

## 15. Supported capabilities

Supported subset, with runtime evidence where noted (see
`docs/CAPABILITY_MATRIX.md` and `docs/SEMANTIC_PROOF_MATRIX.md`):

- DISPLAY, STOP RUN, MOVE, ADD/SUBTRACT/MULTIPLY, DIVIDE/COMPUTE (targeted),
  IF/ELSE, EVALUATE (lowered to IF/ELSE), PERFORM, PERFORM VARYING,
  STRING/UNSTRING (bounded subset), EXIT PROGRAM.
- Static resolved CALL chains (A→B→C proof), fail-closed negatives for
  unresolved/dynamic/cyclic/arity-mismatch.
- Sequential files (LINE SEQUENTIAL) verified end-to-end.
- Copybooks verified end-to-end via shared Java model.
- String comparison via `String.equals`.
- Numeric VALUE semantics oracle-verified byte-identical for DISPLAY output.

## 16. Partial capabilities

- STRING/UNSTRING beyond the delimited certified subset.
- CALL parameter modes outside BY REFERENCE literal subset (BY VALUE/BY CONTENT
  not certified).
- Numeric arithmetic precision beyond IEEE-754 double representable range.
- DIVIDE/COMPUTE precision edges.
- CALL/lifecycle proof for broader multi-program, cyclic, and GOBACK/EXIT edges.
- Comparator coverage for every artifact type.

## 17. Unsupported capabilities

- GO TO Java mapping (emitted as comment), GOBACK as transform target, INVALID
  KEY / START / REWRITE / DELETE in source (source-level UNSUPPORTED).
- Indexed/relative file semantics (detected, rejected outside the certified
  boundary).
- JCL/CICS/DB2 runtime equivalence (modeled only; no runtime lane).
- Dynamic, unresolved, cyclic, or arity-mismatched CALL (fail closed).
- EXEC SQL / EXEC CICS, SORT, MERGE, ACCEPT, INITIALIZE, INSPECT, SEARCH, SET,
  ALTER, NEXT SENTENCE, SIZE ERROR — no deterministic Java mapping.

## 18. Known limitations

- Not universal COBOL compatibility; subset-certified.
- Not universal z/OS or mainframe equivalence (GnuCOBOL oracle only).
- No universal JCL/CICS/DB2 equivalence without runtime proof.
- Numeric edge areas remain under active differential proof
  (COMP/COMP-3 encoding, rounding/overflow paths).
- Evidence/verdict production-path tamper/replay coverage can be expanded.
- Persistence is single-node SQLite; durable queue, retention, rate limiting,
  audit logging, and TLS are deployment/production hardening items.
- The integrated proof **is** wired (corrected 2026-10-10, BL-008): `api/service.py`
  builds it via `runtime_evidence_from_result` during validation (line ~1002-1013)
  and persists it as `run.modernization_report["integrated_proof"]`, and
  `get_integrated_proof` (line ~1142) serves it with a recompute fallback for runs
  that predate persistence. It is exposed by `api/app.py:get_run_integrated_proof`
  (line ~632). The earlier claim that it was "not yet wired into `api/service.py`"
  contradicted the code and has been removed (Master README Section 78 — actual
  repository state wins).

## 19. Current CI status

Push CI #417 — GREEN. PR CI #418 — GREEN.
Baseline commit: `fedb7dd0c55163d711a9c8abc7333e4e3fc3cba4` on
`codex/universal-core`. CI gates: ingestion, backend + COBOL/Java Docker,
frontend typecheck/build. Run #306 remains in historical documents only.

## 20. Demo workflow

Canonical demos (fail-closed proof):

SUCCESS demo:

1. Upload a supported COBOL workload ZIP.
2. Discovery + capability analysis classify it SUPPORTED.
3. Modernization plan selects executable entrypoint and transformable units.
4. Deterministic transformation generates Java.
5. Java and GnuCOBOL oracle execute under Docker.
6. Artifacts compared under the artifact contract.
7. Evidence manifest validated.
8. Verdict: VERIFIED with complete evidence.

NEGATIVE demo (the important one — it proves the pipeline fails closed):

1. Upload a workload with an unsupported construct or dependency
   (e.g., EXEC SQL, EXEC CICS, dynamic CALL, indexed/relative files, or a
   JCL/DB2/CICS job stream).
2. Capability analysis classifies it PARTIAL/UNSUPPORTED.
3. Modernization is blocked or proof is marked incomplete.
4. Central status is NOT VERIFIED with an explicit reason.
5. Unsupported behavior remains visible; nothing silently becomes VERIFIED.

## 21. Installation / run instructions

Prerequisites: Docker (authoritative execution + GnuCOBOL oracle), Java 21
toolchain (temurin), Maven, Node/npm for the frontend, Python for the API/engine.

- Backend/API: `api/` service exposing ingestion, discovery, modernization,
  verdict, and validate endpoints over SQLite-backed state.
- Frontend: `frontend/` React (Vite) UI; `npm run dev` / `npm run build`.
- CI: `.github/workflows` covers ingestion, backend/oracle/Docker, and
  frontend/build.
- Run instructions and environment variables (`CONTROL_PLANE_API_TOKEN`,
  `CONTROL_PLANE_MAX_CONCURRENT_JOBS`) are documented in
  `docs/ARCHITECTURE.md` and deployment notes.

## 22. Production-readiness status

Not production-certified. The engine is deterministic and fail-closed with green
CI and a proven subset; production gaps remain: durable job queue with resume,
per-client rate limiting, retention/TTL, audit logging, external secret
management and TLS at the deployment boundary, multi-node coordination,
broader mutation/adversarial proof, and expanded numeric/file semantics proof.
See `docs/KNOWN_ISSUES.md` and `docs/REMEDIATION_MATRIX.md`.

## Positioning vs. alternatives

SystemaOps is not a generic code converter, not a file-by-file rewrite tool,
not a coding agent, not a Claude/Codex-style assistant, and not a black-box AI
conversion.

Traditional:

```
COBOL → Generated Java → Compilation
```

SystemaOps:

```
COBOL
→ Discovery
→ Dependency Analysis
→ Capability
→ Plan
→ Deterministic Transformation
→ Java Runtime
→ Oracle Runtime where available
→ Artifact Capture
→ Comparison
→ Evidence
→ Deterministic Verdict
```

Generic converters stop at "it compiles." SystemaOps stops only at a bounded,
evidence-backed verdict — and refuses to fabricate one where proof is missing.

## Non-claims

- No universal COBOL modernization.
- No universal z/OS support.
- No universal CICS equivalence.
- No universal DB2 equivalence.
- No JCL equivalence without runtime proof.
- No complete behavioral equivalence for unsupported constructs.
- No AI-powered semantic certainty.
