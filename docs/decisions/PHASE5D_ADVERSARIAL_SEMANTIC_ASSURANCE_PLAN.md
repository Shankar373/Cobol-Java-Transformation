# Phase 5D — Adversarial Semantic Assurance Plan

## 1. Threat Model

Treat the candidate and all candidate-produced artifacts as UNTRUSTED.

### Adversary Goals
A. Produce output that looks correct but is semantically wrong.
B. Produce a subset of expected artifacts.
C. Add extra records/artifacts.
D. Exploit formatting/normalization.
E. Exploit ordering.
F. Exploit duplicate records.
G. Exploit numeric edge cases.
H. Exploit boundary conditions.
I. Exploit malformed evidence.
J. Exploit missing evidence.
K. Exploit inconsistent artifact metadata.
L. Exploit content-hash mismatches.
M. Exploit evidence from the wrong execution.
N. Exploit wrong workload/candidate/oracle identities.
O. Trigger infrastructure states that might incorrectly become VERIFIED.

## 2. Attack Classes

### 2.1 Evidence Tampering
- Change comparison result from MISMATCH to MATCH
- Set verdict_evidence field to VERIFIED directly
- Remove comparison evidence that found a mismatch
- Alter manifest contents after hash computation
- Swap oracle and candidate artifact IDs
- Tamper with EvidenceEnvelope content

### 2.2 Identity Confusion
- **Cross-run**: Evidence from run_A used in manifest for run_B
- **Cross-workload**: Artifact from workload_A used in workload_B manifest
- **Cross-oracle**: Evidence from oracle_A attributed to oracle_B
- **Candidate binding**: Candidate source_hash mismatch with manifest

### 2.3 Comparator Attacks
All five V1 comparators tested for:
- Substring containment acceptance
- Partial matching / prefix / suffix
- Subset acceptance
- Count-only validation
- Empty output acceptance
- Accidental normalization beyond CRLF→LF

### 2.4 Normalization Attacks
The NormalizationPolicy FORBIDS:
- case_folding
- whitespace_normalization
- encoding_conversion
- trailing_whitespace_removal
- trailing_newline_removal
- substring_containment

Only ALLOWED: crlf_to_lf

### 2.5 Canonical Dump Attacks
- Record reordering
- Duplicate records
- Missing terminal lines
- Invalid file status
- Content manipulation
- Extra/missing records
- Subset acceptance
- Malformed dumps

### 2.6 Semantic / Property-Based
- Different record sets → not MATCH
- Missing record → not VERIFIED
- Single byte change → not VERIFIED
- Key change → not VERIFIED
- Identical state → MATCH (metamorphic)
- Zero checks → not VERIFIED

### 2.7 Infrastructure Attacks
- Oracle timeout → ERROR
- Candidate timeout → ERROR
- Oracle error → ERROR
- Candidate error → ERROR
- Oracle nonzero_exit → UNAVAILABLE
- Candidate nonzero_exit → still comparable
- Missing oracle → UNAVAILABLE
- Missing candidate → UNAVAILABLE

### 2.8 Unsupported Artifact Types
- INDEXED/DATABASE/JSON rejected at ArtifactIdentity construction
- VerdictDeriver._check_for_unsupported detects bypassed types

## 3. Evidence Integrity Model

EvidenceManifest binds all identities via SHA-256 content hashing:
- manifest_hash computed from manifest fields
- verdict.evidence_manifest_hash records the manifest it was derived from
- EvidenceEnvelope.verify_integrity() detects content tampering
- ArtifactIdentity.content_hash per-capture integrity
- ComparisonEvidence.content_hash per-comparison integrity

## 4. Verdict Derivation as Pure Function

VerdictDeriver.derive() is a pure function over EvidenceManifest:
1. Check for errors (timeout_applied, status=error) → ERROR
2. Check for unavailable (no oracle/candidate) → UNAVAILABLE
3. Check for unsupported artifact types → UNSUPPORTED
4. Check manifest completeness → UNPROVEN
5. Check for zero comparisons → UNPROVEN
6. Analyze comparison results (MISMATCH/INCONCLUSIVE)
7. Derive final verdict

## 5. Expected Verdict Behavior

| Condition | Expected Verdict |
|---|---|
| All comparisons MATCH | VERIFIED |
| Any comparison MISMATCH | FAILED |
| Any comparison INCONCLUSIVE | PARTIAL |
| Zero comparisons | UNPROVEN |
| Incomplete manifest | UNPROVEN |
| No oracle execution | UNAVAILABLE |
| No candidate execution | UNAVAILABLE |
| Oracle timeout/error | ERROR |
| Candidate timeout/error | ERROR |
| Oracle nonzero_exit | UNAVAILABLE |
| Candidate nonzero_exit | comparable |
| Unsupported artifact type | UNSUPPORTED |
| EvidenceEnvelope tampered | detected by verify_integrity() |

## 6. Security Preservation

Phase 5D does not modify:
- Docker-only candidate execution
- network none
- memory 512m
- CPU 1.0
- PID 256
- read-only source/input
- timeout
- explicit cleanup
- no host fallback

## 7. Scope

### IN SCOPE
- Evidence tampering tests
- Identity confusion tests
- Comparator attack surface
- Normalization attack surface
- Canonical dump attacks
- Semantic/property-based tests
- Infrastructure attack tests
- Metamorphic testing

### OUT OF SCOPE
- Phase 5E
- Producer/LLM
- Frontend/backend
- DB2/CICS/zOS
- z/OS equivalence
