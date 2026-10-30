# Product Goal-Gap Matrix

Date: 2026-10-30
SHA: bde0e3d90610e5d2840a63c7cd59cb9f90b418cd
Scope: COBOL-to-Java modernization platform (certified subset only; universal COBOL compatibility not claimed).

| Feature / Area | Existing implementation | Evidence | Remaining gap | Risk / User impact | Acceptance criteria | Status |
|---|---|---|---|---|---|---|
| Universal ingestion (ZIP/Git) | Ingestion service, safety checks, limits | Tests + docs | Git/ZIP edge cases, large workloads | Medium | Safe extraction, deterministic errors | Partial |
| Application discovery | Multi-program discovery, CALL/COPY deps | Integration tests | Dynamic CALL, nested copybook ambiguity | Medium | Dependency graph accuracy | Partial |
| Capability engine | Semantic capability registry + analyzer | 145 capability tests | Must stay in sync with parser/generator | High | No false SUPPORTED | Improved (this checkpoint) |
| Modernization planning | Plan from capability findings | Planner tests | Dependency-aware blocking refinement | Medium | Blockers exposed before generation | Partial |
| COBOL parsing/IR | Fixed/free format, many constructs | Parser tests | Unsupported constructs fail closed | Medium | Explicit unsupported nodes | Partial |
| Deterministic Java generation | IR-driven generator | Oracle proofs | Expression precedence/overflow edges | High | Byte-identical oracle output | Partial |
| Runtime verification | Compile/run in Docker, evidence | Integration tests | Full suite runtime, multi-program | High | Docker-gated proofs | In progress |
| Backend orchestration | APIs, persistence, lifecycle | API tests | Concurrency, cancellation, retries | Medium | Status integrity | Partial |
| Frontend | React workflow UI | 172 tests, lint, build | Real backend state wiring, partial results | Medium | No false success | Partial |
| Security | ZIP safety, auth, container limits | Security tests | Signing, license, key custody | High | Fail-closed gates | Blocked (owner) |
| Documentation | Extensive reports | Audit | Support claims must match code | Medium | Accurate scope | Ongoing |
| Trusted signing | Proposal only | Decision record | Owner key custody decision | High | Signed artifacts in prod | Blocked (owner) |
| License | None | Dependency audit | Owner license selection | Legal | LICENSE committed | Blocked (owner) |

## Notes

- Universal COBOL compatibility is intentionally not claimed.
- Owner-dependent signing and license decisions remain explicit blockers.
- Next implementation focus: semantic coverage expansion with oracle proof per construct family.
