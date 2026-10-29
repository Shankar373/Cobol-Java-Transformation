# Design Proposal: Trusted Evidence Signing (L.3.7)

**Status:** Proposal only — NOT implemented. The current seal remains a
tamper-evidence self-seal (see `api/artifact_seal.py`).
**Audit reference:** `docs/AUDIT_4_COMMITS.md` §6 (L.3.7), `docs/FILE_LEVEL_AUDIT.md` L.3.7.
**Date:** 2026-10-29

## 1. Problem

`GET /runs/{id}/download` serves a generated bundle whose bytes are checked
against a persisted seal (`runs.generated_seal`). The seal is a SHA-256
self-seal: an attacker who can rewrite the database can rewrite the seal too,
so the integrity claim is advisory against a database attacker. The module
docstring now states this explicitly (narrowed claim, commit a3509ca).

## 2. Trust boundary

- **Protected against:** filesystem substitution of the bundle after
  execution (the common case — an actor with write access to the staging
  volume swapping sources before export).
- **NOT protected against:** an attacker who can rewrite `runs.generated_seal`
  in the control-plane store, or who holds the signing key.
- **Goal of trusted signing:** make forgery require the signing key, which
  lives outside the database (HSM/KMS or a mounted secret), so a DB-only
  attacker cannot forge a valid seal.

## 3. Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Cosign/sigstore (keyless OIDC) | Industry standard; no long-lived key | Requires network + cosign binary + identity provider; heavy for an air-gapped control plane |
| B. HMAC-SHA256 with server secret | Stdlib only; simple; air-gap friendly | Shared secret must be managed; rotation requires re-sealing runs |
| C. Ed25519 (asymmetric) with a private key file | Offline verification possible with public key; non-repudiation | Key generation/distribution; private key must be protected at rest |
| D. Narrow the claim (done) | Zero risk, honest | No cryptographic authenticity |

**Recommendation:** Option C (Ed25519) for production, with Option B (HMAC) as
a lighter interim. Either requires a key-management decision by the operator.

## 4. Proposed design (Option C, Ed25519)

### 4.1 Key management
- Private key: loaded from `EVIDENCE_SIGNING_KEY_PATH` (PEM, Ed25519) at
  startup; if unset, the control plane runs in **unsigned mode** (current
  self-seal behaviour, clearly labelled "unsigned" in the seal document).
- Public key: published at `/health` (or a dedicated endpoint) for
  out-of-band verification; also stored in the run record for pinning.
- Rotation: a new key gets a new `key_id`; old keys are retained for
  verification of historical runs (a keyring), never for signing.

### 4.2 Seal format change
Current: `{"algorithm":"sha256","files":{...},"sealed_at":...}`
Proposed: add `signature` (base64 Ed25519 over the canonical seal body
excluding `signature` and `sealed_at`), `key_id`, and `signed: true`.
Unsigned seals (no key configured) set `signed: false` and omit `signature`.

### 4.3 Verification
- `verify_generated_seal` checks the seal's `signed` flag:
  - `signed: true` → verify Ed25519 signature with the pinned public key;
    fail closed (ConflictError 409) on any mismatch or unknown key.
  - `signed: false` → current self-seal behaviour (hash equality only),
    labelled unsigned.
- A DB attacker cannot forge a `signed: true` seal without the private key.

### 4.4 Migration
- `runs.generated_seal` is TEXT (JSON). No schema change needed for the
  seal itself; new fields are additive in JSON.
- Existing seals (unsigned) keep verifying as unsigned. No data migration
  required for backward compatibility.
- `DB_SCHEMA_VERSION` unchanged unless a new column is added (e.g. a
  `seal_key_id` index column — optional, not required).

### 4.5 Rollback
- If signing is disabled (key unset), behaviour reverts to today's self-seal.
- Old signed seals remain verifiable as long as the corresponding public
  key is in the keyring.
- No destructive migration: removing the feature leaves unsigned seals
  verifiable.

### 4.6 Compatibility
- Unsigned seals continue to verify (backward compatible).
- Signed seals require the public key; a control plane without the key
  cannot verify signed seals (fail closed, not silent).
- Export/download and approval gates already call `verify_generated_seal`;
  no new enforcement points needed.

## 5. What is NOT in this proposal
- No code changes are made by this proposal. The integrity claim remains
  narrowed (see `api/artifact_seal.py`).
- No key management infrastructure (HSM/KMS) is assumed available.
- No cosign/sigstore dependency is added.

## 6. Decision required
Operator must choose: (a) implement Option C/B with a key-management plan,
or (b) keep the narrowed claim. Until (a) is implemented and verified with
a differential test (forge a seal without the key → 409), the integrity
guarantee stays "filesystem-substitution detection only".
