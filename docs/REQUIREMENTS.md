# Current Requirements

## Functional

1. Securely ingest supported COBOL workloads.
2. Discover programs, copybooks, dependencies, files and supported workload metadata.
3. Build semantic IR without silently discarding recognized meaning.
4. Analyze capability before transformation.
5. Fail closed for unsupported, partial, unavailable or unknown transformation paths.
6. Produce Java deterministically for the supported subset.
7. Compile and execute generated Java in a controlled runtime.
8. Execute the COBOL oracle where inside the oracle boundary.
9. Capture declared artifacts and provenance.
10. Compare only through explicit artifact contracts.
11. Validate evidence integrity before deriving verdicts.
12. Persist and expose lifecycle state through the control plane.
13. Keep UI presentation separate from semantic authority.

## Semantic

- Parser recognition must not imply transformation support.
- IR must preserve distinctions needed by downstream semantics.
- Numeric precision, scale, sign, truncation, rounding and storage representation must not be
  silently collapsed.
- CALL parameter semantics must be explicit.
- File status and error behavior must survive mapping.
- Control-flow scope and fall-through must be preserved.
- Unsupported enterprise constructs must produce explicit diagnostics.

## Verification

- Missing evidence is not success.
- Wrong hashes, identities and types are rejected.
- Unsupported artifact types fail closed.
- Comparator behavior is deterministic and versioned.
- Verdict derivation is deterministic and evidence-driven.
- Mutation and adversarial tests must exercise the real verification path.

## Security

- Secure archive extraction and resource limits.
- Isolated execution, network restrictions and hard timeouts.
- No implicit host write access.
- Production deployment requires authentication, authorization, isolation, retention,
  audit logging, rate limiting and safer persistent serialization.

## Current non-goals

Universal COBOL compatibility, universal z/OS equivalence, automatic certification of
JCL/CICS/DB2 semantics without runtime proof, silent fallback and LLM-based semantic decisions.
